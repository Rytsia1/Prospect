"""P0 security regression tests (docs/SECURITY.md). PostgreSQL + moto; runs with TEST_DATABASE_URL.

Each test lowers one limit on the live settings object (monkeypatch), so it proves the control
that limit drives, and the rest of the suite keeps its generous defaults.
"""

import hashlib
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sample_pdf import build_report_2024
from sqlalchemy import delete, select, update
from test_documents import PDF, complete, create, put_file, storage_key
from test_worker import only_this_tests_jobs, state  # noqa: F401 (autouse fixture)

from app.auth import cookie_name, start_session, token_for
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import (
    Document,
    DocumentStatus,
    JobStatus,
    ProcessingJob,
    RateLimitCounter,
    User,
    UserSession,
)
from app.worker import process_next, retry_delay, sweep

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)
client = TestClient(app)
API = "/api/v1"


def user_session() -> tuple[dict[str, str], str]:
    token = client.post(f"{API}/sessions").cookies[cookie_name()]
    return {"Authorization": f"Bearer {token}"}, token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ready_document(storage, headers, data: bytes, **fields) -> str:
    """Upload through the API and process it."""
    fields = {"sha256": hashlib.sha256(data).hexdigest()} | fields
    created = create(headers, size_bytes=len(data), **fields).json()
    put_file(created, data)
    assert complete(headers, created["document"]["id"]).status_code == 200
    process_next(storage)
    return created["document"]["id"]


def status_of(document_id: str) -> DocumentStatus:
    with SessionLocal() as s:
        return s.get_one(Document, uuid.UUID(document_id)).status


# --- Authentication ----------------------------------------------------------------------


def test_valid_token_is_accepted():
    headers, _ = user_session()
    assert client.get(f"{API}/documents", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "authorization",
    ["", "Bearer", "Bearer abc", "Bearer v1.x.y.z", "Bearer v2.a.b.c.d", "Basic dXNlcg=="],
)
def test_malformed_tokens_are_rejected(authorization):
    response = client.get(f"{API}/documents", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_tampered_signature_is_rejected():
    _, token = user_session()
    forged = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert client.get(f"{API}/documents", headers=bearer(forged)).status_code == 401
    # A longer expiry is not accepted either: it is covered by the signature.
    version, sid, issued, expires, sig = token.split(".")
    longer = f"{version}.{sid}.{issued}.{int(expires) + 10**6}.{sig}"
    assert client.get(f"{API}/documents", headers=bearer(longer)).status_code == 401


def test_expired_token_is_rejected():
    _, token = user_session()
    with SessionLocal() as s, s.begin():
        row = s.get_one(UserSession, uuid.UUID(token.split(".")[1]))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expired = token_for(row)  # validly signed, but its expiry has passed
    response = client.get(f"{API}/documents", headers=bearer(expired))
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Session expired"


def test_server_side_expiry_wins_over_the_token():
    headers, token = user_session()
    with SessionLocal() as s, s.begin():
        s.execute(
            update(UserSession)
            .where(UserSession.id == uuid.UUID(token.split(".")[1]))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert client.get(f"{API}/documents", headers=headers).status_code == 401


def test_revoked_session_is_rejected():
    headers, _ = user_session()
    assert client.delete(f"{API}/sessions/current", headers=headers).status_code == 204
    response = client.get(f"{API}/documents", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Session is no longer valid"


def test_unknown_session_is_rejected():
    _, token = user_session()
    with SessionLocal() as s:
        user_id = s.get_one(UserSession, uuid.UUID(token.split(".")[1])).user_id
    now = datetime.now(UTC).replace(microsecond=0)
    ghost = UserSession(  # validly signed, never stored
        id=uuid.uuid4(), user_id=user_id, created_at=now, expires_at=now + timedelta(hours=1)
    )
    assert client.get(f"{API}/documents", headers=bearer(token_for(ghost))).status_code == 401


def test_refresh_keeps_the_user_and_revokes_the_old_token(storage):
    headers, _ = user_session()
    created = create(headers).json()
    fresh = client.post(f"{API}/sessions/refresh", headers=headers).cookies[cookie_name()]
    assert client.get(f"{API}/documents", headers=headers).status_code == 401  # old one revoked
    listed = client.get(f"{API}/documents", headers=bearer(fresh)).json()["items"]
    assert [d["id"] for d in listed] == [created["document"]["id"]]  # same owner


def test_tokens_expire_after_the_configured_ttl(tune):
    tune(session_ttl_seconds=60)
    response = client.post(f"{API}/sessions")
    body = response.json()
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(seconds=55) < expires - datetime.now(UTC) <= timedelta(seconds=60)
    assert int(response.cookies[cookie_name()].split(".")[3]) == int(expires.timestamp())


def test_tokens_never_reach_the_logs(caplog):
    _, token = user_session()
    with caplog.at_level(logging.DEBUG):
        client.get(f"{API}/documents", headers=bearer(token))
        client.get(f"{API}/documents", headers=bearer(token + "x"))
    assert token not in caplog.text
    assert "session_invalid" in caplog.text  # the event is logged, without the token


def test_start_session_issues_verifiable_tokens():
    with SessionLocal() as s, s.begin():
        user = User()
        s.add(user)
        s.flush()
        token = token_for(start_session(s, user.id))
    assert client.get(f"{API}/documents", headers=bearer(token)).status_code == 200


# --- Authorization -----------------------------------------------------------------------


def test_one_session_cannot_reach_another_sessions_document(storage, report):
    owner, _ = user_session()
    intruder, _ = user_session()
    doc = ready_document(storage, owner, report)
    fact = client.get(f"{API}/documents/{doc}/metrics", headers=owner).json()["items"][0]
    for method, path in [
        ("get", f"/documents/{doc}"),
        ("patch", f"/documents/{doc}"),
        ("post", f"/documents/{doc}/complete"),
        ("get", f"/documents/{doc}/financials"),
        ("get", f"/documents/{doc}/financials?scope=company"),
        ("get", f"/documents/{doc}/export?format=xlsx"),
        ("get", f"/documents/{doc}/metrics"),
        ("get", f"/documents/{doc}/evidence/{fact['evidence']['id']}"),
        ("get", f"/documents/{doc}/download-url"),
    ]:
        kwargs = {"json": {"company_name": "x"}} if method == "patch" else {}
        response = getattr(client, method)(f"{API}{path}", headers=intruder, **kwargs)
        assert response.status_code == 404, path


# --- Rate limiting -----------------------------------------------------------------------


def test_session_creation_is_limited_per_ip(tune):
    with SessionLocal() as s, s.begin():
        s.execute(delete(RateLimitCounter).where(RateLimitCounter.key.like("sessions:ip:%")))
    tune(rate_limit_sessions="2/86400")
    assert [client.post(f"{API}/sessions").status_code for _ in range(2)] == [201, 201]
    limited = client.post(f"{API}/sessions")
    assert limited.status_code == 429
    assert limited.json()["error"]["message"] == "Rate limit exceeded."
    assert int(limited.headers["Retry-After"]) > 0


def test_exports_are_limited_per_user_not_shared(storage, report, tune):
    a, _ = user_session()
    b, _ = user_session()
    doc_a, doc_b = ready_document(storage, a, report), ready_document(storage, b, report)
    tune(rate_limit_export="2/86400")
    export_a = f"{API}/documents/{doc_a}/export"
    assert [client.get(export_a, headers=a).status_code for _ in range(3)] == [200, 200, 429]
    assert client.get(f"{API}/documents/{doc_b}/export", headers=b).status_code == 200


def test_uploads_are_rate_limited(tune):
    headers, _ = user_session()
    tune(rate_limit_uploads="1/86400")
    assert create(headers).status_code == 201
    response = create(headers)
    assert response.status_code == 429 and "Retry-After" in response.headers


# --- Upload limits -----------------------------------------------------------------------


def test_full_size_upload_is_accepted(storage):
    headers, _ = user_session()
    size = get_settings().max_upload_bytes  # 50 MiB
    created = create(headers, size_bytes=size)
    assert created.status_code == 201
    upload = created.json()["upload"]
    signed = parse_qs(urlparse(upload["url"]).query)["X-Amz-SignedHeaders"][0]
    assert "content-length" in signed.split(";")  # storage enforces the exact size
    httpx.put(upload["url"], content=b"%PDF-" + b"\0" * (size - 5), headers=upload["headers"])
    assert complete(headers, created.json()["document"]["id"]).status_code == 200


def test_upload_over_the_limit_is_refused_before_any_url_is_issued():
    headers, _ = user_session()
    response = create(headers, size_bytes=get_settings().max_upload_bytes + 1)
    assert response.status_code == 413
    assert response.json()["error"]["message"] == "Upload exceeds the maximum allowed size."
    assert "upload" not in response.json()


def test_oversized_stored_object_cannot_complete(storage, tune):
    # Real storage rejects a body that differs from the signed Content-Length; moto does not,
    # so this also proves the server-side backstop: the stored size is checked again.
    tune(max_upload_bytes=1000)
    headers, _ = user_session()
    created = create(headers, size_bytes=100).json()
    doc_id = created["document"]["id"]
    put_file(created, PDF + b"0" * 2000)
    assert complete(headers, doc_id).status_code == 422
    assert storage.stat(storage_key(doc_id)) is None  # deleted at once
    with SessionLocal() as s:
        document = s.get_one(Document, uuid.UUID(doc_id))
        assert document.status == DocumentStatus.FAILED and document.object_deleted_at


def test_wrong_stored_content_type_is_rejected(storage):
    headers, _ = user_session()
    doc_id = create(headers).json()["document"]["id"]
    storage.upload(storage_key(doc_id), PDF, "text/html")  # bypassing the signed type
    assert complete(headers, doc_id).status_code == 422


def test_checksum_mismatch_fails_processing(storage, report):
    headers, _ = user_session()
    good = ready_document(storage, headers, report, sha256=hashlib.sha256(report).hexdigest())
    assert status_of(good) == DocumentStatus.READY
    bad = ready_document(storage, headers, report, sha256="0" * 64)
    document, job = state(uuid.UUID(bad))
    assert document.status == DocumentStatus.FAILED
    assert document.processing_error == "The stored file does not match the uploaded file."
    assert job.attempts == 1  # not retried


# --- Processing limits -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("processing_max_pages", 2, "The PDF has more than 2 pages."),
        ("processing_max_text_bytes", 100, "The document exceeds the extracted-text limit."),
        ("processing_max_table_cells", 5, "The document exceeds the table-size limit."),
        ("processing_max_facts", 3, "The document has more financial facts than the limit."),
        ("processing_max_evidence", 3, "The document has more evidence items than the limit."),
        ("processing_timeout_seconds", 0.01, "Document processing took too long and was stopped."),
    ],
)
def test_resource_limits_fail_the_document_once(storage, report, tune, setting, value, message):
    tune(**{setting: value})
    headers, _ = user_session()
    doc = ready_document(storage, headers, report)
    document, job = state(uuid.UUID(doc))
    assert document.status == DocumentStatus.FAILED
    assert document.processing_error == message  # user-safe, no internals
    assert (job.status, job.attempts, job.locked_at) == (JobStatus.FAILED, 1, None)
    assert process_next(storage) is False  # never retried


def test_retry_backoff_is_exponential_with_jitter(tune):
    tune(processing_retry_base_seconds=30)
    for attempts, low in ((1, 30), (2, 60), (3, 120)):
        delays = [retry_delay(attempts) for _ in range(50)]
        assert all(low <= d < low * 1.5 for d in delays)
        assert len(set(delays)) > 1  # jittered


# --- Quotas ------------------------------------------------------------------------------


def test_document_quota(tune):
    tune(quota_max_documents=2)
    headers, _ = user_session()
    assert [create(headers).status_code for _ in range(2)] == [201, 201]
    over = create(headers)
    assert over.status_code == 409 and over.json()["error"]["code"] == "quota_exceeded"


def test_storage_quota(tune):
    tune(quota_max_storage_bytes=len(PDF) * 2)
    headers, _ = user_session()
    assert [create(headers).status_code for _ in range(3)] == [201, 201, 409]


def test_concurrent_uploads_cannot_bypass_the_quota(tune):
    tune(quota_max_documents=3)
    headers, _ = user_session()
    body = {
        "filename": "r.pdf",
        "content_type": "application/pdf",
        "size_bytes": 10,
        "sha256": "0" * 64,
    }

    def attempt(_):
        return TestClient(app).post(f"{API}/documents", json=body, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(attempt, range(8)))
    assert codes == [201] * 3 + [409] * 5


def test_active_processing_jobs_are_limited(storage, tune):
    tune(quota_max_active_jobs=1)
    headers, _ = user_session()
    first, second = create(headers).json(), create(headers).json()
    put_file(first)
    put_file(second)
    assert complete(headers, first["document"]["id"]).status_code == 200
    blocked = complete(headers, second["document"]["id"])
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "quota_exceeded"
    assert status_of(second["document"]["id"]) == DocumentStatus.UPLOADING  # can retry later


def test_daily_processing_jobs_are_limited(storage, tune):
    tune(quota_max_daily_jobs=1)
    headers, _ = user_session()
    first, second = create(headers).json(), create(headers).json()
    put_file(first)
    put_file(second)
    assert complete(headers, first["document"]["id"]).status_code == 200
    assert complete(headers, second["document"]["id"]).status_code == 429


# --- Financials and export bounds --------------------------------------------------------


def test_facts_are_paged_in_the_database(storage, report):
    headers, _ = user_session()
    doc = ready_document(storage, headers, report)
    seen: list[str] = []
    offset: int | None = 0
    while offset is not None:
        url = f"{API}/documents/{doc}/metrics?limit=5&offset={offset}"
        page = client.get(url, headers=headers).json()
        assert len(page["items"]) <= 5
        seen += [f["id"] for f in page["items"]]
        offset = page["next_offset"]
    assert len(seen) == len(set(seen)) == 22  # every fact exactly once
    too_many = get_settings().page_max_limit + 1
    response = client.get(f"{API}/documents/{doc}/metrics?limit={too_many}", headers=headers)
    assert response.status_code == 422  # the client cannot raise the cap


def test_oversized_financials_are_refused_not_truncated(storage, report, tune):
    headers, _ = user_session()
    doc = ready_document(storage, headers, report)
    tune(financials_max_facts=5)
    response = client.get(f"{API}/documents/{doc}/financials", headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "financial_data_too_large"


def test_company_scope_is_bounded(storage, report, tune, tmp_path):
    headers, _ = user_session()
    older = build_report_2024(tmp_path / "ar2024.pdf").read_bytes()
    doc = ready_document(storage, headers, report, company_name="PT Contoh")
    ready_document(storage, headers, older, company_name="PT Contoh")
    tune(financials_max_documents=1)
    response = client.get(f"{API}/documents/{doc}/financials?scope=company", headers=headers)
    assert response.status_code == 413


def test_exports_are_bounded(storage, report, tune):
    headers, _ = user_session()
    doc = ready_document(storage, headers, report)
    export = f"{API}/documents/{doc}/export"
    assert client.get(f"{export}?format=xlsx", headers=headers).status_code == 200
    tune(export_max_records=10)
    response = client.get(f"{export}?format=json", headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "export_too_large"
    # Narrowing the selection brings it under the limit: nothing is silently truncated.
    narrowed = f"{export}?format=csv&metrics=revenue&periods=FY2025"
    assert client.get(narrowed, headers=headers).status_code == 200
    tune(export_max_records=10_000, export_max_bytes=100)
    assert client.get(export, headers=headers).status_code == 413


# --- Cleanup -----------------------------------------------------------------------------


def test_sweep_releases_abandoned_uploads_and_failed_objects(storage):
    headers, _ = user_session()
    abandoned, failed = create(headers).json(), create(headers).json()
    put_file(abandoned)  # uploaded, never completed
    put_file(failed)
    abandoned_id, failed_id = abandoned["document"]["id"], failed["document"]["id"]
    with SessionLocal() as s, s.begin():
        s.execute(
            update(Document)
            .where(Document.id == uuid.UUID(abandoned_id))
            .values(created_at=datetime.now(UTC) - timedelta(hours=2))
        )
        s.execute(  # e.g. a permanent processing failure
            update(Document)
            .where(Document.id == uuid.UUID(failed_id))
            .values(status=DocumentStatus.FAILED)
        )
        s.add(RateLimitCounter(key="old", count=1, expires_at=datetime.now(UTC) - timedelta(1)))

    live = create(headers).json()
    put_file(live)  # a fresh, in-progress upload
    while any(sweep(storage).values()):  # batches of 100; the test database is shared
        pass
    for doc_id in (abandoned_id, failed_id):
        assert storage.stat(storage_key(doc_id)) is None
        with SessionLocal() as s:
            document = s.get_one(Document, uuid.UUID(doc_id))
            assert document.status == DocumentStatus.FAILED and document.object_deleted_at
    assert storage.stat(storage_key(live["document"]["id"])) is not None  # left alone
    with SessionLocal() as s:
        assert s.get(RateLimitCounter, "old") is None


def test_failed_processing_leaves_no_running_job(storage, report, tune):
    tune(processing_max_pages=1)
    headers, _ = user_session()
    doc = ready_document(storage, headers, report)
    with SessionLocal() as s:
        jobs = s.scalars(
            select(ProcessingJob).where(ProcessingJob.document_id == uuid.UUID(doc))
        ).all()
    assert [(j.status, j.locked_at) for j in jobs] == [(JobStatus.FAILED, None)]
