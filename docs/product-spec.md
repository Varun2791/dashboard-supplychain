# V1 Product Specification

Binding sources: `AGENTS.md` (scope, data, privacy, UX rules), `DECISIONS.md` ADR-001–ADR-024 and Phase 2 ADRs (ADR-025+), `PLAN.md` Phase 2.
`docs/` contracts are the implementable detail of those decisions. Where this spec and an Accepted ADR disagree, the ADR wins and this spec must be fixed.

## 1. V1 product contract

V1 is a local-first web application that turns one DataCo-compatible supply-chain CSV per session into a profile, a validation/data-quality report, an auditable canonical dataset, correctly-grained KPIs, and an interactive dashboard.

Exact capabilities:

1. Local CSV upload (drag/drop + file picker), one file per session.
2. DataCo source-shape recognition through an explicit source-to-canonical mapping (ADR-001). No generic column mapping.
3. Immutable raw preservation per session with a server-generated UUIDv4 session identifier (ADR-003, ADR-030).
4. Read-only dataset profiling and schema validation before any cleaning.
5. Auditable cleaning limited to documented reversible normalizations; all other observations are flagged, never silently repaired (ADR-003).
6. Canonical model construction: `orders`, `order_items`, `products`, `customers_sanitized`, `calendar`, `data_quality_issues`, plus processing-audit metadata (ADR-002, ADR-007).
7. Backend-owned KPI engine at declared grain; the frontend renders typed API contracts and performs no KPI math (ADR-023).
8. Six views: Upload, Data Quality, Overview, Delivery, Commercial, Diagnostics.
9. Shared filters, KPI-definition/population/exclusion disclosure, empty/loading/error states, explicit reset.
10. Sanitized exports only: cleaned order-items CSV, canonical orders CSV, data-quality report, cleaning/audit report, with version/provenance metadata.
11. Automated tests (unit, contract, integration, golden reference, adversarial fixtures, frontend behavior) and portfolio documentation.

## 2. Non-goals (V1 will not do these)

- Arbitrary user-defined column mapping or saved mappings (V2 backlog).
- Authentication, multi-user accounts, cloud persistence, deployment.
- Any external transmission of uploaded data: no AI analysis, telemetry, analytics, geocoding, storage, or enrichment (ADR-004).
- Forecasting, ML, late-shipment prediction (ADR-018).
- Supplier, procurement, inventory, warehouse, freight-cost, returns, emissions, OTIF/fill-rate/stockout/turnover/supplier/procurement/warehouse/freight/return/perfect-order/customer-lead-time/forecast-accuracy/CLV/causal-loss analytics (ADR-019).
- Power BI or external BI export; mobile-native apps; access-log ingestion (ADR-006).
- A database added for future possibilities; recognized-revenue accounting; customer on-time-delivery claims (ADR-009, ADR-011).

## 3. Complete user journey

1. **Launch.** User starts the app with one documented command. The Upload view is the entry point with no data loaded. It states: local-only processing, DataCo-compatible CSV expected, 250 MB hard upload cap, reference file is ~95.9 MB / 180,519 rows, and a privacy notice (no data leaves the machine).
2. **Upload.** User drops or selects a `.csv` file. The server runs synchronous upload/header guards (extension, size, emptiness, header parse, encoding) and returns promptly with `202 Accepted` plus a status URL (see `docs/api-contract.md`). A UUIDv4 session ID is issued. The raw file is stored once, made read-only, and hashed (SHA-256).
3. **Processing states.** Profiling, cleaning, canonicalization, and KPI analysis proceed as explicit session states (`UPLOADING → VALIDATING → PROFILING → CLEANING → CANONICALIZING → ANALYZING → READY`, with `FAILED` / `EXPIRED` terminals). The UI polls the status endpoint and shows stage progress. Stage-specific errors are actionable; unexpected errors are never hidden behind empty results or zero KPIs.
4. **Validation.** The schema report classifies every source column as required / optional / redundant / excluded / unknown, shows the exact DataCo→canonical mapping, and names any missing critical field that blocks canonicalization/analytics. Unknown enum values are flagged, never silently mapped.
5. **Profiling / data quality.** A pre-cleaning profile runs without mutation: dimensions, grain confirmation (“N lines ≠ M orders”), missingness, cardinality, exact vs key duplicates, order-invariance conflicts, numeric/enum/date/geography/formula checks. Every issue carries a stable `DQ-*` rule ID, severity, affected count, the exact downstream stage it blocks (if any), and its treatment. There is no “acknowledge ERROR and continue” override: ERROR-gated stages stay gated.
6. **Cleaning review.** The cleaning report shows, per rule and field, detected / fixed / flagged / excluded / unchanged counts with reasons. Re-running the same input reproduces the same output and log. Negative-profit rows, cancelled orders, suspected-fraud orders, and repeated order/product lines are retained.
7. **Dashboard exploration.** The user moves between Overview, Delivery, Commercial, and Diagnostics. Shared filters (date, market, region, category, shipping mode, status, outcome) narrow populations without redefining KPIs. Every KPI card shows its approved label, eligible population, exclusions, and status scope. Data-quality warnings persist on every view; they are never converted into success decoration.
8. **Diagnostics and drilldown.** From a poor KPI the user inspects associated dimensional combinations and paginated order-level rows. Language is associational (“associated with”), never causal. No personal fields appear anywhere.
9. **Export.** The user builds approved exports from the active session (optionally filtered). Exports carry provenance/version metadata and pass the privacy header-allowlist gate. Raw data is never exportable.
10. **Reset and session end.** Explicit Reset deletes the whole session tree idempotently and returns the UI to its empty state. Sessions expire after a documented TTL and on-disk pressure policy; restart sweeps abandoned sessions. Terminal ingestion/processing failures remove partial derived files and the unusable raw upload, retaining only privacy-safe manifest/error metadata for diagnostics.

## 4. Screens / routes

All routes consume the typed backend contracts in `docs/api-contract.md`. No route computes KPIs locally.

| Route | Screen | Business question answered | Required data contract |
|---|---|---|---|
| `/upload` | Upload + session status | “Can my file be safely processed locally, and if not, exactly why?” | upload accept, session status, schema report summary |
| `/data-quality` | Source profile, schema coverage, issues by severity/treatment, cleaning-log preview, excluded-field explanation | “What is risky in this file, what changed, and what remains flagged?” | profile, data-quality issues, cleaning report |
| `/overview` | Headline KPI cards, net-value/profit trend on order date, shipment-outcome distribution, market/region performance | “What happened across commercial value and shipment performance?” | overview KPIs + trend/breakdown series |
| `/delivery` | Late/on-schedule by mode, actual vs scheduled days and variance, region/market/category/time splits, eligible-population note | “Where and under which shipping conditions do schedule failures occur?” | delivery KPIs + groupings + eligible counts |
| `/commercial` | Net value, profit, margin, discount, units; department/category/product/market/region/segment splits; loss-making analysis | “Which products and geographies are associated with value, profit, discount, and loss?” | commercial KPIs + groupings + status scope |
| `/diagnostics` | Shared filters, multi-dimensional ranking, order-level drilldown, empty/zero-eligible handling | “Which combinations and orders are associated with a poor KPI?” | filtered KPIs + paginated sanitized orders |

## 5. Application / session states

Session lifecycle (authoritative detail in `docs/api-contract.md` and `docs/architecture.md`):

- `UPLOADING` — bytes being received/stored; header guards not yet passed.
- `VALIDATING` — extension/size/encoding/header/duplicate-header checks and schema mapping.
- `PROFILING` — read-only detection pass; no mutation.
- `CLEANING` — approved reversible normalizations only, with audit log.
- `CANONICALIZING` — canonical tables built; order-invariance enforced; derivations applied.
- `ANALYZING` — KPI engine run; totals reconciled.
- `READY` — dashboard and export endpoints serve results.
- `FAILED` — terminal; only privacy-safe manifest/error metadata retained when the session cannot validly continue.
- `EXPIRED` — terminal; session tree removed.

UI states per view: empty (no session), loading (session not READY, stage shown), error (stage + code + guidance), empty-result (filters exclude everything), zero-eligible (KPI unavailable with reason, never 0%), ready.

## 6. UX behavior

- Views are organized around the business questions above, not chart types.
- Active filters, KPI definitions, populations, exclusions, and status scope are visible where the KPI is shown.
- Counts render as whole numbers; rates render with one decimal in the UI; money renders with consistent 2 dp neutral-unit formatting and no currency symbol (ADR-010).
- Charts have accessible labels, keyboard-reachable controls, readable contrast, and non-color-only distinctions (patterns/labels as well as color).
- Tables declare units, support sorting, show empty states, and paginate (cursor-based order drilldown).
- Data-quality warnings remain visible; before/after counts never imply all issues were fixed.
- A synthetic-data/methodology disclosure appears on Overview and in portfolio docs (ADR-021): findings describe the demo dataset, not a real company.
- Filters persist across Overview/Delivery/Commercial/Diagnostics; filter reset is explicit and one click.
- No dashboard component may use a KPI label other than the approved display label in `docs/kpi-contracts.md`; labels render from the backend contract. Contract tests catch unauthorized label changes (no global word-ban lint: docs may legitimately contrast “recorded net order value” with “recognized revenue”).

## 7. Privacy / local-processing behavior

- All processing happens in the locally running application environment (ADR-004). The UI states this on the Upload view.
- Direct personal fields (first name, last name, street, email, password) and precise customer coordinates / IP-like fields are excluded from canonical structures, API payloads, logs, exports, tables, charts, and screenshots (ADR-005). Profiling may count such columns without displaying values.
- Customer analytics use only the sanitized customer ID, segment, and approved coarse customer-side geography (ADR-005, ADR-016; see `docs/canonical-schema.md`).
- Logs contain technical metadata, counts, rule IDs, and error codes only — never row contents, cell values, or personal fields.
- Raw uploads, derived files, and exports live under session-scoped temp storage, are git-ignored, and are removed on reset, expiry, restart sweep, or terminal failure (leaving only privacy-safe error metadata).
