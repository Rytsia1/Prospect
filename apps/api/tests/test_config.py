"""Security-sensitive settings fail closed in production. No database."""

import pytest
from pydantic import ValidationError

from app.config import Settings, secret_problem

STRONG = "q8Zr1vT3xK0pW7nL2cF9hJ4sD6gB5mY1aE8uR3tI0oP"
REQUIRED = {
    "database_url": "postgresql://u:p@db/x",
    "object_storage_endpoint": "https://storage.test",
    "object_storage_bucket": "b",
    "object_storage_access_key": "k",
    "object_storage_secret_key": "s",
}


@pytest.mark.parametrize(
    "secret",
    ["", "ci", "replace-me-with-a-long-random-string", "short-but-random-3x9", "a" * 64],
)
def test_production_refuses_weak_secrets(secret):
    assert secret_problem(secret)
    with pytest.raises(ValidationError, match="APP_SECRET is not safe"):
        Settings(**REQUIRED, environment="production", app_secret=secret)


def test_production_accepts_a_strong_secret():
    assert secret_problem(STRONG) is None
    Settings(**REQUIRED, environment="production", app_secret=STRONG)


def test_development_allows_placeholders():
    Settings(**REQUIRED, environment="development", app_secret="ci")


def test_environment_defaults_to_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ValidationError, match="APP_SECRET is not safe"):
        Settings(_env_file=None, **REQUIRED, app_secret="ci")  # forgotten ENVIRONMENT: closed


@pytest.mark.parametrize("rate", ["5", "5/0", "five/60", "-1/60"])
def test_malformed_rate_limits_are_refused(rate):
    with pytest.raises(ValidationError):
        Settings(**REQUIRED, app_secret=STRONG, rate_limit_export=rate)


def test_lease_must_outlast_the_processing_timeout():
    with pytest.raises(ValidationError, match="LEASE"):
        Settings(
            **REQUIRED,
            app_secret=STRONG,
            processing_timeout_seconds=600,
            processing_lease_seconds=300,
        )
