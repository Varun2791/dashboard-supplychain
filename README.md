# Supply Chain Analytics Dashboard

Local-first web application that turns a DataCo-compatible supply-chain CSV into a dataset profile, a validation and data-quality report, an auditable canonical dataset, correctly-grained KPIs, and an interactive dashboard.

## Status: V1 core engineering baseline (Phases 0–17 complete)

The repository contains the full local-first V1: validated CSV upload with immutable raw storage and session lifecycle (202/status/reset/TTL/restart-sweep), DataCo schema recognition and canonical mapping, value-level profiling with stable `DQ-*` data-quality rules, auditable cleaning (governed label-whitespace trim only, per-rule detected/fixed/flagged/excluded/unchanged log), the canonical model (`order_items`, `orders`, `products`, `customers_sanitized`, `calendar`, `data_quality_issues`), the backend-owned KPI engine (30 KPI contracts; recorded commercial values, on-schedule shipment semantics, amount-weighted rates), the accessible React/shadcn/Recharts dashboard (Upload, Data Quality, Overview, Delivery, Commercial, Diagnostics), and four governed exports (sanitized cleaned items, canonical orders, data-quality report, cleaning report). Reference verification runs green against the unmodified public DataCo CSV (kept out of the repository): 180,519 order items, 65,752 orders, all `AGENTS.md` controls reproduced with 0 blocking data-quality issues. See `PLAN.md` for the phase record and `docs/architecture.md` §3 for the measured resource envelope.

## Local-first / privacy principle

All uploaded data is processed only in the locally running application environment. Nothing is sent to external AI, telemetry, analytics, geocoding, storage, or enrichment services. Direct personal fields never enter analytical outputs, logs, or exports. See `AGENTS.md` and `docs/product-spec.md`.

## Reference dataset (not included)

The V1 reference/demo dataset is **DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS**, published on **Mendeley Data** (versioned record `https://data.mendeley.com/datasets/8gx2fvg2k6/5`, DOI `10.17632/8gx2fvg2k6.5`; see `DECISIONS.md` ADR-041). It is **not distributed in this repository** (see `DECISIONS.md` ADR-024) and is never committed: obtain it from the governed public source.

To obtain it yourself:

1. Open the versioned Mendeley Data record above.
2. Use the download controls provided by Mendeley Data to obtain the structured file `DataCoSupplyChainDataset.csv` (the V1 application reference input). The record also lists `tokenized_access_logs.csv`, which is outside V1 application scope, and `DescriptionDataCoSupplyChain.csv`, which is source documentation rather than an application input.
3. Any access requirements shown by Mendeley Data at download time apply.
4. Keep the downloaded file outside this repository and upload the local CSV through the application's Upload view for local verification.

The source record labels the dataset **CC BY 4.0**; follow the source record's current license and terms. The repository's MIT license applies to repository code, not automatically to externally obtained dataset content. Automated tests use small synthetic/invented fixtures under `backend/tests/fixtures/` instead of the DataCo dataset. DataCo is the V1 reference/demo dataset, not a universal supply-chain schema: reference-data findings describe the supplied dataset and should not be treated as real-company operational conclusions.

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
