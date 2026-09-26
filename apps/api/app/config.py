from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All config comes from environment variables (or a local, git-ignored .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    object_storage_endpoint: str
    object_storage_bucket: str
    object_storage_access_key: SecretStr
    object_storage_secret_key: SecretStr
    app_secret: SecretStr
    # Comma-separated. Production must list only the deployed frontend origin.
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    max_upload_bytes: int = 50 * 1024 * 1024

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        # Managed providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
