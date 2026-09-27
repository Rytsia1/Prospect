import io
from urllib.parse import parse_qs, urlparse

from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.storage import S3ObjectStorage


def make_storage() -> S3ObjectStorage:
    return S3ObjectStorage("https://storage.test", "docs", "access", "secret")


def test_signed_urls_are_private_and_expiring():
    storage = make_storage()
    for signed in (
        storage.signed_download_url("user/doc.pdf", expires_in=60),
        storage.signed_upload_url("user/doc.pdf", "application/pdf", 1234, expires_in=60),
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
    url = urlparse(storage.signed_upload_url("k.pdf", "application/pdf", 1234, 60))
    signed = parse_qs(url.query)["X-Amz-SignedHeaders"][0].split(";")
    assert "content-length" in signed and "content-type" in signed
    # The signature depends on the approved length: one byte more is a different request.
    other = urlparse(storage.signed_upload_url("k.pdf", "application/pdf", 1235, 60))
    assert parse_qs(url.query)["X-Amz-Signature"] != parse_qs(other.query)["X-Amz-Signature"]


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
