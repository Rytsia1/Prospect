"""Private object storage. The rest of the app depends on `ObjectStorage`, never on boto3."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings


@dataclass(frozen=True)
class ObjectStat:
    size: int
    content_type: str | None


class ObjectStorage(Protocol):
    def upload(self, key: str, data: bytes, content_type: str) -> None: ...
    def download(self, key: str) -> bytes: ...
    def download_file(self, key: str, path: Path) -> None: ...
    def delete(self, key: str) -> None: ...
    def stat(self, key: str) -> ObjectStat | None: ...
    def read_prefix(self, key: str, length: int) -> bytes: ...
    def signed_download_url(self, key: str, expires_in: int) -> str: ...
    def signed_upload_url(
        self, key: str, content_type: str, content_length: int, expires_in: int
    ) -> str: ...


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

    def download_file(self, key: str, path: Path) -> None:
        """Stream an object to disk without holding it in memory."""
        self.client.download_file(self.bucket, key, str(path))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def stat(self, key: str) -> ObjectStat | None:
        """Stored size and content type, or None if the object does not exist."""
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            return ObjectStat(head["ContentLength"], head.get("ContentType"))
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def read_prefix(self, key: str, length: int) -> bytes:
        response = self.client.get_object(
            Bucket=self.bucket, Key=key, Range=f"bytes=0-{length - 1}"
        )
        return response["Body"].read()

    def signed_download_url(self, key: str, expires_in: int) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in
        )

    def signed_upload_url(
        self, key: str, content_type: str, content_length: int, expires_in: int
    ) -> str:
        """A PUT URL whose signature covers Content-Length and Content-Type.

        The storage service recomputes the signature from the request's actual headers, so a
        body of any other length (or another type) is rejected by storage itself, before the
        application sees it. The API only signs lengths within MAX_UPLOAD_BYTES. (Works on R2,
        which does not support presigned POST policies with content-length-range.)
        """
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": content_length,
            },
            ExpiresIn=expires_in,
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
