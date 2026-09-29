import re
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
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
    # Fail closed: production unless ENVIRONMENT=development (local) or test (CI, pytest) is set
    # explicitly, so a forgotten variable can never let weak settings through.
    environment: Literal["development", "test", "production"] = "production"
    database_url: str
    # Trusted browser origins (comma-separated): CORS and CSRF Origin checks. Production: the
    # deployed frontend only, https. CORS_ORIGINS is the pre-P1 name, still accepted.
    allowed_origins: str = Field(
        "http://localhost:3000", validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ORIGINS")
    )
    log_level: str = "INFO"
    # Largest request body the API reads (JSON only: PDFs go straight to storage). Checked before
    # the body is read or parsed, so it also bounds unauthenticated requests.
    max_request_body_bytes: int = Field(1_048_576, ge=1024)
    # Every database statement is cancelled after this (a runaway query cannot hold a connection
    # or lock forever). The worker's bulk insert of a large document is well inside it.
    db_statement_timeout_ms: int = Field(30_000, ge=1000)

    # --- Storage ---------------------------------------------------------------------------
    object_storage_endpoint: str
    object_storage_bucket: str
    object_storage_access_key: SecretStr
    object_storage_secret_key: SecretStr
    signed_url_ttl_seconds: int = 900

    # --- Auth (API only: the worker needs neither, see api_problems) -----------------------
    app_secret: SecretStr | None = None  # HMAC key for session tokens; ≥ 32 random bytes
    # Shared with the web app's /api proxy (apps/web/middleware.ts): only a request carrying it
    # may name the client IP (X-Prospect-Client-IP). Everyone else is rate limited by the TCP
    # peer address, so a direct client cannot spoof its IP.
    trusted_proxy_secret: SecretStr | None = None
    # VERCEL=1 is set by the platform itself (never in the repo): the API runs as the `api`
    # service of the Vercel project (vercel.json, docs/ADR-006). Its edge then routes browsers
    # straight to the API and sets X-Real-IP itself, so no web proxy and no proxy secret exist.
    vercel: bool = False
    session_ttl_seconds: int = 86_400
    # The session cookie is HttpOnly, SameSite=Strict, Path=/ and, when secure, Secure with the
    # __Host- prefix. Production requires secure; only plain-http local development turns it off.
    session_cookie_secure: bool = True

    # --- Rate limits ("<requests>/<window seconds>", per user; sessions per client IP) -----
    rate_limit_sessions: str = "5/60"
    rate_limit_session_refresh: str = "10/3600"
    rate_limit_uploads: str = "20/3600"
    rate_limit_complete: str = "30/3600"
    rate_limit_financials: str = "60/60"
    rate_limit_compute: str = "30/60"  # diff, scenario preview, data quality
    rate_limit_export: str = "10/60"
    rate_limit_writes: str = "60/60"  # creating companies, scenarios, watchlist entries
    # Per client IP as well, so opening new anonymous sessions does not reset the limits.
    rate_limit_sessions_daily: str = "50/86400"
    rate_limit_uploads_ip: str = "60/3600"
    rate_limit_complete_ip: str = "90/3600"
    rate_limit_export_ip: str = "30/60"

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
    # PDF objects (xref entries) a document may declare; far above real annual reports.
    processing_max_objects: int = 500_000
    # Largest parse result the parser child may hand back; it is also the child's file-size
    # limit (RLIMIT_FSIZE), i.e. the most it can write to disk.
    processing_max_result_bytes: int = 256 * 1024**2
    # The parser child's network: required = parse only inside an empty network namespace (Linux
    # with unprivileged user namespaces); best_effort = use one when the host allows it and log
    # when not; off = never try (development on other systems). Production may not use off.
    processing_network_isolation: Literal["required", "best_effort", "off"] = "best_effort"

    # --- Quotas (per user) -----------------------------------------------------------------
    quota_max_documents: int = 100
    quota_max_storage_bytes: int = 2 * 1024**3
    quota_max_active_jobs: int = 3
    quota_max_daily_jobs: int = 50
    # Across all users: queued + running jobs. New sessions cannot flood the queue past it.
    quota_max_queued_jobs: int = 500
    quota_max_companies: int = 100
    quota_max_scenarios: int = 200

    # --- Threat scanning and retention -----------------------------------------------------
    # clamav: scan every PDF with clamd before parsing; none: documents are not scanned (and are
    # marked so). Production must choose explicitly: unset refuses to start.
    document_scanner: Literal["none", "clamav"] | None = None
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 60
    # Anonymous workspace lifecycle (docs/SECURITY.md §2): a session lives SESSION_TTL_SECONDS
    # (refreshed while in use). Once a user has had no usable session for WORKSPACE_GRACE_HOURS,
    # the whole workspace (documents, files, derived data) is deleted: nobody can reach it again.
    # Independently, every document is deleted DOCUMENT_RETENTION_DAYS after upload (required in
    # production), and FAILED documents' records after FAILED_DOCUMENT_RETENTION_HOURS.
    workspace_grace_hours: int = Field(24, ge=1)
    document_retention_days: int | None = Field(30, ge=1)
    failed_document_retention_hours: int = Field(24, ge=1)
    # Storage objects under uploads/ or documents/ with no database record are deleted only once
    # older than this (app/reconcile.py).
    reconcile_orphan_grace_hours: int = Field(48, ge=1)

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
        "rate_limit_writes",
        "rate_limit_sessions_daily",
        "rate_limit_uploads_ip",
        "rate_limit_complete_ip",
        "rate_limit_export_ip",
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
        origins = self.origin_list
        if not origins or any(o == "*" or o != o.rstrip("/") for o in origins):
            raise ValueError("ALLOWED_ORIGINS lists exact origins (scheme://host[:port]), no '*'")
        if self.environment == "production":
            for name in ("app_secret", "trusted_proxy_secret"):
                value = getattr(self, name)
                problem = value is not None and secret_problem(value.get_secret_value())
                if problem:
                    raise ValueError(f"{name.upper()} is not safe for production: {problem}")
            if not self.object_storage_endpoint.startswith("https://"):
                raise ValueError("OBJECT_STORAGE_ENDPOINT must be https in production")
            if self.document_retention_days is None:
                raise ValueError("DOCUMENT_RETENTION_DAYS must be set in production")
            if not all(o.startswith("https://") for o in origins):
                raise ValueError("ALLOWED_ORIGINS must be https:// origins in production")
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE must be true in production")
            if self.processing_network_isolation == "off":
                raise ValueError("PROCESSING_NETWORK_ISOLATION cannot be off in production")
            if self.document_scanner is None:
                raise ValueError(
                    "DOCUMENT_SCANNER must be set in production: clamav, or none to accept "
                    "unscanned documents explicitly"
                )
        return self

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


def api_problems(settings: Settings) -> list[str]:
    """What stops the API (not the worker) from starting. The API signs sessions and trusts the
    web proxy; the worker does neither, so it must not need (or hold) these secrets."""
    problems = []
    if settings.app_secret is None:
        problems.append("APP_SECRET is required")
    on_proxy = not settings.vercel  # on Vercel the edge names the client (app/ratelimit.py)
    if settings.environment == "production" and on_proxy and settings.trusted_proxy_secret is None:
        problems.append(
            "TRUSTED_PROXY_SECRET is required in production (else every browser shares the "
            "proxy's IP for rate limits)"
        )
    return problems


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
