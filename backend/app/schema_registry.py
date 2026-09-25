"""V1 DataCo source-to-canonical mapping registry (ADR-001, ADR-007, ADR-030).

Every entry reproduces an exact source header string from accepted
governance (`DECISIONS.md` ADR-007, `docs/canonical-schema.md` sections 1,
5, 6, 9). No local DataCo file exists in this environment, so the governed
text is the authority; nothing here is guessed from memory.

Lookup policy (`docs/canonical-schema.md` section 9): matching normalizes
BOM, surrounding whitespace, and case for *lookup* and always preserves the
original header text in reports. Anything else (typos, synonyms,
punctuation rewrites, fuzzy/AI matching) never maps.

Required policy (`docs/data-quality-rules.md` DQ-SCHEMA-001): a field is
required when the V1 pipeline needs it — IDs, dates, amounts, quantities,
and delivery fields. Dimensions and merchandising names are optional: their
absence degrades breakdowns gracefully instead of failing the session.

Bounded deferrals (documented, not guessed):
- customer-side geography column names are not exactly specified in
  governance, so they are absent from this registry and surface as
  unrecognized extras until a later phase governs them;
- exact direct-personal header strings are likewise unspecified, so such
  columns also surface as unrecognized extras. Safety holds by
  construction: only exact-registry entries can ever map to canonical
  fields, so unlisted columns can never leak into canonical outputs.
"""

from __future__ import annotations

from dataclasses import dataclass

# Reference identifier for the V1 mapping (ADR-001: reference, not schema).
SCHEMA_REFERENCE_ID = "dataco-v1"

# Source grain carried in schema metadata (ADR-002). Phase 5 reports it;
# canonical table construction belongs to a later phase.
SOURCE_GRAIN_ORDER_ITEM = "order_item"


@dataclass(frozen=True)
class MappingEntry:
    """One governed source-header mapping (originals preserved in reports)."""

    source_header: str
    canonical_field: str
    required: bool
    role: str


@dataclass(frozen=True)
class TimestampContract:
    """Parser expectation recorded as metadata, not executed in Phase 5."""

    canonical_field: str
    source_header: str
    parse: str
    timezone_naive: bool


# Required canonical source fields: IDs, dates, amounts, quantities, and
# delivery fields (DQ-SCHEMA-001). Missing any of these fails the session.
REQUIRED_MAPPINGS: tuple[MappingEntry, ...] = (
    MappingEntry("Order Id", "order_id", True, "order key; repeats per line"),
    MappingEntry(
        "Order Item Id",
        "order_item_id",
        True,
        "unique line key at order-item grain",
    ),
    MappingEntry("Customer Id", "customer_id", True, "sanitized customer key"),
    MappingEntry("Product Card Id", "product_id", True, "product key"),
    MappingEntry("Product Category Id", "category_id", True, "category key"),
    MappingEntry(
        "order date (DateOrders)",
        "order_timestamp",
        True,
        "KPI date basis; explicit month-first parse",
    ),
    MappingEntry(
        "shipping date (DateOrders)",
        "ship_timestamp",
        True,
        "validation evidence only; explicit month-first parse",
    ),
    MappingEntry("Sales", "gross_sales", True, "pre-discount line value"),
    MappingEntry("Order Item Discount", "discount_amount", True, "line discount"),
    MappingEntry(
        "Order Item Total",
        "net_sales",
        True,
        "authoritative recorded net line value (ADR-008)",
    ),
    MappingEntry(
        "Benefit per order",
        "profit_amount",
        True,
        "recorded line profit despite source label; negatives retained",
    ),
    MappingEntry("Order Item Product Price", "unit_price", True, "per-unit price"),
    MappingEntry("Order Item Quantity", "quantity_units", True, "line units"),
    MappingEntry(
        "Days for shipping (real)",
        "actual_shipping_days",
        True,
        "authoritative actual days for shipment KPIs (ADR-015)",
    ),
    MappingEntry(
        "Days for shipment (scheduled)",
        "scheduled_shipping_days",
        True,
        "schedule reference for shipment KPIs",
    ),
    MappingEntry(
        "Delivery Status",
        "delivery_status",
        True,
        "cancel signal; exact value 'Shipping canceled' (ADR-012/013)",
    ),
    MappingEntry("Order Status", "order_status", True, "commercial lifecycle state"),
    MappingEntry("Shipping Mode", "shipping_mode", True, "shipment class"),
)

# Optional canonical source fields: recognized dimensions whose absence
# degrades breakdowns gracefully instead of failing the session.
OPTIONAL_MAPPINGS: tuple[MappingEntry, ...] = (
    MappingEntry("Customer Segment", "customer_segment", False, "customer tier"),
    MappingEntry(
        "Order Country", "destination_country", False, "destination geography"
    ),
    MappingEntry("Order Region", "destination_region", False, "destination geography"),
    MappingEntry("Market", "destination_market", False, "destination grouping"),
    MappingEntry("Department Name", "department_name", False, "merch hierarchy"),
    MappingEntry("Category Name", "category_name", False, "merch hierarchy"),
    MappingEntry("Product Name", "product_name", False, "display label"),
)

# Governed redundant copies (ADR-007): recognized, never mapped.
REDUNDANT_HEADERS: frozenset[str] = frozenset(
    {
        "Order Customer Id",
        "Sales per customer",
        "Order Profit Per Order",
    }
)

# Leakage-flagged audit evidence (ADR-018, ADR-030): recognized, classified
# as excluded, never a classification input and never `is_late`.
AUDIT_ONLY_HEADERS: frozenset[str] = frozenset({"Late_delivery_risk"})

# Exact cancel signal value (canonical-schema section 6).
CANCEL_SIGNAL_VALUE = "Shipping canceled"


def lookup_key(header: str) -> str:
    """Registry lookup normalization: BOM-drop, strip, casefold.

    Mirrors the Phase-4 duplicate-detection normalization so a file rejected
    for duplicates can never carry two headers that map to one entry, and so
    lookup stays deterministic. Originals are always preserved in reports.
    """
    return header.replace("\ufeff", "").strip().casefold()


# Normalized lookup table: exact governed strings, no aliases.
_LOOKUP: dict[str, MappingEntry] = {}
for _entry in (*REQUIRED_MAPPINGS, *OPTIONAL_MAPPINGS):
    _key = lookup_key(_entry.source_header)
    if _key in _LOOKUP:  # pragma: no cover - registry self-check
        raise ValueError(f"Registry collision on normalized header: {_key!r}")
    _LOOKUP[_key] = _entry


_REDUNDANT_KEYS = frozenset(lookup_key(name) for name in REDUNDANT_HEADERS)
_AUDIT_KEYS = frozenset(lookup_key(name) for name in AUDIT_ONLY_HEADERS)


def lookup(header: str) -> MappingEntry | None:
    """Return the governed mapping for a source header, if any."""
    return _LOOKUP.get(lookup_key(header))


def is_redundant(header: str) -> bool:
    """True for governed redundant copies (recognized, never mapped)."""
    return lookup_key(header) in _REDUNDANT_KEYS


def is_audit_only(header: str) -> bool:
    """True for leakage-flagged audit evidence (never mapped)."""
    return lookup_key(header) in _AUDIT_KEYS


TIMESTAMP_CONTRACTS: tuple[TimestampContract, ...] = (
    TimestampContract(
        "order_timestamp",
        "order date (DateOrders)",
        "explicit month-first",
        True,
    ),
    TimestampContract(
        "ship_timestamp",
        "shipping date (DateOrders)",
        "explicit month-first",
        True,
    ),
)
