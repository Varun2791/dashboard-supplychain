# V1 Export Contract

Binding: ADR-003 (provenance labels), ADR-005 (PII exclusion), ADR-010 (no currency), ADR-024 (generated files stay out of Git), ADR-040 (serving/filtering/provenance semantics; additive to ADR-033/ADR-038).

## 1. Approved exports (only these four)

Raw data is never exportable. Every export derives from canonical structures or audit logs.

| Kind (`POST /exports` value) | Content | Source |
|---|---|---|
| `cleaned_items` (CSV) | sanitized cleaned order-item rows | `order_items` allowlist (§2) |
| `orders` (CSV) | one row per order with aggregated totals | `orders` allowlist (§2) |
| `quality_report` (JSON in V1; CSV summary deferred) | profile + issues by rule/severity/treatment + schema coverage | profiling + `data_quality_issues` |
| `cleaning_report` (JSON in V1; CSV deferred) | step log with rule/field/counts/reason/outcome + totals reconciliation + versions | cleaning audit log + manifest |

No format selector exists in V1. The "optional CSV" wording in earlier
revisions is a deferred option, not a V1 requirement. No fifth export
kind exists: the CSV `.meta.json` sidecar (§4) is part of its logical
export, not a kind.

## 1a. Filter applicability by kind (ADR-040)

| Kind | Filters |
|---|---|
| `cleaned_items` | APPLIED — only the §1b vocabulary |
| `orders` | APPLIED — only the §1b vocabulary |
| `quality_report` | REJECTED — whole-session audit artifact |
| `cleaning_report` | REJECTED — whole-session audit artifact |

A report request containing any non-empty filter fails validation
(`422 INVALID_FILTER_VALUE`: filters not applicable to report
exports). Filters are never silently ignored, accepted-and-recorded,
or applied to report content.

## 1b. Data-export filter vocabulary (V1)

The public Phase-16 filter set is exactly the Phase-15 shared set:
`from`, `to`, `market`, `region`, `category`, `shipping_mode`,
`order_status`, `shipment_outcome`. `department` and
`customer_segment` are NOT public export filters in V1 even though
`KpiFilters` internally supports them, so the export surface never
exceeds the user-visible analytics filter state. Value semantics reuse
Phase 15: `from`/`to` on `order_timestamp`; canonical destination
market/region; existing accepted `shipping_mode` / `order_status` /
`shipment_outcome` vocabularies (no coercion, fuzzy matching, or
shipping-mapping expansion). Unknown keys/values fail validation.

Category is grain-specific: `cleaned_items` includes a line when that
item's canonical `category_name` matches; `orders` matches by direct
equality on the canonical order-level category field, so
multi-merchandise orders with null order-level category are excluded.
No membership semantics; no cross-grain repair (ADR-038 preserved).

## 1c. Reconciliation by artifact (E1 reading)

PLAN Phase-16 "Exported counts and totals reconcile with the active
dataset and filters" means per artifact: `cleaned_items` reconciles to
the governed filtered item population; `orders` reconciles to the
governed filtered order population; `quality_report` reconciles to
whole-session DQ evidence (analytics filters N/A); `cleaning_report`
reconciles to whole-session cleaning evidence (analytics filters N/A).
Under merchandise/category filters the two data exports are governed
at different grains, so their commercial totals are NOT required to be
equal when multi-merchandise orders exist — the Phase-16 analogue of
the accepted Phase-15 qualification. Each reconciles to its own
population.

## 2. Field allowlists (privacy gate input)

`cleaned_items` columns: `session_id?, source_row_number, order_item_id, order_id, customer_id, product_id, category_id, quantity_units, unit_price, gross_sales, discount_amount, net_sales, profit_amount, order_status, shipping_mode, customer_segment, order_timestamp, ship_timestamp, actual_shipping_days, scheduled_shipping_days, shipment_outcome, is_late, schedule_variance_days, order_date, destination_country, destination_region, destination_market, department_name, category_name, product_name`.

`orders` columns: `order_id, customer_id, order_timestamp, order_status, shipping_mode, customer_segment, destination_country, destination_region, destination_market, scheduled_shipping_days, actual_shipping_days, shipment_outcome, is_late, line_count, total_units, gross_value, discount_total, net_value, profit_total`.

Reports carry counts, rule IDs, and metadata — never row contents or personal values.

## 3. Privacy exclusions (fail closed)

Banned from every export: customer first/last name, street, email, password; customer latitude/longitude or precise coordinates; destination postal codes as precise locators; IP addresses / access-log fields; redundant raw copies of any banned column; unmapped unknown columns. `DQ-PRIVACY-003` checks candidate headers against this list before writing bytes: any hit blocks the export (`422 EXPORT_BLOCKED`) and logs the event with counts only. Verified by an allowlist unit test per export kind.

## 4. Provenance / version metadata

Every export embeds (JSON reports, in the primary artifact) or
sidecars (CSV → same basename `.meta.json`, one logical export with
two persisted files):

```
{ appVersion, schemaVersion, sessionId, sourceFilenameSafe, sourceSha256,
  sourceBytes, generatedAt, filtersApplied, exportKind,
  dataProvenance: "cleaned" | "canonical" | "report",
  currencyNote: "currency unspecified — numeric units only",
  syntheticDataNote: "demo dataset; findings describe the file, not a real company" }
```

`filtersApplied` is truthful (ADR-040): it contains ONLY filters that
actually narrowed artifact content — the normalized active filters for
`cleaned_items`/`orders`, and an empty object `{}` for the
filter-independent reports. Rejected/requested filters are never
recorded as applied; there is no `requestedFilters` in V1. The sidecar
carries no raw rows, PII, filesystem paths, secrets, or raw manifest
internals.

## 4a. Sidecar access and identity

The sidecar is retrievable via `GET
/sessions/{id}/exports/{exportId}/metadata` (same `exportId`, no
second ID, no bundle/ZIP, no CSV comment metadata). JSON reports have
no sidecar, so that endpoint uses export-not-found semantics for them.
POST identity: top-level `filename`/`bytes`/`sha256` always refer to
the PRIMARY artifact; `metadata: { filename, bytes, sha256 }` refers
only to the sidecar (CSV kinds), or `metadata: null` for JSON reports
(stable response shape). All hashes/sizes are computed from persisted
bytes; there is no combined/bundle hash. A CSV export is successfully
created only when BOTH files are fully generated, hashed, and
atomically published — POST `201` never returns for a half-valid
record, and failure leaves no downloadable record. GET endpoints serve
persisted bytes; content is never regenerated during GET.

## 5. Filenames

`{safeBasename}_{kind}_app{appVersion}_schema{schemaVersion}_{YYYYMMDDTHHMMSS}.csv|json` (+ `.meta.json` for CSVs). `safeBasename`: alphanumerics, `-`, `_` only, truncated to 40 chars, derived from — never equal to — the user-supplied path. Response includes `sha256` and `bytes` of the primary artifact plus the sidecar `metadata` object (or `metadata: null` for JSON reports) per §4a.

## 6. CSV / JSON behavior

- CSV: UTF-8 with BOM (Excel compatibility), LF endings, RFC 4180 quoting, header row always, stable column order per §2.
- JSON: UTF-8, ISO-8601 naive datetimes, money as 2-dp strings, nulls as `null`.
- Exports reopen correctly in Excel/Sheets/LibreOffice without executing cell contents (see §7). Filtered data exports reconcile row counts and totals with the same governed filtered populations as the on-screen analytics views; reports are whole-session and filter-independent (§1a/§1c).

## 7. Spreadsheet-injection protection (string cells only)

Rule: protection applies **only to string/text cells** whose trimmed content begins with `=`, `+`, `-`, or `@` (or contains a `DDE`-style pipe pattern). Such cells are prefixed with a single quote `'` and quoted per RFC 4180, so spreadsheet software treats them as text.

**Typed numeric and date values are never quote-prefixed.** A legitimate negative number (e.g., `-12.50` profit, `-2` variance) serializes as a plain typed value and must remain directly computable in a spreadsheet. Type information is decided by the canonical schema (`decimal`/`int`/`date`), not by inspecting cell text: numbers stay numbers, strings that look formulaic get protected.

Tests must cover both sides: (a) string cells like `=SUM(A1:A2)`, `+cmd`, `-evil`, `@x` are neutralized; (b) typed negatives (`profit_amount = -45.77`, `schedule_variance_days = -3`) serialize unquoted and parse back to equal values.

## 8. Numeric / date / null formatting

- Money: fixed 2 dp (`0.00`), no currency symbol, no thousands separator.
- Rates in CSV detail: decimal fraction to 4 dp plus a `pct_display_1dp` column where the UI shows it; JSON mirrors the API KPI shape.
- Dates: naive ISO-8601 (`YYYY-MM-DDTHH:MM:SS`); date-only fields `YYYY-MM-DD`.
- Nulls: empty CSV field / JSON `null`. Never `0`, `N/A`, `-`, or invented text. `is_late` empty for cancelled shipments.
- Counts: plain integers, no separators.

## 9. Reproducibility

Same session (same source, canonical artifacts, normalized filters,
app/schema versions): primary data content is deterministically
reproducible; volatile metadata may differ where this contract permits
it. Cross session (same source SHA, processing/code/schema versions,
normalized filters): primary data content is
semantically/content-equivalent; metadata need not be byte-identical
because `sessionId`, `generatedAt`, filename timestamps, and safe
source-name provenance may differ. No byte-identical complete-package
promise is made across sessions. The `.meta.json` provenance lets a
second user with the public reference dataset regenerate and compare
content-equivalent primary artifacts (byte equality modulo
timestamp/metadata fields, which are documented as volatile).
