# V1 KPI Contracts

Authority: the backend KPI engine is the sole owner of every definition here. Frontend components render the approved display label from the API payload and perform no calculation. Contract tests assert each canonical KPI ID and its approved display label; unauthorized label changes fail tests. (Docs may legitimately contrast approved terms with prohibited ones, so no global word-ban lint exists.)

Global rules:

- **Date basis:** `order_timestamp` for every KPI unless the row says otherwise.
- **Terminology:** `recorded net order value` (never recognized revenue); `on-schedule shipment rate` (never customer on-time delivery); `net order value associated with late shipments` (association, never causation / lost sales). Strict cancellations and suspected fraud stay separate (ADR-013).
- **Classification input:** shipment outcomes come only from the §6 derivation in `docs/canonical-schema.md` (day-field comparison; `Late_delivery_risk` is audit evidence only).
- **Filters** narrow the eligible population and are echoed in responses; they never change a formula, grain, or label. Unknown enum filter values are rejected (`422`), never silently mapped.
- **Unavailable, not zero:** empty eligible population, zero denominator, or fully-missing required fields → `{ value: null, status: "unavailable", reason }`. Never `0`/`0%`.
- **Missing data:** a row missing a KPI’s required field is excluded from that KPI and counted in `missingDataCount`.
- **Formatting:** counts integers; money 2 dp neutral units (no currency symbol, ADR-010); rates 1 decimal in UI, 4 decimals in tests/exports. Margin and discount rates are amount-weighted (ADR-014).
- **Reference expectations** are regression controls for the unmodified DataCo file (ADR-020), not production constants.

## Volume / entity counts

| KPI ID | Approved display label | Meaning · grain | Formula (N / D) | Eligible population · exclusions | Required fields | Zero/missing | Reference |
|---|---|---|---|---|---|---|---|
| `kpi.items.count` | Order-item lines | lines in scope · item | count(items) | all canonical items; none | `order_item_id` | — | 180,519 |
| `kpi.orders.count` | Orders | distinct orders · order | count(distinct `order_id`) | all canonical orders | `order_id` | null if 0 orders | 65,752 |
| `kpi.orders.shipment_eligible_count` | Shipment-eligible orders | orders usable for adherence · order | count(outcome ≠ SHIPPING_CANCELED) | eligible only; cancelled excluded, `is_late=null` | `shipment_outcome` | unavailable if 0 | 62,897 |
| `kpi.customers.count` | Customers | distinct sanitized customers | count(distinct `customer_id`) | all | `customer_id` | — | 20,652 |
| `kpi.products.count` | Products | distinct products | count(distinct `product_id`) | all | `product_id` | — | 118 |
| `kpi.units.total` | Units | total units · item summed | sum(`quantity_units`) | all items | `quantity_units` | — | 384,079 |

## Commercial value

Status scope defaults to all-status with the scope labeled on every card (ADR-009).

| KPI ID | Approved display label | Meaning · grain | Formula | Population · exclusions | Required | Zero/missing | Reference |
|---|---|---|---|---|---|---|---|
| `kpi.value.gross` | Gross order value | pre-discount recorded value | sum(`gross_sales`) | all-status | `gross_sales` | — | 36,784,735.01 |
| `kpi.value.discount` | Discounts | recorded discounts | sum(`discount_amount`) | all-status | `discount_amount` | — | 3,730,378.40 |
| `kpi.value.net` | Recorded net order value | authoritative commercial total | sum(`net_sales`) | all-status | `net_sales` | — | 33,054,402.38 |
| `kpi.profit.recorded` | Recorded profit | includes negatives (ADR-017) | sum(`profit_amount`) | all-status | `profit_amount` | — | 3,966,902.97 |
| `kpi.margin.profit` | Profit margin | amount-weighted | sum(profit)/sum(net) | rows with both non-null; denom>0 | both | unavailable if Σnet=0 | ~12.0% (recompute) |
| `kpi.rate.discount` | Discount rate | amount-weighted | sum(discount)/sum(gross) | denom>0 | both | unavailable if Σgross=0 | ~10.14% (recompute) |
| `kpi.value.aov` | Average net per order | order-grain mean | sum(`net_value`)/count(orders) | orders in scope | `net_value` | unavailable if 0 orders | ~502.71 (recompute) |
| `kpi.units.per_order` | Units per order | mean units | sum(units)/count(orders) | orders in scope | — | unavailable if 0 | ~5.84 (recompute) |
| `kpi.lines.per_order` | Lines per order | mean lines | count(items)/count(orders) | orders in scope | — | unavailable if 0 | ~2.75 (recompute) |
| `kpi.orders.loss_making_rate` | Loss-making-order rate | share of orders with `profit_total<0` · order | count(loss)/count(orders) | all-status | `profit_total` | unavailable if 0 | 13,909 orders (rate recompute) |
| `kpi.value.net_associated_with_late` | Net order value associated with late shipments | association only · order | sum(`net_value` where `is_late=true`); plus share of in-scope net | eligible late orders; commercial scope labeled | `net_value`, `is_late` | unavailable if eligible=0 | computed, never “lost” |

## Shipment performance (eligible population only, ADR-012)

Eligible = distinct orders with `shipment_outcome ≠ SHIPPING_CANCELED`. Cancelled orders carry `is_late = null` (derivation) and never count as non-late.

| KPI ID | Approved display label | Formula (N / D) | Required | Zero/missing | Reference |
|---|---|---|---|---|---|
| `kpi.ship.late_rate` | Late-shipment rate | 36,048 / 62,897 | `is_late`, day fields | unavailable if eligible=0 | 57.3127% |
| `kpi.ship.on_schedule_rate` | On-schedule shipment rate | (15,127+11,722) / 62,897 | same | unavailable if 0 | 42.6873% |
| `kpi.ship.early_rate` | Early-shipment rate | 15,127 / 62,897 | same | unavailable if 0 | ~24.0526% (recompute) |
| `kpi.ship.exact_rate` | Exactly on-schedule rate | 11,722 / 62,897 | same | unavailable if 0 | ~18.6347% (recompute) |
| `kpi.ship.late_count` / `early_count` / `exact_count` | Late / early / exactly on-schedule orders | counts within eligible | same | — | 36,048 / 15,127 / 11,722 |
| `kpi.ship.avg_actual_days` | Average actual shipping days | sum(`actual_shipping_days`)/eligible non-null actual | `actual_shipping_days` | unavailable if 0 | computed |
| `kpi.ship.avg_scheduled_days` | Average scheduled shipping days | sum(`scheduled_shipping_days`)/eligible | `scheduled_shipping_days` | unavailable if 0 | computed |
| `kpi.ship.variance_days` | Average schedule variance (days) | sum(`schedule_variance_days`)/eligible with both | both | unavailable if 0 | computed; negative = ahead |

## Cancellation / fraud (separate, ADR-013)

| KPI ID | Approved display label | Formula | Required | Reference |
|---|---|---|---|---|
| `kpi.orders.strict_cancel_rate` | Strict cancellation rate | 1,367 / 65,752 (`order_status=CANCELED`) | `order_status` | ~2.079% (recompute) |
| `kpi.orders.fraud_rate` | Suspected-fraud rate | 1,488 / 65,752 (`SUSPECTED_FRAUD`) | `order_status` | ~2.263% (recompute) |
| `kpi.orders.blocked_rate` | Shipping-blocked rate | 2,855 / 65,752 (combined, only when labeled exactly so) | `order_status` | ~4.342% (recompute) |

## Dimensional breakdowns (no contract change)

`by` ∈ `shipping_mode | order_status | shipment_outcome | customer_segment | destination_market | destination_region | destination_country | department_name | category_name | product_name | order_month`. Grouping re-slices numerator/denominator under identical formulas; per-group unavailable rules apply independently. Trend series use `order_date` buckets. Drilldown rows are sanitized orders with the same population semantics as the headline.
