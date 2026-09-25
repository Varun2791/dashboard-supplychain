# V1 Data-Quality Rule Catalogue

Binding: ADR-003 (auditable), ADR-008 (tolerance), ADR-015 (days authoritative), ADR-017 (retain negatives), ADR-005/ADR-016 (privacy/geo).

## 1. Four separate concepts

| Concept | What it is | Example | Logged as |
|---|---|---|---|
| **Detection** (profiling) | read-only observation of the raw file | “1,240 lines have unparseable order timestamps” | `data_quality_issues` row: rule, severity, count, blocked stage |
| **Cleaning transformation** | approved reversible normalization of a carried value | trim label whitespace; cast ID to string; exact enum map | `fixed` count with reason |
| **Canonical derivation** | new field computed by a recorded formula | `shipment_outcome` from day fields; `is_late = null` for cancelled; variances; calendar fields | derivation record — never a “fix” |
| **Validation result** | check outcome that may gate a stage | gross−discount≈net tolerance; invariance; `Late_delivery_risk` agreement | severity + blocked stage; changes no data |

`is_late = null` for shipping-cancelled orders is a canonical derivation (the cancelled population is outside the adherence question), not a repaired quality issue. `Late_delivery_risk` agreement is a validation result only.

## 2. Severity and blocking model

- `ERROR` names the exact downstream stage it blocks (e.g., blocks CANONICALIZING). The gated stage stays gated until the input is fixed or replaced.
- There is **no acknowledgement/waiver flow** in V1: no “accept ERROR and continue anyway.” `ERROR` never implies an override workflow.
- `WARNING` / `INFO` never block any stage but remain visible in the UI and reports.
- Detection and treatment are separate columns: a rule detects; the pipeline then records `detected / fixed / flagged / excluded / unchanged` per AGENTS.md.
- Only rules marked “auto-transform: yes” may change carried values, and only via the documented reversible ops (trim, string cast, exact enum map, privacy exclusion, null-adherence derivation at canonicalization).

Pipeline stages referenced: `INGESTION · SCHEMA_MAPPING · PROFILING · CLEANING · CANONICALIZATION · KPI_ANALYSIS · EXPORT`.

## 3. Rule catalogue

### DQ-FILE — file integrity (block INGESTION)

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-FILE-001 | Valid CSV upload | extension ≠ `.csv` or MIME/parse evidence contradicts CSV | ERROR | INGESTION | excluded (reject; no session data kept beyond error metadata) | no |
| DQ-FILE-002 | Non-empty file | 0 bytes or header-only | ERROR | INGESTION | excluded | no |
| DQ-FILE-003 | Size within budget | bytes > 250 MB | ERROR | INGESTION | excluded | no |
| DQ-FILE-004 | Supported encoding | undecodable as UTF-8-SIG and Latin-1 | ERROR | INGESTION | excluded with guidance | no |
| DQ-FILE-005 | Intact CSV body | mid-file quoting/truncation parse error | ERROR | INGESTION (and any partial PROFILING discarded) | excluded; partial derived removed | no |

### DQ-SCHEMA — schema recognition (block SCHEMA_MAPPING / CANONICALIZATION)

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-SCHEMA-001 | Required columns present | any critical DataCo header missing (IDs, dates, amounts, quantities, delivery fields) | ERROR | CANONICALIZING and KPI_ANALYSIS | flagged; precise missing-column guidance | no |
| DQ-SCHEMA-002 | No duplicate headers | duplicate normalized header names | ERROR | SCHEMA_MAPPING | excluded (reject file) | no |
| DQ-SCHEMA-003 | Unknown columns quarantined | unmapped columns present | INFO | none | excluded from canonical; retained in raw only | no (exclusion is not a mutation) |
| DQ-SCHEMA-004 | Redundant-copy agreement | redundant copies (e.g., second product-ID column) disagree | WARNING | none | flagged | no |

### DQ-KEY — keys and grain (block CANONICALIZATION where stated)

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-KEY-001 | Item-ID uniqueness | duplicate `Order Item Id` | ERROR | CANONICALIZATION (`order_items` build; nothing deduplicated) | flagged | no |
| DQ-KEY-002 | Order-ID repetition is legitimate | `distinct(Order Id) < rows` | INFO | none | unchanged (informational; confirms item grain) | no |
| DQ-KEY-003 | Order+Product is not a key | duplicate (`Order Id`, `Product Id`) pairs exist | INFO | none | unchanged (refutes bad dedup) | no |

### DQ-DATE — dates (block per row-population, not whole file unless critical)

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-DATE-001 | Order timestamp parseable | month-first parse of `order date (DateOrders)` fails | ERROR | KPI_ANALYSIS for affected rows (rows excluded from date-binned KPIs; file-wide failure — the upload contains data rows but zero parseable governed order timestamps — blocks CANONICALIZATION) | flagged | no |
| DQ-DATE-002 | Ship timestamp parseable | month-first parse of `shipping date (DateOrders)` fails | WARNING | none (evidence field only) | flagged | no |
| DQ-DATE-003 | Ship ≥ order evidence | `ship_timestamp < order_timestamp` | WARNING | none (KPI uses day fields regardless) | flagged | no |
| DQ-DATE-004 | Same-Day pattern noted | Same-Day rows with ~12 h timestamp gaps | INFO | none | unchanged | no |

### DQ-NUM — numeric and formula checks

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-NUM-001 | Non-negative quantities/prices | `quantity_units < 0` or `unit_price < 0` | WARNING | none | flagged | no |
| DQ-NUM-002 | Net-tolerance agreement | `\|gross − discount − net\| > $0.05`/line (documented tolerance; ADR-008) | WARNING | none (net stays authoritative) | flagged | no |
| DQ-NUM-003 | Extreme negative profit retained | profit ratio < −1.0 (threshold documented) | WARNING | none (ADR-017: retained, never clipped/deleted) | flagged | no |
| DQ-NUM-004 | Zero-denominator guard | Σnet=0, Σgross=0, or eligible=0 in a requested slice | INFO | none (KPI returns unavailable) | unchanged | no |

### DQ-CAT — categorical / enum mapping

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-CAT-001 | Known order status | value outside mapped `order_status` set | WARNING | none (row excluded from status-split KPIs, counted as unknown) | flagged | no |
| DQ-CAT-002 | Known shipping mode | value outside 4 mapped modes | WARNING | none | flagged | no |
| DQ-CAT-003 | Known customer segment | value outside 3 mapped segments | WARNING | none | flagged | no |
| DQ-CAT-004 | Known delivery status | value outside mapped delivery set | WARNING | none (unrecognized cancel signal → row treated as eligible only if day fields support it, flagged) | flagged | no |
| DQ-CAT-005 | Label whitespace normalization | leading/trailing whitespace in label fields | INFO | none | fixed (trim; count logged) | **yes** |

### DQ-GRAIN — cross-row consistency (block CANONICALIZATION)

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-GRAIN-001 | Order-invariance holds | same `order_id` disagrees on status/mode/dates/days/customer/destination | ERROR | CANONICALIZATION (`orders` build; no first-row pick) | flagged | no |
| DQ-GRAIN-002 | Totals reconcile | Σ(items)→orders vs Σ(items)→dataset differ beyond $0.01×lines tolerance | ERROR | KPI_ANALYSIS (totals must reconcile first) | flagged | no |
| DQ-GRAIN-003 | Product-invariance holds | same `product_id` disagrees on `category_id`/`department_name`/`category_name`/`product_name` (≥2 distinct non-missing stripped values; missing vs one value is not a conflict; `unit_price` never invariant) | ERROR | CANONICALIZATION (`products` build; no representative value) | flagged | no |
| DQ-GRAIN-004 | Customer-invariance holds | same `customer_id` disagrees on `customer_segment` (≥2 distinct non-missing stripped values; missing vs one value is not a conflict) | ERROR | CANONICALIZATION (`customers_sanitized` build; no representative segment) | flagged | no |

### DQ-BUSINESS — business-rule validation (results, not repairs)

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-BUSINESS-001 | Cancelled adherence is null (derivation check) | SHIPPING_CANCELED row with `is_late ≠ null` after canonicalization | ERROR | KPI_ANALYSIS (builder self-check) | corrected by re-running derivation | derivation, not a fix |
| DQ-BUSINESS-002 | Shipping days plausible | `actual < 0` or `scheduled ≤ 0` | WARNING | none | flagged | no |
| DQ-BUSINESS-003 | Late-risk agreement (audit only) | `Late_delivery_risk` disagrees with day-field outcome | WARNING | none (`Late_delivery_risk` never classifies) | flagged | no |
| DQ-BUSINESS-004 | Fraud/cancel separation held | any combined metric shown without separate counts | INFO | none (design gate for review) | flagged in review | no |

### DQ-PRIVACY — privacy enforcement (block EXPORT where stated)

| Rule | Name | Detection logic | Severity | Blocks | Treatment | Auto-transform |
|---|---|---|---|---|---|---|
| DQ-PRIVACY-001 | Direct personal fields excluded | first/last/street/email/password columns present in source | INFO | none (excluded by construction) | excluded from canonical/API/exports/logs | **yes (exclusion)** |
| DQ-PRIVACY-002 | Precise geo excluded | customer lat/long, street/ZIP-precise, or IP-like columns present | INFO | none | excluded; missing destination ZIP never imputed | **yes (exclusion)** |
| DQ-PRIVACY-003 | Export privacy gate | export candidate header intersects the banned list | ERROR | EXPORT (fails closed) | excluded + export blocked | no |

## 4. Audit-log shape

Per rule and field: `{ ruleId, field, detected, fixed, flagged, excluded, unchanged, reason }` plus session totals reconciliation (gross/discount/net/profit pre/post cleaning — cleaning must not move totals; any delta is itself a `DQ-GRAIN-002` finding). Re-running the same input reproduces the same log.
