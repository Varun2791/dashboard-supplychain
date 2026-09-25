# Supply Chain Analytics Dashboard

Local-first web application that turns a DataCo-compatible supply-chain CSV into a dataset profile, a validation and data-quality report, an auditable canonical dataset, correctly-grained KPIs, and an interactive dashboard.

## Status: implementation in progress (Phase 6)

The repository currently contains the governance documents, Phase 2 contracts, the Phase 3 application shell, the Phase 4 CSV ingestion pipeline (validated upload → immutable raw + manifest → 202/status/reset lifecycle), Phase 5 V1 DataCo schema validation (header recognition → canonical mapping metadata → VALIDATING-to-PROFILING/FAILED lifecycle with a schema report endpoint), and Phase 6 value-level profiling/data-quality assessment (single-pass governed parsing → PROFILING-stage DQ rule findings → typed profile + data-quality reports → PROFILING-to-CLEANING/FAILED lifecycle). Profiling is diagnostic: no source values are repaired, raw remains immutable, and every finding links a stable `DQ-*` rule. Cleaning, canonical models, KPIs, dashboard analytics, and exports are **not implemented yet** — see `PLAN.md` for the phase-gated sequence. There are no screenshots because there is no dashboard yet.

## Local-first / privacy principle

All uploaded data is processed only in the locally running application environment. Nothing is sent to external AI, telemetry, analytics, geocoding, storage, or enrichment services. Direct personal fields never enter analytical outputs, logs, or exports. See `AGENTS.md` and `docs/product-spec.md`.

## Reference dataset (not included)

The V1 reference dataset is the public DataCo supply-chain CSV. It is **not distributed in this repository** (see `DECISIONS.md` ADR-024) and is never committed: obtain it separately for local verification. Automated tests use small invented fixtures under `backend/tests/fixtures/` instead. The MIT license in this repository applies to the application source code only, not to the external DataCo dataset.

## Architecture summary

- Frontend: Vite + React + TypeScript (strict) + shadcn/ui + Tailwind + Recharts, served locally.
- Backend: Python 3.12 + FastAPI + Pydantic v2 + pandas/pyarrow, with a typed `/api/v1` contract.
- One documented async pipeline: upload → validate → profile → clean → canonicalize → analyze → export, with session-scoped temporary storage.
- Full contracts: `docs/` (product spec, architecture, API, canonical schema, KPIs, data-quality rules, exports). Binding decisions: `DECISIONS.md`. Operating rules: `AGENTS.md`.

## Prerequisites

- Node 24 LTS (`nvm use` reads `.nvmrc`; local Node 26 also runs the shell, CI enforces 24).
- npm (ships with Node).
- Python 3.12 (see `.python-version`; the backend resolves it via `requires-python`).
- uv (Python package manager).

## Local development

```sh
make install          # install frontend (npm ci) + backend (uv sync) dependencies
make dev-backend      # FastAPI on http://127.0.0.1:8000
make dev-frontend     # Vite dev server
```

Backend health check: `GET http://127.0.0.1:8000/api/v1/health`.

Non-secret local overrides: copy `.env.example` to `.env` (gitignored).

## Tests and checks

```sh
make test-frontend    # Vitest + React Testing Library + axe
make test-backend     # pytest
make lint             # ESLint + Ruff check/format
make typecheck        # tsc + mypy
make format-check     # Prettier + Ruff format
make check            # all of the above
```

CI (`.github/workflows/ci.yml`) runs the same non-secret checks on every push and pull request.

## Governance / contracts

- `AGENTS.md` — permanent operating rules.
- `PLAN.md` — phase-gated execution plan (read before changing code).
- `DECISIONS.md` — binding architectural and analytical decisions (ADR-001+).
- `docs/` — implementable V1 contracts (product, architecture, API, schema, KPIs, quality rules, exports).
