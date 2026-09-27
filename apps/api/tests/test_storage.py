import io
from urllib.parse import parse_qs, urlparse

from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.storage import S3ObjectStorage, sha256_header

SHA = "a" * 64


def make_storage() -> S3ObjectStorage:
    return S3ObjectStorage("https://storage.test", "docs", "access", "secret")


def test_signed_urls_are_private_and_expiring():
    storage = make_storage()
    for signed in (
        storage.signed_download_url("user/doc.pdf", expires_in=60),
        storage.signed_upload_url("user/doc.pdf", "application/pdf", 1234, SHA, expires_in=60),
    ):
        url = urlparse(signed)
        query = parse_qs(url.query)
        assert url.path == "/docs/user/doc.pdf"
        assert query["X-Amz-Expires"] == ["60"]
        assert "X-Amz-Signature" in query


def test_upload_url_signature_binds_size_and_type():
    """Storage recomputes the signature from the request's real Content-Length and
    Content-Type, so an upload of any other size or type is refused by storage itself."""
    storage = make_storage()
    url = urlparse(storage.signed_upload_url("k.pdf", "application/pdf", 1234, SHA, 60))
    signed = parse_qs(url.query)["X-Amz-SignedHeaders"][0].split(";")
    assert "content-length" in signed and "content-type" in signed
    # The signature depends on the approved length: one byte more is a different request.
    other = urlparse(storage.signed_upload_url("k.pdf", "application/pdf", 1235, SHA, 60))
    assert parse_qs(url.query)["X-Amz-Signature"] != parse_qs(other.query)["X-Amz-Signature"]


def test_upload_url_signature_binds_the_checksum_and_key():
    """S3/R2 verify x-amz-checksum-sha256 against the body; because the header is signed, the
    client can neither drop it nor swap in the checksum of other bytes. The key is in the
    signed path, so the URL writes nowhere else, and only PUT is allowed."""
    storage = make_storage()
    url = urlparse(storage.signed_upload_url("uploads/k.pdf", "application/pdf", 1234, SHA, 60))
    assert "x-amz-checksum-sha256" in parse_qs(url.query)["X-Amz-SignedHeaders"][0].split(";")
    assert url.path == "/docs/uploads/k.pdf"
    other = urlparse(
        storage.signed_upload_url("uploads/k.pdf", "application/pdf", 1234, "b" * 64, 60)
    )
    assert parse_qs(url.query)["X-Amz-Signature"] != parse_qs(other.query)["X-Amz-Signature"]
    assert sha256_header("00" * 32) == "A" * 43 + "="  # base64 of the raw digest, not hex


def test_stat_reports_the_stored_checksum_as_hex():
    storage = make_storage()
    with Stubber(storage.client) as stub:
        stub.add_response(
            "head_object",
            {
                "ContentLength": 4,
                "ContentType": "application/pdf",
                "ChecksumSHA256": sha256_header(SHA),
            },
            {"Bucket": "docs", "Key": "k.pdf", "ChecksumMode": "ENABLED"},
        )
        stat = storage.stat("k.pdf")
    assert stat is not None and stat.sha256 == SHA


def test_lifecycle_rules_expire_unfinished_uploads_and_retained_documents(storage):
    rules = {r["ID"]: r for r in storage.apply_lifecycle(document_retention_days=90)}
    assert rules["expire-unfinished-uploads"]["Filter"] == {"Prefix": "uploads/"}
    assert rules["expire-retained-documents"]["Expiration"] == {"Days": 91}
    stored = storage.client.get_bucket_lifecycle_configuration(Bucket=storage.bucket)["Rules"]
    assert {r["ID"] for r in stored} == set(rules)
    # Without a retention period, documents are never expired by storage.
    assert [r["ID"] for r in storage.apply_lifecycle(None)] == ["expire-unfinished-uploads"]


def test_upload_download_delete():
    storage = make_storage()
    with Stubber(storage.client) as stub:
        key = {"Bucket": "docs", "Key": "k.pdf"}
        stub.add_response(
            "put_object", {}, {**key, "Body": b"%PDF", "ContentType": "application/pdf"}
        )
        stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(b"%PDF"), 4)}, key)
        stub.add_response("delete_object", {}, key)

        storage.upload("k.pdf", b"%PDF", "application/pdf")
        assert storage.download("k.pdf") == b"%PDF"
        storage.delete("k.pdf")
        stub.assert_no_pending_responses()
