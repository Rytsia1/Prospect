"""Private object storage. The rest of the app depends on `ObjectStorage`, never on boto3."""

from functools import lru_cache
from typing import Literal, Protocol

import boto3
from botocore.config import Config

from app.config import get_settings

SignedUrlMethod = Literal["get", "put"]


class ObjectStorage(Protocol):
    def upload(self, key: str, data: bytes, content_type: str) -> None: ...
    def download(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def signed_url(self, key: str, method: SignedUrlMethod, expires_in: int = 900) -> str: ...


class S3ObjectStorage:
    """S3-compatible storage: Cloudflare R2 in production (also MinIO / Supabase S3 locally)."""

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",  # required value for R2
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def upload(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def download(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def signed_url(self, key: str, method: SignedUrlMethod, expires_in: int = 900) -> str:
        operation = {"get": "get_object", "put": "put_object"}[method]
        return self.client.generate_presigned_url(
            operation, Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in
        )


@lru_cache
def get_storage() -> ObjectStorage:
    s = get_settings()
    return S3ObjectStorage(
        endpoint=s.object_storage_endpoint,
        bucket=s.object_storage_bucket,
        access_key=s.object_storage_access_key.get_secret_value(),
        secret_key=s.object_storage_secret_key.get_secret_value(),
    )
