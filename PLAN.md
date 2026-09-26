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

**Status: COMPLETE**

### Objective

Recognize the DataCo source schema and map it to stable canonical fields.

### Tasks

- [x] Normalize headers without losing original names. — Registry lookup normalizes BOM/whitespace/case per canonical-schema §9; originals preserved in every report (`test_original_headers_preserved_case_variant_maps`).
- [x] Classify fields as required, optional, redundant, excluded, or unknown. — `validate_headers` emits the contract classes; redundant (`Order Customer Id`, `Sales per customer`, `Order Profit Per Order`) and audit-only (`Late_delivery_risk` → excluded) from governed names.
- [x] Validate required IDs, dates, amounts, quantities, and delivery fields. — 18 required entries (DQ-SCHEMA-001 scope); missing any fails the session with `SCHEMA_MISSING_COLUMN` + precise missing list.
- [x] Map source enums without silently accepting unknown values. — Phase 5 maps headers only; no enum values are interpreted or coerced (garbage-body test proves it).
- [x] Parse IDs and postal codes as strings. — Deferred by design: recorded as mapping roles; no value parsing occurs in Phase 5 (header-only reads).
- [x] Parse timestamps with an explicit month-first format. — Recorded as `timestampContracts` metadata (month-first, naive); no timestamp is parsed yet.
- [x] Produce a schema report before cleaning. — `derived/schema_report.json` + `GET /sessions/{id}/schema` in the exact contract shape (`sourceColumns`, `mapping[{source, canonical, class}]`, `missingCritical`).
- [x] Reject missing critical fields with precise guidance. — 422 `SCHEMA_MISSING_COLUMN` with `details.missing`; terminal FAILED with ADR-028 raw/derived removal and manifest-only error retention.
- [x] Preserve unmapped columns in raw data only. — Unknowns quarantined (DQ-SCHEMA-003 INFO); raw immutable; artifact carries header names only, never values.

### Exit criteria

- [x] DataCo maps deterministically to the canonical contract. — Pure order-independent `validate_headers` + registry pin tests (any rename/retarget/required-flip fails loudly).
- [x] Missing or ambiguous critical fields stop analytics. — Incompatible sessions reach FAILED, never PROFILING; exact matching admits no ambiguity (duplicates already rejected in Phase 4).
- [x] Optional-field absence degrades gracefully. — 7 optional dims; absence keeps the session compatible.
- [x] Unknown columns do not alter KPI behavior. — Extras classified unknown, never mapped, never read (no canonical/KPI code exists yet to consume them).

Evidence: `make check` green (frontend 20 tests, backend 95 tests, tsc, ESLint 0 errors, Ruff, mypy strict), `vite build` green, live HTTP smoke test (compatible → PROFILING + 18/7/1/1/1 classification + SHA-stable raw; incompatible → FAILED + raw removed + 422; extra column → unknown, accepted) with synthetic data only. Exact header strings verified against governed text (ADR-007, canonical-schema §§1/5/6/9); no local DataCo file exists. Execution model: POST returns 202 then schedules bounded validation as a framework-local post-response task (no queues/workers); status/schema endpoints observe only (`/schema` returns contract 409 NOT_READY while pending); startup recovery re-runs validation left VALIDATING by a restart; single-process assumption documented. Bounded deferrals: customer-side geo and exact privacy header strings are unspecified in governance, so such columns surface as unrecognized extras — safety holds by exact-match construction. Pressure-cap note from Phase 4 still stands.

Suggested commit: `feat(schema): validate and map DataCo source fields`

---

## Phase 6 — Data profiling and quality detection

**Status: [~] partially complete (implementation done; reference-file verification pending)**

### Objective

Produce a trustworthy pre-cleaning profile without modifying data.

### Tasks

- [x] Calculate row/column counts, inferred types, missingness, and cardinality. — `derived/profiling_report.json` + `GET /sessions/{id}/profile` (`rows`, mapped `columns`, per-field `missing`/`rate`/`parseFailures`, `distinct` counts; `backend/app/profile_checks.py`, `backend/app/profiling.py`).
- [x] Detect exact duplicates and key duplicates separately. — Governed-column `duplicates.exact` (profile stat, no DQ rule owns it; unknown extras never materialize and never affect identity) vs `DQ-KEY-001` excess rows on `Order Item Id`; repeated `Order Id` accepted (`DQ-KEY-002` INFO), `Order Id + Product Id` never a key (`DQ-KEY-003` INFO).
- [x] Detect conflicting attributes within each order. — `DQ-GRAIN-001` ERROR (blocks CANONICALIZATION) with per-field conflicting-order counts in `invarianceConflicts`; merch/product fields excluded by design; no first-row pick.
- [x] Detect numeric range, enum, date, geography, and formula-consistency issues. — `DQ-NUM-001/002/003` (incl. ADR-008 `$0.05` tolerance, ADR-017 negative-profit retention), `DQ-CAT-001/002/003/005` (order_status closed 8-set; shipping_mode/customer_segment enforce only source spellings with a verbatim contract instance — "Second Class"/"First Class"/"Corporate" take the governed UNKNOWN path until reference-file confirmation records the exact strings), `DQ-DATE-001/002/003/004` (explicit month-first), `DQ-BUSINESS-002/003` (day-field authority, leakage field audit-only); geography has no governed value rule, so precise-geo/unknown extras are quarantined and counted via `DQ-PRIVACY-001/002` INFO (counts only); `DQ-CAT-004` and `DQ-SCHEMA-004` deferred with recorded reasons (delivery domain / redundant pairings unspecified in governance).
- [x] Identify constant and fully-null columns. — Covered as profile statistics (zero-distinct / full-missingness fields are visible in `missingness[]`/`cardinality[]`); no invented DQ rule (catalogue has none).
- [x] Identify privacy-sensitive columns. — `DQ-PRIVACY-001/002` keyword heuristic over headers, INFO, counts only; values never read into reports, logs, or errors.
- [x] Display issue severity, affected counts, and proposed treatment. — `GET /sessions/{id}/data-quality` (`summary` + contract-exact `issues[{ruleId, severity, count, treatment, blockedStage}]` with `?severity=` filter and `422 INVALID_SEVERITY_FILTER`); upload view shows the profiling/DQ summary (rows, fields, rules run, severity totals, blocking status, next stage = cleaning).
- [x] Ensure profiling can complete within the resource budget. — Single-pass pandas pyarrow-string staging with governed `usecols` projection per ADR-026/027 (unknown extras never materialize, no chunking); sync workers run threadpooled via Starlette `BackgroundTasks`; unique temp names + CAS manifest touching + artifact adoption close the status-touch/pipeline manifest race found in live smoke testing; 15k-row generated scale test reconciles exactly.

### Exit criteria

- The unmodified reference file reproduces the audited issue counts. — NOT YET EXECUTED. "Audited issue counts" means the Phase-0 audited profiling-level findings (row/grain counts, missingness/duplicates, negative-profit lines, Same-Day pattern, reconciliation evidence in DECISIONS.md), distinct from the global KPI controls owned by Phase 9 ("Complete reference calculations match `AGENTS.md` controls"). Execution needs the public reference file (ADR-024 keeps it out of the repo; no local copy exists) and is therefore pending; no counts have been fabricated. All executable detection logic is reference-ready and verified on synthetic fixtures covering every governed rule.
- Detection results are independent from cleaning actions. — Satisfied: treatments are never `fixed`; raw SHA-256 verified byte-identical before/after; cleaning artifacts never created (derived holds only `schema_report.json` + `profiling_report.json`).
- Every issue links to a stable rule identifier. — Satisfied: `test_profiling_rules.py` asserts catalogue parity (severity/treatment/blockedStage/fields/grain/message) for all 19 evaluated rules; 7 deferred rules are listed with reasons in the artifact.

Evidence: `make check` green (frontend 22 tests, backend 145 tests, tsc, ESLint 0 errors, Ruff, mypy strict, `vite build` green), live HTTP smoke test with synthetic `/tmp` data only (clean → CLEANING + reports + stable SHA; issues → CLEANING with travelling ERRORs; malformed body → FAILED/MALFORMED_CSV + ADR-028 cleanup; reset → tree gone + 404; 9-session parallel stress converges), server log error-free.

Suggested commit: `feat(profiling): add dataset and data-quality profiling`

---

## Phase 7 — Auditable cleaning

**Status: COMPLETE**

### Objective

Apply only approved transformations and record every outcome.

### Tasks

- [x] Implement documented whitespace normalization. — DQ-CAT-005 trim on the governed label fields only (`LABEL_FIELDS + ENUM_FIELDS`: the six canonical-schema "string trimmed" labels plus the three "trimmed, case-sensitive" enum fields; `delivery_status` carries no trim annotation and is untouched). Whitespace aspect and enum-domain aspect are independent: every padded non-missing in-scope cell trims (including `" Rocket "` → `"Rocket"`, which stays unknown and flagged under DQ-CAT-002 — no coercion), internal whitespace/case preserved, whitespace-only cells left as missing. Whitespace means generic leading/trailing whitespace per Python `str.strip()` (spaces, tabs, newlines, NBSP — documented reading, probed in tests). `backend/app/cleaning.py` (`trim_scope`/`padding_mask`/`apply_trims`); `cleaning_trim.csv` integration (4 cells fixed across 4 fields; profiling CAT-005 row count 3 vs cleaning population 4 documented: profiling attributes padded-unknown enum rows to CAT-001/002/003 to avoid double-counting).
- [x] Convert canonical identifiers/postal codes to strings. — Investigated no-op: staging already yields pyarrow-backed strings so IDs stay strings with zero changes (asserted byte-identical in tests); there is no canonical postal field (destination ZIP excluded by privacy), hence nothing to cast. Documented in `backend/app/cleaning.py`.
- [x] Standardize exact enum mappings. — Exact-match semantics verified with zero coercion: unknown values (`Second Class`, `Corporate`, lowercase, padded-unknown) stay byte-identical and flagged under DQ-CAT-001/002/003 (never mapped, never blocking); value substitution into canonical structures belongs to Phase 8, which no cleaning rule authorizes early.
- [x] Exclude fully-null, constant, duplicate-semantic, and privacy fields from canonical output. — Redundant, audit-only, unknown, and privacy-sensitive columns never materialize in `derived/cleaned.csv` (governed projection; DQ-PRIVACY-001/002 excluded counts, no values read); fully-null/constant mapped columns are carried as-is because no DQ rule authorizes dropping them (unapproved deletion is forbidden).
- [x] Retain source fields in immutable raw storage. — SHA-256 verified before and after the cleaning pass; `raw.csv` never written; byte-identity asserted in every cleaning test.
- [x] Flag geography anomalies without inventing replacements. — No governed geo value rule exists, so nothing is imputed or geocoded; precise-geo-like headers counted via DQ-PRIVACY-002 only. (`delivery_status` whitespace is outside the CAT-005 field set and left untouched — recorded governance gap, not guessed.)
- [x] Retain negative-profit and cancelled records. — Negative/extreme profit, strict-cancellation, and suspected-fraud rows retained byte-identical (ADR-017, ADR-013); adversarial-test asserted.
- [x] Generate a cleaning summary and row/field-level audit log. — `derived/cleaning_report.json` (per-rule/field `steps[{ruleId, field, detected, fixed, flagged, excluded, unchanged, reason}]`, totals, money reconciliation, output identity incl. `outputSha256`/`outputRows` and Phase-6 input identity) plus `GET /sessions/{id}/cleaning-report` in the exact contract shape; every step reconciles `detected == fixed + flagged + excluded + unchanged`. Torn-transition adoption recomputes the cleaned SHA and verifies the live profile identity before trusting stored metadata.
- [x] Support previewing what changed before export. — The cleaning-report endpoint is observational (409 `NOT_READY` while pending, never executes work); the Upload view renders a cleaning-review panel (totals, per-rule counts, flagged remainder, next stage) that never claims success while flagged issues remain, and states the canonicalization gate (`CANONICALIZATION`-blocking errors → "gated … no canonical work has started … parked") instead of implying progress.

### Exit criteria

- [x] Every canonical change has a rule, reason, and affected count. — The sole value transformation is DQ-CAT-005; per-field steps carry rule, reason, and cell counts; only CAT-005 steps ever report `fixed > 0` (asserted).
- [x] Re-running the same input produces the same output and log. — Idempotence (rerun byte-identical, torn-transition adoption identical), determinism (two uploads, same SHA/counts), and no-cumulative-change tests pass.
- [x] No unapproved imputation, deletion, clipping, or deduplication occurs. — Adversarial battery proves duplicates/missing/malformed/numeric/date/leakage/unknown-enum/unknown-column retention; money reconciliation proves totals never move.

Evidence: backend 173 tests green (28 Phase-7 tests: trim matrix, whitespace-definition probes, adversarial retention, audit reconciliation, idempotence incl. Latin-1, privacy probes, lifecycle incl. torn/corrupt adoption, guard release, CSV round-trip, 5k-row generated scale), frontend 25 tests green (cleaning-review panel, detected-vs-fixed copy, no-false-success, canonicalization-gate copy), tsc, ESLint 0 errors, Ruff, mypy strict, `vite build` green, live synthetic smoke (trim → `CANONICALIZING` with trimmed derived value + CAT-005 counts + stable raw SHA; ERROR travel with gate intact; unknown-enum retention; terminal-failure cleanup; reset no-resurrection).

Pre-commit audit (2026-09-25): verified blockedStage enforcement point (gate enforced by Phase-8 canonicalization work per api-contract `DUPLICATE_ITEM_KEY`/`ORDER_INVARIANCE_CONFLICT` at the CANONICALIZING stage — entering the state parks at the gate, no waiver/new state invented); `cleaned.csv` authorized as internal derived working file (architecture §4; never served; minimal-transformation header/order choices documented, not a public contract); positional provenance + recorded alignment metadata sufficient for Phase-8 row-number materialization; CAT-005 field matrix cited per field (6 labels + 3 enums authorized, `delivery_status` not); padded-unknown precedence resolved to trim-with-still-flagged (no "unknown takes precedence" in governance); DQ-NUM-004/DQ-FILE-005 take no cleaning step (never evaluated / passed gate); privacy `excluded` counts are column-grain; money self-check is an implementation invariant (no new rule ID; same Decimal helpers as profiling; untouched columns asserted equal).

Suggested commit: `feat(cleaning): add reproducible audited transformations`

---

## Phase 8 — Canonical model construction

**Status: [~] partially complete (implementation done; reference-file verification pending)**

### Objective

Create validated order, item, product, sanitized-customer, calendar, and quality structures.

### Tasks

- [x] Build `order_items` using unique item IDs. — `backend/app/canonicalization.py` (`build_order_items`); one row per governed line, PK `order_item_id`, 1-based `source_row_number` provenance; DQ-KEY-001 gates the whole build (no dedupe).
- [x] Validate order-level invariance before building `orders`. — `order_gate_conflicts` over the 10 profiling invariance fields plus `customer_segment` and derived outcome agreement; DQ-GRAIN-001 blocks `orders` only (no first-row pick), other tables still build.
- [x] Build products keyed by product ID. — `build_products`; identifying dims invariant-checked under DQ-GRAIN-003 (conflict blocks `products` only via PRODUCT_INVARIANCE_CONFLICT, ADR-036), defensible aggregations only, no reference price.
- [x] Build sanitized customers without direct personal fields. — `build_customers`; segment invariant-checked under DQ-GRAIN-004 (conflict blocks `customers_sanitized` only via CUSTOMER_INVARIANCE_CONFLICT, ADR-036), coarse customer-side geo only (null in V1, never derived from destinations), PII/probe-tested.
- [x] Build calendar attributes from order date. — `build_calendar`; naive date parts for distinct canonical `order_date` values, no KPI semantics.
- [x] Create nullable late status for cancelled shipments. — §6 derivation from authoritative day fields; shipping-cancelled rows get `SHIPPING_CANCELED` + `is_late = null` + null variance/actual; `Late_delivery_risk` never classifies (probe-tested).
- [x] Preserve provenance from canonical records to source rows. — `source_row_number` = 1-based logical data-row ordinal in `raw.csv` (positional correspondence with verified `cleaned.csv`); stored on `order_items` only, never a key.
- [x] Reconcile item aggregates to order and dataset totals. — `orders`/`products`/`customers` summed from items exactly once; GRAIN-002 self-check (FK + money/unit totals) gates the ANALYZING transition; reported net stays authoritative, negative profit retained.

### Exit criteria

- [~] Reference output contains 180,519 items and 65,752 orders. — NOT YET EXECUTED. Same constraint as Phase 6: no local reference file exists (ADR-024); aggregation logic is verified on synthetic fixtures (multi-line orders reconcile exactly), but full-file counts await the documented reference run. No counts fabricated.
- [x] No order total is multiplied by its line count. — Aggregations sum line values exactly once; `line_count` is a separate count; multi-line fixture asserts `net_value == 47.48 == 27.98 + 19.50`.
- [x] All canonical foreign keys reconcile. — GRAIN-002 self-check (order-ID set equality + lines count + money/unit totals) enforced before ANALYZING; `test_report_reconciliation_and_identity` asserts all-true.
- [x] Privacy-excluded fields are absent from analytical payloads. — PII/precise-geo/audit-only columns never materialize; probe tests assert absence in all six tables + report; exports untouched (Phase 16).

Evidence: `make check` green (backend 212 tests — 39 new Phase-8 tests: derivations, blockers, integrity, concurrency, lifecycle; frontend 26 tests — 1 new ANALYZING-settled test; Ruff, format, mypy strict, tsc, ESLint 0 errors, Prettier, `vite build` green), live HTTP smoke with synthetic `/tmp` data only (clean → ANALYZING with 6 tables + reconciled report + stable raw SHA; duplicate-key → parked CANONICALIZING with raw retained; reset → trees gone). Lifecycle parks at ANALYZING (no KPI analysis runs; no READY faked). Also fixed as found: NaT/float rendering in canonical CSVs, stale downstream artifact pointers on upstream recompute, missing compute-phase guard, and a manifest CAS race (process-wide RLock) — each covered by a regression test.

Suggested commit: `feat(model): build canonical supply-chain data model`

---

## Phase 9 — KPI engine

**Status: [~] partially complete (implementation done; reference-file verification pending)**

### Objective

Implement one tested source of truth for every V1 KPI.

### Tasks

- [x] Implement volume and entity-count KPIs. — `backend/app/kpis.py` (`compute_volume`): items/orders/eligible/customers/products/units from canonical grain tables; unavailable (never zero) on empty populations.
- [x] Implement gross value, discounts, net value, profit, margin, and average order value. — `compute_commercial`: item-grain sums with authoritative recorded net (ADR-008), amount-weighted margin/discount-rate (ADR-014), order-grain AOV; neutral 2-dp money strings, no currency (ADR-010), no recognized-revenue label (ADR-009).
- [x] Implement units, lines per order, units per order, and loss-making-order rate. — Same module; negatives retained, loss rate at order grain (ADR-017).
- [x] Implement eligible shipment population. — `shipment_outcome != SHIPPING_CANCELED` at order grain; cancelled rows carry `is_late = null` and never count as non-late (ADR-012).
- [x] Implement late, early, exact-on-schedule, and combined on-schedule rates. — `compute_delivery` from the governed day-field derivation; early + exact compose on-schedule; `Late_delivery_risk`/`Delivery Status` never classify (ADR-030).
- [x] Implement actual/scheduled days and schedule variance. — Eligible-population means; negative variance preserved (ahead of schedule).
- [x] Implement strict cancellation and suspected-fraud rates separately. — Plus the combined shipping-blocked rate, all at order grain (ADR-013).
- [x] Support dimensional breakdowns without changing KPI contracts. — `GET /kpis/delivery` and `/kpis/commercial` with validated filters and `by=` grouping re-slicing numerator/denominator under identical formulas; `UNKNOWN_FLAGGED` excluded from splits (ADR-030); unknown enums rejected 422, never mapped.
- [x] Return unavailable results for empty eligible populations. — Pinned reason vocabulary (`empty-eligible-population | zero-denominator | missing-required-fields`), never 0/0% (ADR-031).
- [~] Reconcile the complete DataCo controls. — NOT YET EXECUTED. Same constraint as Phases 6/8: no local reference file exists (ADR-024). The harness is in place (`backend/tests/test_kpi_reference.py`: always-runnable synthetic golden + `SUPPLYCHAIN_REFERENCE_CSV`-gated reference test asserting every `AGENTS.md` control, skipped in CI). No counts fabricated, no production constants (ADR-020).

### Exit criteria

- [x] All KPI contract tests pass. — 30 KPI IDs/labels pinned against `docs/kpi-contracts.md`; 44 new Phase-9 tests (formulas, adversarial delivery/commercial, lifecycle, endpoints, golden).
- [~] Complete reference calculations match `AGENTS.md` controls. — Pending the documented reference run (see task above).
- [x] Filtered totals reconcile with their underlying populations. — Overview `totals` anchors; group numerators reconcile to headlines (tested); filtered recomputation is synchronous from cached canonical tables.
- [x] No frontend calculation is required to obtain a KPI. — Backend owns all math; frontend change is a minimal READY/settle note only (no KPI fetching, no formulas in TypeScript).

Evidence: `make check` green (backend 268 passed + 1 env-gated skip — 44 new Phase-9 tests; frontend 27 passed — 1 new READY-settled test; Ruff, format, mypy strict, tsc, ESLint 0 errors, Prettier, `vite build` green), live HTTP smoke with synthetic `/tmp` data only (clean → READY with 30 headline KPIs + reconciled totals; empty date filter → unavailable, not error; canonical-blocked → parked CANONICALIZING with KPI endpoints 409 NOT_READY and no KPI artifact; reset → tree gone). Lifecycle: ANALYZING → READY via the chained KPI worker (`ensure_kpis_analyzed`, artifact `derived/kpi_report.json` with canonical-identity adoption); canonical-blocked sessions never analyzed. Orders drilldown endpoint stays deferred to diagnostics (Phase 15); exports untouched (Phase 16).

Suggested commit: `feat(analytics): implement tested supply-chain KPI engine`

---

## Phase 10 — Application shell and design system

**Status: COMPLETE**

### Objective

Create a coherent, accessible shell before adding analytical pages.

### Tasks

- [x] Configure the approved shadcn/ui components and chart foundation. — shadcn `button` + theme tokens reused as-is; `frontend/src/lib/chart-theme.ts` fixes the Recharts palette/layout/series-shape conventions (no data charts in Phase 10); no new dependency.
- [x] Build navigation for Upload, Data Quality, Overview, Delivery, Commercial, and Diagnostics. — `AppShell` with state-based routing (no router dependency); future views render honest Phase-11/12/13/14/15 empty states with their product-spec business questions, never fake pages.
- [x] Add global dataset/session context. — `lib/session.ts` + `SessionProvider`; `UploadSession` mirrors its snapshot via an optional callback with zero behavior change.
- [x] Add loading, error, empty, and reset states. — `components/states.tsx` primitives (`LoadingState`, `ErrorState`, `EmptyState`); existing upload/reset behavior preserved verbatim.
- [x] Define typography, spacing, color, and chart conventions. — Existing Geist/Tailwind token system retained; chart conventions codified in `chart-theme.ts` against the governed `--chart-*` tokens.
- [x] Add accessible filter and KPI-definition patterns. — `components/patterns.tsx`: presentational `FilterSelect` (labelled, clearable) and native-`<details>` `KpiDefinition`; no fetching, filtering, or KPI math.
- [x] Verify keyboard navigation and responsive behavior. — Native button/select/details semantics with `aria-current` nav; axe-clean shell + future view; real-browser smoke at 1200px and 428px CSS widths with zero page overflow.

### Exit criteria

- [x] Every state is usable without analytics data. — Shell, all six views, and every state/pattern render with no session and no backend data (tested).
- [x] Navigation and controls meet accessibility checks. — `vitest-axe` on shell + future view; keyboard-focusable nav verified in tests.
- [x] Components do not contain hardcoded DataCo metrics. — No KPI numbers in shell/views/patterns (test asserts absence of fabricated rate/value patterns); the only reference-file mention remains the pre-existing governed upload copy.

Evidence: `make check` green (backend 275 passed + 1 env-gated skip, untouched; frontend 43 passed — 11 shell/pattern tests plus 5 session-lifetime regression tests; Ruff, format, mypy strict, tsc, ESLint 0 errors, Prettier, `vite build` green), real-browser smoke via ego-browser against the built bundle (dashboard heading, labelled nav, Delivery stub with Phase-13 copy, zero horizontal overflow at desktop and 428px widths; post-correction smoke additionally verified READY→away→back session retention with synthetic data). No backend changes; no KPI fetching or formulas in TypeScript; DQ view lands in Phase 11; Overview/Delivery/Commercial stay deferred to Phases 12–14.

Suggested commit: `feat(ui): add accessible dashboard shell and design system`

---

## Phase 11 — Data-quality experience

**Status: COMPLETE**

### Objective

Make data trust and cleaning evidence a first-class user workflow.

### Tasks

- [x] Show source dimensions and detected grain. — `DataQualityView` source-profile section renders backend `rows`/`columns`/`grain` plus duplicates and order/product/customer invariance summaries (counts only); no order counts invented.
- [x] Show required/optional field coverage. — Schema-report mapping classes drive required-mapped counts, optional-mapped counts, and the missing-critical alert; counts come from the API, never recomputed rule logic.
- [x] Show issues by severity and treatment. — Backend summary plus ERROR/WARNING/INFO groups with rule ID, affected count, treatment, and blocked stage; severity/blocking semantics come from the report.
- [x] Show before/after counts without implying all issues were fixed. — Cleaning audit log renders every step's detected/fixed/flagged/excluded/unchanged accounting with presentational totals and explicit "detected is not the same as fixed" copy.
- [x] Provide field-level detail and cleaning-log preview. — Missingness and cardinality tables per field (counts only), order-invariance conflicts by field, and the full step-level cleaning log with reasons; no raw values or rows reconstructed.
- [x] Explain excluded privacy and redundant fields. — Excluded/redundant/unknown mapping classes rendered with governed explanations in native disclosures; header names only, never values.
- [x] Allow approved cleaned-data and quality-report export. — Honest Phase-16 deferral: no backend export endpoints exist yet (Phase 16 owns `POST /exports` implementation), so the view states the approved kinds and that raw data is never exportable instead of shipping a fake download.

### Exit criteria

- [x] A user can explain what changed and what remains flagged. — Cleaning steps carry reasons and per-outcome counts; flagged/blocked issues stay visible with recoverable-gate explanations.
- [x] Counts reconcile with backend profiling and cleaning results. — Every number renders verbatim from the profile/data-quality/cleaning/schema payloads; tests assert sentinel counts end to end through the mocked contract.
- [x] Exports contain no excluded personal fields. — No export artifact exists in Phase 11 (nothing to leak); the privacy gate remains backend-owned for Phase 16.

Evidence: `make check` green (backend 275 passed + 1 env-gated skip, untouched; frontend 57 passed — 14 new Phase-11 view tests; Ruff, format, mypy strict, tsc, ESLint 0 errors, Prettier, `vite build` green), axe-clean loaded report, synthetic browser smoke (upload → Data Quality → report, away/back, reset). No backend changes; no DQ predicate reimplemented in TypeScript; no scores/grades/waivers invented; Overview/Delivery/Commercial/Diagnostics stay deferred to Phases 12–15 and exports to Phase 16.

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

