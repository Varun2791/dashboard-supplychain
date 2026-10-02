"""ADR-043 session-scoped canonical KPI-table cache (synthetic data only).

Matrix: cold miss loads once, same-session hit, no cross-session
contamination, capacity-one replacement, oversized served-but-not-retained
(with explicit A-preservation), filter non-mutation of cached bases,
warm/cold payload equivalence, UNKNOWN_FLAGGED grouping semantics,
DELETE invalidation, post-eviction reload, unknown/non-READY governed
errors, restart-empty equivalence, byte-guard boundary, capacity bound.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app import kpi_cache
from app import kpis as kpi_service
from app.config import settings
from app.main import app

CANON_BYTES = (Path(__file__).parent / "fixtures" / "canonical_small.csv").read_bytes()
ALT_BYTES = (
    Path(__file__).parent / "fixtures" / "v1_reference_synthetic.csv"
).read_bytes()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    kpi_cache.clear()
    yield
    kpi_cache.clear()


def upload_ok(client: TestClient, content: bytes) -> str:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    session_id = response.json()["data"]["sessionId"]
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "READY"
    return session_id


def park_at_analyzing(session_root: str, content: bytes) -> str:
    """An ANALYZING session (canonical done, KPI analysis never run)."""
    from app.canonicalization import ensure_canonicalized
    from app.cleaning import ensure_cleaned
    from app.profiling import ensure_profiled
    from app.schema_validation import ensure_schema_validated

    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    with open(paths.raw, "wb") as handle:
        handle.write(content)
    now = session_store.utcnow_naive_iso()
    manifest = session_store.build_manifest(
        session_id=session_id,
        filename_safe="data.csv",
        size_bytes=len(content),
        sha256_hex=hashlib.sha256(content).hexdigest(),
        encoding="utf-8",
        now=now,
    )
    session_store.write_manifest(paths, manifest)
    validated = ensure_schema_validated(paths, manifest, now)
    profiled = ensure_profiled(paths, validated, now)
    cleaned = ensure_cleaned(paths, profiled, now)
    canonicalized = ensure_canonicalized(paths, cleaned, now)
    assert canonicalized.state == "ANALYZING"
    return session_id


def counting_loader(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"n": 0}
    real = kpi_service.load_canonical_tables

    def wrapper(paths: session_store.SessionPaths) -> kpi_service.KpiTables:
        calls["n"] += 1
        return real(paths)

    monkeypatch.setattr(kpi_service, "load_canonical_tables", wrapper)
    return calls


def strip_meta(payload: dict[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    meta = dict(body.get("meta", {}))
    meta.pop("generatedAt", None)
    meta.pop("sessionId", None)
    body["meta"] = meta
    return body


def test_cold_access_loads_once_and_warm_access_hits(
    client: TestClient, session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A/B: first analytical access misses (one load), repeats hit."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    # Count serving-path loads only: the upload pipeline already ran.
    calls = counting_loader(monkeypatch)
    first = client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    assert first.status_code == 200
    assert calls["n"] == 1
    info = kpi_cache.cache_info()
    assert info["sessionId"] == session_id
    assert info["sessionCount"] == 1
    second = client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    third = client.get(f"/api/v1/sessions/{session_id}/kpis/commercial")
    assert second.status_code == 200
    assert third.status_code == 200
    assert calls["n"] == 1
    assert kpi_cache.cache_info()["hits"] >= 2


def test_session_b_never_receives_session_a_tables(
    client: TestClient, session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C: cross-session reads reload; B is served B's own tables."""
    _ = session_root
    session_a = upload_ok(client, CANON_BYTES)
    session_b = upload_ok(client, ALT_BYTES)
    # Count serving-path loads only: both upload pipelines already ran.
    calls = counting_loader(monkeypatch)
    body_a = client.get(f"/api/v1/sessions/{session_a}/kpis/overview").json()
    assert calls["n"] == 1
    body_b = client.get(f"/api/v1/sessions/{session_b}/kpis/overview").json()
    assert calls["n"] == 2
    assert body_b["meta"]["sessionId"] == session_b
    assert strip_meta(body_b) != strip_meta(body_a)
    assert kpi_cache.cache_info()["sessionId"] == session_b


def test_capacity_one_replacement_evicts_a_when_b_retained(
    client: TestClient, session_root: str
) -> None:
    """D/P: at most one session is ever reachable; B replaces A."""
    _ = session_root
    session_a = upload_ok(client, CANON_BYTES)
    session_b = upload_ok(client, ALT_BYTES)
    client.get(f"/api/v1/sessions/{session_a}/kpis/overview")
    assert kpi_cache.cache_info()["sessionId"] == session_a
    client.get(f"/api/v1/sessions/{session_b}/kpis/overview")
    info = kpi_cache.cache_info()
    assert info["sessionId"] == session_b
    assert info["sessionCount"] == 1


def test_oversized_bundle_served_but_not_retained(
    client: TestClient, session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E: a valid request over the guard still succeeds, uncached."""
    _ = session_root
    monkeypatch.setattr(settings, "kpi_cache_retain_mb", 0)
    session_id = upload_ok(client, CANON_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    assert response.status_code == 200
    assert len(response.json()["data"]["kpis"]) == 30
    assert kpi_cache.cache_info()["sessionCount"] == 0


def test_oversized_b_does_not_evict_cached_a(
    client: TestClient, session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F: an uncacheable B leaves a valid cached A intact."""
    _ = session_root
    session_a = upload_ok(client, CANON_BYTES)
    session_b = upload_ok(client, ALT_BYTES)
    client.get(f"/api/v1/sessions/{session_a}/kpis/overview")
    assert kpi_cache.cache_info()["sessionId"] == session_a
    monkeypatch.setattr(settings, "kpi_cache_retain_mb", 0)
    response = client.get(f"/api/v1/sessions/{session_b}/kpis/overview")
    assert response.status_code == 200
    assert kpi_cache.cache_info()["sessionId"] == session_a


def test_filtered_request_does_not_mutate_cached_base(
    client: TestClient, session_root: str
) -> None:
    """G: read-only borrow contract — filters narrow views, never bases."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    tables = kpi_cache.get(session_id)
    assert tables is not None
    items_before = tables.items.copy(deep=True)
    orders_before = tables.orders.copy(deep=True)
    bytes_before = kpi_cache.retained_bytes(tables)
    filtered = client.get(f"/api/v1/sessions/{session_id}/kpis/commercial?region=South")
    assert filtered.status_code == 200
    grouped = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipping_mode"
    )
    assert grouped.status_code == 200
    assert tables.items.equals(items_before)
    assert tables.orders.equals(orders_before)
    assert kpi_cache.retained_bytes(tables) == bytes_before


def test_warm_and_cold_payloads_are_equivalent(
    client: TestClient, session_root: str
) -> None:
    """H: cache changes performance only — analytical values identical."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    cold = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()
    warm = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()
    assert strip_meta(warm) == strip_meta(cold)
    cold_delivery = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipping_mode"
    ).json()
    warm_delivery = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipping_mode"
    ).json()
    assert strip_meta(warm_delivery) == strip_meta(cold_delivery)


def test_unknown_flagged_grouping_semantics_survive_cache(
    client: TestClient, session_root: str
) -> None:
    """I: governed split exclusions identical on cold and warm paths."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    kpi_cache.clear()
    cold = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipping_mode"
    ).json()
    warm = client.get(
        f"/api/v1/sessions/{session_id}/kpis/delivery?by=shipping_mode"
    ).json()
    for payload in (cold, warm):
        keys = [group["key"] for group in payload["data"]["groups"]]
        assert "" not in keys
        assert "UNKNOWN_FLAGGED" not in keys
    assert strip_meta(warm) == strip_meta(cold)


def test_governed_delete_invalidates_cached_session(
    client: TestClient, session_root: str
) -> None:
    """J: DELETE evicts memory; the session is gone afterwards (404)."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    assert client.get(f"/api/v1/sessions/{session_id}/kpis/overview").status_code == 200
    assert kpi_cache.cache_info()["sessionId"] == session_id
    deleted = client.delete(f"/api/v1/sessions/{session_id}")
    assert deleted.status_code == 200
    assert kpi_cache.cache_info()["sessionCount"] == 0
    assert kpi_cache.get(session_id) is None
    assert client.get(f"/api/v1/sessions/{session_id}/kpis/overview").status_code == 404


def test_reload_after_eviction_is_correct(
    client: TestClient, session_root: str
) -> None:
    """K: post-eviction reads rebuild from artifacts with equal values."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    before = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()
    kpi_cache.clear()
    after = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()
    assert after["error"] is None
    assert strip_meta(after) == strip_meta(before)


def test_unknown_session_is_never_served_from_cache(
    client: TestClient, session_root: str
) -> None:
    """L: an unknown id 404s even with a populated cache."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    client.get(f"/api/v1/sessions/{session_id}/kpis/overview")
    ghost = str(uuid.uuid4())
    response = client.get(f"/api/v1/sessions/{ghost}/kpis/overview")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_non_ready_session_is_never_served_from_cache(
    client: TestClient, session_root: str
) -> None:
    """M: parked ANALYZING sessions stay 409 and are never cached."""
    pending = park_at_analyzing(session_root, CANON_BYTES)
    response = client.get(f"/api/v1/sessions/{pending}/kpis/overview")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_READY"
    assert kpi_cache.get(pending) is None
    assert kpi_cache.cache_info()["sessionCount"] == 0


def test_empty_cache_reloads_successfully(
    client: TestClient, session_root: str
) -> None:
    """N: restart-equivalent empty cache is correctness-neutral."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    warm = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()
    kpi_cache.clear()  # restart: no restoration, no warming
    reloaded = client.get(f"/api/v1/sessions/{session_id}/kpis/overview").json()
    assert reloaded["error"] is None
    assert strip_meta(reloaded) == strip_meta(warm)


def test_byte_guard_boundary(
    client: TestClient, session_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O: <= limit is cacheable, > limit is not (real tables, exact edge)."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(settings.session_root, session_id)
    tables = kpi_service.load_canonical_tables(paths)
    size = kpi_cache.retained_bytes(tables)
    assert size > 0
    monkeypatch.setattr(kpi_cache, "retention_limit_bytes", lambda: size)
    assert kpi_cache.put_if_cacheable(session_id, tables) is True
    kpi_cache.clear()
    monkeypatch.setattr(kpi_cache, "retention_limit_bytes", lambda: size - 1)
    assert kpi_cache.put_if_cacheable(session_id, tables) is False
    assert kpi_cache.cache_info()["sessionCount"] == 0


def test_retained_bytes_use_deep_memory_not_rss(
    client: TestClient, session_root: str
) -> None:
    """Accounting sanity: deep bytes are positive and track frame content."""
    _ = session_root
    session_id = upload_ok(client, CANON_BYTES)
    paths = session_store.session_paths(settings.session_root, session_id)
    tables = kpi_service.load_canonical_tables(paths)
    size = kpi_cache.retained_bytes(tables)
    shallow = int(tables.items.memory_usage(index=True, deep=False).sum())
    assert size >= shallow
    assert size < settings.kpi_cache_retain_bytes
