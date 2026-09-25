# DECISIONS.md

## Purpose

This file records decisions that materially affect scope, data meaning, architecture, privacy, or KPI behavior. Accepted decisions are binding until explicitly superseded.

Each new entry must include status, context, decision, consequences, and any superseded decision. Do not rewrite historical entries to make later choices appear original.

Status values:

- `Accepted`: binding
- `Proposed`: awaiting approval
- `Superseded`: replaced by a later decision
- `Rejected`: considered and not selected

---

## ADR-001 — DataCo is the V1 reference mapping, not the universal schema

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The supplied DataCo file is rich enough to demonstrate ingestion, profiling, cleaning, modelling, KPI calculation, and dashboard analysis, but its column names and business coverage are dataset-specific.

### Decision

V1 accepts the DataCo source shape through an explicit source-to-canonical mapping. Internal logic depends on canonical fields, not raw DataCo labels. Arbitrary column mapping is a V2 feature.

### Consequences

- V1 can be tested deeply instead of pretending to support unknown schemas.
- New datasets require a new mapping or the future mapping workflow.
- UI and API terminology remain independent from awkward source labels.

---

## ADR-002 — Order and order-item grain remain separate

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The main CSV contains 180,519 unique order items but 65,752 orders. Order IDs repeat, and an order/product pair can contain multiple legitimate lines.

### Decision

Create separate `orders` and `order_items` canonical structures. Delivery and status KPIs operate on distinct orders. Sales, discounts, units, and line profit originate from order items.

### Consequences

- `Order Id` is never used as a row-deduplication key.
- `Order Id + Product Id` is also not a deduplication key.
- Aggregations must declare their grain and reconcile across structures.

---

## ADR-003 — Raw uploads are immutable and cleaning is auditable

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Silent cleaning would make it impossible to explain why rows, fields, or values changed.

### Decision

Preserve each raw upload unchanged for its local session. Build cleaned/canonical outputs separately. Record each rule and its detected, fixed, flagged, excluded, and unchanged counts.

### Consequences

- Cleaning can be reproduced and reviewed.
- Missing or suspicious business values are not automatically invented.
- Exports clearly identify whether they contain raw, cleaned, or canonical data.

---

## ADR-004 — Local-first processing with no external data transmission

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Uploads may contain customer and operational data. The demo file itself contains names, streets, coordinates, and an unrelated access log with IP addresses.

### Decision

V1 processes uploads only in the locally running application environment. Uploaded data is not sent to external AI, telemetry, analytics, geocoding, storage, or enrichment services.

### Consequences

- External services cannot be required for core analytics.
- Temporary data must have a defined local lifecycle.
- Maps must use supplied geography or bundled mappings rather than silently geocoding uploaded addresses.

---

## ADR-005 — Direct personal fields are excluded from the analytical model

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Customer first name, last name, street, email, and password add no required V1 analytical value. Email and password are masked constants, while names and addresses still resemble personal data.

### Decision

The analytical model and UI exclude first name, last name, street, email, and password. Customer analysis uses a sanitized customer ID, segment, and approved coarse geography only.

### Consequences

- Direct personal fields cannot appear in API payloads, logs, exports, tables, or screenshots.
- Data-quality profiling may count excluded fields without displaying their raw values.

---

## ADR-006 — The access-log CSV is outside V1

**Status:** Accepted  
**Date:** 2026-09-24

### Context

`tokenized_access_logs.csv` contains 469,977 web events, raw-looking IP addresses, only 76 products, and no reliable order/customer key. It is a web-traffic dataset, not an order fact table.

### Decision

Do not ingest or join the access log in V1. Treat it as a possible separate V2 web-analytics module requiring its own privacy and deduplication design.

### Consequences

- V1 scope remains supply-chain performance rather than clickstream attribution.
- IP-address handling is not added accidentally.

---

## ADR-007 — Canonical source-of-truth fields

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Several raw columns are exact duplicates or have misleading names.

### Decision

Use the following canonical sources:

| Canonical field | Raw source | Rule |
|---|---|---|
| `order_id` | `Order Id` | Cast to string |
| `order_item_id` | `Order Item Id` | Cast to string; unique |
| `customer_id` | `Customer Id` | `Order Customer Id` is redundant |
| `product_id` | `Product Card Id` | Other product-ID copy is redundant |
| `category_id` | `Product Category Id` | Other category-ID copy is redundant |
| `unit_price` | `Order Item Product Price` | Product-price copy is redundant |
| `gross_sales` | `Sales` | Pre-discount line value |
| `discount_amount` | `Order Item Discount` | Line discount |
| `net_sales` | `Order Item Total` | Authoritative reported net line value |
| `profit_amount` | `Benefit per order` | Treat as line profit despite source label |
| `order_timestamp` | `order date (DateOrders)` | Explicit month-first parse |
| `ship_timestamp` | `shipping date (DateOrders)` | Explicit month-first parse |
| `actual_shipping_days` | `Days for shipping (real)` | KPI source |
| `scheduled_shipping_days` | `Days for shipment (scheduled)` | KPI source |

Source discount and profit ratios are retained only for audit/validation. Aggregate ratios are recalculated from amounts.

### Consequences

- Redundant raw columns remain in the immutable upload but not in the canonical analytics model.
- `Sales per customer` is not interpreted as customer-level sales.
- `Order Profit Per Order` is not interpreted as already-aggregated order profit.

---

## ADR-008 — Monetary calculations use reported net sales with tolerance-based validation

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Gross sales minus discount differs from reported net sales by small row-level floating/rounding amounts and approximately 45.77 over the complete file.

### Decision

Use reported `Order Item Total` as canonical net sales. Validate gross minus discount against it with a documented cent-level tolerance. Use decimal-safe calculation and round only at defined output boundaries.

### Consequences

- The pipeline does not create false data-quality errors from source precision.
- Recalculated net sales is validation evidence, not a replacement value.

---

## ADR-009 — Commercial KPIs describe recorded order value, not recognized revenue

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The dataset includes complete, closed, pending, processing, on-hold, cancelled, payment-review, and suspected-fraud orders. It does not document accounting recognition or settlement.

### Decision

Headline commercial values use labels such as `gross order value`, `net order value`, and `recorded profit`. Status scope must be visible. Do not label these values recognized revenue.

### Consequences

- All-status totals can be shown without making an accounting claim.
- Users can filter statuses, but filtered results retain the same terminology.
- A future recognized-revenue metric requires an authoritative business rule absent from DataCo.

---

## ADR-010 — Currency is unspecified

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The source describes sales and profit amounts but does not define their currency.

### Decision

Canonical monetary values have no inferred currency. The application uses neutral currency-unit formatting unless a clearly displayed demo assumption is separately approved.

### Consequences

- The dashboard must not silently add dollar, pound, or euro symbols.
- Exports retain numeric values without invented currency metadata.

---

## ADR-011 — Shipment adherence is not customer on-time delivery

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The source contains order and shipping timestamps plus scheduled and actual shipping-day fields, but no customer receipt timestamp or promised-delivery timestamp.

### Decision

Use `on-schedule shipment rate`, `late-shipment rate`, and `shipping days`. Do not claim customer on-time delivery, end-to-end fulfilment time, or last-mile delivery performance.

### Consequences

- Shipment KPIs remain faithful to available evidence.
- OTIF and perfect-order metrics remain out of scope.

---

## ADR-012 — Shipment KPI population excludes cancelled shipments

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The complete file has 65,752 orders, including 2,855 `Shipping canceled` orders. Treating cancelled orders as non-late would understate late rates.

### Decision

The eligible population for early, exact-on-schedule, late, and average-shipping-day KPIs is distinct orders whose delivery outcome is not `Shipping canceled`. Cancelled orders receive `is_late = null`.

Reference population:

- eligible orders: 62,897;
- late: 36,048;
- early: 15,127;
- exactly on schedule: 11,722;
- late rate: 57.3127%; and
- combined on-schedule rate: 42.6873%.

### Consequences

- KPI denominators are explicit and testable.
- Empty eligible populations return unavailable rather than zero percent.

---

## ADR-013 — Strict cancellation and suspected fraud are separate outcomes

**Status:** Accepted  
**Date:** 2026-09-24

### Context

All 2,855 shipping-cancelled orders consist of 1,367 `CANCELED` and 1,488 `SUSPECTED_FRAUD` orders.

### Decision

Report strict cancellation rate and suspected-fraud rate separately. A combined shipping-blocked/cancelled outcome may also be shown if clearly named.

### Consequences

- The application cannot call all shipping-cancelled records customer cancellations.
- The two populations remain independently filterable and testable.

---

## ADR-014 — Aggregate rates are amount-weighted

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Averaging row-level discount or profit ratios gives each line equal weight regardless of value.

### Decision

Calculate:

- profit margin as `sum(profit_amount) / sum(net_sales)`; and
- discount rate as `sum(discount_amount) / sum(gross_sales)`.

Use explicit unavailable behavior when the denominator is zero.

### Consequences

- Headline percentages reconcile to displayed amounts.
- Raw row ratios are diagnostic inputs only.

---

## ADR-015 — Actual shipping days are authoritative for shipment KPIs

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Timestamp-derived elapsed days match the reported field except for all 9,737 Same-Day rows, whose timestamps commonly differ by 12 hours while the reported duration is integer-valued.

### Decision

Use `Days for shipping (real)` as canonical actual shipping days. Use timestamp differences for validation and diagnostics only.

### Consequences

- Same-Day rows are not falsely rewritten.
- Date inconsistencies can be reported without changing the business KPI.

---

## ADR-016 — Geographic fields retain distinct meanings

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Order fields describe destination geography. Customer latitude/longitude and customer address fields describe the customer/store-side location and include at least one clear coordinate anomaly. Most destination ZIP codes are missing.

### Decision

Keep customer geography and order-destination geography separate. Never plot customer coordinates as order destinations. Do not impute missing destination postal codes or externally geocode uploaded addresses.

### Consequences

- Maps must state which geography they show.
- Country/region views may use categorical destination fields without pretending precise coordinates exist.

---

## ADR-017 — Negative profit is retained

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The dataset contains 33,784 negative-profit lines, 13,909 loss-making orders, and profit ratios as low as -2.75. These may be unusual but are internally consistent with reported profit amounts.

### Decision

Retain negative and extreme-profit observations. Flag severe values for investigation and expose loss-making-order/item analysis. Do not clip, winsorize, delete, or convert them to missing values in V1.

### Consequences

- Profit totals remain faithful to the source.
- Outlier treatment cannot silently improve dashboard results.

---

## ADR-018 — Predictive modelling is excluded from V1 and must be leakage-safe later

**Status:** Accepted  
**Date:** 2026-09-24

### Context

`Late_delivery_risk` exactly reproduces late delivery status. Actual shipping days and shipping timestamp are post-outcome fields. Order ID almost perfectly encodes time, and the product assortment changes over time.

### Decision

Do not implement forecasting or late-shipment prediction in V1. Any future model must define its prediction timestamp, exclude post-outcome fields, avoid order-ID time leakage, and use temporal validation.

### Consequences

- High but meaningless leaked model accuracy cannot be presented as a project result.
- Descriptive diagnostics must use association language rather than causal claims.

---

## ADR-019 — Unsupported KPI families are explicitly prohibited

**Status:** Accepted  
**Date:** 2026-09-24

### Context

DataCo does not contain inventory, supplier, procurement, warehouse, freight-cost, returns, promised-receipt, in-full, emissions, or forecast data.

### Decision

Do not calculate or imply OTIF, fill rate, stockouts, inventory turnover, supplier performance, procurement savings, warehouse productivity, freight cost, return rate, perfect-order rate, customer delivery lead time, forecast accuracy, emissions, customer lifetime value, or causal loss from lateness.

### Consequences

- Adding one of these KPIs requires new authoritative source data and a new accepted decision.

---

## ADR-020 — Reference controls are regression tests, not production constants

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The audited DataCo results provide strong end-to-end verification, but hardcoding them would make analytics appear correct for only one file.

### Decision

Use the audited counts, totals, and rates as golden-test expectations for the unmodified reference input. Production results must always be calculated from the active upload.

### Consequences

- The full pipeline can be regression-tested.
- Synthetic edge-case fixtures remain necessary for conditions absent from DataCo.

---

## ADR-021 — DataCo is suitable for demonstration, not real-world inference

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Order timestamps occur predominantly at exact 21-minute intervals, order IDs nearly perfectly encode time, and product availability changes sharply late in the period. These are strong signs of generated or heavily synthesized data.

### Decision

Use DataCo to demonstrate application behavior, analytics engineering, grain handling, and data-quality controls. Do not present its demand patterns, operational rates, or trends as findings about a real company or market.

### Consequences

- Portfolio documentation must disclose the dataset's synthetic characteristics.
- Insights are phrased as findings within the demo dataset.
- Business recommendations must be illustrative, not asserted as real operational advice.

---

## ADR-022 — Frontend presentation uses React, shadcn/ui, and Recharts

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The product needs an interactive web interface with cards, filters, tables, dialogs, accessible controls, and analytical charts. The project specifically intends to use shadcn/ui.

### Decision

Use a TypeScript React frontend, shadcn/ui for the component foundation, and Recharts through the shadcn chart patterns. Exact framework and supported versions are finalized in Phase 2.

### Consequences

- Components remain source-controlled and customizable.
- Visual components consume backend KPI contracts and do not recreate calculations.
- Adding an alternative chart or component library requires a demonstrated gap.

---

## ADR-023 — Python owns parsing, canonicalization, and KPI logic

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The reference file is large enough to require explicit parsing and memory decisions, while Python provides a clear, testable ecosystem for tabular validation and analytics.

### Decision

Use a Python backend for ingestion, validation, cleaning, canonical transformation, and KPI calculation. Expose typed API contracts to the frontend. The exact web framework and dataframe engine are finalized after Phase 2 benchmarking and dependency review.

### Consequences

- Business logic remains outside React components.
- Dataframe-library-specific operations must be isolated behind domain functions where practical.
- Selecting FastAPI, pandas, Polars, DuckDB, or another implementation detail requires measured justification, not résumé-driven technology stacking.

---

## ADR-024 — Raw datasets are not committed or redistributed

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The reference archive is large, separately distributed, and unnecessary for cloning the source repository.

### Decision

Exclude the DataCo archive, extracted source CSVs, uploads, and generated cleaned datasets from Git. Document how to obtain the public reference dataset and provide small synthetic test fixtures instead.

### Consequences

- Repository history stays small and avoids accidental personal-data artifacts.
- Full reference tests require a documented local dataset path or opt-in test setup.

---

## ADR-025 — Concrete application and runtime architecture

**Status:** Accepted  
**Date:** 2026-09-24

### Context

ADR-022 fixed React + shadcn/ui + Recharts and ADR-023 fixed Python ownership of logic, but left the exact framework, runtimes, package managers, and quality gates open for Phase 2.

### Decision

- Frontend: Vite + React single-page app, TypeScript `strict`, shadcn/ui + Tailwind + Radix, Recharts only, npm + `package-lock.json`, Vitest + React Testing Library + axe, ESLint + Prettier + `tsc --noEmit`.
- Backend: Python 3.12.x (minimum 3.11), FastAPI + Pydantic v2 + Uvicorn, uv + `uv.lock` with a documented pip fallback, pytest + TestClient/httpx + coverage, Ruff + mypy on domain/KPI/schema code.
- No Next.js/SSR, no Django/Flask, no Poetry, no Pandera/Great Expectations, no second chart library, no Playwright suite until Phase 17 proves a need. Each rejection is justified by the absence of a V1 requirement, not by preference.
- Route handlers validate I/O and call domain services; business logic lives outside HTTP and UI layers.

### Consequences

- One documented command starts the app and one runs all checks (Phase 3 implements).
- Adding any dependency requires a concrete V1 requirement and a recorded justification.
- Full detail and per-choice rationale live in `docs/architecture.md`.

---

## ADR-026 — pandas with pyarrow-backed dtypes is the V1 dataframe engine

**Status:** Accepted  
**Date:** 2026-09-24

### Context

ADR-023 deferred the dataframe choice pending Phase 2 review. The reference file is ~95.9 MB / 180,519 rows: large enough to need dtype discipline, small enough to fit comfortably in memory.

### Decision

Use pandas 2.x with pyarrow-backed string dtypes for all V1 ingestion, validation, cleaning, canonicalization, and KPI work, isolated behind domain functions. Defer Polars: its speed advantages address no measured V1 bottleneck, while its thinner `Decimal` support and higher API churn add review risk for tolerance-based money validation. DuckDB as primary engine is rejected for the same reason. Reconsider only with Phase 17 measurements via a new ADR.

### Consequences

- Single-pass, header-first, in-memory processing is the V1 design; streaming/chunking is not required.
- Engine-specific operations stay behind domain functions so a future switch does not rewrite analytics.
- Comparison evidence lives in `docs/architecture.md`.

---

## ADR-027 — Upload and resource budget

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The pipeline needs an enforced size cap and honest performance language before implementation.

### Decision

- Hard limit: 250 MB per upload, enforced pre-parse (`Content-Length` plus on-disk bytes); over-limit fails fast with no orphaned data.
- ~500k order-item rows on an 8 GB laptop and reference-file end-to-end timing targets are Phase 17 validation targets and working budgets, explicitly NOT guaranteed product claims until benchmarking confirms them. Docs and UI must label them as targets.
- Parsing is header-first (≤1 MB sniff for header/encoding/dialect, duplicate-header and column-count checks) followed by one full read with explicit `dtype=str` staging and controlled casts. No chunked/streaming implementation in V1 absent OOM evidence.
- Input safeguards: never trust filename/MIME alone; reject empty/header-only files; cap header count and cell length; UUID-only stored filenames; UTF-8-SIG then Latin-1 encoding fallback, else fail with guidance.

### Consequences

- Users get a clear, enforceable cap; the project makes no unsupported performance promises.
- Phase 17 publishes measured limits and timings; only then may claims harden.

---

## ADR-028 — Local session lifecycle

**Status:** Accepted  
**Date:** 2026-09-24

### Context

ADR-003 and ADR-004 require immutable local sessions with a defined lifecycle, but left ID format, layout, expiry, and failure semantics open.

### Decision

- Session ID is one server-generated UUIDv4. It encodes no user, filename, timestamp, or source information. No ULID hybrid.
- Layout: `.tmp/sessions/{uuid}/` with `manifest.json`, read-only `raw.csv`, `derived/`, and `exports/` (all git-ignored).
- The immutable raw remains while the session can validly continue, until reset/expiry. On terminal ingestion/processing failure (session cannot validly continue): remove partial derived files and the raw upload, retaining only privacy-safe manifest/error metadata (IDs, stage, codes, sizes, counts — never cell values or personal fields). Recoverable sessions keep their raw until reset/expiry.
- Reset (`DELETE`) is idempotent full-tree removal. Expiry is a documented TTL (default 24 h sliding) plus on-disk pressure caps; restart sweeps abandoned/incomplete/expired sessions, logging counts only.
- Logs carry metadata, counts, rule IDs, and error codes only.

### Consequences

- Failed uploads cannot accumulate into a covert data store; diagnostics keep what is privacy-safe and nothing more.
- Full lifecycle detail lives in `docs/architecture.md` and `docs/api-contract.md`.

---

## ADR-029 — Async API and processing contract

**Status:** Accepted  
**Date:** 2026-09-24

### Context

The reference file cannot be fully processed inside a reasonable request timeout, and the earlier proposal left 201-vs-202 behavior ambiguous.

### Decision

- One behavior: `POST /api/v1/sessions/uploads` runs only cheap synchronous guards (extension/MIME evidence, size, emptiness, header parse, duplicate headers, encoding sniff), creates the session, stores the immutable raw, and returns `202 Accepted` with the session ID and status URL. It never waits for full processing.
- Long work proceeds through explicit states — `UPLOADING → VALIDATING → PROFILING → CLEANING → CANONICALIZING → ANALYZING → READY`, with terminal `FAILED` / `EXPIRED` — observed via `GET /sessions/{id}/status`. Downstream reads return `200` when ready or `409 NOT_READY` otherwise.
- One consistent typed envelope (`data` / `meta` / `error`), a documented error-code table with failing stage attached, filter conventions (filters narrow populations, never redefine KPIs; unknown enums rejected), and money/date/null serialization (money as 2-dp strings, naive ISO dates, unavailable KPIs as `null` with reason, never zero).

### Consequences

- The UI stays responsive with stage-specific progress; no request path can time out on full-file processing.
- No KPI/business logic lives in route handlers. Full contract lives in `docs/api-contract.md`.

---

## ADR-030 — Canonical schema, enums, and derivation rules

**Status:** Accepted  
**Date:** 2026-09-24

### Context

ADR-007 fixed source-of-truth columns but Phase 2 needed the complete field contracts, enum closure, geography discipline, and the corrected shipment-classification rule.

### Decision

- Canonical structures per `docs/canonical-schema.md`, with every field tagged source-derived (S), system metadata (M), deterministic derived (D), or aggregated (A). No field exists without a V1 KPI, filter, drilldown, reconciliation, or audit consumer.
- Shipment classification derives solely from authoritative day fields for eligible orders: `actual > scheduled → LATE`, `== → ON_SCHEDULE`, `< → EARLY`; shipping-cancelled orders get `shipment_outcome = SHIPPING_CANCELED` and `is_late = null` as a canonical derivation. `Late_delivery_risk` is validation/audit evidence only and never classifies; timestamp differences are validation evidence only (ADR-015 preserved).
- Products contain only identifying dims plus defensible aggregations (`line_count`, `total_units`, `total_net_value`, `total_profit_amount`); no reference-price field.
- `customers_sanitized` carries coarse customer geography only from customer-side fields, never derived from order destinations; absent values stay `null`, never imputed.
- Unknown source enum values become `UNKNOWN_FLAGGED`: counted, reported, excluded from split KPIs — never silently coerced.
- Direct personal fields, precise coordinates, destination postal codes as locators, IPs, and redundant copies can never enter canonical structures.

### Consequences

- Analytics cannot be skewed by leaked risk flags, invented prices, destination-as-customer geography, or silent enum coercion.
- Observation vs cleaning vs derivation vs validation are logged as distinct concepts.

---

## ADR-031 — KPI contract ownership and behavior

**Status:** Accepted  
**Date:** 2026-09-24

### Context

AGENTS.md and ADR-009–ADR-014 fixed terminology, populations, and weighting, but Phase 2 needed the per-KPI executable contracts and the testing model.

### Decision

- Every authorized V1 KPI has one backend-owned contract in `docs/kpi-contracts.md` (ID, approved display label, meaning, grain, formula, numerator/denominator, eligible population, exclusions, date basis on `order_timestamp`, required fields, filter behavior, unavailable/zero behavior, formatting, DataCo regression expectation).
- Empty eligible populations, zero denominators, and fully-missing required fields return unavailable (`value: null` + reason), never zero percent.
- Dashboard components render approved labels from the backend contract; contract tests assert KPI IDs and approved labels so unauthorized label changes fail. No global banned-word CI lint (docs may legitimately contrast approved terms with prohibited ones).
- Binding terminology preserved: recorded net order value, on-schedule shipment rate, association-not-causation, strict-cancellation vs suspected-fraud separation, unspecified currency, amount-weighted rates.

### Consequences

- No component can independently redefine a KPI; label drift is caught by tests without censoring documentation language.

---

## ADR-032 — Data-quality severity, blocking, and concept separation

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Quality findings need stable IDs, honest severity, and unambiguous gating without an override workflow the product does not have.

### Decision

- Stable rule families `DQ-FILE / DQ-SCHEMA / DQ-KEY / DQ-DATE / DQ-NUM / DQ-CAT / DQ-GRAIN / DQ-BUSINESS / DQ-PRIVACY` with per-rule IDs in `docs/data-quality-rules.md`.
- Each rule states the exact downstream stage it blocks, if any (e.g., malformed file blocks INGESTION; missing critical schema blocks CANONICALIZATION and KPI_ANALYSIS; duplicate item key blocks CANONICALIZATION; informational missingness blocks nothing). `ERROR` gates its named stage until the input is fixed or replaced.
- No acknowledgement/waiver feature exists in V1: `ERROR` does not imply an override workflow.
- Detection (profiling), cleaning transformation (approved reversible ops only), canonical derivation (recorded formulas), and validation results (gating checks that change no data) are separate logged concepts. `is_late = null` for cancelled shipments is a derivation, not a fix.

### Consequences

- Users always know what is blocked, where, and why — with no false promise that warnings can waive errors.

---

## ADR-033 — Export contract

**Status:** Accepted  
**Date:** 2026-09-24

### Context

Exports must be retainable and reproducible without leaking personal data or executable content.

### Decision

- Four approved exports only (raw never exportable): sanitized cleaned order-item CSV, canonical order CSV, data-quality report, cleaning/audit report — each with field allowlists, provenance/version metadata (app/schema versions, session, source hash, filters, currency and synthetic-data notes), and deterministic naming.
- Privacy gate `DQ-PRIVACY-003` fails closed: any banned header blocks the export.
- Spreadsheet-injection protection applies only to string/text cells that spreadsheet software could interpret as formulas (leading `= + - @`, DDE patterns): quote-prefix, RFC 4180 quoting. Typed numeric/date values keep proper serialization — legitimate negatives stay computable. The distinction is documented and tested on both sides.
- Formatting: UTF-8+BOM CSV with LF endings; fixed 2-dp money without currency symbol; naive ISO dates; nulls as empty/JSON-null, never invented text.

### Consequences

- Exports reconcile with the on-screen session and filters, reopen safely in common spreadsheet tools, and carry enough provenance for independent reproduction.
- Full contract lives in `docs/export-contract.md`.

---

## ADR-034 — Graft structural-context pilot (CLI-only, local)

**Status:** Accepted  
**Date:** 2026-09-25

### Context

Phases 8+ are increasingly cross-file: canonical construction, the KPI engine, and dashboard views cut across profiling, cleaning, sessions, API schemas, and frontend contracts. Repeated dependency and lifecycle discovery has a real cost, and a structural code graph may reduce it. Graft (`@nanonets/graft`, repo `trailhq/Graft`, MIT) builds a local tree-sitter symbol graph with CLI queries (`ask`, `callers`, `grep`, `map`, `blast`, `skeleton`, `check`). It is a development aid, not part of the product or runtime. It has no dedicated OpenCode integration; its generic `agents` host would inject a marker section into `AGENTS.md`, which is unacceptable for a governance file. Its marketing ("no telemetry") is contradicted by its own `TELEMETRY.md` (anonymous opt-out telemetry), so posture must be set explicitly, not assumed.

### Decision

- Graft is admitted as a **PILOT** only: CLI-only use against committed code, structural/local build only.
- Install as a machine/developer tool via pinned npx execution, `npx -y @nanonets/graft@0.19.0` (pilot version `0.19.0`, engines `node >= 20`; compatible with the Node 24 pin). A global `npm install -g` was rejected by the machine (root-owned prefix, no sudo per least-privilege); npx is the officially documented no-global alternative and keeps zero persistent install state outside the npm cache. Never an application dependency: nothing in `package.json`, `package-lock.json`, `pyproject.toml`, or `uv.lock`.
- Telemetry **disabled**: first package fetch ran under `DO_NOT_TRACK=1` (covers the postinstall hook) plus persistent `graft telemetry disable`, verified via `graft telemetry status` (off) and `graft telemetry debug` (nothing queued, sends nothing).
- **Prohibited in pilot:** `graft init` (any host: `agents`, `claude`, `codex`, all others); any `AGENTS.md`/`GEMINI.md`/rule-file injection; MCP server registration; `graft build --deep` (sends source to a configured LLM provider); Trail Brain (`graft brain push`, cloud); any cloud or source upload.
- Generated state is local only: `graft/` (nodes, `.graph/`, `.cache/`) and `.graft/` (build config) are gitignored and never committed. `graft build` may append the `graft/` ignore entry itself; the `.gitignore` change is made deliberately and kept minimal. Known tool behavior (v0.19.0): `graft build` also drops an untracked `.ignore` at the repo root to keep `graft/` greppable; the pilot deletes it (generated state stays out of code search and out of the footprint) and re-deletes it if regenerated.
- Authority: Graft may **LOCATE and EXPLAIN** code relationships. It may **NOT** establish requirements. On any conflict between Graft output and `AGENTS.md`, `PLAN.md`, `DECISIONS.md`, contract docs, or actual source, the authoritative source wins and must be opened directly. Graft output is never cited as justification in decisions, tests, or approvals.
- Direct-read requirement: Graft output never replaces direct reading of `AGENTS.md`, `PLAN.md`, `DECISIONS.md`, exact API contracts, exact DQ rules/thresholds, exact enum domains, KPI contracts, acceptance criteria, source files being modified, or tests proving modified behavior.
- Authority hierarchy for any Graft-assisted work: (1) safety/security/privacy; (2) `AGENTS.md`/accepted ADRs/`PLAN.md`/contract docs; (3) correctness/auditability; (4) phase acceptance criteria; (5) tests proving 1–4; (6) reuse/native/stdlib/minimal implementation; (7) cosmetic brevity.
- Rollback: stop invoking the pinned package, `rm -rf graft/ .graft/`, revert the `.gitignore` entries, optionally `rm -rf ~/.graft/` (rotates telemetry IDs) and clear the npx cache entry, verify `git status` clean. No global package to uninstall under the npx method.
- Pilot success criteria (measurable): at least two structural findings cross-checked correct against source; observable reduction in discovery reads on cross-file tasks; zero governance drift; zero external transmission (telemetry off, no `--deep`); local state confined to ignored paths. Verdict (`USE` / `CONTINUE PILOT` / `REMOVE`) recorded before permanent adoption; pilot status alone never implies adoption.

### Consequences

- Cross-file discovery (DQ-contract tracing, API/backend/frontend coupling, test impact, lifecycle/recovery code) gets a cheap local aid.
- A second tool surface (global npm package, local cache dirs) must be maintained, version-pinned in future ADR updates, and kept out of the repo and product.
- Any future widening (`init` wiring, MCP, `--deep`, Trail Brain) requires a new accepted decision.

### Pilot evidence (2026-09-25)

- Method: pinned `npx -y @nanonets/graft@0.19.0` (global install blocked by root-owned prefix, no sudo); telemetry off via `telemetry disable` + `DO_NOT_TRACK=1`, verified (`telemetry status`: off; `telemetry debug`: nothing queued); structural `graft build` only — 42 files, 478 nodes, 1178 edges, Python + TS/TSX full-fidelity.
- Smoke: `map`, `skeleton backend/app/cleaning.py`, `callers run_cleaning` / `ensure_cleaned`, `grep CANONICALIZING` (91 hits, symbol-grouped, backend + frontend), depth-2 dependency fan-out of `ensure_cleaned`, `check` in sync. Four findings cross-checked correct against source (profiling→cleaning call edge at `profiling.py:581`, SHA/helper deps of `ensure_cleaned`, its single-caller result, lifecycle function `make_canonicalizing_progress` in `sessions.py`).
- Limitations found: `callers` missed module-attribute call sites (`cleaning_service.run_cleaning` in tests) — direct search still required for completeness; `graft build` drops an untracked `.ignore` at repo root (deleted per ignore policy, re-delete if regenerated); per-query "tokens saved" reply nudges are inert with telemetry off.
- Privacy: no `.tmp/`, session, raw-upload, personal-field, or key content in generated state; no `--deep`; no Trail Brain; no MCP.
- Verdict: CONTINUE PILOT.

---

## ADR-035 — Ponytail minimalism-review pilot (global, lite default)

**Status:** Accepted  
**Date:** 2026-09-25

### Context

Cleaning (Phase 7) and upcoming canonical/KPI work add defensive code that must stay, alongside a real risk of accidental complexity (duplicated helpers, one-call-site abstractions, redundant DTOs, duplicated tests). Ponytail (project `DietrichGebert/ponytail`, MIT) is a reviewer that pressures reuse and minimal diffs via a per-turn ruleset plus `/ponytail-review` delete-lists. Unlike Graft it documents explicit OpenCode support (plugin + six slash commands). Its standing `full`/`ultra` modes and "YAGNI applies to tests" norm conflict with binding auditability and test requirements, so its intensity must be bounded by governance, not by vendor default.

### Decision

- Ponytail is admitted as a **PILOT** only, from the **official source only**: npm package `@dietrichgebert/ponytail` (pilot version `4.10.0`) loaded as an OpenCode plugin. Third-party mirrors (`opencode-ponytail`, `ponytail-opencode-plugin`, `@metalbolicx/opencode-ponytail`, and similar) are prohibited unless the official project explicitly adopts one.
- Integration verified against OpenCode `1.18.22`: `{ "plugin": ["@dietrichgebert/ponytail"] }` in the **global/machine-level** config (`~/.config/opencode/opencode.jsonc`), per the official Ponytail README and the OpenCode plugin docs (npm plugins auto-installed via Bun into `~/.cache/opencode/`). No project-repo configuration, no checkout inside the repo.
- Default mode **`lite`**: build what's asked, name the lazier alternative in one line. `full` only for deliberately scoped review passes. `ultra` is **not permitted** as a standing mode (it challenges requirements, which only the `DECISIONS.md` process may change).
- **Prohibited:** project `AGENTS.md` edits; `package.json`/`package-lock.json`/`pyproject.toml`/`uv.lock` entries; automatic application of review suggestions; whole-repo rewrites.
- Authority: Ponytail may **identify avoidable complexity**. It may **NOT** delete or weaken governed behavior: atomic writes, SHA verification, CAS/state guards, restart recovery, concurrency guards, privacy-safe artifacts, `blockedStage` handling, audit logs, negative/adversarial/a11y tests, or anything required by 1–5 below. Deletion recommendations against such behavior are rejected with the ADR cited.
- Authority hierarchy (binding over any Ponytail suggestion): (1) safety/security/privacy; (2) `AGENTS.md`/accepted ADRs/`PLAN.md`/contract docs; (3) correctness/auditability; (4) phase acceptance criteria; (5) tests required to prove 1–4; (6) reuse/native/stdlib/minimal implementation; (7) cosmetic brevity. Ponytail's ladder operates only within the space 1–5 leave open; explicitly requested docs/prose/tests are exempt from terseness norms.
- Rollback: remove the plugin entry from global OpenCode config, run the project's `scripts/uninstall.js` equivalent cleanup before deleting any checkout, remove `~/.config/ponytail/`, and manually remove `~/.config/opencode/.ponytail-active` (the OpenCode mode flag, not covered by `uninstall.js` v4.10.0), verify no Ponytail activation in a fresh session. Nothing in the application repo to revert.
- Pilot success criteria (measurable): review output catches real duplication on the Phase-7 diff without modification; `lite` shows no repeated pressure to remove governed defenses (boundary smoke); zero repository contamination; reversible global state. Verdict (`USE` / `CONTINUE PILOT` / `REMOVE`) recorded before permanent adoption.

### Consequences

- Diff hygiene gets a second reviewer biased toward reuse and small diffs, active only where governance permits.
- Every Ponytail suggestion must still pass the contract-correctness review and full checks; a suggestion that weakens a governed invariant costs review time rather than saving it — the pilot measures this trade directly.
- Any widening (standing `full`, `ultra` audits, project-level config) requires a new accepted decision.

### Pilot evidence (2026-09-25)

- Method: official npm `@dietrichgebert/ponytail@4.10.0` as global OpenCode plugin entry in `~/.config/opencode/opencode.jsonc`, verified against OpenCode `1.18.22` plugin docs (npm plugins auto-installed via Bun); default `lite` via `~/.config/ponytail/config.json`, resolved at runtime (`getDefaultMode()` → `lite` from that path). No application-repo files touched.
- Static verification of the published tarball: all six slash commands ship (`.opencode/command/`); no network calls in hooks/plugin/commands/skills (one docs URL in help text only); no install scripts; the "When NOT to be lazy" safety clause intact (trust-boundary validation, data-loss handling, security, accessibility, explicitly requested work).
- Live command smoke (`/ponytail`, `/ponytail-review`, Phase-7 review, governed-defense boundary test) is BLOCKED in this environment: headless `opencode run` fails with model insufficient-balance, and no user funds were spent probing further. Deferred until a funded model is available; contract-audit-before-review ordering stands.
- Rollback gap found: `uninstall.js` v4.10.0 does not remove the OpenCode mode flag `~/.config/opencode/.ponytail-active`; manual removal recorded above.
- Verdict: CONTINUE PILOT (not USE) pending live smoke.

---

## Decision-change template

Copy this section when proposing a new material decision:

```markdown
## ADR-XXX — Decision title

**Status:** Proposed  
**Date:** YYYY-MM-DD

### Context

What fact, constraint, or problem requires a decision?

### Decision

What exactly will the project do?

### Consequences

- What becomes easier or harder?
- What new constraints or work follow?

### Supersedes

ADR-XXX, if applicable.
```

