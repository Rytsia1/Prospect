"""P2 adversarial security tests (docs/SECURITY_P2_AUDIT.md).

Two kinds of test live here:
- attacks that were tried and resisted: ordinary regression tests;
- confirmed findings, not yet remediated: `xfail(strict=True)` tests that assert the SECURE
  behaviour. They fail today (the evidence), and turn into an XPASS error the moment the fix
  lands, so the marker must then be removed. Never "fix" one by weakening the assertion.

Everything is bounded and seeded (CI-safe). Needs TEST_DATABASE_URL (a migrated database).
"""

import hashlib
import os
import random
import threading
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_documents import create, put_file
from test_p15 import fill, workspace  # noqa: F401 (module fixture: one owner's resources)
from test_security import API, ready_document, user_session
from test_security_p1 import TRUSTED, browser, make_company, user_of
from test_worker import only_this_tests_jobs  # noqa: F401 (autouse fixture)

import app.quality as quality
import app.worker as worker
from app.db import SessionLocal
from app.main import app
from app.models import DataQualityIssue, Document, ProcessingJob
from app.pipeline import Limits, analyze
from app.processing import ProcessingError
from app.sandbox import run_isolated

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)
client = TestClient(app, raise_server_exceptions=False)  # a 500 is a result, not a crash


def finding(ref: str):
    return pytest.mark.xfail(strict=True, reason=f"{ref}: open (docs/SECURITY_P2_AUDIT.md)")


def parallel(n: int, call) -> list[int]:
    with ThreadPoolExecutor(n) as pool:
        return sorted(r.status_code for r in pool.map(lambda _: call(), range(n)))


@pytest.fixture(scope="module")
def attacker(storage, report):
    """A session with its own READY document (revenue accepted), ready to mix in foreign ids."""
    headers, _ = user_session()
    document = ready_document(storage, headers, report, filename="年度报告 2025.pdf")
    facts = client.get(f"{API}/documents/{document}/metrics?limit=200", headers=headers).json()
    revenue = [f for f in facts["items"] if f["metric"] == "revenue"]
    for fact in revenue:
        client.post(f"{API}/financial-facts/{fact['id']}/accept", json={}, headers=headers)
    return {"headers": headers, "doc": document, "period": revenue[0]["period_label"],
            "facts": facts["items"]}  # fmt: skip


# --- Anonymous session attacks (resisted) --------------------------------------------------------


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_signature_cannot_be_moved_to_another_session_or_a_later_expiry():
    _, mine = user_session()
    _, theirs = user_session()
    m, t = mine.split("."), theirs.split(".")
    swapped = ".".join([m[0], t[1], m[2], m[3], m[4]])  # my signature, their session id
    extended = ".".join([*m[:3], "9999999999", m[4]])
    for token in (swapped, extended, "v2" + mine[2:], mine[:-64] + mine[-64:].upper()):
        assert client.get(f"{API}/documents", headers=_bearer(token)).status_code == 401


@pytest.mark.parametrize("cookie", ["", "x", "v1." + "a" * 8000])
def test_empty_garbage_and_oversized_credentials_are_just_unauthenticated(cookie):
    b = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    b.cookies.set("__Host-prospect_session", cookie)
    assert b.get(f"{API}/documents").status_code == 401
    assert client.get(f"{API}/documents", headers=_bearer("a." * 30000)).status_code == 401


# --- CSRF bypass attempts (resisted) ----------------------------------------------------------


def test_csrf_bypass_variants_are_refused():
    b, token = browser()

    def post(headers, content=None):
        json = None if content else {"name": uuid.uuid4().hex}
        return b.post(f"{API}/companies", json=json, content=content, headers=headers).status_code

    assert post({"Origin": TRUSTED, "X-CSRF-Token": token}) == 201  # control
    for headers in (
        {"Origin": TRUSTED, "X-CSRF-Token": f"{token}, {token}"},  # duplicated
        {"Origin": TRUSTED, "X-CSRF-Token": token.upper()},
        {"Origin": TRUSTED, "X-CSRF-Token": ""},
        {"Referer": TRUSTED + ".evil.example/x", "X-CSRF-Token": token},  # prefix trick
        {"Referer": TRUSTED.replace("://", "://evil.example@") + "/", "X-CSRF-Token": token},
        {"Origin": "null", "X-CSRF-Token": token},
        {"Origin": "file://", "X-CSRF-Token": token},
    ):
        assert post(headers) == 403, headers
    # a "simple" cross-site request: text/plain body, no custom header
    assert post({"Origin": TRUSTED, "Content-Type": "text/plain"}, '{"name": "x"}') == 403
    # the token of a replaced session dies with it
    refreshed = b.post(
        f"{API}/sessions/refresh", headers={"Origin": TRUSTED, "X-CSRF-Token": token}
    )
    assert refreshed.status_code == 200
    assert post({"Origin": TRUSTED, "X-CSRF-Token": token}) == 403


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "file://", TRUSTED + ".evil.example"]
)
def test_cors_never_lets_a_foreign_page_read_responses(origin):
    headers, _ = user_session()
    preflight = client.options(
        f"{API}/documents", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )
    read = client.get(f"{API}/documents", headers=headers | {"Origin": origin})
    for response in (preflight, read):
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-credentials" not in response.headers


# --- Method / path variants (resisted) --------------------------------------------------------


def test_alternative_methods_and_paths_reach_no_handler():
    headers, _ = user_session()
    target = f"{API}/documents/{uuid.uuid4()}"
    for method in ("PUT", "OPTIONS", "HEAD", "TRACE"):
        assert client.request(method, target, headers=headers).status_code == 405
    for path in (f"{API}//documents", f"{API}/DOCUMENTS", f"{API}/documents%2F{uuid.uuid4()}"):
        assert client.get(path, headers=headers).status_code == 404


# --- Races (resisted) -------------------------------------------------------------------------


def test_concurrent_completes_queue_one_job_and_concurrent_deletes_delete_once(storage):
    headers, _ = user_session()
    created = create(headers).json()
    put_file(created)
    document = created["document"]["id"]
    complete = f"{API}/documents/{document}/complete"
    assert parallel(8, lambda: client.post(complete, headers=headers)) == [200] * 8
    with SessionLocal() as s:
        jobs = select(func.count()).where(ProcessingJob.document_id == uuid.UUID(document))
        assert s.scalar(jobs) == 1
    delete = f"{API}/documents/{document}"
    assert parallel(8, lambda: client.delete(delete, headers=headers)) == [204] + [404] * 7
    assert client.post(complete, headers=headers).status_code == 404  # no resurrection


def _start_processing(report, headers) -> str:
    sha = hashlib.sha256(report).hexdigest()
    created = create(headers, size_bytes=len(report), sha256=sha).json()
    put_file(created, report)
    document = created["document"]["id"]
    assert client.post(f"{API}/documents/{document}/complete", headers=headers).status_code == 200
    return document


def _delete_while_parsing(monkeypatch, headers, document):
    parse = worker.run_isolated

    def parse_then_delete(*args, **kwargs):
        result = parse(*args, **kwargs)
        assert client.delete(f"{API}/documents/{document}", headers=headers).status_code == 204
        return result

    monkeypatch.setattr(worker, "run_isolated", parse_then_delete)


def test_deleting_during_processing_never_resurrects_the_document(storage, report, monkeypatch):
    headers, _ = user_session()
    document = _start_processing(report, headers)
    _delete_while_parsing(monkeypatch, headers, document)
    try:
        worker.process_next(storage)
    except Exception:  # noqa: S110 (P2-F7 below; the outcome under test is the database state)
        pass
    with SessionLocal() as s:
        assert s.get(Document, uuid.UUID(document)) is None


@finding("P2-F7")
def test_worker_handles_a_document_deleted_mid_processing(storage, report, monkeypatch):
    headers, _ = user_session()
    document = _start_processing(report, headers)
    _delete_while_parsing(monkeypatch, headers, document)
    assert worker.process_next(storage) is True  # today: NoResultFound escapes process_next


# --- Malicious PDFs (bounded; resisted) -------------------------------------------------------

LIMITS = Limits(
    max_pages=2000, max_text_bytes=50_000_000, max_table_cells=500_000, max_facts=5000,
    max_evidence=5000, max_row_chars=2000,
)  # fmt: skip


def _raw_pdf(objects: list[bytes]) -> bytes:
    out, offsets = b"%PDF-1.7\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    trailer = b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
    return out + trailer % (len(objects) + 1, xref)


def _page_pdf(content: bytes, root=b"", page=b"", compress=False, more=()) -> bytes:
    stream = zlib.compress(content, 9) if compress else content
    flate = b"/Filter /FlateDecode " if compress else b""
    return _raw_pdf([
        b"<< /Type /Catalog /Pages 2 0 R " + root + b">>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> " + page + b">>",
        b"<< " + flate + b"/Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        *more,
    ])  # fmt: skip


NESTED_ARRAY = b"[" * 100_000 + b"]" * 100_000
NESTED_DICT = b"<< /A " * 30_000 + b">> " * 30_000
HOSTILE_PDFS = {
    "flate_bomb": lambda: _page_pdf(b" " * 50_000_000, compress=True),
    "deep_array_nesting": lambda: _page_pdf(b"BT ET", page=b"/X " + NESTED_ARRAY),
    "deep_dict_nesting": lambda: _page_pdf(b"BT ET", page=b"/X " + NESTED_DICT),
    "page_tree_cycle": lambda: _raw_pdf(
        [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [2 0 R] /Count 1 >>"]
    ),
    "lying_page_count": lambda: _raw_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 999999999 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1 1] >>",
    ]),
    "javascript_launch_uri_embedded_file": lambda: _page_pdf(
        b"BT /F1 12 Tf 72 700 Td (Revenue 100 90) Tj ET",
        root=b"/OpenAction << /S /JavaScript /JS (app.alert(1)) >> "
        b"/Names << /EmbeddedFiles << /Names [(x.exe) 6 0 R] >> >> ",
        page=b"/Annots [<< /Subtype /Link /Rect [0 0 9 9] /A << /S /URI "
        b"/URI (http://169.254.169.254/latest/meta-data/) >> >> "
        b"<< /Subtype /Link /Rect [0 0 9 9] /A << /S /Launch /F (cmd.exe) >> >>]",
        more=[b"<< /Type /Filespec /F (x.exe) /EF << /F 7 0 R >> >>",
              b"<< /Type /EmbeddedFile /Length 2 >>\nstream\nMZ\nendstream"],
    ),
    "external_image_reference": lambda: _page_pdf(
        b"q /Im1 Do Q", page=b"/Resources << /XObject << /Im1 6 0 R >> >>",
        more=[b"<< /Subtype /Image /Width 1 /Height 1 /BitsPerComponent 8 /ColorSpace "
              b"/DeviceGray /F (http://127.0.0.1:9/x) /Length 0 >>\nstream\n\nendstream"],
    ),
    "corrupt_xref_and_stream": lambda: (
        b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Length 999999 >>\nstream\n\xff\xfe" + b"\x00" * 5000 + b"\nxref\n?\n%%EOF"
    ),
    "many_objects": lambda: _raw_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1 1] >>",
        *(b"<< /N %d >>" % i for i in range(50_000)),
    ]),
}  # fmt: skip


@pytest.mark.parametrize("name", HOSTILE_PDFS)
def test_hostile_pdf_ends_as_a_result_or_a_safe_rejection(name, tmp_path):
    """Bounded time, this (the worker's) process survives, never a raw exception message. None
    makes a network request: PyMuPDF has no network code and neither has the app; the external
    references point at a closed local port and the link-local metadata address."""
    path = tmp_path / "hostile.pdf"
    path.write_bytes(HOSTILE_PDFS[name]())
    started = time.monotonic()
    try:
        analysis = run_isolated(analyze, (path, LIMITS), 30)
        assert len(analysis.facts) <= LIMITS.max_facts
    except ProcessingError as e:  # includes the timeout, resource-limit and crashed-child cases
        assert "Traceback" not in str(e) and "\\" not in str(e)
    assert time.monotonic() - started < 30


# --- Confirmed findings (xfail until remediated) -----------------------------------------------


@finding("P2-F1")
def test_oversized_request_bodies_are_refused_before_they_are_parsed():
    body = b'{"name": "' + b"a" * (8 * 1024 * 1024)  # 8 MiB, malformed on purpose, no session
    response = client.post(
        f"{API}/companies", content=body, headers={"Content-Type": "application/json"}
    )
    # today: 422 json_invalid, i.e. read and decoded in full before authentication
    assert response.status_code in (401, 413)


@finding("P2-F2")
def test_free_text_fields_are_bounded():
    headers, _ = user_session()
    big = client.post(
        f"{API}/companies",
        json={"name": uuid.uuid4().hex, "description": "a" * (2 * 1024 * 1024)},
        headers=headers,
    )
    assert big.status_code == 422  # today: 201, stored and echoed back


@finding("P2-F2")
def test_company_creation_is_rate_limited(tune):
    tune(rate_limit_compute="5/60")  # the nearest existing bucket; any per-user bucket will do
    headers, _ = user_session()
    statuses = {
        client.post(
            f"{API}/companies", json={"name": uuid.uuid4().hex}, headers=headers
        ).status_code
        for _ in range(10)
    }
    assert 429 in statuses  # today: 10 × 201, no limit of any kind


@finding("P2-F3")
def test_scenario_cannot_reference_another_sessions_company(attacker):
    _, token = user_session()
    company = make_company(user_of(token), f"Victim {uuid.uuid4()}")
    body = {"document_id": attacker["doc"], "company_id": str(company), "name": "x",
            "base_period": attacker["period"], "growth_adjustment": "0"}  # fmt: skip
    foreign = client.post(f"{API}/scenarios", json=body, headers=attacker["headers"])
    unknown = client.post(
        f"{API}/scenarios",
        json=body | {"company_id": str(uuid.uuid4())},
        headers=attacker["headers"],
    )
    # today: 201 (stored as given) vs 500 (foreign-key violation): an existence oracle
    assert (foreign.status_code, unknown.status_code) == (404, 404)


@finding("P2-F4")
@pytest.mark.parametrize("fmt", ["csv", "json", "xlsx"])
def test_export_of_a_non_latin_filename_succeeds(attacker, fmt):
    response = client.get(
        f"{API}/documents/{attacker['doc']}/export?format={fmt}", headers=attacker["headers"]
    )
    assert response.status_code == 200  # today: 500 (header value not latin-1 encodable)
    assert response.headers["content-disposition"].isascii()


@finding("P2-F5")
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/financial-facts/{fact}/correct", {"value": "1e200000", "reason": "overflow"}),
        ("POST", "/financial-facts/{fact}/correct", {"value": "1e-200000", "reason": "underflow"}),
        ("POST", "/financial-facts/{fact}/accept", {"reason": "nul \x00 byte"}),
        ("PATCH", "/documents/{doc}", {"company_name": "nul \x00 byte"}),
        ("POST", "/scenarios", {"document_id": "{doc}", "name": "x", "base_period": "{period}",
                                "growth_adjustment": "0", "target_margin": "1e999999"}),
    ],
)  # fmt: skip
def test_hostile_values_are_rejected_not_a_server_error(attacker, method, path, body):
    ids = {"fact": attacker["facts"][-1]["id"], "doc": attacker["doc"],
           "period": attacker["period"]}  # fmt: skip
    response = client.request(
        method, API + fill(path, ids), json=fill(body, ids), headers=attacker["headers"]
    )
    assert response.status_code == 422  # today: 500


@finding("P2-F5")
def test_uniqueness_races_and_conflicts_are_409_not_500():
    headers, _ = user_session()
    name = uuid.uuid4().hex

    def create_company():
        return client.post(f"{API}/companies", json={"name": name}, headers=headers)

    assert 500 not in parallel(8, create_company)  # today: IntegrityError → 500 for the losers
    company = client.post(f"{API}/companies", json={"name": "W" + name}, headers=headers).json()

    def watch():
        return client.post(f"{API}/watchlist", json={"company_id": company["id"]}, headers=headers)

    assert 500 not in parallel(8, watch)
    rename = client.patch(f"{API}/companies/{company['id']}", json={"name": name}, headers=headers)
    assert rename.status_code == 409


@finding("P2-F6")
def test_concurrent_data_quality_reads_do_not_duplicate_issues(storage, report, monkeypatch):
    headers, _ = user_session()
    document = ready_document(storage, headers, report)
    # Line both requests up right before their check-then-insert, as a real race would.
    barrier, detect = threading.Barrier(2, timeout=10), quality.detect_document_anomalies

    def detect_together(*args):
        found = detect(*args)
        barrier.wait()
        return found

    monkeypatch.setattr(quality, "detect_document_anomalies", detect_together)
    url = f"{API}/data-quality?document_id={document}"
    assert parallel(2, lambda: client.get(url, headers=headers)) == [200, 200]
    with SessionLocal() as s:
        per_key = s.scalars(
            select(func.count())
            .where(DataQualityIssue.document_id == uuid.UUID(document))
            .group_by(DataQualityIssue.rule_type, DataQualityIssue.metric, DataQualityIssue.period)
        )
        assert set(per_key) <= {1}  # today: the same issue stored several times


# --- Bounded fuzzing --------------------------------------------------------------------------

FUZZ_VALUES = [
    "", "a" * 5000, "<img src=x onerror=alert(1)>", "\"><svg/onload=alert(1)>", "javascript:x",
    "=cmd|' /C calc'!A0", "../../etc/passwd", "\x1b[31m‮", "FY2025", "IDR", 0, -1, 2**63,
    10**40, 1.5e308, -0.0, True, None, [], [1] * 50, {}, {"a": {"b": [None]}}, "NaN", "Infinity",
    str(uuid.UUID(int=0)), "not-a-uuid", "accepted", "RESOLVED", "millions",
]  # fmt: skip
# Deliberately absent: NUL bytes and out-of-range exponents, already recorded as P2-F5.
FUZZ_TARGETS = [
    ("POST", "/documents", ["filename", "content_type", "size_bytes", "sha256", "document_type",
                            "fiscal_year", "company_name"]),
    ("PATCH", "/documents/{doc}", ["company_name"]),
    ("POST", "/documents/diff", ["document_a_id", "document_b_id"]),
    ("POST", "/financial-facts/{fact}/accept", ["reason"]),
    ("POST", "/financial-facts/{fact}/correct", ["value", "currency", "scale", "period_type",
                                                 "period_label", "metric_key", "reason"]),
    ("POST", "/financial-facts/{fact}/reject", ["reason"]),
    ("PATCH", "/data-quality/{issue}", ["status", "reason"]),
    ("POST", "/scenarios/calculate", ["document_id", "base_period", "growth_adjustment",
                                      "margin_adjustment", "target_margin"]),
    ("POST", "/scenarios", ["document_id", "company_id", "name", "base_period",
                            "growth_adjustment", "margin_adjustment", "assumptions"]),
    ("POST", "/companies", ["name", "ticker", "country", "currency", "description"]),
    ("PATCH", "/companies/{company}", ["ticker", "country", "currency", "description"]),
    ("POST", "/companies/{company}/documents", ["document_id"]),
    ("POST", "/watchlist", ["company_id"]),
]  # fmt: skip


def test_seeded_fuzz_never_produces_a_server_error_or_leaks_details(workspace):  # noqa: F811
    rng = random.Random(20260928)  # reproducible
    ids = {k: str(v) for k, v in workspace.items() if k != "headers"}
    values = FUZZ_VALUES + list(ids.values())
    failures = []
    for i in range(420):  # bounded
        method, path, fields = FUZZ_TARGETS[i % len(FUZZ_TARGETS)]
        body = {f: rng.choice(values) for f in rng.sample(fields, rng.randint(0, len(fields)))}
        response = client.request(
            method, API + fill(path, ids), json=body, headers=workspace["headers"]
        )
        leaked = "Traceback" in response.text or "sqlalchemy" in response.text.lower()
        if response.status_code >= 500 or leaked:
            failures.append((method, path, body, response.status_code))
    assert failures == []
