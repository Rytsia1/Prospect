"""Worker + viewer API on real PostgreSQL + moto S3. Runs when TEST_DATABASE_URL is set."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sample_pdf import build_sample_report
from sqlalchemy import func, select, update

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
from app.worker import MAX_ATTEMPTS, process_next

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
    assert (pages, sections) == (4, 4) and chunks > 0

    with SessionLocal() as s:
        numbers = s.scalars(
            select(DocumentPage.page_number)
            .where(DocumentPage.document_id == doc_id)
            .order_by(DocumentPage.page_number)
        ).all()
        assert numbers == [1, 2, 3, 4]
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
        assert [b["kind"] for b in page2.blocks] == ["text", "table", "text"]

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
    assert process_next(flaky) is False  # backoff not elapsed yet

    age_job(doc_id, updated_at=datetime.now(UTC) - timedelta(minutes=5))
    assert process_next(flaky) is True
    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.READY and job.attempts == 2


def test_retries_stop_after_max_attempts(storage, report_bytes):
    doc_id = uploaded_document(storage, report_bytes)
    flaky = FlakyStorage(storage, failures=MAX_ATTEMPTS)
    for _ in range(MAX_ATTEMPTS):
        age_job(doc_id, updated_at=datetime.now(UTC) - timedelta(hours=1))
        assert process_next(flaky) is True

    doc, job = state(doc_id)
    assert doc.status == DocumentStatus.FAILED
    assert f"Tried {MAX_ATTEMPTS} times" in (doc.processing_error or "")
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
    return {"Authorization": f"Bearer {token}"}, uuid.UUID(token.split(".")[0])


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
