"""Foundation configuration defaults (ADR-027, ADR-028)."""

from app.config import Settings


def test_phase2_defaults_are_applied() -> None:
    """Documented Phase 2 defaults hold without any environment overrides."""
    config = Settings(_env_file=None)
    assert config.app_env == "local"
    assert config.app_version == "0.1.0"
    assert config.schema_version == 1
    assert config.max_upload_mb == 250
    assert config.max_upload_bytes == 250 * 1024 * 1024
    assert config.session_root == ".tmp/sessions"
    assert config.session_ttl_hours == 24
