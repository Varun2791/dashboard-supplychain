# V1 Export Contract

Binding: ADR-003 (provenance labels), ADR-005 (PII exclusion), ADR-010 (no currency), ADR-024 (generated files stay out of Git).

## 1. Approved exports (only these four)

Raw data is never exportable. Every export derives from canonical structures or audit logs.

| Kind (`POST /exports` value) | Content | Source |
|---|---|---|
| `cleaned_items` (CSV) | sanitized cleaned order-item rows | `order_items` allowlist (§2) |
| `orders` (CSV) | one row per order with aggregated totals | `orders` allowlist (§2) |
| `quality_report` (JSON + optional CSV summary) | profile + issues by rule/severity/treatment + schema coverage | profiling + `data_quality_issues` |
| `cleaning_report` (JSON + optional CSV) | step log with rule/field/counts/reason/outcome + totals reconciliation + versions | cleaning audit log + manifest |

## 2. Field allowlists (privacy gate input)

`cleaned_items` columns: `session_id?, source_row_number, order_item_id, order_id, customer_id, product_id, category_id, quantity_units, unit_price, gross_sales, discount_amount, net_sales, profit_amount, order_status, shipping_mode, customer_segment, order_timestamp, ship_timestamp, actual_shipping_days, scheduled_shipping_days, shipment_outcome, is_late, schedule_variance_days, order_date, destination_country, destination_region, destination_market, department_name, category_name, product_name`.

`orders` columns: `order_id, customer_id, order_timestamp, order_status, shipping_mode, customer_segment, destination_country, destination_region, destination_market, scheduled_shipping_days, actual_shipping_days, shipment_outcome, is_late, line_count, total_units, gross_value, discount_total, net_value, profit_total`.

Reports carry counts, rule IDs, and metadata — never row contents or personal values.

## 3. Privacy exclusions (fail closed)

Banned from every export: customer first/last name, street, email, password; customer latitude/longitude or precise coordinates; destination postal codes as precise locators; IP addresses / access-log fields; redundant raw copies of any banned column; unmapped unknown columns. `DQ-PRIVACY-003` checks candidate headers against this list before writing bytes: any hit blocks the export (`422 EXPORT_BLOCKED`) and logs the event with counts only. Verified by an allowlist unit test per export kind.

## 4. Provenance / version metadata

Every export embeds (JSON) or sidecars (CSV → same basename `.meta.json`):

```
{ appVersion, schemaVersion, sessionId, sourceFilenameSafe, sourceSha256,
  sourceBytes, generatedAt, filtersApplied, exportKind,
  dataProvenance: "cleaned" | "canonical" | "report",
  currencyNote: "currency unspecified — numeric units only",
  syntheticDataNote: "demo dataset; findings describe the file, not a real company" }
```

## 5. Filenames

`{safeBasename}_{kind}_app{appVersion}_schema{schemaVersion}_{YYYYMMDDTHHMMSS}.csv|json` (+ `.meta.json` for CSVs). `safeBasename`: alphanumerics, `-`, `_` only, truncated to 40 chars, derived from — never equal to — the user-supplied path. Response includes `sha256` and `bytes` of the artifact.

## 6. CSV / JSON behavior

- CSV: UTF-8 with BOM (Excel compatibility), LF endings, RFC 4180 quoting, header row always, stable column order per §2.
- JSON: UTF-8, ISO-8601 naive datetimes, money as 2-dp strings, nulls as `null`.
- Exports reopen correctly in Excel/Sheets/LibreOffice without executing cell contents (see §7). Filtered exports reconcile row counts and totals with the on-screen filtered view.

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

Exported counts and totals reconcile with the active session and stated filters; the `.meta.json` provenance lets a second user with the public reference dataset regenerate and compare SHA-equivalent content (byte equality modulo timestamp/metadata fields, which are documented as volatile).
