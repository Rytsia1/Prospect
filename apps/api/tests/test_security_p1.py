"""P1 security regression tests: browser session, CSRF, CORS, headers, request ids, query
validation, upload integrity, deletion, threat scanning, company isolation, audit trail,
retention and error hardening. Needs TEST_DATABASE_URL (a migrated database)."""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from test_documents import PDF, complete, create, put_file, storage_key
from test_security import API, ready_document, user_session
from test_worker import only_this_tests_jobs, state  # noqa: F401 (autouse fixture)

from app.auth import CSRF_HEADER, cookie_name
from app.db import SessionLocal
from app.main import app
from app.models import (
    AuditEvent,
    Calculation,
    Company,
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentType,
    Evidence,
    FinancialFact,
    JobStatus,
    ProcessingJob,
    UserSession,
)
from app.processing import ProcessingError, parse_pdf
from app.scanning import ScannerUnavailable, ScanResult
from app.worker import process_next, sweep

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)
client = TestClient(app)
TRUSTED = "http://localhost:3000"  # the default ALLOWED_ORIGINS in tests
EVIL = "https://evil.example"


def user_of(token: str) -> uuid.UUID:
    with SessionLocal() as s:
        return s.get_one(UserSession, uuid.UUID(token.split(".")[1])).user_id


def browser() -> tuple[TestClient, str]:
    """A browser-like client over https (so the Secure cookie is sent) with a new session."""
    b = TestClient(app, base_url="https://testserver")
    response = b.post(f"{API}/sessions", headers={"Origin": TRUSTED})
    assert response.status_code == 201
    return b, response.json()["csrf_token"]


def browser_create(b: TestClient, headers: dict[str, str]):
    body = {
        "filename": "r.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        "sha256": hashlib.sha256(PDF).hexdigest(),
    }
    return b.post(f"{API}/documents", json=body, headers=headers)


# --- Session cookie ---------------------------------------------------------------------------


def test_session_is_an_httponly_strict_host_cookie_never_in_the_body():
    response = client.post(f"{API}/sessions")
    body, set_cookie = response.json(), response.headers["set-cookie"]
    assert set(body) == {"issued_at", "expires_at", "csrf_token"}  # no token for JavaScript
    assert set_cookie.startswith(f"{cookie_name()}=v1.")
    assert cookie_name().startswith("__Host-")
    attributes = {a.strip().lower() for a in set_cookie.split(";")[1:]}
    assert {"httponly", "secure", "samesite=strict", "path=/"} <= attributes
    assert not any(a.startswith("domain") for a in attributes)


def test_cookie_session_reads_and_signs_out():
    b, csrf = browser()
    assert b.get(f"{API}/documents").status_code == 200  # safe method: cookie alone
    assert b.get(f"{API}/sessions/current").json()["csrf_token"] == csrf
    out = b.delete(f"{API}/sessions/current", headers={"Origin": TRUSTED, CSRF_HEADER: csrf})
    assert out.status_code == 204
    assert "max-age=0" in out.headers["set-cookie"].lower()


def test_refresh_replaces_the_cookie_and_the_csrf_token():
    b, csrf = browser()
    fresh = b.post(f"{API}/sessions/refresh", headers={"Origin": TRUSTED, CSRF_HEADER: csrf})
    assert fresh.status_code == 200
    assert fresh.json()["csrf_token"] != csrf
    assert b.get(f"{API}/documents").status_code == 200  # the new cookie works


def test_tokens_in_query_strings_are_not_accepted():
    _, token = user_session()
    assert client.get(f"{API}/documents?token={token}").status_code == 400


# --- CSRF -------------------------------------------------------------------------------------


def test_csrf_valid_request_is_allowed():
    b, csrf = browser()
    assert browser_create(b, {"Origin": TRUSTED, CSRF_HEADER: csrf}).status_code == 201


def test_csrf_referer_is_accepted_when_origin_is_absent():
    b, csrf = browser()
    headers = {"Referer": f"{TRUSTED}/documents", CSRF_HEADER: csrf}
    assert browser_create(b, headers).status_code == 201


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": TRUSTED},  # missing token
        {"Origin": TRUSTED, CSRF_HEADER: "0" * 64},  # wrong token
        {CSRF_HEADER: "csrf"},  # no Origin or Referer at all
        {"Origin": "null", CSRF_HEADER: "csrf"},  # sandboxed/opaque origin
    ],
)
def test_csrf_rejects_cookie_requests_that_cannot_be_verified(headers):
    b, csrf = browser()
    headers = {k: (csrf if v == "csrf" else v) for k, v in headers.items()}
    response = browser_create(b, headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_csrf_token_of_another_session_is_rejected():
    b, _ = browser()
    _, other_csrf = browser()
    assert browser_create(b, {"Origin": TRUSTED, CSRF_HEADER: other_csrf}).status_code == 403


def test_csrf_untrusted_origin_is_rejected_even_with_the_token():
    b, csrf = browser()
    assert browser_create(b, {"Origin": EVIL, CSRF_HEADER: csrf}).status_code == 403


def test_login_csrf_session_creation_from_another_site_is_rejected():
    assert client.post(f"{API}/sessions", headers={"Origin": EVIL}).status_code == 403
    assert client.post(f"{API}/sessions", headers={"Referer": f"{EVIL}/x"}).status_code == 403


def test_bearer_clients_need_no_csrf_token():
    headers, _ = user_session()  # a script: no cookie, no Origin
    assert create(headers).status_code == 201


def test_cookie_token_is_never_logged(caplog):
    b, csrf = browser()
    token = b.cookies.get(cookie_name())
    with caplog.at_level("DEBUG"):
        b.get(f"{API}/documents")
        browser_create(b, {"Origin": TRUSTED})  # rejected: logged as csrf_rejected
    assert token and token not in caplog.text and csrf not in caplog.text
    assert "csrf_rejected" in caplog.text


# --- CORS -------------------------------------------------------------------------------------


def preflight(origin: str, method: str = "POST", headers: str = "content-type"):
    return client.options(
        f"{API}/documents",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_cors_trusted_origin_is_allowed_without_credentials():
    response = preflight(TRUSTED, headers="content-type,x-csrf-token,authorization")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == TRUSTED
    assert "access-control-allow-credentials" not in response.headers


def test_cors_unknown_origin_is_rejected_and_never_reflected():
    response = preflight(EVIL)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    simple = client.get("/health", headers={"Origin": EVIL})
    assert "access-control-allow-origin" not in simple.headers


@pytest.mark.parametrize(("method", "headers"), [("PUT", "content-type"), ("POST", "x-evil")])
def test_cors_restricts_methods_and_headers(method, headers):
    assert preflight(TRUSTED, method, headers).status_code == 400


# --- Security headers, request ids, production runtime ----------------------------------------


def test_api_responses_carry_security_headers():
    headers = client.get("/health").headers
    assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in headers["permissions-policy"]
    assert headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in headers  # development: plain http allowed
    error = client.get(f"{API}/documents")  # errors too
    assert error.status_code == 401 and error.headers["x-frame-options"] == "DENY"


def test_production_adds_hsts_and_hides_the_docs():
    """Imported fresh with production settings, as the deployed API starts."""
    env = os.environ | {
        "ENVIRONMENT": "production",
        "APP_SECRET": secrets.token_urlsafe(48),  # generated: no secret-shaped literal
        "TRUSTED_PROXY_SECRET": secrets.token_urlsafe(48),
        "ALLOWED_ORIGINS": "https://prospect.example",
        "DOCUMENT_SCANNER": "none",
    }
    script = (
        "import json; from fastapi.testclient import TestClient; from app.main import app;"
        "c = TestClient(app); h = c.get('/health').headers;"
        "print(json.dumps({'hsts': h.get('strict-transport-security'),"
        "'docs': c.get('/docs').status_code, 'openapi': c.get('/openapi.json').status_code}))"
    )
    run = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result == {"hsts": "max-age=31536000; includeSubDomains", "docs": 404, "openapi": 404}


@pytest.mark.parametrize("sent", ["x\tforged", "a" * 65, "id with spaces", "<script>", "é"])
def test_unsafe_request_ids_are_replaced(sent):
    returned = client.get("/health", headers={"X-Request-ID": sent.encode()}).headers[
        "x-request-id"
    ]
    assert returned != sent and uuid.UUID(returned)


def test_safe_request_ids_are_kept():
    response = client.get("/health", headers={"X-Request-ID": "abc-123._x"})
    assert response.headers["x-request-id"] == "abc-123._x"


# --- Query validation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/documents?limit=101", 422),  # limit too large
        ("/documents?limit=0", 422),
        ("/documents?sort=filename", 400),  # no sorting is offered: unknown parameter
        ("/documents?user_id=00000000-0000-0000-0000-000000000000", 400),  # unexpected filter
        ("/documents/not-a-uuid", 422),  # malformed UUID
        ("/financial-facts/review?status=anything", 422),  # values outside the allowed set
        ("/financial-facts/review?metric=" + "m" * 65, 422),
        ("/audit?limit=201", 422),
    ],
)
def test_query_parameters_are_validated(path, status):
    headers, _ = user_session()
    response = client.get(f"{API}{path}", headers=headers)
    assert response.status_code == status, response.text


def test_invalid_scope_is_rejected():
    headers, token = user_session()
    document_id = make_document(user_of(token), None)
    response = client.get(f"{API}/documents/{document_id}/financials?scope=all", headers=headers)
    assert response.status_code == 422


def test_validation_errors_do_not_echo_the_input():
    headers, _ = user_session()
    secret_looking = "do-not-echo-" + "x" * 40
    response = client.post(
        f"{API}/documents", json={"filename": secret_looking, "content_type": 1}, headers=headers
    )
    assert response.status_code == 422
    assert secret_looking not in response.text and '"input"' not in response.text


# --- Upload integrity -------------------------------------------------------------------------


def test_complete_moves_the_verified_file_out_of_uploads(storage):
    headers, _ = user_session()
    created = create(headers).json()
    upload_key = storage_key(created["document"]["id"])
    assert upload_key.startswith("uploads/")
    put_file(created)
    assert complete(headers, created["document"]["id"]).status_code == 200
    final_key = storage_key(created["document"]["id"])
    assert final_key.startswith("documents/") and storage.stat(final_key) is not None
    assert storage.stat(upload_key) is None


def test_checksum_recorded_by_storage_must_match(storage, monkeypatch):
    headers, _ = user_session()
    created = create(headers).json()
    put_file(created)
    real = storage.stat

    def stat_with_other_checksum(key):
        stat = real(key)
        return stat and type(stat)(stat.size, stat.content_type, "b" * 64)

    monkeypatch.setattr(storage, "stat", stat_with_other_checksum)
    response = complete(headers, created["document"]["id"])
    monkeypatch.undo()
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "The uploaded file does not match its checksum."
    assert storage.stat(storage_key(created["document"]["id"])) is None  # cleaned up
    assert status_of(created["document"]["id"]) == DocumentStatus.FAILED


def test_object_tampered_after_completion_is_rejected_before_parsing(storage, report):
    document_id = uploaded(report)
    tampered = report[:-1] + bytes([report[-1] ^ 1])  # same size, one bit different
    storage.upload(storage_key(str(document_id)), tampered, "application/pdf")
    scanner = FakeScanner(ScanResult("clean"))
    process_next(storage, scanner)
    document, job = state(document_id)
    assert document.status == DocumentStatus.FAILED and job.status == JobStatus.FAILED
    assert document.processing_error == "The stored file does not match the uploaded file."
    assert scanner.calls == 0 and document.threat_scan is None  # never scanned or parsed


def test_checksum_is_required_on_upload():
    headers, _ = user_session()
    body = {"filename": "r.pdf", "content_type": "application/pdf", "size_bytes": 10}
    assert client.post(f"{API}/documents", json=body, headers=headers).status_code == 422


def status_of(document_id: str) -> DocumentStatus:
    with SessionLocal() as s:
        return s.get_one(Document, uuid.UUID(document_id)).status


# --- Stronger PDF validation ------------------------------------------------------------------


def test_parser_refuses_non_pdf_content_with_a_pdf_header(tmp_path):
    fake = tmp_path / "x.pdf"
    fake.write_bytes(b"%PDF-1.7\n" + b"\x89PNG\r\n\x1a\n" + os.urandom(2048))
    with pytest.raises(ProcessingError) as raised:
        parse_pdf(fake)
    assert "mupdf" not in str(raised.value).lower()  # a fixed, safe message


def test_magic_bytes_alone_do_not_make_a_document_ready(storage):
    data = b"%PDF-1.4\n" + b"not really a pdf " * 50
    document_id = uploaded(data)
    process_next(storage)
    document, _ = state(document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.processing_error in {
        "The PDF could not be read. It may be damaged.",
        "The PDF has no pages.",
        "The file is not a valid PDF.",
        "No extractable text was found. Scanned PDFs need OCR, which is not supported yet.",
    }


# --- Threat scanning --------------------------------------------------------------------------


class FakeScanner:
    def __init__(self, result: ScanResult | Exception) -> None:
        self.result, self.calls = result, 0

    def scan(self, path: Path) -> ScanResult:
        self.calls += 1
        assert path.read_bytes().startswith(b"%PDF")  # verified bytes, before any parsing
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def uploaded(data: bytes) -> uuid.UUID:
    headers, _ = user_session()
    created = create(headers, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    put_file(created.json(), data)
    assert complete(headers, created.json()["document"]["id"]).status_code == 200
    return uuid.UUID(created.json()["document"]["id"])


def test_clean_scan_allows_processing(storage, report):
    document_id = uploaded(report)
    process_next(storage, FakeScanner(ScanResult("clean")))
    document, _ = state(document_id)
    assert document.status == DocumentStatus.READY and document.threat_scan == "clean"


def test_unscanned_documents_are_marked_so(storage, report):
    document_id = uploaded(report)
    process_next(storage)  # DOCUMENT_SCANNER unset in development: NoOpScanner
    document, _ = state(document_id)
    assert document.status == DocumentStatus.READY and document.threat_scan == "not_scanned"


def test_infected_document_is_rejected_and_not_retried(storage, report):
    document_id = uploaded(report)
    scanner = FakeScanner(ScanResult("infected", "Eicar-Test-Signature"))
    process_next(storage, scanner)
    document, job = state(document_id)
    assert document.status == DocumentStatus.FAILED and job.status == JobStatus.FAILED
    assert document.processing_error == "The file was rejected by the security scan."
    assert process_next(storage, scanner) is False and scanner.calls == 1


def test_scanner_failure_fails_closed_after_bounded_retries(storage, report, tune):
    tune(processing_max_attempts=2, processing_retry_base_seconds=0)
    document_id = uploaded(report)
    scanner = FakeScanner(ScannerUnavailable("clamd unreachable"))
    process_next(storage, scanner)
    document, job = state(document_id)
    assert job.status == JobStatus.QUEUED and document.status == DocumentStatus.QUEUED
    process_next(storage, scanner)
    document, job = state(document_id)
    assert document.status == DocumentStatus.FAILED and job.status == JobStatus.FAILED
    assert document.threat_scan is None  # never recorded as scanned
    assert derived_rows(document_id, (DocumentPage,)) == 0  # never parsed
    assert scanner.calls == 2


# --- Deletion ---------------------------------------------------------------------------------

DERIVED = (DocumentPage, Evidence, FinancialFact, Calculation, ProcessingJob)


def derived_rows(document_id: uuid.UUID, models: tuple = DERIVED) -> int:
    with SessionLocal() as s:
        return sum(
            s.scalar(select(func.count()).where(model.document_id == document_id)) or 0
            for model in models
        )


def test_owner_deletes_document_file_and_derived_data(storage, report):
    headers, _ = user_session()
    document_id = ready_document(storage, headers, report)
    key = storage_key(document_id)
    assert derived_rows(uuid.UUID(document_id)) > 0 and storage.stat(key) is not None

    assert client.delete(f"{API}/documents/{document_id}", headers=headers).status_code == 204
    assert storage.stat(key) is None
    assert derived_rows(uuid.UUID(document_id)) == 0
    assert client.get(f"{API}/documents/{document_id}", headers=headers).status_code == 404
    # Repeating the delete is safe: nothing is left and nothing changes.
    assert client.delete(f"{API}/documents/{document_id}", headers=headers).status_code == 404


def test_another_session_cannot_delete(storage):
    owner, _ = user_session()
    intruder, _ = user_session()
    document_id = create(owner).json()["document"]["id"]
    assert client.delete(f"{API}/documents/{document_id}", headers=intruder).status_code == 404
    assert client.get(f"{API}/documents/{document_id}", headers=owner).status_code == 200


def test_delete_keeps_database_and_storage_consistent_when_storage_fails(storage, monkeypatch):
    headers, _ = user_session()
    document_id = create(headers).json()["document"]["id"]

    def unavailable(key):
        raise EndpointConnectionError(endpoint_url="https://internal-bucket.example")

    monkeypatch.setattr(storage, "delete", unavailable)
    response = client.delete(f"{API}/documents/{document_id}", headers=headers)
    monkeypatch.undo()
    assert response.status_code == 503
    assert "internal-bucket" not in response.text  # no internals in the error
    assert client.get(f"{API}/documents/{document_id}", headers=headers).status_code == 200
    assert client.delete(f"{API}/documents/{document_id}", headers=headers).status_code == 204


# --- Company isolation ------------------------------------------------------------------------


def make_document(user_id: uuid.UUID, company_name: str | None, company_id=None) -> uuid.UUID:
    with SessionLocal() as s, s.begin():
        document = Document(
            user_id=user_id,
            filename="r.pdf",
            document_type=DocumentType.ANNUAL_REPORT,
            mime_type="application/pdf",
            size_bytes=1,
            storage_key=f"documents/{uuid.uuid4()}.pdf",
            company_name=company_name,
            company_id=company_id,
            status=DocumentStatus.READY,
        )
        s.add(document)
        s.flush()
        return document.id


def make_company(user_id: uuid.UUID, name: str) -> uuid.UUID:
    with SessionLocal() as s, s.begin():
        company = Company(user_id=user_id, name=name)
        s.add(company)
        s.flush()
        return company.id


def scope_ids(headers, document_id: uuid.UUID) -> set[uuid.UUID]:
    response = client.get(
        f"{API}/documents/{document_id}/financials?scope=company", headers=headers
    )
    assert response.status_code == 200
    return {uuid.UUID(d["id"]) for d in response.json()["documents"]}


def test_company_scope_never_merges_other_entities_or_owners():
    headers, token = user_session()
    other_headers, other_token = user_session()
    me, other = user_of(token), user_of(other_token)
    acme = make_company(me, "Acme")
    linked, linked_too = make_document(me, "Acme", acme), make_document(me, "Acme", acme)
    unlinked_same_name = make_document(me, "Acme")
    suffixed = make_document(me, "Acme Inc.")
    theirs = make_document(other, "Acme")

    assert scope_ids(headers, linked) == {linked, linked_too}  # by company id only
    assert scope_ids(headers, unlinked_same_name) == {unlinked_same_name}
    assert scope_ids(headers, suffixed) == {suffixed}  # "Acme Inc." is not "Acme"
    assert scope_ids(other_headers, theirs) == {theirs}  # another owner's "Acme" stays apart
    # And no owner can reach the other's company through a company-scoped request.
    response = client.get(
        f"{API}/documents/{linked}/financials?scope=company", headers=other_headers
    )
    assert response.status_code == 404


def test_relabeling_a_document_leaves_its_company_workspace():
    headers, token = user_session()
    document_id = make_document(user_of(token), "Acme", make_company(user_of(token), "Acme"))
    response = client.patch(
        f"{API}/documents/{document_id}", json={"company_name": "Beta"}, headers=headers
    )
    assert response.status_code == 200 and response.json()["company_id"] is None


# --- Audit trail ------------------------------------------------------------------------------


def audit_of(user_id: uuid.UUID) -> list[AuditEvent]:
    with SessionLocal() as s:
        return list(s.scalars(select(AuditEvent).where(AuditEvent.user_id == user_id)))


def test_sensitive_operations_are_audited_without_content(storage, report, tune):
    headers, token = user_session()
    intruder, intruder_token = user_session()
    document_id = ready_document(storage, headers, report)
    client.get(f"{API}/documents/{document_id}/download-url", headers=headers)
    client.get(f"{API}/documents/{document_id}/export?format=json", headers=headers)
    client.get(f"{API}/documents/{document_id}", headers=intruder)  # denied
    tune(rate_limit_export="0/60")
    client.get(f"{API}/documents/{document_id}/export", headers=headers)  # rate limited
    tune(quota_max_documents=0)
    create(headers)  # over quota
    client.delete(f"{API}/documents/{document_id}", headers=headers)

    events = audit_of(user_of(token))
    assert {
        "session_created",
        "document_created",
        "upload_completed",
        "processing_started",
        "processing_completed",
        "document_accessed",
        "export_created",
        "rate_limit_exceeded",
        "quota_exceeded",
        "document_deleted",
    } <= {e.event_type for e in events}
    denied = [
        e for e in audit_of(user_of(intruder_token)) if e.event_type == "authorization_denied"
    ]
    assert denied and denied[0].metadata_json["result"] == "denied"
    # Metadata only: no filenames, evidence, page text, tokens or signed URLs.
    dump = json.dumps([e.metadata_json for e in events]) + " ".join(e.entity_id for e in events)
    for sensitive in ("Annual Report", "Revenue", "Amz", token, "http"):
        assert sensitive not in dump


def test_audit_trail_is_private_to_its_user():
    headers, token = user_session()
    other, _ = user_session()
    mine = client.get(f"{API}/audit", headers=headers).json()["items"]
    theirs = client.get(f"{API}/audit", headers=other).json()["items"]
    assert mine and {e["id"] for e in mine}.isdisjoint({e["id"] for e in theirs})
    assert all(e["user_id"] == str(user_of(token)) for e in mine)


# --- Retention --------------------------------------------------------------------------------


def age(document_id: uuid.UUID, **values) -> None:
    with SessionLocal() as s, s.begin():
        s.execute(update(Document).where(Document.id == document_id).values(**values))


def sweep_all(storage) -> None:
    while any(sweep(storage).values()):  # batches of 100; the test database is shared
        pass


def test_retention_deletes_expired_documents_and_old_failures(storage, report, tune):
    headers, token = user_session()
    old = uuid.UUID(ready_document(storage, headers, report))
    recent = uuid.UUID(ready_document(storage, headers, report))
    old_key = storage_key(str(old))
    age(old, created_at=datetime.now(UTC) - timedelta(days=31))
    failed = make_document(user_of(token), None)
    age(
        failed,
        status=DocumentStatus.FAILED,
        object_deleted_at=datetime.now(UTC),
        updated_at=datetime.now(UTC) - timedelta(hours=25),
    )

    tune(document_retention_days=None)
    sweep_all(storage)
    with SessionLocal() as s:  # no retention configured: documents are kept, old failures not
        assert s.get(Document, old) is not None and s.get(Document, failed) is None

    tune(document_retention_days=30)
    sweep_all(storage)
    with SessionLocal() as s:
        assert s.get(Document, old) is None and s.get(Document, recent) is not None
    assert storage.stat(old_key) is None and derived_rows(old) == 0
    assert any(
        e.event_type == "document_deleted" and e.metadata_json.get("reason") == "retention"
        for e in audit_of(user_of(token))
    )


# --- Error hardening and filenames ------------------------------------------------------------


def test_storage_outage_is_a_generic_503(storage, monkeypatch):
    headers, _ = user_session()
    created = create(headers).json()

    def down(key):
        raise EndpointConnectionError(endpoint_url="https://internal-bucket.example")

    monkeypatch.setattr(storage, "stat", down)
    response = client.post(f"{API}/documents/{created['document']['id']}/complete", headers=headers)
    monkeypatch.undo()
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "service_unavailable",
        "message": "Service temporarily unavailable.",
        "request_id": response.headers["x-request-id"],
    }


def test_filenames_are_display_text_only():
    headers, _ = user_session()
    created = create(headers, filename="..\\..\\evil\u202egpj.pdf\x00<i>").json()["document"]
    assert created["filename"] == "evilgpj.pdf<i>"  # rendered escaped by React
    key = storage_key(created["id"])
    assert key.startswith("uploads/") and "evil" not in key
