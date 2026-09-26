import io
from urllib.parse import parse_qs, urlparse

from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.storage import S3ObjectStorage


def make_storage() -> S3ObjectStorage:
    return S3ObjectStorage("https://storage.test", "docs", "access", "secret")


def test_signed_urls_are_private_and_expiring():
    storage = make_storage()
    for method in ("get", "put"):
        url = urlparse(storage.signed_url("user/doc.pdf", method, expires_in=60))
        query = parse_qs(url.query)
        assert url.path == "/docs/user/doc.pdf"
        assert query["X-Amz-Expires"] == ["60"]
        assert "X-Amz-Signature" in query


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
