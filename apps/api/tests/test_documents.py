"""Upload flow on real PostgreSQL + in-process S3 (moto). Runs when TEST_DATABASE_URL is set."""

import os
import uuid

import boto3
import httpx
import pytest
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Document, ProcessingJob
from app.storage import S3ObjectStorage, get_storage

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)

client = TestClient(app)
PDF = b"%PDF-1.7\n" + b"0" * 100


@pytest.fixture(scope="module", autouse=True)
def storage():
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    creds = {"aws_access_key_id": "test", "aws_secret_access_key": "test"}
    boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1", **creds).create_bucket(
        Bucket="prospect-test"
    )
    storage = S3ObjectStorage(endpoint, "prospect-test", "test", "test")
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    app.dependency_overrides.clear()
    server.stop()


def new_user() -> dict[str, str]:
    token = client.post("/api/v1/sessions").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def create(headers: dict[str, str], **overrides) -> httpx.Response:
    body = {
        "filename": "Annual Report 2025.pdf",
        "content_type": "application/pdf",
        "size_bytes": len(PDF),
        **overrides,
    }
    return client.post("/api/v1/documents", json=body, headers=headers)


def put_file(created: dict, data: bytes = PDF) -> None:
    upload = created["upload"]
    httpx.put(upload["url"], content=data, headers=upload["headers"]).raise_for_status()


def complete(headers: dict[str, str], document_id: str) -> httpx.Response:
    return client.post(f"/api/v1/documents/{document_id}/complete", headers=headers)


def storage_key(document_id: str) -> str:
    with SessionLocal() as s:
        return s.get_one(Document, uuid.UUID(document_id)).storage_key


def queued_jobs(document_id: str) -> int:
    with SessionLocal() as s:
        query = select(func.count()).where(ProcessingJob.document_id == uuid.UUID(document_id))
        return s.scalar(query) or 0


def test_create_upload_complete_becomes_uploaded(storage):
    me = new_user()
    response = create(me, fiscal_year=2025)
    assert response.status_code == 201
    created = response.json()
    doc_id = created["document"]["id"]
    assert created["document"]["status"] == "UPLOADING"
    assert created["document"]["size_bytes"] == len(PDF)
    assert "X-Amz-Expires=900" in created["upload"]["url"]
    assert "storage_key" not in created["document"]  # only reachable via short-lived signed URLs

    put_file(created)
    completed = complete(me, doc_id)
    assert completed.status_code == 200
    assert completed.json()["status"] == "UPLOADED"
    assert queued_jobs(doc_id) == 1

    assert client.get(f"/api/v1/documents/{doc_id}", headers=me).json()["status"] == "UPLOADED"
    assert [d["id"] for d in client.get("/api/v1/documents", headers=me).json()["items"]] == [
        doc_id
    ]
    download = client.get(f"/api/v1/documents/{doc_id}/download-url", headers=me).json()
    assert httpx.get(download["url"]).content == PDF


def test_complete_before_upload_can_be_retried():
    me = new_user()
    created = create(me).json()
    doc_id = created["document"]["id"]
    early = complete(me, doc_id)
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "upload_not_found"
    assert client.get(f"/api/v1/documents/{doc_id}", headers=me).json()["status"] == "UPLOADING"

    put_file(created)
    assert complete(me, doc_id).json()["status"] == "UPLOADED"


def test_complete_is_idempotent():
    me = new_user()
    created = create(me).json()
    put_file(created)
    doc_id = created["document"]["id"]
    complete(me, doc_id)
    assert complete(me, doc_id).json()["status"] == "UPLOADED"
    assert queued_jobs(doc_id) == 1


def test_rejects_unsupported_type():
    response = create(new_user(), filename="notes.txt", content_type="text/plain")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_rejects_oversized_file():
    response = create(new_user(), size_bytes=get_settings().max_upload_bytes + 1)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


@pytest.mark.parametrize(
    ("data", "declared"),
    [(b"MZ\x90\x00 not a pdf at all", None), (PDF + b"extra bytes", len(PDF))],
    ids=["disguised-non-pdf", "size-mismatch"],
)
def test_server_verifies_stored_bytes(storage, data, declared):
    me = new_user()
    created = create(me, size_bytes=declared or len(data)).json()
    doc_id = created["document"]["id"]
    put_file(created, data)

    response = complete(me, doc_id)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_upload"
    document = client.get(f"/api/v1/documents/{doc_id}", headers=me).json()
    assert document["status"] == "FAILED"
    assert document["processing_error"]
    assert storage.size(storage_key(doc_id)) is None  # rejected bytes are deleted
    assert queued_jobs(doc_id) == 0


def test_requires_valid_session():
    assert client.get("/api/v1/documents").status_code == 401
    forged = f"{uuid.uuid4()}.{'0' * 64}"
    response = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_other_users_documents_are_invisible():
    owner, intruder = new_user(), new_user()
    created = create(owner).json()
    put_file(created)
    doc_id = created["document"]["id"]
    complete(owner, doc_id)

    missing = client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=intruder)
    for response in (
        client.get(f"/api/v1/documents/{doc_id}", headers=intruder),
        client.get(f"/api/v1/documents/{doc_id}/download-url", headers=intruder),
        complete(intruder, doc_id),
    ):
        assert response.status_code == 404
        # Same body as a nonexistent id (request ids differ), so nothing leaks.
        assert response.json()["error"]["message"] == missing.json()["error"]["message"]
    assert client.get("/api/v1/documents", headers=intruder).json()["items"] == []
