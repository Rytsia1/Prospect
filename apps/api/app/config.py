import re
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholders that ship in .env.example, CI and tests. Never acceptable in production.
DEVELOPMENT_SECRETS = {
    "replace-me-with-a-long-random-string",
    "local-dev-placeholder",
    "test-app-secret",
    "ci",
    "change-me",
    "secret",
}
MIN_SECRET_BYTES = 32
RATE = re.compile(r"^\d+/\d+$")  # "<requests>/<window seconds>", e.g. "5/60"


class Settings(BaseSettings):
    """All config comes from environment variables (or a local, git-ignored .env).

    Security-sensitive values are grouped below; docs/SECURITY.md explains each one.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Runtime ---------------------------------------------------------------------------
    # Fail closed: production unless ENVIRONMENT=development is set explicitly, so a forgotten
    # variable can never let a weak APP_SECRET through.
    environment: Literal["development", "production"] = "production"
    database_url: str
    cors_origins: str = "http://localhost:3000"  # production: only the deployed frontend
    log_level: str = "INFO"

    # --- Storage ---------------------------------------------------------------------------
    object_storage_endpoint: str
    object_storage_bucket: str
    object_storage_access_key: SecretStr
    object_storage_secret_key: SecretStr
    signed_url_ttl_seconds: int = 900

    # --- Auth ------------------------------------------------------------------------------
    app_secret: SecretStr  # HMAC key for session tokens; ≥ 32 random bytes in production
    session_ttl_seconds: int = 86_400

    # --- Rate limits ("<requests>/<window seconds>", per user; sessions per client IP) -----
    rate_limit_sessions: str = "5/60"
    rate_limit_session_refresh: str = "10/3600"
    rate_limit_uploads: str = "20/3600"
    rate_limit_complete: str = "30/3600"
    rate_limit_financials: str = "60/60"
    rate_limit_compute: str = "30/60"  # diff, scenario preview, data quality
    rate_limit_export: str = "10/60"

    # --- Upload ----------------------------------------------------------------------------
    max_upload_bytes: int = 50 * 1024 * 1024  # enforced by the storage signature, not just here

    # --- Processing (worker) ---------------------------------------------------------------
    processing_max_pages: int = 2000
    processing_timeout_seconds: float = 120
    processing_max_memory_bytes: int = 2 * 1024**3  # parser address space (Linux only)
    processing_max_text_bytes: int = 50_000_000
    processing_max_table_cells: int = 500_000
    processing_max_facts: int = 5_000
    processing_max_evidence: int = 5_000
    processing_max_row_chars: int = 2_000  # longer rows are not used as evidence
    processing_max_attempts: int = 3
    processing_retry_base_seconds: float = 30  # doubles each attempt, plus up to 50% jitter
    processing_lease_seconds: int = 900  # a RUNNING job older than this is reclaimed

    # --- Quotas (per user) -----------------------------------------------------------------
    quota_max_documents: int = 100
    quota_max_storage_bytes: int = 2 * 1024**3
    quota_max_active_jobs: int = 3
    quota_max_daily_jobs: int = 50

    # --- Financials / export ---------------------------------------------------------------
    page_default_limit: int = 100
    page_max_limit: int = 500
    financials_max_documents: int = 20
    financials_max_facts: int = 10_000  # any single unpaged load of facts (all endpoints)
    export_max_records: int = 20_000
    export_max_bytes: int = 20 * 1024 * 1024

    # --- Analytics -------------------------------------------------------------------------
    # Balance-sheet reconciliation (app/workspace.py): a difference within
    # min(printed unit × rounding units, relative tolerance × |assets|) is ROUNDING_DIFFERENCE.
    reconciliation_rounding_units: Decimal = Decimal(3)
    reconciliation_relative_tolerance: Decimal = Decimal("0.0001")

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # Managed providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @field_validator(
        "rate_limit_sessions",
        "rate_limit_session_refresh",
        "rate_limit_uploads",
        "rate_limit_complete",
        "rate_limit_financials",
        "rate_limit_compute",
        "rate_limit_export",
    )
    @classmethod
    def rate_format(cls, value: str) -> str:
        if not RATE.match(value) or int(value.split("/")[1]) == 0:
            raise ValueError("rate limits look like '<requests>/<window seconds>', e.g. '5/60'")
        return value

    @model_validator(mode="after")
    def production_fails_closed(self) -> "Settings":
        if self.processing_lease_seconds <= self.processing_timeout_seconds:
            raise ValueError("PROCESSING_LEASE_SECONDS must exceed PROCESSING_TIMEOUT_SECONDS")
        if self.environment == "production":
            problem = secret_problem(self.app_secret.get_secret_value())
            if problem:
                raise ValueError(f"APP_SECRET is not safe for production: {problem}")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def secret_problem(secret: str) -> str | None:
    """Why a secret is unfit for production, or None. Generate one with
    `python -c "import secrets; print(secrets.token_urlsafe(48))"`."""
    if secret.strip().lower() in DEVELOPMENT_SECRETS:
        return "it is a known development placeholder"
    if len(secret.encode()) < MIN_SECRET_BYTES:
        return f"it must be at least {MIN_SECRET_BYTES} bytes"
    if len(set(secret)) < 12:
        return "it has too little variety to be random"
    return None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
