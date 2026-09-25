"""Domain errors for Phase-4 ingestion.

Each error carries the contract error code, the pipeline stage that failed,
an actionable user-facing message, machine-readable safe details, and the
HTTP status from `docs/api-contract.md`. Route handlers map these to the
error envelope; unexpected exceptions map to `INTERNAL_STAGE_ERROR`.
"""

from __future__ import annotations

from typing import Any

# Contract error codes used by Phase 4 (docs/api-contract.md section 4).
EMPTY_FILE = "EMPTY_FILE"
INVALID_EXTENSION = "INVALID_EXTENSION"
MALFORMED_HEADER = "MALFORMED_HEADER"
UNREADABLE_HEADER = "UNREADABLE_HEADER"
DUPLICATE_HEADERS = "DUPLICATE_HEADERS"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
UNSUPPORTED_ENCODING = "UNSUPPORTED_ENCODING"
MALFORMED_CSV = "MALFORMED_CSV"
NOT_READY = "NOT_READY"
SCHEMA_MISSING_COLUMN = "SCHEMA_MISSING_COLUMN"
INVALID_SEVERITY_FILTER = "INVALID_SEVERITY_FILTER"
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
SESSION_EXPIRED = "SESSION_EXPIRED"
INTERNAL_STAGE_ERROR = "INTERNAL_STAGE_ERROR"
DUPLICATE_ITEM_KEY = "DUPLICATE_ITEM_KEY"
ORDER_INVARIANCE_CONFLICT = "ORDER_INVARIANCE_CONFLICT"
PRODUCT_INVARIANCE_CONFLICT = "PRODUCT_INVARIANCE_CONFLICT"
CUSTOMER_INVARIANCE_CONFLICT = "CUSTOMER_INVARIANCE_CONFLICT"

# Stage reported for every synchronous ingestion guard (docs/api-contract.md).
STAGE_VALIDATING = "VALIDATING"

# Stage reported for value-level profiling failures (DQ-FILE-005 and co).
STAGE_PROFILING = "PROFILING"

# Stage reported for auditable-cleaning failures (Phase 7).
STAGE_CLEANING = "CLEANING"

# Stage reported for canonical-build failures and quality gates (Phase 8).
STAGE_CANONICALIZING = "CANONICALIZING"


class IngestionError(Exception):
    """A contract-mapped ingestion failure (never leaks raw contents)."""

    def __init__(
        self,
        code: str,
        stage: str,
        message: str,
        http_status: int,
        details: dict[str, Any] | None = None,
        session_id: str | None = None,
        session_state: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.http_status = http_status
        self.details = details if details is not None else {}
        self.session_id = session_id
        self.session_state = session_state
