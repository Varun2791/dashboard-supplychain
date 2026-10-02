"""Session-scoped canonical KPI-table cache (ADR-043).

Process-local, capacity-one, lazy, read-only retention of the existing
`KpiTables` result (`items`, `orders`, `product_ids`, `customer_ids`) so
repeated analytical requests for one READY session pay a single
`load_canonical_tables(...)` parse/materialization. Performance
optimization only: persisted canonical artifacts stay authoritative and
no correctness state exists only in memory.

Rules: populate only from the analytical serving path after all READY
gates pass (never pipeline, upload, or startup); borrow read-only with
no copy-on-read; capacity one session; oversized tables are served but
never retained and never evict a cached session; no TTL (READY artifacts
are immutable); no lock (one worker, synchronous pandas in the
event-loop path — revisit if that changes); governed DELETE evicts
before the persisted tree is removed.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pandas as pd

from app.config import settings

if TYPE_CHECKING:
    from app.kpis import KpiTables


# At most one session has reachable cached tables (C4 one-active-session
# bound: N sessions never means N cached frames).
_CACHED_SESSION_ID: str | None = None
_CACHED_TABLES: KpiTables | None = None
_CACHED_BYTES: int = 0
_HITS: int = 0
_MISSES: int = 0


def retention_limit_bytes() -> int:
    """Maximum retained `KpiTables` deep bytes (ADR-043 byte guard)."""
    return settings.kpi_cache_retain_mb * 1024 * 1024


def _frame_bytes(frame: pd.DataFrame) -> int:
    """Deep memory of one canonical frame (pandas accounting, never RSS)."""
    return int(frame.memory_usage(index=True, deep=True).sum())


def _str_list_bytes(values: list[str]) -> int:
    """Retained memory of one id list, container plus elements."""
    total = sys.getsizeof(values)
    for value in values:
        total += sys.getsizeof(value)
    return total


def retained_bytes(tables: KpiTables) -> int:
    """Explicit retained-size accounting for one loaded `KpiTables`."""
    return (
        _frame_bytes(tables.items)
        + _frame_bytes(tables.orders)
        + _str_list_bytes(tables.product_ids)
        + _str_list_bytes(tables.customer_ids)
    )


def get(session_id: str) -> KpiTables | None:
    """Return the cached tables for this session, counting hit/miss."""
    global _HITS, _MISSES
    if _CACHED_SESSION_ID == session_id and _CACHED_TABLES is not None:
        _HITS += 1
        return _CACHED_TABLES
    _MISSES += 1
    return None


def put_if_cacheable(session_id: str, tables: KpiTables) -> bool:
    """Retain `tables` when they fit the byte guard (capacity-one).

    Oversized tables are served by the caller but never retained, and
    never evict an already cached session. Returns True when retained.
    """
    global _CACHED_SESSION_ID, _CACHED_TABLES, _CACHED_BYTES
    size = retained_bytes(tables)
    if size > retention_limit_bytes():
        return False
    _CACHED_SESSION_ID = session_id
    _CACHED_TABLES = tables
    _CACHED_BYTES = size
    return True


def evict(session_id: str) -> bool:
    """Drop this session's entry; missing entries are a no-op (False)."""
    global _CACHED_SESSION_ID, _CACHED_TABLES, _CACHED_BYTES
    if _CACHED_SESSION_ID != session_id:
        return False
    _CACHED_SESSION_ID = None
    _CACHED_TABLES = None
    _CACHED_BYTES = 0
    return True


def clear() -> None:
    """Empty the whole cache (tests, restart-equivalence); keeps counters."""
    global _CACHED_SESSION_ID, _CACHED_TABLES, _CACHED_BYTES
    _CACHED_SESSION_ID = None
    _CACHED_TABLES = None
    _CACHED_BYTES = 0


def cache_info() -> dict[str, int | str | None]:
    """Minimal introspection for tests and evidence (never PII/values)."""
    count = 1 if _CACHED_SESSION_ID is not None else 0
    return {
        "sessionId": _CACHED_SESSION_ID,
        "sessionCount": count,
        "retainedBytes": _CACHED_BYTES,
        "retentionLimitBytes": retention_limit_bytes(),
        "hits": _HITS,
        "misses": _MISSES,
    }
