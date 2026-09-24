# V1 Technical Architecture

Binding: ADR-022 (React/shadcn/Recharts), ADR-023 (Python owns logic), ADR-004 (local-only), ADR-024 (nothing raw in Git).

## 1. Selected stack and rationale

Each dependency is justified against an actual V1 requirement. Nothing is chosen for résumé value.

| Layer | Choice | Why this, for V1 |
|---|---|---|
| UI framework | Vite + React single-page app | V1 is a local single-user tool behind a Python API server. SSR (Next.js) would add a second server, hydration complexity, and zero SEO benefit. Vite produces a static build that the backend can serve locally. |
| Language (frontend) | TypeScript with `strict: true` | Typed API envelopes include nullable adherence flags and unavailable-KPI nulls; strict mode catches those at compile time. Required so the frontend cannot silently misrender them. |
| Components | shadcn/ui + Tailwind + Radix primitives, source-controlled | Binding per ADR-022. Needed for accessible cards, filters, tables, dialogs. No runtime theme dependency. |
| Charts | Recharts via shadcn chart patterns only | Binding per ADR-022. Covers trend, distribution, and breakdown bars required by PLAN Phases 12–14. A second chart library needs a demonstrated gap; none exists. |
| Frontend package manager | npm + `package-lock.json` | Ships with Node, deterministic clean-clone installs, no extra toolchain. pnpm/yarn buy nothing without a monorepo. Node LTS pinned in README (Phase 3). |
| Language (backend) | Python 3.12.x (minimum 3.11) | Stable typing (`X \| None`), broad wheel coverage for pandas/pyarrow/FastAPI. 3.13 is needlessly new for a portfolio V1; below 3.11 loses modern typing ergonomics. Exact patch pinned in `.python-version` (Phase 3). |
| Web framework | FastAPI + Pydantic v2 + Uvicorn | V1 needs typed success/error envelopes, OpenAPI review of contracts without UI code, and a test client for contract tests. Flask lacks first-class typed schemas; Django ships ORM/admin/auth that V1 explicitly excludes. Route handlers validate I/O and call domain services; no KPI logic in handlers. |
| Python dependency manager | uv + `uv.lock`, pip-compatible fallback documented | Reproducible installs from a clean clone with a fast resolver. Fallback (`pip install -r requirements.lock`-equivalent) covers environments without uv. Poetry rejected as heavier with no V1 need. |
| Schema/validation at boundaries | Pydantic v2 for API payloads + explicit hand-written dataframe checks | Pydantic already covers session/filter/export shapes. Grain, invariance, tolerance, and enum-mapping checks need custom domain logic a generic validator would obscure. Pandera / Great Expectations rejected: heavy deps, no V1 requirement. |
| Backend tests | pytest + FastAPI TestClient/httpx + coverage | Covers parsing, mapping, cleaning, KPI unit tests, upload→analytics integration, golden reference, and adversarial fixtures. No further framework needed. |
| Frontend tests | Vitest + React Testing Library + axe (vitest-axe) | V1 frontend tests are loading/error/empty/filter/accessibility behavior. Playwright E2E is deferred until Phase 17 proves a need. |
| Lint/format/type | Backend: Ruff (lint+format) + mypy on domain/kpi/schemas. Frontend: ESLint + Prettier + `tsc --noEmit` | Ruff replaces Black/isort/flake8 with one dep. mypy guards money/date/nullability. One command per side plus one root `check` script (Phase 3). |

## 2. Dataframe engine: pandas vs Polars (decision)

Evidence: reference CSV ≈ 95.9 MB, 180,519 rows × 53 columns. Naive in-memory footprint is roughly 3–5× CSV size (~300–500 MB); with pyarrow-backed string dtypes roughly 150–250 MB. This fits a typical 8 GB laptop with one active session. There is no measured performance emergency.

| Criterion | pandas 2.x + pyarrow | Polars |
|---|---|---|
| Correctness / auditability | Mature nullable `string[pyarrow]`, well-understood groupby/sort semantics, large test corpus for golden tests | Fast and strict, but higher API churn and thinner `Decimal` support/examples |
| Decimal-safe money (ADR-008) | Documented path: stage as string → `Decimal` for canonical totals; floats only for tolerance validation | Same care required, fewer reference examples for gross−discount tolerance validation |
| Determinism | Deterministic with explicit sorts; well understood | Deterministic, but lazy-plan subtleties add review burden |
| Speed/memory at 180k rows | Comfortable; single-pass full read in seconds to tens of seconds | Faster, but speed is not the V1 bottleneck (comprehension UX is) |
| Risk | Low; engine isolated behind domain functions per ADR-023 | Medium; learning + review cost with no measured need |

**Decision: pandas 2.x with pyarrow-backed dtypes for V1.** Polars is explicitly deferred. It may be reconsidered only with Phase 17 measurements showing the pandas budget is exceeded, via a new ADR. DuckDB as primary engine is rejected for the same reason: a query engine adds a dependency when pandas already covers single-file transforms.

## 3. Resource budget

- **Hard limit: 250 MB per upload.** This is the proposed V1 enforced cap (~2.6× the reference file: headroom for similar DataCo-shaped files while bounding disk, memory, and time). Enforced pre-parse by `Content-Length` plus on-disk byte count. Over-limit uploads fail fast with an actionable error and leave no orphaned data.
- **Working budget (validation target, NOT a product claim):** ~500k order-item rows on an 8 GB laptop, and reference-file end-to-end processing targeted at a few minutes. These numbers are Phase 17 benchmarks to run, not guarantees to advertise. Until measured, docs and UI must call them targets. No 1M+ claim in V1.
- **Memory strategy:** single-session in-memory pandas with dtype discipline (`string[pyarrow]` for IDs/postal codes, naive `datetime64[ns]`, nullable `Float64` during validation, `Decimal` for canonical money totals). Avoid duplicate full-copy chains; release intermediate frames. No database in V1. Concurrent full-file sessions are best-effort, not load-tested; disclose this.
- **Parsing strategy:** header-first (sniff ≤1 MB for header/encoding/dialect, validate column count and duplicate headers), then one full read with explicit `dtype=str` staging plus controlled casts. **Streaming/chunking is not required for V1** at this scale; it would complicate invariance checks and provenance with no measured benefit. A chunked fallback is reconsidered only on Phase 17 OOM evidence.
- **Timeout/UX expectations:** transfers on localhost complete quickly; any stage expected to exceed ~10 s runs asynchronously behind the session-status endpoint (see `docs/api-contract.md`) so the UI never hangs. Documented timings are published only after Phase 17 measurement.
- **Input safeguards:** never trust filename/MIME alone (extension + MIME sniff + actual parse check); reject empty/header-only files; reject duplicate headers; cap header count (e.g., ≤200 columns) and cell length to blunt CSV-bomb inputs; UUID-only stored filenames (path-traversal safe); encoding tried as UTF-8-SIG then Latin-1 (DataCo), else fail with guidance; malformed quoting fails with stage + position and cleans up partial outputs.

## 4. Session / temp lifecycle

- **Session ID: one server-generated UUIDv4** (e.g., `3f9d…`). It encodes no user, filename, timestamp, or source information. No ULID hybrid. Returned in every API envelope `meta.sessionId`.
- **Layout (git-ignored, e.g., `.tmp/sessions/`):**
  ```
  .tmp/sessions/{uuid}/
    manifest.json        # ids, versions, source hash/size/encoding, state, stage timings, error metadata
    raw.csv              # immutable (read-only), only while the session can validly continue
    derived/             # canonical tables, DQ findings, cleaning log, KPI cache
    exports/             # built export artifacts for download
  ```
- **Immutable raw:** written once, read-only flag, SHA-256 + byte size + detected encoding recorded in the manifest. Cleaning never touches it. Valid sessions keep it until reset/expiry.
- **Derived/working:** rebuilt deterministically from raw + code version; carries `source_row_number` provenance. Removed on reset, expiry, restart sweep, or failure.
- **Exports:** built only on explicit request under `exports/`, served as downloads, subject to the same expiry as the session.
- **Reset:** `DELETE /api/v1/sessions/{id}` removes the entire session tree idempotently (already-gone → success) and the UI returns to empty state.
- **Expiry:** time TTL (default 24 h sliding on `lastAccessedAt`) plus pressure caps (e.g., keep 5 most-recent sessions / 2 GB total, whichever binds first). Exact values are config with documented defaults (Phase 3); behavior is what this contract fixes.
- **Restart sweep:** on backend startup, scan session manifests; delete trees whose manifest is missing/incomplete, whose state is terminal-failed without retainable raw, or whose TTL/caps are exceeded. Log counts only.
- **Failure cleanup:** on terminal ingestion/processing failure (session cannot validly continue): remove partial `derived/` files **and** the raw upload; retain only the privacy-safe manifest/error metadata needed for diagnostics (session ID, stage, error code, sizes, counts — never cell values or personal fields). For recoverable states where the session remains valid (e.g., a downstream stage can be retried from intact raw), the immutable raw may remain until reset/expiry.
- **Logging allow-list:** session ID, stage, durations, byte/row counts, rule IDs + counts, app/schema versions, error codes. **Deny-list:** names, emails, streets, passwords, coordinates, IPs, full row contents, raw cell values, user file paths.

## 5. Component boundaries

- `ingestion`: receives bytes, enforces guards, stores immutable raw, emits manifest. No business logic.
- `validation`: header/schema classification, enum-map checking (exact match), required-field gating. No cleaning.
- `profiling`: read-only detection producing `data_quality_issues` rows. No mutation.
- `cleaning`: only approved reversible transforms + audit log. No derivations, no KPI math.
- `canonicalization`: builds typed canonical tables, enforces order-invariance, applies deterministic derivations (`shipment_outcome`, `is_late`, variances, calendar fields). Derivations are recorded as derivations, not cleaning fixes.
- `kpi_engine`: sole owner of KPI definitions; consumes canonical tables + filters; returns nullable/unavailable results. No HTTP or React knowledge.
- `export`: allowlisted field projection, injection-safe serialization, metadata attachment, privacy gate.
- `api`: FastAPI routes + Pydantic schemas; orchestrate domain services; map domain errors to the typed error model. No KPI/business logic in handlers.
- `ui`: renders contracts; owns accessibility, filtering UX, and disclosure copy; performs no calculations.

## 6. Architecture / data-flow diagram

```
Browser / UI (Vite + React + TS, shadcn/ui, Recharts)
  Upload · Data Quality · Overview · Delivery · Commercial · Diagnostics
  Renders typed API contracts only. No KPI math. No raw personal fields.
        │  localhost JSON, one typed envelope (data/meta/error)
        ▼
API (FastAPI + Pydantic v2 + Uvicorn)
  uploads · status · schema · profile · data-quality · cleaning-report
  kpis/{overview,delivery,commercial} · orders · exports · session delete
  Handlers validate I/O, call domain services, map errors. No business logic.
        ▼
ingestion → validation → profiling → cleaning → canonicalization → KPI engine → export
  (raw+hash)  (schema map)  (DQ detect)  (audit log)  (orders/items/products/
                                              customers/calendar + derivations)
        │         │             │              │                  │              │
        └─────────┴─────────────┴──────────────┴──────────────────┴──────────────┘
                                    session-scoped temp (.tmp/sessions/{uuid}/)
                                    raw.csv (read-only) · derived/ · exports/
                                    manifest.json + error metadata

PRIVACY BOUNDARY — everything above runs locally; nothing crosses it:
  · No uploaded bytes, derived tables, or cell values leave localhost.
  · No AI / telemetry / analytics / geocoding / storage / enrichment calls.
  · Logs carry metadata + counts + error codes only.
  · Restart / expiry / reset / terminal-failure paths delete session data
    (terminal failure keeps only privacy-safe manifest/error metadata).
  · Raw uploads, derived files, and exports are never committed to Git.
```
