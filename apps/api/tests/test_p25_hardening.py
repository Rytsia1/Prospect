"""P2.5 regression tests: the parser boundary, resource limits, temporary files, filenames,
deletion, financial-data integrity, database limits and least privilege (docs/SECURITY_P2_5.md).

Unit and local-integration tests only (PostgreSQL + moto). What only real infrastructure can
show (R2 signed-URL enforcement, bucket privacy) is in tests/integration/test_r2.py (opt-in);
nothing here is production verification. Needs TEST_DATABASE_URL (a migrated database).
"""

import fractions
import os
import pickle
import re
import secrets
import socket
import sys
import tempfile
import uuid
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, exc, make_url, select, text
from test_documents import create
from test_p15 import production
from test_security import API, ready_document, user_session
from test_security_p1 import user_of
from test_worker import only_this_tests_jobs  # noqa: F401 (autouse fixture)

from app import sandbox
from app.db import SessionLocal, engine
from app.main import app
from app.models import AuditEvent, Document, DocumentStatus, JobStatus, ProcessingJob
from app.processing import ProcessingLimitError, parse_pdf
from app.sandbox import ProcessingCrashed, run_isolated

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)
client = TestClient(app, raise_server_exceptions=False)
DB_ROLES_SQL = Path(__file__).resolve().parent.parent / "deploy" / "db_roles.sql"


# --- Parser boundary --------------------------------------------------------------------------

SECRETS = (
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
    "APP_SECRET",
    "TRUSTED_PROXY_SECRET",
)


@pytest.mark.parametrize("name", SECRETS)
def test_the_parser_process_holds_no_secrets(monkeypatch, name):
    monkeypatch.setenv(name, "must-not-reach-the-parser")  # present in the worker, for sure
    assert run_isolated(os.getenv, name, timeout_seconds=60) is None


class _Payload:
    def __reduce__(self):
        return (os.system, ("echo pwned",))


def test_output_from_the_parser_is_never_unpickled_freely():
    with pytest.raises(pickle.UnpicklingError):
        sandbox.load_result(pickle.dumps((("ok", _Payload()), False)))
    # End to end: a result of a type outside the allowlist is refused, not rebuilt.
    with pytest.raises(ProcessingCrashed):
        run_isolated(fractions.Fraction, "1/3", timeout_seconds=60)


def test_parser_output_is_size_limited():
    with pytest.raises(ProcessingLimitError, match="exceeds the processing limit"):
        run_isolated(bytes, 10_000, timeout_seconds=60, max_result_bytes=1_000)


def test_a_hostile_result_file_cannot_hang_or_flood_the_worker(tmp_path):
    big = tmp_path / "big"
    big.write_bytes(b"x" * 10_000)
    assert len(sandbox._read_result(big, 100)) == 101  # read stops right past the cap
    folder = tmp_path / "folder"
    folder.mkdir()
    with pytest.raises(ProcessingCrashed):
        sandbox._read_result(folder, 100)  # not a regular file
    if sys.platform != "win32":
        link = tmp_path / "link"
        link.symlink_to("/dev/zero")  # would never end
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)  # would block forever
        for hostile in (link, fifo):
            with pytest.raises(ProcessingCrashed):
                sandbox._read_result(hostile, 100)


@pytest.mark.skipif(sys.platform == "linux", reason="Linux may provide the namespace")
def test_required_network_isolation_fails_closed_where_unavailable():
    with pytest.raises(ProcessingCrashed):
        run_isolated(abs, -1, timeout_seconds=60, network="required")


@pytest.mark.skipif(sys.platform != "linux", reason="network namespaces are Linux-only")
def test_the_parser_has_no_network_where_namespaces_are_available():
    with socket.create_server(("127.0.0.1", 0)) as server:
        address = server.getsockname()[:2]
        assert sandbox.can_connect(address)  # control: the worker itself can connect
        try:
            reached = run_isolated(sandbox.can_connect, address, 60, network="required")
        except ProcessingCrashed:
            pytest.skip("this host does not allow unprivileged user namespaces")
        assert reached is False


# --- Hostile PDF structure and resource limits ------------------------------------------------


def _pdf(page_count: int, content: bytes, extra_objects: int = 0) -> bytes:
    """`page_count` pages sharing ONE compressed content stream: a small file whose text grows
    with every page (repeated-object amplification)."""
    stream = zlib.compress(content, 9)
    kids = " ".join(f"{5 + i} 0 R" for i in range(page_count)).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % page_count,
        b"<< /Filter /FlateDecode /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        *(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 3 0 R "
            b"/Resources << /Font << /F1 4 0 R >> >> >>"
            for _ in range(page_count)
        ),
        *(b"<< /N %d >>" % i for i in range(extra_objects)),
    ]
    out, offsets = b"%PDF-1.7\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    trailer = b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
    return out + trailer % (len(objects) + 1, xref)


LINES = b"".join(
    b"BT /F1 9 Tf 20 %d Td (%s) Tj ET\n" % (770 - 11 * i, b"W" * 90) for i in range(68)
)


@pytest.fixture
def amplified(tmp_path) -> Path:
    path = tmp_path / "amplified.pdf"
    path.write_bytes(_pdf(400, LINES))  # a few KB on disk, megabytes of text once extracted
    return path


def test_repeated_objects_cannot_expand_past_the_text_limit(amplified):
    assert amplified.stat().st_size < 100_000  # 400 page objects; one content stream
    with pytest.raises(ProcessingLimitError, match="extracted-text limit"):
        parse_pdf(amplified, max_text_bytes=500_000)


def test_excessive_page_count_is_refused_before_pages_load(amplified):
    with pytest.raises(ProcessingLimitError, match="more than 100 pages"):
        parse_pdf(amplified, max_pages=100)


def test_object_flood_is_refused_before_pages_load(tmp_path):
    path = tmp_path / "objects.pdf"
    path.write_bytes(_pdf(1, LINES, extra_objects=5_000))
    with pytest.raises(ProcessingLimitError, match="more than 1000 objects"):
        parse_pdf(path, max_objects=1_000)


class RecordingTemporaryDirectory(tempfile.TemporaryDirectory):
    made: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        RecordingTemporaryDirectory.made.append(self.name)


@pytest.mark.parametrize("outcome", ["success", "malformed", "timeout"])
def test_temporary_files_are_removed_and_the_job_never_stays_processing(
    storage, report, tune, monkeypatch, outcome
):
    RecordingTemporaryDirectory.made = []
    monkeypatch.setattr(tempfile, "TemporaryDirectory", RecordingTemporaryDirectory)
    if outcome == "timeout":
        tune(processing_timeout_seconds=0.05)  # far shorter than starting the parser
    data = b"%PDF-1.7\n" + os.urandom(2000) if outcome == "malformed" else report
    headers, _ = user_session()
    document_id = uuid.UUID(ready_document(storage, headers, data))
    with SessionLocal() as s:
        document = s.get_one(Document, document_id)
        job = s.scalar(select(ProcessingJob).where(ProcessingJob.document_id == document_id))
    succeeded = outcome == "success"
    assert document.status == (DocumentStatus.READY if succeeded else DocumentStatus.FAILED)
    assert job is not None
    assert job.status == (JobStatus.SUCCEEDED if succeeded else JobStatus.FAILED)
    if outcome == "timeout":
        assert "took too long" in (document.processing_error or "")
    made = RecordingTemporaryDirectory.made
    assert len(made) >= 2  # the worker's download directory and the parser's own
    assert not any(Path(p).exists() for p in made)


# --- Filenames --------------------------------------------------------------------------------

HOSTILE_FILENAMES = [
    "../../secret.pdf",
    "..\\..\\secret.pdf",
    "/etc/passwd",
    "C:\\Windows\\win.ini",
    "%2e%2e%2fsecret.pdf",
    "nul\x00byte.pdf",
    "<script>alert(1)</script>.pdf",
    '"',
    "'",
    "line\nbreak.pdf",
    "carriage\rreturn.pdf",
    "invoice" + chr(0x202E) + "fdp.exe",
    "a" * 990 + ".pdf",  # longer than the 255 shown; the request cap is 1000
]
SERVER_KEY = re.compile(r"^uploads/[A-Za-z0-9_-]{32}\.pdf$")


@pytest.mark.parametrize("filename", HOSTILE_FILENAMES)
def test_hostile_filenames_are_display_text_only(filename):
    headers, _ = user_session()
    created = create(headers, filename=filename)
    assert created.status_code == 201
    document = created.json()["document"]
    with SessionLocal() as s:
        key = s.get_one(Document, uuid.UUID(document["id"])).storage_key
    assert SERVER_KEY.match(key)  # never derived from the name
    shown = document["filename"]
    assert len(shown) <= 255 and "/" not in shown and "\\" not in shown
    assert not any(ord(c) < 32 or 0x202A <= ord(c) <= 0x202E for c in shown)


def test_duplicate_filenames_get_distinct_objects():
    headers, _ = user_session()
    one, two = (create(headers, filename="Report.pdf").json() for _ in range(2))
    with SessionLocal() as s:
        keys = {s.get_one(Document, uuid.UUID(d["document"]["id"])).storage_key for d in (one, two)}
    assert len(keys) == 2


# --- Deletion and financial-data integrity ----------------------------------------------------


def _accept(headers, document, metrics) -> str:
    """Accept the FY2025 facts of `metrics`; returns the id of another fact to play with."""
    facts = client.get(f"{API}/documents/{document}/metrics?limit=200", headers=headers).json()
    items = facts["items"]
    chosen = [f for f in items if f["metric"] in metrics and f["period_label"] == "FY2025"]
    assert {f["metric"] for f in chosen} == set(metrics)
    for fact in chosen:
        accepted = client.post(
            f"{API}/financial-facts/{fact['id']}/accept", json={}, headers=headers
        )
        assert accepted.status_code == 200
    return next(f["id"] for f in items if f not in chosen)


def test_deleting_a_document_leaves_no_copy_of_its_data_reachable(storage, report):
    headers, token = user_session()
    document = ready_document(storage, headers, report)
    other_fact = _accept(headers, document, {"revenue", "net_income"})
    marker = "424242.123456"
    corrected = client.post(
        f"{API}/financial-facts/{other_fact}/correct",
        json={"value": marker, "reason": "check deletion"},
        headers=headers,
    )
    assert corrected.status_code == 200
    company = client.post(f"{API}/companies", json={"name": f"Co {uuid.uuid4()}"}, headers=headers)
    company_id = company.json()["id"]
    linked = client.post(
        f"{API}/companies/{company_id}/documents", json={"document_id": document}, headers=headers
    )
    assert linked.status_code == 200
    # Built from the company only: before P2.5 this kept copied values after the delete.
    scenario = client.post(
        f"{API}/scenarios",
        json={"company_id": company_id, "name": "s", "base_period": "FY2025",
              "growth_adjustment": "0.1"},
        headers=headers,
    )  # fmt: skip
    assert scenario.status_code == 201
    evidence = client.get(f"{API}/documents/{document}/metrics", headers=headers).json()
    evidence_id = evidence["items"][0]["evidence"]["id"]

    assert client.delete(f"{API}/documents/{document}", headers=headers).status_code == 204

    for path in (
        f"/documents/{document}",
        f"/documents/{document}/download-url",
        f"/documents/{document}/evidence/{evidence_id}",
        f"/documents/{document}/export?format=json",
        f"/financial-facts/{other_fact}/history",
        f"/scenarios/{scenario.json()['id']}",
    ):
        assert client.get(API + path, headers=headers).status_code == 404, path
    trail = client.get(f"{API}/audit?limit=200", headers=headers)
    assert marker not in trail.text and "Annual Report" not in trail.text
    events = {e["event_type"] for e in trail.json()["items"]}
    assert {"document_created", "document_deleted"} <= events  # the security record stays
    with SessionLocal() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.user_id == user_of(token)))
        assert not [e for e in rows if e.before_value or e.after_value]


def test_missing_net_income_is_never_treated_as_zero(storage, report):
    headers, _ = user_session()
    document = ready_document(storage, headers, report)
    _accept(headers, document, {"revenue"})
    facts = client.get(f"{API}/documents/{document}/metrics?limit=200", headers=headers).json()
    net_income = next(
        f for f in facts["items"] if f["metric"] == "net_income" and f["period_label"] == "FY2025"
    )
    rejected = client.post(
        f"{API}/financial-facts/{net_income['id']}/reject", json={"reason": "wrong row"},
        headers=headers,
    )  # fmt: skip
    assert rejected.status_code == 200  # so there is no usable net income for FY2025
    body = {"document_id": document, "base_period": "FY2025"}
    response = client.post(f"{API}/scenarios/calculate", json=body, headers=headers)
    assert response.status_code == 422  # before P2.5: 200 with a net income of 0
    assert response.json()["error"]["code"] == "missing_base_fact"


@pytest.mark.parametrize("value", ["1e30", "1e-7", "12345678901234567890123456789012"])
def test_corrections_are_bounded_decimals(storage, report, value):
    headers, _ = user_session()
    document = ready_document(storage, headers, report)
    fact = _accept(headers, document, {"revenue"})
    response = client.post(
        f"{API}/financial-facts/{fact}/correct", json={"value": value, "reason": "bounds"},
        headers=headers,
    )  # fmt: skip
    assert response.status_code == 422


# --- Database and request resource limits -----------------------------------------------------


def test_every_database_connection_has_a_statement_timeout():
    with engine.connect() as connection:
        assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "30s"


def test_chunked_bodies_are_counted_while_they_stream():
    chunks = iter([b'{"name": "', b"a" * 700_000, b"a" * 700_000, b'"}'])
    response = client.post(
        f"{API}/companies", content=chunks, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_companies_are_capped_per_user(tune):
    tune(quota_max_companies=2)
    headers, _ = user_session()
    statuses = [
        client.post(f"{API}/companies", json={"name": f"c{i}"}, headers=headers).status_code
        for i in range(3)
    ]
    assert statuses == [201, 201, 409]


def test_network_isolation_cannot_be_off_in_production():
    with pytest.raises(ValidationError, match="PROCESSING_NETWORK_ISOLATION"):
        production(processing_network_isolation="off")


def test_service_role_can_use_rows_but_not_change_the_schema():
    """deploy/db_roles.sql, applied for real: a login in the group reads and writes rows and
    cannot create, alter or drop tables, truncate, move the schema version or make roles."""
    with engine.begin() as connection:
        connection.exec_driver_sql(DB_ROLES_SQL.read_text())
    name, password = f"prospect_t_{secrets.token_hex(4)}", secrets.token_urlsafe(24)
    with engine.begin() as connection:  # test-only role, dropped below
        connection.exec_driver_sql(
            f"CREATE ROLE {name} LOGIN PASSWORD '{password}' IN ROLE prospect_app"
        )
    url = make_url(os.environ["TEST_DATABASE_URL"]).set(username=name, password=password)
    service = create_engine(url)
    try:
        with service.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() >= 0
        for statement in (
            "CREATE TABLE p25_probe (id int)",
            "ALTER TABLE documents ADD COLUMN p25_probe int",
            "DROP TABLE rate_limits",
            "TRUNCATE rate_limits",
            "UPDATE alembic_version SET version_num = version_num",
            "CREATE ROLE p25_probe",
        ):
            with service.connect() as connection, pytest.raises(exc.ProgrammingError):
                connection.execute(text(statement))
    finally:
        service.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP ROLE {name}")
