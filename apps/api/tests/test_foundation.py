from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@app.get("/_test/boom")
def boom() -> None:
    raise RuntimeError("secret internal detail")


@app.get("/_test/typed/{n}")
def typed(n: int) -> int:
    return n


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_request_id_is_echoed():
    assert client.get("/health", headers={"X-Request-ID": "abc"}).headers["X-Request-ID"] == "abc"


def test_not_found_uses_error_shape():
    response = client.get("/nope", headers={"X-Request-ID": "r1"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "request_id": "r1"}
    }


def test_validation_error_uses_error_shape():
    body = client.get("/_test/typed/abc").json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["loc"] == ["path", "n"]


def test_unhandled_error_hides_internals():
    response = client.get("/_test/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text


def test_errors_carry_cors_headers_so_browsers_can_read_them():
    response = client.get("/_test/boom", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_managed_database_urls_get_psycopg_driver():
    for url in ("postgres://u:p@h/db", "postgresql://u:p@h/db"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h/db"


def test_allowed_origins_parsed():
    s = Settings(allowed_origins="https://a.example, https://b.example,")
    assert s.origin_list == ["https://a.example", "https://b.example"]


def test_secrets_are_not_printed():
    assert "test-app-secret" not in repr(Settings())
