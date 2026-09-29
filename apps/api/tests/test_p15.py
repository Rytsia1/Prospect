"""P1.5 regression tests: proxy/client-IP trust, anonymous session lifecycle, upload intents,
storage/database consistency and reconciliation, the authorization matrix, configuration and
multi-session abuse limits. Needs TEST_DATABASE_URL (a migrated database)."""

import hashlib
import ipaddress
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select, update
from starlette.requests import Request
from test_documents import create, put_file, storage_key
from test_security import API, ready_document, user_session
from test_security_p1 import make_company, make_document, user_of
from test_worker import only_this_tests_jobs, state  # noqa: F401 (autouse fixture)

import app.documents as documents_module
from app.config import Settings, api_problems, get_settings
from app.db import SessionLocal
from app.main import app
from app.models import (
    DataQualityIssue,
    Document,
    DocumentStatus,
    JobStatus,
    ProcessingJob,
    Scenario,
    User,
    UserSession,
    WatchlistEntry,
)
from app.ratelimit import CLIENT_IP_HEADER, PROXY_SECRET_HEADER, client_ip
from app.reconcile import reconcile
from app.worker import process_next, sweep

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)
client = TestClient(app)
PROXY = "p" * 20 + "roxy-shared-secret-0123456789"  # test-only value


def fresh_ip() -> str:
    """A client address no other test (or earlier run) has used: its own rate-limit bucket."""
    return str(ipaddress.IPv6Address(uuid.uuid4().int))


def via_proxy(ip: str, headers: dict[str, str] | None = None) -> dict[str, str]:
    return {PROXY_SECRET_HEADER: PROXY, CLIENT_IP_HEADER: ip, **(headers or {})}


def request_with(headers: dict[str, str], peer: str = "10.1.2.3") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 1234)})


def sweep_all(storage) -> None:
    while any(sweep(storage).values()):  # batches; the test database is shared
        pass


# --- Proxy / client IP ------------------------------------------------------------------------

SPOOFS = {
    "X-Forwarded-For": "1.1.1.1",
    "X-Real-IP": "2.2.2.2",
    "Forwarded": "for=3.3.3.3",
    CLIENT_IP_HEADER: "4.4.4.4",
}


def test_forwarding_headers_never_name_the_client_without_the_proxy_secret(tune):
    tune(trusted_proxy_secret=None)
    assert client_ip(request_with(SPOOFS)) == "10.1.2.3"
    tune(trusted_proxy_secret=SecretStr(PROXY))
    assert client_ip(request_with(SPOOFS)) == "10.1.2.3"  # no secret sent
    wrong = SPOOFS | {PROXY_SECRET_HEADER: PROXY[:-1] + "x"}
    assert client_ip(request_with(wrong)) == "10.1.2.3"


def test_trusted_proxy_names_the_client(tune):
    tune(trusted_proxy_secret=SecretStr(PROXY))
    assert client_ip(request_with(via_proxy("203.0.113.7"))) == "203.0.113.7"
    assert client_ip(request_with(via_proxy("2001:db8::1"))) == "2001:db8::1"
    for junk in ("not-an-ip", "1.2.3.4, 5.6.7.8", ""):
        assert client_ip(request_with(via_proxy(junk))) == "10.1.2.3"


def test_on_vercel_the_edge_set_real_ip_names_the_client(tune):
    # docs/ADR-006: Vercel's edge routes browsers straight to the API and sets X-Real-IP itself.
    tune(trusted_proxy_secret=None, vercel=True)
    assert client_ip(request_with({"X-Real-IP": "203.0.113.9"})) == "203.0.113.9"
    assert client_ip(request_with({"X-Real-IP": "2001:db8::9"})) == "2001:db8::9"
    for junk in ("not-an-ip", "1.2.3.4, 5.6.7.8", ""):  # only a well-formed address
        assert client_ip(request_with({"X-Real-IP": junk})) == "10.1.2.3"
    # Other forwarding headers and the proxy's own header still name no one.
    others = {k: v for k, v in SPOOFS.items() if k != "X-Real-IP"}
    assert client_ip(request_with(others)) == "10.1.2.3"
    tune(vercel=False)  # anywhere else X-Real-IP is whatever the client sent
    assert client_ip(request_with({"X-Real-IP": "203.0.113.9"})) == "10.1.2.3"


def test_spoofed_headers_cannot_escape_the_session_rate_limit(tune):
    tune(trusted_proxy_secret=SecretStr(PROXY), rate_limit_sessions="2/60")
    statuses = [
        client.post(f"{API}/sessions", headers={CLIENT_IP_HEADER: fresh_ip()}).status_code
        for _ in range(3)
    ]
    assert statuses[-1] == 429  # every attempt counted against the same (peer) identity


def test_distinct_visitors_behind_the_proxy_get_their_own_limit(tune):
    tune(trusted_proxy_secret=SecretStr(PROXY), rate_limit_sessions="2/60")
    one, two = fresh_ip(), fresh_ip()
    first = [client.post(f"{API}/sessions", headers=via_proxy(one)).status_code for _ in range(3)]
    assert first == [201, 201, 429]
    assert client.post(f"{API}/sessions", headers=via_proxy(two)).status_code == 201


# --- Anonymous session lifecycle ---------------------------------------------------------------


def expire(token: str, when: datetime, revoked: bool = False) -> None:
    with SessionLocal() as s, s.begin():
        values = {"revoked_at": when} if revoked else {"expires_at": when}
        s.execute(
            update(UserSession)
            .where(UserSession.id == uuid.UUID(token.split(".")[1]))
            .values(**values)
        )


def test_new_session_is_an_isolated_workspace(storage):
    old, _ = user_session()
    document_id = create(old).json()["document"]["id"]
    new, _ = user_session()
    assert client.get(f"{API}/documents", headers=new).json()["items"] == []
    assert client.get(f"{API}/documents/{document_id}", headers=new).status_code == 404


def test_expired_session_cannot_reach_its_workspace(storage):
    headers, token = user_session()
    document_id = create(headers).json()["document"]["id"]
    expire(token, datetime.now(UTC) - timedelta(seconds=1))
    assert client.get(f"{API}/documents/{document_id}", headers=headers).status_code == 401
    assert client.post(f"{API}/sessions/refresh", headers=headers).status_code == 401


def test_unreachable_workspaces_are_deleted_after_the_grace_period(storage, report):
    now = datetime.now(UTC)
    gone_headers, gone = user_session()
    kept_headers, kept = user_session()
    signed_out_headers, signed_out = user_session()
    gone_user, kept_user, signed_out_user = (user_of(t) for t in (gone, kept, signed_out))
    gone_doc = uuid.UUID(ready_document(storage, gone_headers, report))
    gone_key = storage_key(str(gone_doc))
    kept_doc = uuid.UUID(create(kept_headers).json()["document"]["id"])
    signed_out_doc = uuid.UUID(create(signed_out_headers).json()["document"]["id"])
    with SessionLocal() as s, s.begin():  # all three users are two days old
        s.execute(
            update(User)
            .where(User.id.in_([gone_user, kept_user, signed_out_user]))
            .values(created_at=now - timedelta(days=2))
        )
    expire(gone, now - timedelta(hours=25))  # expired past the 24 h grace
    expire(signed_out, now - timedelta(hours=1), revoked=True)  # signed out, still in grace
    with SessionLocal() as s, s.begin():
        brand_new = User()  # a user whose first session is being created right now
        s.add(brand_new)
        s.flush()
        brand_new_id = brand_new.id

    sweep_all(storage)
    with SessionLocal() as s:
        assert s.get(User, kept_user) and s.get(Document, kept_doc)
        assert s.get(Document, signed_out_doc) and s.get(User, brand_new_id)
        assert s.get(User, gone_user) is None and s.get(Document, gone_doc) is None
    assert storage.stat(gone_key) is None  # the file went too, not just the rows


# --- Upload intents ----------------------------------------------------------------------------


def test_upload_goes_straight_to_private_storage_under_a_server_key(storage):
    headers, _ = user_session()
    created = create(headers, filename="Board Minutes (secret).pdf").json()
    url = urlparse(created["upload"]["url"])
    assert created["upload"]["method"] == "PUT"
    assert url.netloc == urlparse(storage.client.meta.endpoint_url).netloc  # storage, not the API
    key = storage_key(created["document"]["id"])
    assert key.startswith("uploads/") and "Board" not in key and "secret" not in url.path
    assert "X-Amz-Signature=" in url.query and "X-Amz-Expires=900" in url.query
    put_file(created)
    completed = client.post(
        f"{API}/documents/{created['document']['id']}/complete", headers=headers
    )
    assert completed.is_success


@pytest.mark.parametrize(
    "extra", [{"storage_key": "documents/mine.pdf"}, {"user_id": str(uuid.uuid4())}]
)
def test_client_cannot_choose_the_object_key_or_owner(storage, extra):
    headers, _ = user_session()
    assert create(headers, **extra).status_code == 422


def test_oversized_upload_intent_is_refused(storage):
    headers, _ = user_session()
    too_big = get_settings().max_upload_bytes + 1
    assert create(headers, size_bytes=too_big).status_code == 413


def test_another_session_cannot_complete_the_upload(storage):
    owner, _ = user_session()
    intruder, _ = user_session()
    created = create(owner).json()
    put_file(created)
    document_id = created["document"]["id"]
    url = f"{API}/documents/{document_id}/complete"
    assert client.post(url, headers=intruder).status_code == 404
    assert client.post(url, headers=owner).is_success


def test_wrong_checksum_never_becomes_ready(storage, report):
    headers, _ = user_session()
    document_id = ready_document(storage, headers, report, sha256="0" * 64)
    document, _ = state(uuid.UUID(document_id))
    assert document.status == DocumentStatus.FAILED


# --- Storage / database consistency ------------------------------------------------------------


def test_database_failure_after_the_copy_is_recoverable(storage, monkeypatch):
    headers, _ = user_session()
    created = create(headers).json()
    document_id = created["document"]["id"]
    put_file(created)
    upload_key = storage_key(document_id)

    def broken_job(**_):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(documents_module, "ProcessingJob", broken_job)
    failed = client.post(f"{API}/documents/{document_id}/complete", headers=headers)
    monkeypatch.undo()
    assert failed.status_code == 500
    with SessionLocal() as s:  # rolled back: still an upload, the uploaded bytes still there
        document = s.get_one(Document, uuid.UUID(document_id))
        assert document.status == DocumentStatus.UPLOADING and document.storage_key == upload_key
    assert storage.stat(upload_key) is not None

    retried = client.post(f"{API}/documents/{document_id}/complete", headers=headers)
    assert retried.status_code == 200  # the copy is deterministic, so retrying is safe
    final_key = storage_key(document_id)
    assert final_key.startswith("documents/") and storage.stat(final_key) is not None
    later = reconcile(storage, now=datetime.now(UTC) + timedelta(days=30))
    assert final_key not in later.orphan_objects


def test_storage_never_written_after_the_database_intent_is_cleaned_up(storage):
    headers, _ = user_session()
    document_id = create(headers).json()["document"]["id"]  # the PUT never happens
    complete = client.post(f"{API}/documents/{document_id}/complete", headers=headers)
    assert complete.status_code == 409  # detected: nothing uploaded
    with SessionLocal() as s, s.begin():
        s.execute(
            update(Document)
            .where(Document.id == uuid.UUID(document_id))
            .values(created_at=datetime.now(UTC) - timedelta(hours=2))
        )
    sweep_all(storage)
    with SessionLocal() as s:
        document = s.get(Document, uuid.UUID(document_id))
        assert document is not None and document.status == DocumentStatus.FAILED


def test_missing_object_is_detected_and_fails_permanently(storage, report):
    headers, _ = user_session()
    ready = uuid.UUID(ready_document(storage, headers, report))
    storage.delete(storage_key(str(ready)))
    assert ready in reconcile(storage).missing_objects

    created = create(
        headers, size_bytes=len(report), sha256=hashlib.sha256(report).hexdigest()
    ).json()
    put_file(created, report)
    document_id = created["document"]["id"]
    assert client.post(f"{API}/documents/{document_id}/complete", headers=headers).is_success
    storage.delete(storage_key(document_id))
    process_next(storage)
    document, job = state(uuid.UUID(document_id))
    assert document.status == DocumentStatus.FAILED and job.status == JobStatus.FAILED
    assert document.processing_error == "The uploaded file is missing. Upload it again."
    assert process_next(storage) is False  # not retried


def test_orphan_objects_are_deleted_only_when_old_and_under_our_prefixes(storage):
    orphan = f"documents/orphan-{uuid.uuid4()}.pdf"
    unrelated = f"elsewhere/{uuid.uuid4()}.pdf"
    for key in (orphan, unrelated):
        storage.upload(key, b"%PDF-1.4", "application/pdf")
    headers, _ = user_session()
    known = storage_key(create(headers).json()["document"]["id"])
    storage.upload(known, b"%PDF-1.4", "application/pdf")  # an in-progress upload

    recent = reconcile(storage, delete=True)
    assert orphan not in recent.deleted_objects and storage.stat(orphan) is not None

    later = reconcile(storage, delete=True, now=datetime.now(UTC) + timedelta(days=3))
    assert orphan in later.deleted_objects and storage.stat(orphan) is None
    assert storage.stat(unrelated) is not None  # never listed: not a Prospect prefix
    assert storage.stat(known) is not None  # has a database record


def test_dry_run_reports_without_deleting(storage):
    orphan = f"uploads/orphan-{uuid.uuid4()}.pdf"
    storage.upload(orphan, b"%PDF-1.4", "application/pdf")
    result = reconcile(storage, now=datetime.now(UTC) + timedelta(days=3))
    assert orphan in result.orphan_objects and storage.stat(orphan) is not None


# --- Authorization matrix ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(storage, tmp_path_factory):
    """One owner's resources of every kind, referenced by id."""
    from sample_pdf import build_sample_report

    data = build_sample_report(tmp_path_factory.mktemp("matrix") / "r.pdf").read_bytes()
    headers, token = user_session()
    owner = user_of(token)
    document = ready_document(storage, headers, data)
    fact = client.get(f"{API}/documents/{document}/metrics", headers=headers).json()["items"][0]
    company = make_company(owner, f"Matrix {uuid.uuid4()}")
    with SessionLocal() as s, s.begin():
        s.execute(
            update(Document).where(Document.id == uuid.UUID(document)).values(company_id=company)
        )
        scenario = Scenario(
            user_id=owner, document_id=uuid.UUID(document), name="s", base_period="FY2025"
        )
        issue = DataQualityIssue(
            user_id=owner, document_id=uuid.UUID(document), rule_type="t", severity="INFO",
            description="d",
        )  # fmt: skip
        s.add_all([scenario, issue, WatchlistEntry(user_id=owner, company_id=company)])
        s.flush()
        ids = {"scenario": scenario.id, "issue": issue.id}
    return {
        "headers": headers,
        "doc": document,
        "fact": fact["id"],
        "evidence": fact["evidence"]["id"],
        "company": company,
        **ids,
    }


# (method, path, body): every endpoint that takes another resource's id.
MATRIX = [
    ("GET", "/documents/{doc}", None),
    ("PATCH", "/documents/{doc}", {"company_name": "x"}),
    ("DELETE", "/documents/{doc}", None),
    ("POST", "/documents/{doc}/complete", None),
    ("GET", "/documents/{doc}/download-url", None),
    ("GET", "/documents/{doc}/pages", None),
    ("GET", "/documents/{doc}/pages/1", None),
    ("GET", "/documents/{doc}/sections", None),
    ("GET", "/documents/{doc}/metrics", None),
    ("GET", "/documents/{doc}/calculations", None),
    ("GET", "/documents/{doc}/financials", None),
    ("GET", "/documents/{doc}/financials?scope=company", None),
    ("GET", "/documents/{doc}/evidence/{evidence}", None),
    ("GET", "/documents/{doc}/export?format=json", None),
    ("GET", "/documents/{doc}/diff?other_id={doc}", None),
    ("POST", "/documents/diff", {"document_a_id": "{doc}", "document_b_id": "{doc}"}),
    ("GET", "/financial-facts/{fact}/history", None),
    ("POST", "/financial-facts/{fact}/accept", {}),
    ("POST", "/financial-facts/{fact}/correct", {"value": "1", "reason": "not mine"}),
    ("POST", "/financial-facts/{fact}/reject", {"reason": "not mine"}),
    ("GET", "/companies/{company}", None),
    ("PATCH", "/companies/{company}", {"name": "stolen"}),
    ("DELETE", "/companies/{company}", None),
    ("POST", "/companies/{company}/documents", {"document_id": "{doc}"}),
    ("DELETE", "/companies/{company}/documents/{doc}", None),
    ("GET", "/scenarios/{scenario}", None),
    ("PATCH", "/scenarios/{scenario}", {"name": "stolen"}),
    ("DELETE", "/scenarios/{scenario}", None),
    ("POST", "/scenarios/calculate", {"document_id": "{doc}", "base_period": "FY2025"}),
    ("PATCH", "/data-quality/{issue}", {"status": "IGNORED"}),
    ("POST", "/watchlist", {"company_id": "{company}"}),
    ("DELETE", "/watchlist/{company}", None),
]


def fill(value, ids):
    if isinstance(value, str):
        return value.format(**ids)
    if isinstance(value, dict):
        return {k: fill(v, ids) for k, v in value.items()}
    return value


@pytest.mark.parametrize(("method", "path", "body"), MATRIX)
def test_other_session_and_no_session_are_denied(workspace, method, path, body):
    url, json = API + fill(path, workspace), fill(body, workspace)
    other, _ = user_session()
    response = client.request(method, url, json=json, headers=other)
    assert response.status_code in (403, 404), (method, path, response.status_code)
    assert client.request(method, url, json=json).status_code == 401  # no session
    # The owner still sees everything unchanged.
    owner = workspace["headers"]
    assert client.get(f"{API}/documents/{workspace['doc']}", headers=owner).status_code == 200
    company = client.get(f"{API}/companies/{workspace['company']}", headers=owner).json()
    assert company["name"].startswith("Matrix")


@pytest.mark.parametrize(
    "path",
    [
        "/documents/{doc}",
        "/documents/{doc}/metrics",
        "/documents/{doc}/evidence/{evidence}",
        "/documents/{doc}/export?format=csv",
        "/documents/{doc}/download-url",
        "/financial-facts/{fact}/history",
        "/companies/{company}",
        "/scenarios/{scenario}",
    ],
)
def test_the_owner_is_allowed(workspace, path):
    assert client.get(API + fill(path, workspace), headers=workspace["headers"]).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/documents",
        "/companies",
        "/scenarios?document_id={doc}",
        "/financial-facts/review?document_id={doc}",
        "/data-quality?document_id={doc}",
        "/watchlist",
        "/audit?entity_id={doc}",
    ],
)
def test_lists_never_contain_another_sessions_rows(workspace, path):
    other, _ = user_session()
    response = client.get(API + fill(path, workspace), headers=other)
    assert response.status_code in (200, 404)
    for key in ("doc", "fact", "company", "scenario", "issue"):
        assert str(workspace[key]) not in response.text


def test_audit_trail_is_readable_only_by_its_owner(workspace):
    events = client.get(f"{API}/audit", headers=workspace["headers"]).json()["items"]
    assert events and len({e["user_id"] for e in events}) == 1
    assert client.get(f"{API}/audit").status_code == 401


# --- Configuration -----------------------------------------------------------------------------

REQUIRED = {
    "database_url": "postgresql://u:p@db/x",
    "object_storage_endpoint": "https://storage.example",
    "object_storage_bucket": "b",
    "object_storage_access_key": "k",
    "object_storage_secret_key": "s",
    "allowed_origins": "https://prospect.example",
    "document_scanner": "none",
}
STRONG = "Zq8r1vT3xK0pW7nL2cF9hJ4sD6gB5mY1aE8uR3tI0oP"


def production(**overrides):
    base = REQUIRED | {"environment": "production", "app_secret": STRONG}
    return Settings(_env_file=None, **(base | overrides))


def test_api_needs_its_secrets_the_worker_does_not(monkeypatch):
    for name in ("APP_SECRET", "TRUSTED_PROXY_SECRET"):
        monkeypatch.delenv(name, raising=False)
    worker = production(app_secret=None)  # the worker's settings: no APP_SECRET, no proxy secret
    assert worker.app_secret is None
    assert api_problems(worker) == [
        "APP_SECRET is required",
        "TRUSTED_PROXY_SECRET is required in production (else every browser shares the proxy's "
        "IP for rate limits)",
    ]
    assert api_problems(production(trusted_proxy_secret=STRONG[::-1])) == []
    # On Vercel there is no web proxy, so there is no proxy secret to require (docs/ADR-006).
    assert api_problems(production(vercel=True)) == []


@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"app_secret": "ci"}, "APP_SECRET is not safe"),
        ({"trusted_proxy_secret": "short"}, "TRUSTED_PROXY_SECRET is not safe"),
        ({"object_storage_endpoint": "http://storage.example"}, "OBJECT_STORAGE_ENDPOINT"),
        ({"document_retention_days": None}, "DOCUMENT_RETENTION_DAYS"),
        ({"session_cookie_secure": False}, "SESSION_COOKIE_SECURE"),
    ],
)
def test_insecure_production_settings_refuse_to_start(override, problem):
    with pytest.raises(ValidationError, match=problem):
        production(**override)


def test_test_environment_is_not_production():
    Settings(_env_file=None, **(REQUIRED | {"environment": "test", "app_secret": "ci"}))


def test_api_process_refuses_to_start_without_app_secret(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "APP_SECRET"}
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    run = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        env=env,
        cwd=tmp_path,  # no .env file here
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode != 0 and "APP_SECRET is required" in run.stderr


# --- Anonymous-session abuse -------------------------------------------------------------------


def test_new_sessions_do_not_reset_the_per_ip_upload_limit(storage, tune):
    tune(trusted_proxy_secret=SecretStr(PROXY), rate_limit_uploads_ip="3/3600")
    ip = fresh_ip()
    statuses = []
    for _ in range(5):  # a fresh anonymous session for every upload
        headers, _ = user_session()
        statuses.append(create(via_proxy(ip, headers)).status_code)
    assert statuses == [201, 201, 201, 429, 429]


def test_concurrent_sessions_cannot_exceed_the_per_ip_upload_limit(storage, tune):
    tune(trusted_proxy_secret=SecretStr(PROXY), rate_limit_uploads_ip="3/3600")
    ip = fresh_ip()
    sessions = [user_session()[0] for _ in range(8)]

    def attempt(headers):
        return create(via_proxy(ip, headers)).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, sessions))
    assert statuses.count(201) == 3 and statuses.count(429) == 5


def test_daily_session_creation_is_capped_per_ip(tune):
    tune(trusted_proxy_secret=SecretStr(PROXY), rate_limit_sessions_daily="3/86400")
    ip = fresh_ip()
    statuses = [client.post(f"{API}/sessions", headers=via_proxy(ip)).status_code for _ in range(4)]
    assert statuses == [201, 201, 201, 429]


def test_the_global_processing_queue_is_capped(storage, tune):
    headers, _ = user_session()
    created = create(headers).json()
    put_file(created)
    with SessionLocal() as s:
        queued = s.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        )
    tune(quota_max_queued_jobs=queued or 0)
    url = f"{API}/documents/{created['document']['id']}/complete"
    response = client.post(url, headers=headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "quota_exceeded"


def test_company_scope_is_owned_before_it_is_grouped():
    headers, token = user_session()
    _, other = user_session()
    shared = f"Same Name {uuid.uuid4()}"
    mine = make_document(user_of(token), shared, make_company(user_of(token), shared))
    theirs = make_document(user_of(other), shared, make_company(user_of(other), shared))
    view = client.get(f"{API}/documents/{mine}/financials?scope=company", headers=headers).json()
    assert [d["id"] for d in view["documents"]] == [str(mine)]
    assert client.get(f"{API}/documents/{theirs}/financials", headers=headers).status_code == 404


# --- Non-ASCII credentials (header values decode as latin-1) ----------------------------------


def test_non_ascii_credentials_are_rejected_not_a_server_error(tune):
    headers, token = user_session()
    weird = token[:-1] + "é"
    raw = {"Authorization": f"Bearer {weird}".encode("latin-1")}
    assert client.get(f"{API}/documents", headers=raw).status_code == 401
    browser = TestClient(app, base_url="https://testserver")
    csrf = browser.post(f"{API}/sessions", headers={"Origin": "http://localhost:3000"}).json()
    bad_csrf = {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": ("é" + csrf["csrf_token"]).encode("latin-1"),
    }
    assert browser.post(f"{API}/sessions/refresh", headers=bad_csrf).status_code == 403
    tune(trusted_proxy_secret=SecretStr(PROXY))
    spoof = {PROXY_SECRET_HEADER: "é" * 10, CLIENT_IP_HEADER: "203.0.113.9"}
    assert client_ip(request_with(spoof)) == "10.1.2.3"
