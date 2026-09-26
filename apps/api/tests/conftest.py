import os

import pytest

# Dummy placeholders so Settings validates in unit tests. Real env vars take precedence.
for key, value in {
    "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
    "OBJECT_STORAGE_ENDPOINT": "https://storage.test",
    "OBJECT_STORAGE_BUCKET": "test-bucket",
    "OBJECT_STORAGE_ACCESS_KEY": "test-access-key",
    "OBJECT_STORAGE_SECRET_KEY": "test-secret-key",
    "APP_SECRET": "test-app-secret",
}.items():
    os.environ.setdefault(key, value)

# DB tests run against TEST_DATABASE_URL (a migrated database), never DATABASE_URL.
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]


@pytest.fixture(scope="session")
def storage():
    """In-process S3 (moto) wired into the API in place of R2. Needs no credentials or network."""
    import boto3
    from moto.server import ThreadedMotoServer

    from app.main import app
    from app.storage import S3ObjectStorage, get_storage

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
