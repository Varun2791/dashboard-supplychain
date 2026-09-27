"""Deterministic synthetic benchmark-data generator (ADR-042).

Produces DataCo-compatible V1 *header-shape* CSVs with invented values only:
no DataCo bytes, no copied rows, no reference expectations. Governed text
(`DECISIONS.md` ADR-007, `docs/canonical-schema.md`, `app/schema_registry.py`)
is the authority for header strings and enum spellings; everything else is
synthesized from a seeded ``random.Random``.

Two scenario profiles:

- ``valid``: satisfies V1 schema validation and reaches READY (zero
  blocking issues by construction). Used for performance measurement.
- ``quality-stress``: valid shape plus deterministic unknowns, missing
  values, padding, and arithmetic mismatches. Used to exercise detection;
  not required to reach READY.

Duplicate item keys are never emitted (duplicate-key negatives stay a
separate fixture per ADR-042).

Privacy: personal-field columns carry obviously synthetic tokens only
(``@example.invalid`` addresses, ``SYN-`` labels). No real names, real
emails, streets, or credentials are ever generated.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Version-pinned generator identity (ADR-042). Determinism must never rely
# on git revision alone; reports carry this alongside the seed and tier.
GENERATOR_VERSION = "1"

# Exact governed source header set/order. The 25 mapped headers mirror
# `app/schema_registry.py`; the redundant / audit-only / extra columns
# mirror the committed synthetic fixtures (which demonstrably reach READY).
HEADER: tuple[str, ...] = (
    "Order Id",
    "Order Item Id",
    "Customer Id",
    "Product Card Id",
    "Product Category Id",
    "order date (DateOrders)",
    "shipping date (DateOrders)",
    "Sales",
    "Order Item Discount",
    "Order Item Total",
    "Benefit per order",
    "Order Item Product Price",
    "Order Item Quantity",
    "Days for shipping (real)",
    "Days for shipment (scheduled)",
    "Delivery Status",
    "Order Status",
    "Shipping Mode",
    "Customer Segment",
    "Order Country",
    "Order Region",
    "Market",
    "Department Name",
    "Category Name",
    "Product Name",
    "Order Customer Id",
    "Late_delivery_risk",
    "Warehouse Zone",
    "Customer Email",
    "Buyer Latitude",
)

PROFILE_VALID = "valid"
PROFILE_STRESS = "quality-stress"
PROFILES: tuple[str, ...] = (PROFILE_VALID, PROFILE_STRESS)

# Governed benchmark tiers (ADR-042). The 180,519 tier matches only the
# governed reference row count and header shape — never distribution,
# quality, cardinalities, or KPI controls. Only SMALL is executed in the
# measurement-infrastructure pass; other tiers are definitions, not runs.
TIERS: dict[str, dict[str, int]] = {
    "small": {"rows": 5000, "products": 60, "customers": 800, "categories": 12},
    "medium": {"rows": 75000, "products": 110, "customers": 9000, "categories": 24},
    "reference_count": {
        "rows": 180519,
        "products": 118,
        "customers": 20652,
        "categories": 30,
    },
    "target": {"rows": 500000, "products": 160, "customers": 50000, "categories": 36},
}

# Closed order-status set (canonical-schema section 7).
ORDER_STATUSES: tuple[str, ...] = (
    "COMPLETE",
    "CLOSED",
    "PENDING",
    "PROCESSING",
    "ON_HOLD",
    "CANCELED",
    "PAYMENT_REVIEW",
    "SUSPECTED_FRAUD",
)
# Cumulative order-status mix (sums to 1.0; invented, not reference data).
_STATUS_MIX: tuple[tuple[str, float], ...] = (
    ("COMPLETE", 0.880),
    ("CLOSED", 0.910),
    ("PENDING", 0.930),
    ("PROCESSING", 0.950),
    ("ON_HOLD", 0.960),
    ("CANCELED", 0.980),
    ("PAYMENT_REVIEW", 0.985),
    ("SUSPECTED_FRAUD", 1.0),
)

# Only verbatim-evidenced source spellings (profile_checks-ADRs stay clean).
SHIPPING_MODES: tuple[str, ...] = ("Standard Class", "Same Day")
CUSTOMER_SEGMENTS: tuple[str, ...] = ("Consumer", "Home Office")

CANCEL_DELIVERY_STATUS = "Shipping canceled"
NORMAL_DELIVERY_STATUS = "Shipped"

_CSV_NEWLINE = "\n"


@dataclass(frozen=True)
class TierConfig:
    """Resolved generation parameters for one benchmark run."""

    tier: str
    profile: str
    seed: int
    rows: int
    products: int
    customers: int
    categories: int


@dataclass(frozen=True)
class GeneratedDataset:
    """Generator output plus identity metadata (no measurements)."""

    config: TierConfig
    content: bytes
    sha256: str
    actual_rows: int


def resolve_config(
    tier: str,
    seed: int,
    profile: str = PROFILE_VALID,
    rows: int | None = None,
) -> TierConfig:
    """Resolve a tier name to concrete parameters (rows may be overridden)."""
    if tier not in TIERS:
        raise ValueError(
            f"Unknown benchmark tier '{tier}'. Use one of {sorted(TIERS)}."
        )
    if profile not in PROFILES:
        raise ValueError(
            f"Unknown benchmark profile '{profile}'. Use one of {list(PROFILES)}."
        )
    base = TIERS[tier]
    requested = base["rows"] if rows is None else rows
    if requested < 1:
        raise ValueError(f"Requested row count must be >= 1, got {requested}.")
    return TierConfig(
        tier=tier,
        profile=profile,
        seed=seed,
        rows=requested,
        products=base["products"],
        customers=base["customers"],
        categories=base["categories"],
    )


def _money(cents: int) -> str:
    """Format integer cents as 2-dp money without float error."""
    sign = "-" if cents < 0 else ""
    magnitude = abs(cents)
    return f"{sign}{magnitude // 100}.{magnitude % 100:02d}"


def _pick_status(rng: random.Random) -> str:
    draw = rng.random()
    for status, ceiling in _STATUS_MIX:
        if draw < ceiling:
            return status
    return "COMPLETE"  # pragma: no cover - float safety net


def generate_dataset(
    tier: str = "small",
    seed: int = 20260926,
    profile: str = PROFILE_VALID,
    rows: int | None = None,
) -> GeneratedDataset:
    """Generate a deterministic synthetic benchmark CSV.

    Identical (generator version, tier config, seed, profile) inputs yield
    byte-identical output; only the seeded RNG is consumed.
    """
    config = resolve_config(tier, seed, profile, rows)
    rng = random.Random(config.seed)
    stress = config.profile == PROFILE_STRESS

    # Product catalog: identifying dims are a pure function of product_id,
    # so product invariance (DQ-GRAIN-003) holds by construction.
    products: list[dict[str, str | int]] = []
    for pid in range(1, config.products + 1):
        category = (pid % config.categories) + 1
        family = ("Widget", "Gadget", "Gizmo", "Doohickey")[pid % 4]
        products.append(
            {
                "id": f"SYN-PROD-{pid:04d}",
                "category_id": f"SYN-CAT-{category:02d}",
                "department": f"SYN-Dept-{(category % 4) + 1:02d}",
                "category_name": f"SYN-Category-{category:02d}",
                "product_name": f"SYN-{family}-{pid:03d}",
                "price_cents": 300 + ((pid * 7919) % 49700),
            }
        )
    # Customer catalog: segment is a pure function of customer_id, so
    # customer invariance (DQ-GRAIN-004) holds by construction.
    segments: list[str] = []
    for cid in range(1, config.customers + 1):
        segments.append("Consumer" if cid % 5 != 4 else "Home Office")

    lines: list[str] = []
    order_seq = 0
    item_seq = 0
    base_date = date(2021, 1, 1)
    while len(lines) < config.rows:
        remaining = config.rows - len(lines)
        draw = rng.random()
        if draw < 0.55:
            wanted = 1
        elif draw < 0.80:
            wanted = 2
        elif draw < 0.92:
            wanted = 3
        else:
            wanted = 4
        line_count = min(wanted, remaining)
        order_seq += 1
        customer_num = rng.randint(1, config.customers)

        # Per-order attributes are drawn once, so order invariance
        # (DQ-GRAIN-001) holds by construction across the order's lines.
        status = _pick_status(rng)
        mode = "Standard Class" if rng.random() < 0.7 else "Same Day"
        scheduled = 0 if mode == "Same Day" else rng.randint(2, 7)
        mix = rng.random()
        if mix < 0.40:
            actual = scheduled + rng.randint(1, 4)
        elif mix < 0.75:
            actual = max(0, scheduled - rng.randint(1, 3))
        else:
            actual = scheduled
        shipped = rng.random() >= 0.045
        ordered_at = datetime.combine(
            base_date + timedelta(days=rng.randrange(0, 365)),
            datetime.min.time(),
        ) + timedelta(hours=rng.randrange(0, 24), minutes=rng.randrange(0, 60))
        shipped_at = ordered_at + timedelta(days=actual)
        is_late = shipped and actual > scheduled

        for _ in range(line_count):
            item_seq += 1
            product = products[rng.randrange(len(products))]
            assert isinstance(product["price_cents"], int)
            price_cents: int = product["price_cents"]
            quantity = rng.randint(1, 9)
            gross = quantity * price_cents
            rate_choice = rng.random()
            if rate_choice < 0.30:
                pct = 0
            elif rate_choice < 0.55:
                pct = 5
            elif rate_choice < 0.75:
                pct = 10
            elif rate_choice < 0.88:
                pct = 15
            elif rate_choice < 0.96:
                pct = 20
            else:
                pct = 25
            discount = (gross * pct + 50) // 100
            net = gross - discount
            if rng.random() < 0.05:
                margin = -rng.uniform(0.01, 0.30)
            else:
                margin = rng.uniform(-0.08, 0.35)
            profit = int(round(net * margin))

            row_status = status
            row_mode = mode
            row_segment = segments[customer_num - 1]
            row_net = net
            order_ts = ordered_at.strftime("%m-%d-%Y %H:%M")
            ship_ts = shipped_at.strftime("%m-%d-%Y %H:%M")
            product_name = str(product["product_name"])
            if stress:
                roll = rng.random()
                if roll < 0.02:
                    row_status = "BOGUS_STATUS"
                elif roll < 0.04:
                    ship_ts = ""
                elif roll < 0.05:
                    product_name = f" {product_name} "
                elif roll < 0.06:
                    row_net = net + 100
                if rng.random() < 0.02:
                    row_mode = "SYN-Unknown-Mode"
                    row_segment = "SYN-Unknown-Segment"

            cells = [
                f"SYN-ORDER-{order_seq:06d}",
                f"SYN-ITEM-{item_seq:06d}",
                f"SYN-CUST-{customer_num:06d}",
                str(product["id"]),
                str(product["category_id"]),
                order_ts,
                ship_ts,
                _money(gross),
                _money(discount),
                _money(row_net),
                _money(profit),
                _money(price_cents),
                str(quantity),
                str(actual),
                str(scheduled),
                NORMAL_DELIVERY_STATUS if shipped else CANCEL_DELIVERY_STATUS,
                row_status,
                row_mode,
                row_segment,
                f"SYN-Land-{(order_seq % 4) + 1}",
                ("North", "South", "East", "West")[order_seq % 4],
                f"SYN-Market-{(order_seq % 3) + 1}",
                str(product["department"]),
                str(product["category_name"]),
                product_name,
                str(order_seq % 997),
                "1" if is_late else "0",
                f"Zone {(order_seq % 9) + 1}",
                f"synthetic.user{customer_num:06d}@example.invalid",
                f"{10 + (customer_num % 4000) / 100:.2f}",
            ]
            lines.append(",".join(cells))

    content = (
        ",".join(HEADER) + _CSV_NEWLINE + _CSV_NEWLINE.join(lines) + _CSV_NEWLINE
    ).encode("utf-8")
    return GeneratedDataset(
        config=config,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        actual_rows=len(lines),
    )
