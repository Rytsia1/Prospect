"""Private object storage. The rest of the app depends on `ObjectStorage`, never on boto3.

Keys: browsers upload to `uploads/<random>.pdf`; once /complete has verified the object it is
copied to `documents/<random>.pdf`. Bucket lifecycle rules (`python -m app.storage lifecycle`)
expire anything left under uploads/ after a day, so abandoned uploads disappear even if the API
and worker never run their own cleanup.
"""

import base64
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings

UPLOAD_PREFIX, DOCUMENT_PREFIX = "uploads/", "documents/"


@dataclass(frozen=True)
class ObjectStat:
    size: int
    content_type: str | None
    sha256: str | None = None  # hex, when the storage service recorded a SHA-256 checksum


def sha256_header(sha256_hex: str) -> str:
    """x-amz-checksum-sha256 carries the digest base64-encoded."""
    return base64.b64encode(bytes.fromhex(sha256_hex)).decode()


class ObjectStorage(Protocol):
    def upload(self, key: str, data: bytes, content_type: str) -> None: ...
    def download(self, key: str) -> bytes: ...
    def download_file(self, key: str, path: Path) -> None: ...
    def delete(self, key: str) -> None: ...
    def copy(self, source: str, target: str) -> None: ...
    def stat(self, key: str) -> ObjectStat | None: ...
    def read_prefix(self, key: str, length: int) -> bytes: ...
    def signed_download_url(self, key: str, expires_in: int) -> str: ...
    def signed_upload_url(
        self, key: str, content_type: str, content_length: int, sha256: str, expires_in: int
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

    def copy(self, source: str, target: str) -> None:
        """Server-side copy within the bucket (the bytes never pass through the API)."""
        self.client.copy_object(
            Bucket=self.bucket, Key=target, CopySource={"Bucket": self.bucket, "Key": source}
        )

    def stat(self, key: str) -> ObjectStat | None:
        """Stored size, content type and SHA-256 (if recorded), or None if there is no object."""
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
            recorded = head.get("ChecksumSHA256")
            return ObjectStat(
                head["ContentLength"],
                head.get("ContentType"),
                base64.b64decode(recorded).hex() if recorded else None,
            )
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
        self, key: str, content_type: str, content_length: int, sha256: str, expires_in: int
    ) -> str:
        """A PUT URL for exactly this key, whose signature covers Content-Length, Content-Type
        and x-amz-checksum-sha256.

        The storage service recomputes the signature from the request's actual headers, so a
        body of any other length (or another type) is rejected by storage itself, before the
        application sees it, and S3/R2 reject a body whose SHA-256 differs from the signed one.
        The API only signs lengths within MAX_UPLOAD_BYTES. (R2 does not support presigned POST
        policies with content-length-range.)
        """
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": content_length,
                "ChecksumSHA256": sha256_header(sha256),
            },
            ExpiresIn=expires_in,
        )

    def apply_lifecycle(self, document_retention_days: int | None) -> list[dict]:
        """Storage-side cleanup that does not depend on the application running."""
        rules: list[dict] = [
            {
                "ID": "expire-unfinished-uploads",
                "Filter": {"Prefix": UPLOAD_PREFIX},
                "Status": "Enabled",
                "Expiration": {"Days": 1},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
            }
        ]
        if document_retention_days:  # backstop, a day after the worker's own retention delete
            rules.append(
                {
                    "ID": "expire-retained-documents",
                    "Filter": {"Prefix": DOCUMENT_PREFIX},
                    "Status": "Enabled",
                    "Expiration": {"Days": document_retention_days + 1},
                }
            )
        self.client.put_bucket_lifecycle_configuration(
            Bucket=self.bucket, LifecycleConfiguration={"Rules": rules}
        )
        return rules


def _s3() -> S3ObjectStorage:
    s = get_settings()
    return S3ObjectStorage(
        endpoint=s.object_storage_endpoint,
        bucket=s.object_storage_bucket,
        access_key=s.object_storage_access_key.get_secret_value(),
        secret_key=s.object_storage_secret_key.get_secret_value(),
    )


@lru_cache
def get_storage() -> ObjectStorage:
    return _s3()


if __name__ == "__main__":
    # One-off, with credentials allowed to configure the bucket: python -m app.storage lifecycle
    if sys.argv[1:] != ["lifecycle"]:
        sys.exit("usage: python -m app.storage lifecycle")
    for rule in _s3().apply_lifecycle(get_settings().document_retention_days):
        print("applied lifecycle rule:", rule["ID"])
