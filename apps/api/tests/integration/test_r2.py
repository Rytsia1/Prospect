"""Opt-in integration tests against a REAL S3-compatible bucket (Cloudflare R2 in production).

These establish what the provider itself enforces; the moto-based suite cannot (moto verifies
neither signed lengths nor checksums). They never run in normal CI. To run them:

    R2_INTEGRATION=1 \
    R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com \
    R2_BUCKET=<a test bucket, not production> \
    R2_ACCESS_KEY=<object read/write token> R2_SECRET_KEY=<secret> \
    uv run pytest tests/integration -v

Use a dedicated test bucket and a token scoped to it. Objects are written under uploads/ and
deleted afterwards (the uploads/ lifecycle rule removes any left behind). Credentials are read
from the environment only; never commit them.
"""

import hashlib
import os
import uuid
from urllib.parse import urlparse, urlunparse

import httpx
import pytest

from app.storage import S3ObjectStorage, sha256_header

ENV = ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY", "R2_SECRET_KEY")
pytestmark = pytest.mark.skipif(
    os.getenv("R2_INTEGRATION") != "1" or not all(os.getenv(k) for k in ENV),
    reason="opt-in: set R2_INTEGRATION=1 and R2_ENDPOINT/R2_BUCKET/R2_ACCESS_KEY/R2_SECRET_KEY",
)
PDF = b"%PDF-1.4\n% prospect integration test\n" + b"x" * 1000


@pytest.fixture
def r2():
    return S3ObjectStorage(*(os.environ[k] for k in ENV))


@pytest.fixture
def key(r2):
    name = f"uploads/integration-{uuid.uuid4()}.pdf"
    yield name
    r2.delete(name)


def signed_put(r2, key, body: bytes, sha: str, length: int | None = None):
    url = r2.signed_upload_url(key, "application/pdf", length or len(body), sha, 60)
    headers = {"Content-Type": "application/pdf", "x-amz-checksum-sha256": sha256_header(sha)}
    return httpx.put(url, content=body, headers=headers, timeout=30)


def test_correct_checksum_is_accepted_and_reported(r2, key):
    sha = hashlib.sha256(PDF).hexdigest()
    assert signed_put(r2, key, PDF, sha).status_code == 200
    stat = r2.stat(key)
    assert stat is not None and stat.size == len(PDF)
    # Whether the provider reports the checksum decides who verifies it: /complete (if it does)
    # or only the worker's own hash (if not). Record which one is true for this provider.
    assert stat.sha256 in (sha, None)
    print(f"provider reports SHA-256 on HEAD: {stat.sha256 == sha}")


def test_body_that_does_not_match_the_signed_checksum_is_rejected(r2, key):
    tampered = PDF[:-1] + b"y"  # same length, different bytes
    response = signed_put(r2, key, tampered, hashlib.sha256(PDF).hexdigest())
    assert response.status_code in (400, 403), response.text
    assert r2.stat(key) is None


def test_body_of_another_length_is_rejected(r2, key):
    sha = hashlib.sha256(PDF).hexdigest()
    response = signed_put(r2, key, PDF + b"extra", sha, length=len(PDF))
    assert response.status_code in (400, 403), response.text
    assert r2.stat(key) is None


def test_signed_url_writes_only_its_own_key(r2, key):
    sha = hashlib.sha256(PDF).hexdigest()
    url = urlparse(r2.signed_upload_url(key, "application/pdf", len(PDF), sha, 60))
    other = urlunparse(url._replace(path=url.path.replace("integration-", "integration-other-")))
    headers = {"Content-Type": "application/pdf", "x-amz-checksum-sha256": sha256_header(sha)}
    assert httpx.put(other, content=PDF, headers=headers, timeout=30).status_code == 403


def test_object_changed_after_upload_is_visible_to_verification(r2, key):
    """Completion trusts nothing the client says: a changed object has a different size or,
    where reported, a different checksum; the worker re-hashes the bytes regardless."""
    sha = hashlib.sha256(PDF).hexdigest()
    assert signed_put(r2, key, PDF, sha).status_code == 200
    r2.upload(key, PDF[:-1] + b"z", "application/pdf")  # replaced out of band
    stat = r2.stat(key)
    assert stat is not None and stat.sha256 != sha
    assert hashlib.sha256(r2.download(key)).hexdigest() != sha  # what the worker computes
