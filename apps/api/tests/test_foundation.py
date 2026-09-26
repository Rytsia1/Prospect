from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app


def test_health():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_managed_database_urls_get_psycopg_driver():
    for url in ("postgres://u:p@h/db", "postgresql://u:p@h/db"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h/db"


def test_cors_origins_parsed():
    s = Settings(cors_origins="https://a.example, https://b.example,")
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]
