"""Structured foundation-level configuration.

Only settings accepted in Phase 2 contracts (ADR-027, ADR-028, ADR-029)
exist here. No production/cloud configuration, no secrets.
Values may be overridden with a gitignored local `.env` (see `.env.example`).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend settings with documented Phase 2 defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    app_version: str = "0.1.0"
    schema_version: int = 1
    max_upload_mb: int = 250
    session_root: str = ".tmp/sessions"
    session_ttl_hours: int = 24
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000

    @property
    def max_upload_bytes(self) -> int:
        """Maximum upload size in bytes (ADR-027: 250 MB hard cap)."""
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
