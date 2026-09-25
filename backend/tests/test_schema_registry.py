"""Mapping-registry regression contract (ADR-007, ADR-030, canonical-schema).

Every accepted source header is pinned exactly: an accidental rename, a
changed canonical target, a flipped required flag, or lost timestamp
metadata fails loudly here. Lookup normalization (BOM/case/whitespace) is
governed by canonical-schema section 9; everything else must not map.
"""

from __future__ import annotations

from app.schema_registry import (
    AUDIT_ONLY_HEADERS,
    OPTIONAL_MAPPINGS,
    REDUNDANT_HEADERS,
    REQUIRED_MAPPINGS,
    SCHEMA_REFERENCE_ID,
    SOURCE_GRAIN_ORDER_ITEM,
    TIMESTAMP_CONTRACTS,
    is_audit_only,
    is_redundant,
    lookup,
    lookup_key,
)

CORE_MAPPINGS = {
    "Order Id": "order_id",
    "Order Item Id": "order_item_id",
    "Customer Id": "customer_id",
    "Product Card Id": "product_id",
    "Product Category Id": "category_id",
    "Order Item Product Price": "unit_price",
    "Sales": "gross_sales",
    "Order Item Discount": "discount_amount",
    "Order Item Total": "net_sales",
    "Benefit per order": "profit_amount",
    "order date (DateOrders)": "order_timestamp",
    "shipping date (DateOrders)": "ship_timestamp",
    "Days for shipping (real)": "actual_shipping_days",
    "Days for shipment (scheduled)": "scheduled_shipping_days",
}

EXTRA_REQUIRED = {
    "Delivery Status": "delivery_status",
    "Order Status": "order_status",
    "Shipping Mode": "shipping_mode",
    "Order Item Quantity": "quantity_units",
}

OPTIONAL_EXPECTED = {
    "Customer Segment": "customer_segment",
    "Order Country": "destination_country",
    "Order Region": "destination_region",
    "Market": "destination_market",
    "Department Name": "department_name",
    "Category Name": "category_name",
    "Product Name": "product_name",
}


def test_reference_and_grain_constants() -> None:
    assert SCHEMA_REFERENCE_ID == "dataco-v1"
    assert SOURCE_GRAIN_ORDER_ITEM == "order_item"


def test_core_adr007_mappings_exact() -> None:
    for source, canonical in CORE_MAPPINGS.items():
        entry = lookup(source)
        assert entry is not None, f"missing registry entry for {source!r}"
        assert entry.source_header == source
        assert entry.canonical_field == canonical
        assert entry.required is True


def test_delivery_and_quantity_required() -> None:
    for source, canonical in EXTRA_REQUIRED.items():
        entry = lookup(source)
        assert entry is not None, f"missing registry entry for {source!r}"
        assert entry.canonical_field == canonical
        assert entry.required is True


def test_optional_mappings_exact() -> None:
    assert len(OPTIONAL_MAPPINGS) == len(OPTIONAL_EXPECTED)
    for source, canonical in OPTIONAL_EXPECTED.items():
        entry = lookup(source)
        assert entry is not None, f"missing registry entry for {source!r}"
        assert entry.canonical_field == canonical
        assert entry.required is False


def test_required_count_is_stable() -> None:
    assert len(REQUIRED_MAPPINGS) == len(CORE_MAPPINGS) + len(EXTRA_REQUIRED)


def test_governed_normalization_maps() -> None:
    """BOM/case/whitespace variants map (canonical-schema section 9)."""
    assert lookup("ORDER ID") is not None
    assert lookup("order id") is not None
    assert lookup("  Order Id  ") is not None
    assert lookup("﻿Sales") is not None
    assert lookup("ORDER ID").canonical_field == "order_id"  # type: ignore[union-attr]


def test_non_normalization_differences_never_map() -> None:
    """Only BOM/case/whitespace variants map (canonical-schema section 9).

    Typos, synonyms, and punctuation rewrites must not silently map. Case
    variants such as "ORDER ID" DO map by the governed normalization; the
    entries below differ by more than normalization and must not.
    """
    for header in [
        "order number",
        "Order Ids",
        "Order-Id",
        "OrderId",
        "Sales Amount",
        "Total Sales",
        "Discount",
        "Profit",
        "Order Date",
        "Ship Date",
        "Days Late",
        "Customer ID ",
        "  ",
        "",
    ]:
        if header.strip() == "":
            assert lookup(header) is None
            continue
        # "Customer ID " strips to a case variant of a governed header, so it
        # maps by the governed normalization; the rest must not.
        if lookup_key(header) == lookup_key("Customer Id"):
            assert lookup(header) is not None
        else:
            assert lookup(header) is None, f"{header!r} must not map"


def test_redundant_copies_recognized_never_mapped() -> None:
    assert REDUNDANT_HEADERS == frozenset(
        {"Order Customer Id", "Sales per customer", "Order Profit Per Order"}
    )
    for header in REDUNDANT_HEADERS:
        assert is_redundant(header) is True
        assert lookup(header) is None


def test_audit_only_never_mapped() -> None:
    assert AUDIT_ONLY_HEADERS == frozenset({"Late_delivery_risk"})
    assert is_audit_only("Late_delivery_risk") is True
    assert lookup("Late_delivery_risk") is None


def test_timestamp_contracts_month_first_naive() -> None:
    by_field = {item.canonical_field: item for item in TIMESTAMP_CONTRACTS}
    for field in ("order_timestamp", "ship_timestamp"):
        assert by_field[field].parse == "explicit month-first"
        assert by_field[field].timezone_naive is True
    assert by_field["order_timestamp"].source_header == ("order date (DateOrders)")
    assert by_field["ship_timestamp"].source_header == ("shipping date (DateOrders)")
