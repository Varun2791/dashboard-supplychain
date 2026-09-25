# PLAN.md

## Purpose

This is the execution plan for the Supply Chain Analytics Dashboard. It is a living control document, not a wishlist. Agents must work phase by phase and may not mark a task complete until its acceptance criteria pass.

Status markers:

- `[ ]` not started
- `[~]` in progress or partially complete
- `[x]` complete and verified
- `[!]` blocked; explain the blocker directly below the item

## Product objective

Create a local-first web application that turns a DataCo-compatible supply-chain CSV into:

1. a dataset profile;
2. a validation and data-quality report;
3. an auditable cleaned/canonical dataset;
4. correctly-grained operational and commercial KPIs; and
5. an interactive dashboard suitable for a supply-chain analytics portfolio.

## V1 success criteria

V1 is complete when a user can upload the unmodified DataCo main CSV, understand every detected issue and applied transformation, view validated KPIs at the correct grain, filter and investigate results, export approved outputs, and reproduce the reference acceptance controls in automated tests without transmitting source data externally.

## Current state

- [x] Actual archive contents inspected.
- [x] Main dataset profiled at row, order-item, order, customer, product, date, categorical, and numeric levels.
- [x] Dataset grain and keys established.
- [x] Nulls, duplicate behavior, redundancies, leakage, and KPI limitations established.
- [x] Reference KPI controls calculated.
- [x] `AGENTS.md`, `PLAN.md`, and `DECISIONS.md` created.
- [ ] Application repository foundation created.
- [x] Product specification and technical architecture finalized.
- [ ] Application implementation started.

---

## Phase 0 — Dataset ground truth

**Status: COMPLETE**

### Objective

Establish verified facts before selecting architecture or implementing analytics.

### Completed work

- [x] Inventory all files in the archive.
- [x] Confirm the primary CSV shape: 180,519 rows and 53 columns.
- [x] Confirm order-item grain and `Order Item Id` uniqueness.
- [x] Confirm 65,752 unique orders and 62,897 non-cancelled shipment orders.
- [x] Profile nulls, types, cardinalities, exact duplicates, and candidate business keys.
- [x] Validate order-level invariance and product-level consistency.
- [x] Parse and bound order/shipping timestamps.
- [x] Profile categorical values and numeric ranges.
- [x] Identify misleading, redundant, constant, privacy-sensitive, and leakage-prone fields.
- [x] Define defensible KPI populations and reference values.
- [x] Establish limitations and excluded KPI families.

### Exit evidence

Dataset findings are captured as accepted decisions in `DECISIONS.md` and regression controls in `AGENTS.md`.

---

## Phase 1 — Governance and scope control

**Status: COMPLETE**

### Objective

Create durable rules that prevent agents from changing grain, KPI meaning, scope, or architecture without review.

### Tasks

- [x] Define permanent operating rules in `AGENTS.md`.
- [x] Create this phase-gated execution plan.
- [x] Record accepted analytical and architecture decisions.
- [x] Separate V1 from future features.
- [x] Establish reference acceptance controls.
- [x] Define the change process for decisions and plan status.

### Exit criteria

- All three control files exist and agree on V1 scope.
- DataCo counts and KPI rules are recorded once as authoritative controls.
- Future agents have explicit instructions for data, tests, privacy, Git, and completion.

Suggested commit: `docs: add project governance and phased delivery plan`

---

## Phase 2 — Product specification and technical architecture

**Status: COMPLETE**

### Objective

Translate accepted decisions into implementable contracts before scaffolding feature code.

### Tasks

- [x] Write the V1 product requirements and user journey. → `docs/product-spec.md` (§1–§7).
- [x] Define maximum upload size and resource budget using the 95.9 MB reference CSV. → `docs/architecture.md` (§3); 250 MB hard cap, ~500k-row/timing figures as validation targets only.
- [x] Confirm the frontend, backend, package manager, and supported runtime versions. → `docs/architecture.md` (§1); ADR-025.
- [x] Define the local execution and temporary-file lifecycle. → `docs/architecture.md` (§4); ADR-028.
- [x] Define API endpoints and typed response/error contracts. → `docs/api-contract.md`; ADR-029.
- [x] Create the canonical field mapping and enum definitions. → `docs/canonical-schema.md`; ADR-030.
- [x] Write complete KPI contracts, including unavailable/zero behavior. → `docs/kpi-contracts.md`; ADR-031.
- [x] Define data-quality rule identifiers and severity levels. → `docs/data-quality-rules.md`; ADR-032.
- [x] Define export formats and privacy exclusions. → `docs/export-contract.md`; ADR-033.
- [x] Produce a lightweight architecture diagram. → `docs/architecture.md` (§6).
- [x] Record any new material choices in `DECISIONS.md`. → ADR-025 through ADR-033 (ADR-001–ADR-024 untouched).

### Exit criteria

- Every V1 screen has a purpose and required data contract. — Satisfied: `docs/product-spec.md` §4 maps each route to its business question and backend contract.
- Every KPI has one backend-owned definition. — Satisfied: `docs/kpi-contracts.md` with KPI-ID/label contract tests; ADR-031.
- The canonical schema and API contracts are reviewable without application code. — Satisfied: `docs/canonical-schema.md`, `docs/api-contract.md`.
- Upload and cleanup behavior is explicit. — Satisfied: async 202 + status model, UUIDv4 sessions, reset/expiry/restart/terminal-failure semantics.
- No unresolved decision could force a repository-wide rewrite. — Satisfied: all 12 review corrections applied. Known deferred verifications (exact non-ADR-007 header strings confirmed at implementation via normalization; `$0.05` tolerance, TTL/cap values, and Node patch version finalized as documented defaults in Phase 3) are bounded and cannot force rewrites.

### Exit criteria

- Every V1 screen has a purpose and required data contract.
- Every KPI has one backend-owned definition.
- The canonical schema and API contracts are reviewable without application code.
- Upload and cleanup behavior is explicit.
- No unresolved decision could force a repository-wide rewrite.

### Do not

- Build dashboard components.
- Add forecasting, ML, authentication, or generic mapping.
- Create a database merely for future possibilities.

Suggested commit: `docs: define v1 product and architecture contracts`

---

## Phase 3 — Repository foundation

**Status: COMPLETE**

### Objective

Create a minimal, reproducible development environment with quality gates.

### Tasks

- [x] Initialize the chosen frontend and backend workspaces. — `frontend/` (Vite + React + TS strict + shadcn/Tailwind + Recharts, npm lockfile) and `backend/` (Python 3.12 + FastAPI + Pydantic v2 + pandas/pyarrow, uv lockfile).
- [x] Add root README, license, `.gitignore`, and environment examples. — `README.md`, `LICENSE` (MIT + dataset notice), `.gitignore`, `.env.example`; plus `.editorconfig`, `.nvmrc` (24), `.python-version` (3.12).
- [x] Add formatter, linter, type-check, and test commands. — ESLint + Prettier + `tsc -b` + Vitest (frontend); Ruff check/format + mypy strict + pytest (backend); `make check` runs all.
- [x] Configure CI for non-secret checks. — `.github/workflows/ci.yml` (Node 24 LTS + Python 3.12; install/typecheck/lint/format/tests/build).
- [x] Add structured application configuration. — `backend/app/config.py` (app/schema versions, 250 MB cap, session root/TTL, local host/port) with defaults test.
- [x] Add a safe temporary-data directory strategy. — ADR-028 layout under gitignored `.tmp/sessions/`; all 12 representative ignore paths verified via `git check-ignore`.
- [x] Add small synthetic fixtures; do not add the DataCo archive. — `backend/tests/fixtures/synthetic_sample.csv` (4 invented SYN- rows, no personal data); no DataCo file in repo.
- [x] Add contributor commands and supported runtime versions. — `Makefile` + `README.md` (Node 24 LTS, Python 3.12.14, uv 0.12.18).
- [x] Confirm a clean clone can install and run tests. — `npm ci` path + `uv sync --frozen` path documented in Makefile/CI; all suites green (frontend 3 tests, backend 3 tests, tsc, ESLint 0 errors, Ruff, mypy strict, vite build).

### Exit criteria

- One documented command starts the local application.
- One documented command runs all required checks.
- CI passes on the empty application shell.
- Raw data, uploads, caches, and environment files are ignored.

Suggested commit: `chore: initialize application workspace and quality gates`

---

## Phase 4 — CSV ingestion

**Status: COMPLETE**

### Objective

Accept a CSV safely and establish immutable upload metadata.

### Tasks

- [x] Implement drag/drop and file-picker upload. — `frontend/src/components/UploadSession.tsx` (+ `UploadSession.test.tsx`: picker, drop, selected-file display).
- [x] Validate extension, MIME evidence, size, and empty files. — `backend/app/ingestion.py` (`has_csv_extension`, `mime_is_csv_plausible`, `declared_size_exceeds`, `EMPTY_FILE` variants); covered in `test_upload_guards.py`.
- [x] Detect supported encoding, including the DataCo Latin-1 input. — `detect_encoding` (UTF-8-SIG → Latin-1 + text-plausibility → `UNSUPPORTED_ENCODING`); UTF-8/BOM/Latin-1 success tests.
- [x] Parse CSV headers before loading the full dataset. — `parse_header` on the ≤1 MB sniff; column cap (200); `check_duplicate_headers` on strip/BOM-drop/casefold normalization; originals preserved.
- [x] Stream or otherwise bound memory use. — 1 MB chunked `stream_upload_to_temp` with live byte cap + incremental SHA-256 and a fused byte-level emptiness scan; CSV parsing is bounded to the ≤1 MB sniff, so no second full-file pass delays the 202 (ADR-029); per-field cap via `csv.field_size_limit`.
- [x] Generate session/upload identifiers. — server UUIDv4 (`sessions.new_session_id`); UUID-format gate on status/delete.
- [x] Preserve the raw file unchanged for the session. — atomic promote to read-only `raw.csv`; byte-identity + SHA test; status/reset never rewrite it.
- [x] Return stage-specific, actionable errors. — contract envelope + codes (`EMPTY_FILE`, `INVALID_EXTENSION`, `MALFORMED_HEADER`, `UNREADABLE_HEADER`, `DUPLICATE_HEADERS`, `FILE_TOO_LARGE`, `UNSUPPORTED_ENCODING`, `MALFORMED_CSV`, `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `INTERNAL_STAGE_ERROR`); frontend code→guidance map.
- [x] Remove session data on expiry or explicit reset. — idempotent `DELETE`; 24 h sliding TTL (410 + tree removal); startup `sweep_sessions` for corrupt/FAILED/expired trees; all deterministic (frozen time, no sleeps).

### Tests

- [x] Valid DataCo-shaped CSV. — `test_dataco_shaped_headers_are_not_schema_gated` (synthetic bytes; no DataCo file in repo).
- [x] Empty file, malformed quoting, wrong extension, unsupported encoding, oversized file, duplicate headers, and interrupted upload. — `test_upload_guards.py` matrix; 250 MB boundary via small-limit unit test on the streaming writer (no 250 MB fixture). Sniff-bounded rule: breakage within the first 1 MB fails synchronously; breakage beyond it is accepted at POST and owned by profiling (DQ-FILE-005) — covered by an explicit boundary test.
- [x] Filename/path traversal attempts. — traversal-name uploads collapse to a safe leaf inside the UUID tree; encoded IDs rejected as unknown.

### Exit criteria

- [x] Valid upload reaches profiling without mutation. — 202 stores immutable raw and parks the session at VALIDATING; downstream stages intentionally not started (truthful progress, no faked READY).
- [x] Invalid uploads fail safely without orphaned data. — every guard failure removes the session tree (asserted per failure test).
- [x] Uploaded data remains local. — relative `/api` calls (+ Vite dev proxy), no external transmission; logs carry IDs/counts/codes only.

Evidence: `make check` green (frontend 15 tests, backend 56 tests, tsc, ESLint 0 errors, Ruff, mypy strict), `vite build` green, live HTTP smoke test (health → 202 → status VALIDATING → hash-verified raw → DELETE → 410/400 rejections) with synthetic `/tmp` data only.

Bounded/deferred (not invented in Phase 4): on-disk pressure caps (session count/total bytes) appear in architecture only as examples with no Phase-3 config values, so no new defaults were added — TTL + sweep are implemented; caps await a future ADR if Phase 17 requires them.

Suggested commit: `feat(ingestion): add validated local csv upload pipeline`

---

## Phase 5 — Schema validation and source mapping

**Status: NOT STARTED**

### Objective

Recognize the DataCo source schema and map it to stable canonical fields.

### Tasks

- [ ] Normalize headers without losing original names.
- [ ] Classify fields as required, optional, redundant, excluded, or unknown.
- [ ] Validate required IDs, dates, amounts, quantities, and delivery fields.
- [ ] Map source enums without silently accepting unknown values.
- [ ] Parse IDs and postal codes as strings.
- [ ] Parse timestamps with an explicit month-first format.
- [ ] Produce a schema report before cleaning.
- [ ] Reject missing critical fields with precise guidance.
- [ ] Preserve unmapped columns in raw data only.

### Exit criteria

- DataCo maps deterministically to the canonical contract.
- Missing or ambiguous critical fields stop analytics.
- Optional-field absence degrades gracefully.
- Unknown columns do not alter KPI behavior.

Suggested commit: `feat(schema): validate and map DataCo source fields`

---

## Phase 6 — Data profiling and quality detection

**Status: NOT STARTED**

### Objective

Produce a trustworthy pre-cleaning profile without modifying data.

### Tasks

- [ ] Calculate row/column counts, inferred types, missingness, and cardinality.
- [ ] Detect exact duplicates and key duplicates separately.
- [ ] Detect conflicting attributes within each order.
- [ ] Detect numeric range, enum, date, geography, and formula-consistency issues.
- [ ] Identify constant and fully-null columns.
- [ ] Identify privacy-sensitive columns.
- [ ] Display issue severity, affected counts, and proposed treatment.
- [ ] Ensure profiling can complete within the resource budget.

### Exit criteria

- The unmodified reference file reproduces the audited issue counts.
- Detection results are independent from cleaning actions.
- Every issue links to a stable rule identifier.

Suggested commit: `feat(profiling): add dataset and data-quality profiling`

---

## Phase 7 — Auditable cleaning

**Status: NOT STARTED**

### Objective

Apply only approved transformations and record every outcome.

### Tasks

- [ ] Implement documented whitespace normalization.
- [ ] Convert canonical identifiers/postal codes to strings.
- [ ] Standardize exact enum mappings.
- [ ] Exclude fully-null, constant, duplicate-semantic, and privacy fields from canonical output.
- [ ] Retain source fields in immutable raw storage.
- [ ] Flag geography anomalies without inventing replacements.
- [ ] Retain negative-profit and cancelled records.
- [ ] Generate a cleaning summary and row/field-level audit log.
- [ ] Support previewing what changed before export.

### Exit criteria

- Every canonical change has a rule, reason, and affected count.
- Re-running the same input produces the same output and log.
- No unapproved imputation, deletion, clipping, or deduplication occurs.

Suggested commit: `feat(cleaning): add reproducible audited transformations`

---

## Phase 8 — Canonical model construction

**Status: NOT STARTED**

### Objective

Create validated order, item, product, sanitized-customer, calendar, and quality structures.

### Tasks

- [ ] Build `order_items` using unique item IDs.
- [ ] Validate order-level invariance before building `orders`.
- [ ] Build products keyed by product ID.
- [ ] Build sanitized customers without direct personal fields.
- [ ] Build calendar attributes from order date.
- [ ] Create nullable late status for cancelled shipments.
- [ ] Preserve provenance from canonical records to source rows.
- [ ] Reconcile item aggregates to order and dataset totals.

### Exit criteria

- Reference output contains 180,519 items and 65,752 orders.
- No order total is multiplied by its line count.
- All canonical foreign keys reconcile.
- Privacy-excluded fields are absent from analytical payloads.

Suggested commit: `feat(model): build canonical supply-chain data model`

---

## Phase 9 — KPI engine

**Status: NOT STARTED**

### Objective

Implement one tested source of truth for every V1 KPI.

### Tasks

- [ ] Implement volume and entity-count KPIs.
- [ ] Implement gross value, discounts, net value, profit, margin, and average order value.
- [ ] Implement units, lines per order, units per order, and loss-making-order rate.
- [ ] Implement eligible shipment population.
- [ ] Implement late, early, exact-on-schedule, and combined on-schedule rates.
- [ ] Implement actual/scheduled days and schedule variance.
- [ ] Implement strict cancellation and suspected-fraud rates separately.
- [ ] Support dimensional breakdowns without changing KPI contracts.
- [ ] Return unavailable results for empty eligible populations.
- [ ] Reconcile the complete DataCo controls.

### Exit criteria

- All KPI contract tests pass.
- Complete reference calculations match `AGENTS.md` controls.
- Filtered totals reconcile with their underlying populations.
- No frontend calculation is required to obtain a KPI.

Suggested commit: `feat(analytics): implement tested supply-chain KPI engine`

---

## Phase 10 — Application shell and design system

**Status: NOT STARTED**

### Objective

Create a coherent, accessible shell before adding analytical pages.

### Tasks

- [ ] Configure the approved shadcn/ui components and chart foundation.
- [ ] Build navigation for Upload, Data Quality, Overview, Delivery, Commercial, and Diagnostics.
- [ ] Add global dataset/session context.
- [ ] Add loading, error, empty, and reset states.
- [ ] Define typography, spacing, color, and chart conventions.
- [ ] Add accessible filter and KPI-definition patterns.
- [ ] Verify keyboard navigation and responsive behavior.

### Exit criteria

- Every state is usable without analytics data.
- Navigation and controls meet accessibility checks.
- Components do not contain hardcoded DataCo metrics.

Suggested commit: `feat(ui): add accessible dashboard shell and design system`

---

## Phase 11 — Data-quality experience

**Status: NOT STARTED**

### Objective

Make data trust and cleaning evidence a first-class user workflow.

### Tasks

- [ ] Show source dimensions and detected grain.
- [ ] Show required/optional field coverage.
- [ ] Show issues by severity and treatment.
- [ ] Show before/after counts without implying all issues were fixed.
- [ ] Provide field-level detail and cleaning-log preview.
- [ ] Explain excluded privacy and redundant fields.
- [ ] Allow approved cleaned-data and quality-report export.

### Exit criteria

- A user can explain what changed and what remains flagged.
- Counts reconcile with backend profiling and cleaning results.
- Exports contain no excluded personal fields.

Suggested commit: `feat(data-quality): add transparent quality and cleaning report`

---

## Phase 12 — Executive overview

**Status: NOT STARTED**

### Objective

Answer: what happened across commercial value and shipment performance?

### Tasks

- [ ] Add core KPI cards with definitions and populations.
- [ ] Add order-value/profit trend using order date.
- [ ] Add shipment outcome distribution.
- [ ] Add market or region performance with clear geography semantics.
- [ ] Surface active status and eligibility filters.
- [ ] Add dataset-syntheticity/methodology disclosure where appropriate.

### Exit criteria

- Cards and charts reconcile with the KPI engine.
- No visual calls recorded order value recognized revenue.
- No visual calls shipment adherence customer delivery performance.

Suggested commit: `feat(dashboard): add executive overview`

---

## Phase 13 — Delivery analytics

**Status: NOT STARTED**

### Objective

Answer: where and under which shipping conditions do schedule failures occur?

### Tasks

- [ ] Break down late/on-schedule outcomes by shipping mode.
- [ ] Add actual versus scheduled days and variance.
- [ ] Add region, market, category, and time breakdowns.
- [ ] Keep cancelled and suspected-fraud outcomes separate.
- [ ] Support order-level drilldown without personal fields.
- [ ] Explain eligible-population exclusions.

### Exit criteria

- All delivery rates use distinct eligible orders.
- No cancelled shipment is classified as non-late.
- Drilldown totals reconcile with summaries.

Suggested commit: `feat(dashboard): add shipment performance analytics`

---

## Phase 14 — Commercial analytics

**Status: NOT STARTED**

### Objective

Answer: which products and geographies are associated with value, profit, discount, and loss?

### Tasks

- [ ] Add net order value, profit, margin, discount, and units analysis.
- [ ] Add department, category, product, market, region, and segment breakdowns.
- [ ] Add loss-making order and item analysis.
- [ ] Show order-status scope explicitly.
- [ ] Use weighted rates and reconciled totals.
- [ ] Avoid causal claims about delivery and sales/profit.

### Exit criteria

- Aggregated amounts reconcile to item-level facts.
- Margin and discount rates are amount-weighted.
- All labels preserve the dataset's commercial limitations.

Suggested commit: `feat(dashboard): add commercial and profitability analytics`

---

## Phase 15 — Diagnostics and interactions

**Status: NOT STARTED**

### Objective

Let users move from a poor KPI to the combinations and records associated with it.

### Tasks

- [ ] Add shared date, market, region, category, shipping-mode, status, and outcome filters.
- [ ] Define filter interaction and reset behavior.
- [ ] Add multi-dimensional diagnostic ranking.
- [ ] Add safe order-level drilldown.
- [ ] Add empty-result and zero-eligible-population behavior.
- [ ] Preserve selected filters across relevant views.

### Exit criteria

- Filtered headline values reconcile with filtered detail.
- Diagnostics describe association, not causation.
- No interaction exposes excluded customer fields.

Suggested commit: `feat(diagnostics): add cross-filtering and operational drilldown`

---

## Phase 16 — Export and reproducibility

**Status: NOT STARTED**

### Objective

Allow users to retain approved outputs and reproduce processing evidence.

### Tasks

- [ ] Export sanitized cleaned items.
- [ ] Export canonical orders.
- [ ] Export data-quality summary and cleaning log.
- [ ] Include schema/version and processing metadata.
- [ ] Apply spreadsheet-injection protections to CSV exports.
- [ ] Confirm raw personal fields never appear.
- [ ] Document how another user obtains the public reference dataset.

### Exit criteria

- Exported counts and totals reconcile with the active dataset and filters.
- Exports reopen correctly in common CSV tools.
- No raw dataset or uploaded artifact enters Git.

Suggested commit: `feat(export): add sanitized data and quality-report exports`

---

## Phase 17 — Hardening, performance, and accessibility

**Status: NOT STARTED**

### Objective

Make V1 reliable on the full reference file and safe against malformed inputs.

### Tasks

- [ ] Benchmark upload, parsing, profiling, canonicalization, and KPI latency.
- [ ] Measure peak memory on the 95.9 MB reference CSV.
- [ ] Optimize only measured bottlenecks.
- [ ] Test concurrent or repeated local sessions as supported.
- [ ] Test cleanup after success, failure, reset, and process restart.
- [ ] Run dependency and input-security review.
- [ ] Run keyboard, contrast, focus, labeling, and screen-reader checks.
- [ ] Run complete unit, integration, reference, and frontend suites.

### Exit criteria

- Resource limits and expected processing times are documented.
- No critical security or accessibility finding remains.
- Full reference processing completes within the agreed local budget.
- All checks pass from a clean checkout.

Suggested commit: `test: harden full-file processing and accessibility`

---

## Phase 18 — Documentation and portfolio release

**Status: NOT STARTED**

### Objective

Publish a reproducible project whose claims can be defended in an interview.

### Tasks

- [ ] Complete README with problem, scope, screenshots, architecture, setup, tests, and limitations.
- [ ] Document the dataset source and download steps without redistributing it.
- [ ] Publish canonical schema and KPI definitions.
- [ ] Publish data-quality methodology and reference controls.
- [ ] Add architecture and data-flow diagrams.
- [ ] Add representative screenshots with no personal data.
- [ ] Document synthetic-data limitations and prohibited interpretations.
- [ ] Prepare concise CV, GitHub, and interview descriptions.
- [ ] Review Git history and release notes.

### Exit criteria

- A new user can reproduce the demo from a clean clone.
- Portfolio claims match implemented behavior.
- Screenshots and documentation use defensible terminology.
- The repository contains no dataset, secret, upload, cache, or personal output.

Suggested commit: `docs: prepare reproducible portfolio release`

---

## V2 backlog — not authorized for V1 implementation

- [ ] User-driven column mapping for non-DataCo schemas.
- [ ] Saved reusable schema mappings.
- [ ] Additional public reference datasets.
- [ ] Browser-only processing investigation.
- [ ] Optional database persistence.
- [ ] Authentication and multi-user isolation.
- [ ] Forecasting with suitability checks.
- [ ] Leakage-safe late-shipment prediction.
- [ ] Web-access-log analytics as a separate module.
- [ ] Power BI or external BI export.
- [ ] Deployment, only after privacy and storage decisions are approved.

Moving an item from this backlog requires an accepted decision, revised acceptance criteria, and explicit user approval.

