"""Worker + viewer API on real PostgreSQL + moto S3. Runs when TEST_DATABASE_URL is set."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sample_pdf import build_sample_report
from sqlalchemy import func, select, update

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import (
    Document,
    DocumentChunk,
    DocumentPage,
    DocumentSection,
    DocumentStatus,
    DocumentType,
    JobStatus,
    ProcessingJob,
    User,
)
from app.worker import process_next

MAX_ATTEMPTS = get_settings().processing_max_attempts

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)
client = TestClient(app)


@pytest.fixture(scope="module")
def report_bytes(tmp_path_factory) -> bytes:
    return build_sample_report(tmp_path_factory.mktemp("pdf") / "report.pdf").read_bytes()


@pytest.fixture(autouse=True)
def only_this_tests_jobs():
    """Park jobs left over by other tests so the worker only sees jobs made here."""
    with SessionLocal() as s, s.begin():
        s.execute(
            update(ProcessingJob)
            .where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
            .values(status=JobStatus.FAILED)
        )


def uploaded_document(storage, data: bytes, user_id: uuid.UUID | None = None) -> uuid.UUID:
    """A document as Phase 1 leaves it: UPLOADED, bytes in storage, one queued job."""
    key = f"documents/{uuid.uuid4()}.pdf"
    storage.upload(key, data, "application/pdf")
    with SessionLocal() as s, s.begin():
        if user_id is None:
            user = User()
            s.add(user)
            s.flush()
            user_id = user.id
        doc = Document(
            user_id=user_id,
            filename="Annual Report 2025.pdf",
            document_type=DocumentType.ANNUAL_REPORT,
            mime_type="application/pdf",
            size_bytes=len(data),
            storage_key=key,
            status=DocumentStatus.UPLOADED,
        )
        s.add(doc)
        s.flush()
        s.add(ProcessingJob(document_id=doc.id))
        return doc.id


def state(document_id: uuid.UUID) -> tuple[Document, ProcessingJob]:
    with SessionLocal() as s:
        doc = s.get_one(Document, document_id)
        job = s.scalars(select(ProcessingJob).where(ProcessingJob.document_id == document_id)).one()
        return doc, job


def counts(document_id: uuid.UUID) -> tuple[int, int, int]:
    with SessionLocal() as s:
        return tuple(  # type: ignore[return-value]
            s.scalar(select(func.count()).where(m.document_id == document_id))
            for m in (DocumentPage, DocumentSection, DocumentChunk)
        )


def age_job(document_id: uuid.UUID, **values) -> None:
    """Move a job's clock back so backoff/lease windows have passed."""
    with SessionLocal() as s, s.begin():
        s.execute(
            update(ProcessingJob).where(ProcessingJob.document_id == document_id).values(**values)
        )


def test_worker_turns_upload_into_pages_sections_chunks(storage, report_bytes):
    doc_id = uploaded_document(storage, report_bytes)
    assert process_next(storage) is True

    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.READY and doc.processing_error is None
    assert job.status == JobStatus.SUCCEEDED and job.attempts == 1
    pages, sections, chunks = counts(doc_id)
    assert (pages, sections) == (5, 5) and chunks > 0

    with SessionLocal() as s:
        numbers = s.scalars(
            select(DocumentPage.page_number)
            .where(DocumentPage.document_id == doc_id)
            .order_by(DocumentPage.page_number)
        ).all()
        assert numbers == [1, 2, 3, 4, 5]
        # Every chunk carries its document and page number, consistent with its page row.
        rows = s.execute(
            select(DocumentChunk.document_id, DocumentChunk.page_number, DocumentPage.page_number)
            .join(DocumentPage, DocumentPage.id == DocumentChunk.page_id)
            .where(DocumentChunk.document_id == doc_id)
        ).all()
        assert rows and all(d == doc_id and n is not None and n == pn for d, n, pn in rows)
        page2 = s.scalars(
            select(DocumentPage).where(
                DocumentPage.document_id == doc_id, DocumentPage.page_number == 2
            )
        ).one()
        assert page2.page_metadata["label"] == "86"
        assert [b["kind"] for b in page2.blocks] == ["text", "text", "table", "text"]

    assert process_next(storage) is False  # nothing left to do


def test_reprocessing_the_same_document_does_not_duplicate(storage, report_bytes):
    doc_id = uploaded_document(storage, report_bytes)
    process_next(storage)
    first = counts(doc_id)

    # The job is delivered again (after its retry backoff).
    age_job(doc_id, status=JobStatus.QUEUED, updated_at=datetime.now(UTC) - timedelta(hours=1))
    assert process_next(storage) is True
    assert counts(doc_id) == first
    assert state(doc_id)[0].status == DocumentStatus.READY


def test_unreadable_pdf_fails_permanently_with_safe_reason(storage):
    doc_id = uploaded_document(storage, b"%PDF-1.7\nnot actually a pdf")
    process_next(storage)

    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.FAILED
    assert doc.processing_error == "The PDF could not be read. It may be damaged."
    assert job.status == JobStatus.FAILED and job.attempts == 1
    assert counts(doc_id) == (0, 0, 0)
    assert process_next(storage) is False  # a permanent failure is not retried


class FlakyStorage:
    """Delegates to real storage but fails the first `failures` downloads."""

    def __init__(self, storage, failures: int) -> None:
        self.storage, self.failures = storage, failures

    def download_file(self, key, path) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("storage unavailable")
        self.storage.download_file(key, path)


def test_transient_errors_are_retried_with_backoff(storage, report_bytes):
    doc_id = uploaded_document(storage, report_bytes)
    flaky = FlakyStorage(storage, failures=1)
    process_next(flaky)

    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.QUEUED  # waiting to retry, not stuck in PROCESSING
    assert job.status == JobStatus.QUEUED and job.attempts == 1
    # Exponential backoff with jitter: base (30 s) × 2^0 × [1, 1.5).
    assert job.run_after is not None
    delay = (job.run_after - datetime.now(UTC)).total_seconds()
    assert 25 < delay <= 45
    assert process_next(flaky) is False  # backoff not elapsed yet

    age_job(doc_id, run_after=datetime.now(UTC) - timedelta(seconds=1))
    assert process_next(flaky) is True
    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.READY and job.attempts == 2


def test_retries_stop_after_max_attempts(storage, report_bytes):
    doc_id = uploaded_document(storage, report_bytes)
    flaky = FlakyStorage(storage, failures=MAX_ATTEMPTS)
    for _ in range(MAX_ATTEMPTS):
        age_job(doc_id, run_after=datetime.now(UTC) - timedelta(seconds=1))
        assert process_next(flaky) is True

    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.FAILED
    assert doc.processing_error == "Document processing failed."  # generic, user-safe
    assert "storage unavailable" not in (doc.processing_error or "")  # internals stay in logs
    assert job.status == JobStatus.FAILED and job.attempts == MAX_ATTEMPTS


def test_job_of_a_crashed_worker_is_reclaimed(storage, report_bytes):
    doc_id = uploaded_document(storage, report_bytes)
    stale = datetime.now(UTC) - timedelta(hours=1)
    age_job(doc_id, status=JobStatus.RUNNING, locked_at=stale, attempts=1)

    assert process_next(storage) is True
    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.READY and job.attempts == 2


def test_repeatedly_crashing_job_is_failed_not_left_processing(storage, report_bytes):
    doc_id = uploaded_document(storage, report_bytes)
    stale = datetime.now(UTC) - timedelta(hours=1)
    age_job(doc_id, status=JobStatus.RUNNING, locked_at=stale, attempts=MAX_ATTEMPTS)

    process_next(storage)
    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.FAILED
    assert job.status == JobStatus.FAILED


def session_headers() -> tuple[dict[str, str], uuid.UUID]:
    token = client.post("/api/v1/sessions").json()["token"]
    return {"Authorization": f"Bearer {token}"}, user_of(token)


def user_of(token: str) -> uuid.UUID:
    """The user behind a session token (tokens carry the session id, not the user id)."""
    from app.models import UserSession

    with SessionLocal() as s:
        return s.get_one(UserSession, uuid.UUID(token.split(".")[1])).user_id


def test_viewer_api_serves_pages_and_sections_to_owner_only(storage, report_bytes):
    owner, owner_id = session_headers()
    intruder, _ = session_headers()
    doc_id = uploaded_document(storage, report_bytes, user_id=owner_id)
    process_next(storage)
    base = f"/api/v1/documents/{doc_id}"

    pages = client.get(f"{base}/pages", headers=owner).json()["items"]
    assert [(p["page_number"], p["label"]) for p in pages] == [
        (1, "i"),
        (2, "86"),
        (3, "87"),
        (4, "88"),
        (5, "89"),
    ]
    assert pages[3]["extraction_status"] == "partial" and pages[3]["char_count"] == 0

    page2 = client.get(f"{base}/pages/2", headers=owner).json()
    assert page2["page_number"] == 2
    assert "Revenue | 12,400 | 10,500" in page2["text"]

    sections = client.get(f"{base}/sections", headers=owner).json()["items"]
    assert sections[0]["title"] is None
    assert sections[2]["title"] == "Consolidated Statement of Profit or Loss"

    assert client.get(f"{base}/pages/99", headers=owner).status_code == 404
    assert client.get(f"{base}/pages/0", headers=owner).status_code == 422
    for path in ("/pages", "/pages/2", "/sections"):
        response = client.get(f"{base}{path}", headers=intruder)
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Document not found"


def test_worker_stores_facts_linked_to_page_section_and_chunk(storage, report_bytes):
    from decimal import Decimal

    from app.models import Evidence, FactStatus, FinancialFact, FinancialMetric

    doc_id = uploaded_document(storage, report_bytes)
    process_next(storage)
    with SessionLocal() as s:
        rows = s.execute(
            select(FinancialFact, FinancialMetric.key, Evidence, DocumentChunk, DocumentPage)
            .join(FinancialMetric, FinancialMetric.id == FinancialFact.metric_id)
            .join(Evidence, Evidence.id == FinancialFact.evidence_id)
            .join(DocumentChunk, DocumentChunk.id == Evidence.chunk_id)
            .join(DocumentPage, DocumentPage.id == Evidence.page_id)
            .where(FinancialFact.document_id == doc_id)
        ).all()
    assert len(rows) == 22
    assert {key for _, key, *_ in rows} == {
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "total_assets",
        "current_assets",
        "current_liabilities",
        "total_liabilities",
        "equity",
        "cash",
        "total_debt",
    }
    for fact, _key, evidence, chunk, page in rows:
        assert fact.status == FactStatus.ACCEPTED and fact.currency == "IDR"
        assert isinstance(fact.value_numeric, Decimal)
        # Why is this value believed? The row is on the page, inside the chunk, in the section.
        assert evidence.content in page.text and evidence.content in chunk.content
        assert chunk.page_number == evidence.page_number == page.page_number
        assert chunk.section_id == evidence.section_id
    revenue = next(f for f, key, *_ in rows if key == "revenue" and f.fiscal_year == 2025)
    assert revenue.value_numeric == Decimal("12400000000000")
    assert (revenue.original_text, revenue.scale) == ("12,400", "billions")


def test_reprocessing_does_not_duplicate_facts(storage, report_bytes):
    from app.models import Calculation, Evidence, FinancialFact

    doc_id = uploaded_document(storage, report_bytes)
    process_next(storage)
    age_job(doc_id, status=JobStatus.QUEUED, updated_at=datetime.now(UTC) - timedelta(hours=1))
    process_next(storage)
    with SessionLocal() as s:
        assert s.scalar(select(func.count()).where(Calculation.document_id == doc_id)) == 12
        for model in (FinancialFact, Evidence):
            assert s.scalar(select(func.count()).where(model.document_id == doc_id)) == 22


def test_metrics_api_returns_facts_with_evidence_to_owner_only(storage, report_bytes):
    owner, owner_id = session_headers()
    intruder, _ = session_headers()
    doc_id = uploaded_document(storage, report_bytes, user_id=owner_id)
    process_next(storage)

    response = client.get(f"/api/v1/documents/{doc_id}/metrics", headers=owner)
    items = response.json()["items"]
    assert len(items) == 22
    revenue = next(i for i in items if i["metric"] == "revenue" and i["period_label"] == "FY2025")
    assert revenue["value"] == "12400000000000"  # a decimal string, never a JSON float
    assert (revenue["currency"], revenue["status"], revenue["period_type"]) == (
        "IDR",
        "accepted",
        "annual",
    )
    assert revenue["evidence"]["page_number"] == 2
    assert revenue["evidence"]["page_label"] == "86"
    assert revenue["evidence"]["section_title"] == "Consolidated Statement of Profit or Loss"
    assert revenue["evidence"]["content"] == "Revenue | 12,400 | 10,500"
    assert revenue["evidence"]["unit"] == "(Rp billion)"

    denied = client.get(f"/api/v1/documents/{doc_id}/metrics", headers=intruder)
    assert denied.status_code == 404


def test_calculations_api_returns_ratios_with_source_facts_to_owner_only(storage, report_bytes):
    owner, owner_id = session_headers()
    intruder, _ = session_headers()
    doc_id = uploaded_document(storage, report_bytes, user_id=owner_id)
    process_next(storage)

    items = client.get(f"/api/v1/documents/{doc_id}/calculations", headers=owner).json()["items"]
    by = {(i["metric"], i["period_label"]): i for i in items}
    assert len(items) == 12

    growth = by[("revenue_growth", "FY2025")]
    assert growth["status"] == "calculated" and growth["unit"] == "percent"
    assert growth["value"] == "0.1809523809523809523809523809523810"  # 1,900 / 10,500, a string
    assert {(i["metric"], i["period_label"]) for i in growth["inputs"]} == {
        ("revenue", "FY2024"),
        ("revenue", "FY2025"),
    }
    assert all(i["evidence"]["page_number"] == 2 for i in growth["inputs"])

    # No FY2023 revenue: not possible, never zero; the fact that was found is still shown.
    missing = by[("revenue_growth", "FY2024")]
    assert (missing["status"], missing["value"], missing["reason_code"]) == (
        "not_possible",
        None,
        "MISSING_INPUT",
    )
    assert missing["reason"] == "Revenue for FY2023 was not found."
    assert [i["period_label"] for i in missing["inputs"]] == ["FY2024"]

    roa = by[("roa", "FY2025")]
    assert roa["formula_key"] == "roa_average_assets"
    assert roa["value"] == "0.04009216589861751152073732718894009"  # 1.74 / 43.4
    assert {i["evidence"]["page_number"] for i in roa["inputs"]} == {2, 5}
    # FY2024 has no opening balance sheet: a labeled ending-assets variant, never the average.
    assert by[("roa", "FY2024")]["formula_key"] == "roa_ending_assets"
    assert by[("roa", "FY2024")]["notes"]
    assert by[("current_ratio", "2025-12-31")]["value"] == "1.25"
    assert by[("debt_to_equity", "2025-12-31")]["unit"] == "times"

    response = client.get(f"/api/v1/documents/{doc_id}/calculations", headers=intruder)
    assert response.status_code == 404
