"""Shared backend test fixtures: per-test session-root isolation (Phase 17D).

Every test that uploads through the API must write sessions under a
per-test temporary directory, never the developer's real
`backend/.tmp/sessions` scratch root. Module-level `session_root`
fixtures only activate when requested; tests taking only `client`
silently used the production default and leaked ~60 directories per
full-suite run (17D-01). This autouse fixture closes that gap for all
current and future tests without touching production lifecycle code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _isolate_session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Redirect the session root to a per-test temp dir (restored after)."""
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root
