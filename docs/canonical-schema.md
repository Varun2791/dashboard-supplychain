# V1 Canonical Schema

Binding: ADR-002 (grain), ADR-007 (source-of-truth fields), ADR-008 (net authoritative), ADR-015 (actual days authoritative), ADR-016 (geo separation), ADR-005 (PII exclusion), ADR-003 (provenance).

Conventions: identifiers and postal codes are `string` (non-null where key). Money is decimal-safe, serialized per `docs/api-contract.md`. Dates are timezone-naive. `null` means absent/inapplicable — never an invented value.

Every field below is tagged with exactly one origin class:

- **S — source-derived:** value carried from a mapped source column (possibly type-cast / trimmed / enum-mapped).
- **M — system metadata:** added by the pipeline (provenance, session scope).
- **D — deterministic derived:** computed from canonical fields by a recorded formula (a derivation, not a cleaning fix).
- **A — aggregated:** summed/counted from lower-grain canonical rows exactly once.

No speculative fields: anything not required by a V1 KPI, filter, drilldown, reconciliation, or audit report is out. In particular there is no product reference-price field and no customer geography derived from destinations.

## 1. `order_items` — grain: one row per source line (`order_item_id` PK)

| Field | Type | Null | Class | Source / formula | Business meaning |
|---|---|---|---|---|---|
| `session_id` | string | NN | M | pipeline | session scope |
| `source_row_number` | int ≥1 | NN | M | ingestion order | provenance to raw line |
| `order_item_id` | string, unique | NN | S | `Order Item Id`, cast | line key |
| `order_id` | string, FK→orders | NN | S | `Order Id`, cast | order key (repeats legitimately) |
| `customer_id` | string | NN | S | `Customer Id` (`Order Customer Id` redundant, ADR-007) | sanitized customer key |
| `product_id` | string | NN | S | `Product Card Id` | product key |
| `category_id` | string | NN | S | `Product Category Id` | category key |
| `quantity_units` | int ≥0 | NN | S | `Order Item Quantity` | units on the line |
| `unit_price` | decimal(12,2) | NN | S | `Order Item Product Price` | per-unit price |
| `gross_sales` | decimal(12,2) | NN | S | `Sales` | pre-discount line value |
| `discount_amount` | decimal(12,2) | NN | S | `Order Item Discount` | line discount |
| `net_sales` | decimal(12,2) | NN | S | `Order Item Total`, authoritative (ADR-008) | recorded net line value |
| `profit_amount` | decimal(12,2) | NN | S | `Benefit per order` (mislabeled source label) | recorded line profit; may be negative (ADR-017) |
| `order_status` | enum | NN | S | `Order Status`, exact-map (§5) | commercial lifecycle state |
| `shipping_mode` | enum | NN | S | `Shipping Mode`, exact-map | shipment class |
| `customer_segment` | enum | NN | S | `Customer Segment`, exact-map | customer tier |
| `order_timestamp` | datetime naive | NN | S | `order date (DateOrders)`, month-first parse | date basis for all KPIs |
| `ship_timestamp` | datetime naive | nullable | S | `shipping date (DateOrders)`, month-first parse | validation evidence only |
| `actual_shipping_days` | int ≥0 | nullable (null when no shipment occurred) | S | `Days for shipping (real)`, authoritative (ADR-015) | KPI source for adherence |
| `scheduled_shipping_days` | int ≥0 | NN | S | `Days for shipment (scheduled)` | KPI source for adherence |
| `destination_country` | string trimmed | NN | S | `Order Country` | destination geography |
| `destination_region` | string trimmed | NN | S | `Order Region` | destination geography |
| `destination_market` | string trimmed | NN | S | `Market` | destination grouping |
| `department_name` | string trimmed | NN | S | `Department Name` | merch hierarchy |
| `category_name` | string trimmed | NN | S | `Category Name` | merch hierarchy |
| `product_name` | string trimmed | NN | S | `Product Name` | display label |
| `shipment_outcome` | enum | NN | D | §6 derivation (cancel flag, else days comparison) | LATE / EARLY / ON_SCHEDULE / SHIPPING_CANCELED |
| `is_late` | bool | nullable (null iff SHIPPING_CANCELED) | D | §6 derivation | adherence flag; null is a derivation, not a fix |
| `schedule_variance_days` | int | nullable (null iff cancelled) | D | `actual − scheduled` | days ahead (−) / behind (+) schedule |
| `order_date` | date naive | NN | D | date part of `order_timestamp` | calendar join key |

Deliberately not canonical: source discount/profit ratio columns (audit/validation evidence only, ADR-007); `Late_delivery_risk` (validation evidence only — never drives classification); redundant ID/price copies; `Sales per customer`; `Order Profit Per Order`; any personal or precise-geo column (§7).

## 2. `orders` — grain: one row per `order_id` (`order_id` PK)

Built only after order-invariance validation passes (conflicts → `DQ-GRAIN-001`, build blocked, no first-row pick).

| Field | Type | Null | Class | Formula | Meaning |
|---|---|---|---|---|---|
| `order_id` | string PK | NN | S | group key | order key |
| `session_id` | string | NN | M | pipeline | scope |
| `customer_id` | string | NN | S | invariant across lines | ordering customer |
| `order_timestamp` | datetime naive | NN | S | invariant | order date basis |
| `order_status` | enum | NN | S | invariant | status |
| `shipping_mode` | enum | NN | S | invariant | shipment class |
| `customer_segment` | enum | NN | S | invariant | tier |
| `destination_country/region/market`, `department?` no — destination + merch dims carried where invariant | string | NN | S | invariant | dimensional attrs |
| `scheduled_shipping_days` | int | NN | S | invariant | schedule |
| `actual_shipping_days` | int | nullable | S | invariant | authoritative actual |
| `shipment_outcome` | enum | NN | D | invariant of line derivation, re-checked at order level | outcome |
| `is_late` | bool | nullable | D | null iff SHIPPING_CANCELED | adherence |
| `line_count` | int | NN | A | count(lines) | lines per order |
| `total_units` | int | NN | A | sum(`quantity_units`) | units per order |
| `gross_value` | decimal | NN | A | sum(`gross_sales`) | order gross |
| `discount_total` | decimal | NN | A | sum(`discount_amount`) | order discount |
| `net_value` | decimal | NN | A | sum(`net_sales`) | recorded net order value |
| `profit_total` | decimal | NN | A | sum(`profit_amount`) | recorded order profit |

Order totals are aggregated from items exactly once; nothing multiplies a line value by a line count.

## 3. `products` — grain: one row per `product_id` (PK)

Only fields required for V1 analytics and defensible aggregations. No reference-price field (a median/mode unit price would be a new derived business concept with no V1 consumer).

| Field | Type | Null | Class | Source / formula |
|---|---|---|---|---|
| `product_id` | string PK | NN | S | `Product Card Id` |
| `category_id` | string | NN | S | `Product Category Id`, invariant-checked |
| `department_name` | string | NN | S | invariant-checked |
| `category_name` | string | NN | S | invariant-checked |
| `product_name` | string | NN | S | invariant-checked |
| `line_count` | int | NN | A | count(lines) |
| `total_units` | int | NN | A | sum(`quantity_units`) |
| `total_net_value` | decimal | NN | A | sum(`net_sales`) |
| `total_profit_amount` | decimal | NN | A | sum(`profit_amount`) |

## 4. `customers_sanitized` — grain: one row per `customer_id` (PK)

Customer geography comes **only** from customer-side source fields (e.g., customer city/state/country columns). It is never derived from order-destination geography: a customer’s most-common destination must not be substituted as customer location (ADR-016). If customer-side geography is absent, the fields are `null` and flagged — never imputed from destinations.

| Field | Type | Null | Class | Source / formula |
|---|---|---|---|---|
| `customer_id` | string PK | NN | S | `Customer Id` |
| `customer_segment` | enum | NN | S | invariant-checked |
| `customer_country` | string | nullable | S | customer-side country only |
| `customer_state` | string | nullable | S | customer-side state only |
| `customer_city` | string | nullable | S | customer-side city only (coarse; no street/ZIP) |
| `order_count` | int | NN | A | count(distinct orders) |
| `total_net_value` | decimal | NN | A | sum(`net_sales`) |
| `total_profit_amount` | decimal | NN | A | sum(`profit_amount`) |

## 5. `calendar` — grain: one row per date in range (D, all fields)

`date` (PK), `year`, `quarter`, `month`, `iso_week`, `day_of_week`, `is_weekend` — derived from the date part of canonical `order_timestamp` values present in the session.

## 6. Derivation rules (canonical derivations, not cleaning)

**Shipment outcome / `is_late`** — the only classifier is the authoritative day fields (ADR-015). `Late_delivery_risk` is validation/audit evidence and must not drive classification; timestamp differences are validation evidence only.

```
if delivery_status == "Shipping canceled" (exact source value for cancellation):
    shipment_outcome = SHIPPING_CANCELED
    is_late = null                        # canonical derivation (see §8)
elif actual_shipping_days > scheduled_shipping_days:  shipment_outcome = LATE;         is_late = true
elif actual_shipping_days == scheduled_shipping_days: shipment_outcome = ON_SCHEDULE;  is_late = false
else:                                                  shipment_outcome = EARLY;        is_late = false
```

`schedule_variance_days = actual_shipping_days − scheduled_shipping_days` (null when cancelled). `order_date = date(order_timestamp)`.

## 7. Enum definitions (exact-match mapping; unknown → flagged)

| Enum | Canonical values | Source examples mapped exactly (trimmed, case-sensitive) |
|---|---|---|
| `order_status` | `COMPLETE \| CLOSED \| PENDING \| PROCESSING \| ON_HOLD \| CANCELED \| PAYMENT_REVIEW \| SUSPECTED_FRAUD` | e.g., `COMPLETE`, `CANCELED`, `SUSPECTED_FRAUD` (full table verified at implementation against header-normalized source) |
| `shipment_outcome` | `LATE \| EARLY \| ON_SCHEDULE \| SHIPPING_CANCELED` | derived per §6; cancel detected from `Delivery Status = "Shipping canceled"` |
| `shipping_mode` | `STANDARD_CLASS \| SECOND_CLASS \| FIRST_CLASS \| SAME_DAY` | e.g., `Standard Class`, `Same Day` |
| `customer_segment` | `CONSUMER \| CORPORATE \| HOME_OFFICE` | e.g., `Consumer`, `Home Office` |
| `issue_severity` | `ERROR \| WARNING \| INFO` | DQ catalogue |
| `treatment` | `detected \| fixed \| flagged \| excluded \| unchanged` | audit log |

Any source value outside the mapped set becomes `UNKNOWN_FLAGGED` for reporting: counted, shown as unknown, excluded from split KPIs. It is never silently coerced into a known category.

## 8. Observation vs cleaning vs derivation vs validation

- **Source observation:** what the raw file contains (e.g., “2,855 orders have `Delivery Status = Shipping canceled`”).
- **Cleaning transformation:** an approved reversible normalization of a carried value (trim whitespace; cast ID to string; exact enum map). Logged as `fixed`.
- **Canonical derivation:** a new field computed by a recorded formula (`shipment_outcome`, `is_late = null` for cancelled, variances, calendar fields). Logged as derived — **not** as a “fixed” data-quality issue.
- **Validation result:** a check outcome that may block a stage (tolerance check, invariance check, `Late_delivery_risk` agreement check). Logged with severity and blocked stage; it changes no data.

## 9. Exact DataCo→canonical mapping (source of truth: ADR-007 + this doc)

| Canonical field | Raw source header | Notes |
|---|---|---|
| `order_id` | `Order Id` | string cast |
| `order_item_id` | `Order Item Id` | string cast, unique |
| `customer_id` | `Customer Id` | `Order Customer Id` redundant |
| `product_id` | `Product Card Id` | other product-ID copy redundant |
| `category_id` | `Product Category Id` | other category-ID copy redundant |
| `unit_price` | `Order Item Product Price` | product-price copy redundant |
| `gross_sales` | `Sales` | pre-discount |
| `discount_amount` | `Order Item Discount` | — |
| `net_sales` | `Order Item Total` | authoritative; tolerance-validated |
| `profit_amount` | `Benefit per order` | line profit despite label |
| `order_timestamp` | `order date (DateOrders)` | month-first parse |
| `ship_timestamp` | `shipping date (DateOrders)` | month-first parse |
| `actual_shipping_days` | `Days for shipping (real)` | authoritative |
| `scheduled_shipping_days` | `Days for shipment (scheduled)` | — |
| `order_status` | `Order Status` | exact enum map |
| `shipping_mode` | `Shipping Mode` | exact enum map |
| `customer_segment` | `Customer Segment` | exact enum map |
| cancel signal | `Delivery Status` | `"Shipping canceled"` exact value only |
| audit-only | `Late_delivery_risk`, source ratio columns, timestamp pairs | validation evidence, never classification input |
| destination dims | `Order Country`, `Order Region`, `Market` (+ state/category/product/department name columns) | trimmed labels |
| customer-side geo | customer city/state/country columns | coarse only; never destinations |

Header matching normalizes BOM/case/whitespace for lookup but preserves original names in the schema report. classifications: required / optional / redundant / excluded / unknown per `docs/data-quality-rules.md`.

## 10. Privacy exclusions

The following can never enter any canonical analytical structure, API payload, export, log, or screenshot: customer first name, last name, street, email, password; customer latitude/longitude or other precise coordinates; destination postal codes used as precise locators (missing values never imputed); IP addresses / access-log fields; redundant raw copies of any of the above. Profiling counts excluded columns without displaying values. The export privacy gate (`DQ-PRIVACY-003`) fails closed on any banned header.
