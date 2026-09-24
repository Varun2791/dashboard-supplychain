# V1 API Contract

Base path: `/api/v1`. All responses use the single envelope below. Route handlers contain no KPI/business logic: they validate I/O with Pydantic, call domain services, and map domain errors to the error model.

## 1. Processing model (async; one behavior)

`POST /sessions/uploads` **always** behaves the same way:

1. Runs only the cheap synchronous guards: transport integrity, extension/MIME evidence, size ≤ 250 MB, non-empty, header parse, duplicate-header check, encoding sniff.
2. Creates the session (UUIDv4), stores the immutable raw file, writes the manifest with state `VALIDATING`.
3. Returns **`202 Accepted`** immediately with the session ID and the status URL. It never waits for profiling/cleaning/canonicalization/KPIs, and never returns `201` with full results.

Justification: the reference file (≈95.9 MB / 180,519 rows) cannot be fully processed inside a reasonable request timeout, and processing time varies by machine. One async behavior keeps the UI responsive, gives stage-specific progress through the status endpoint, and removes the 201-vs-202 ambiguity: uploads are resource creation that completes asynchronously, so `202` + polling is the only upload behavior. All downstream `GET`s return `200` when ready or `409 NOT_READY` with the current state when the required stage has not completed.

Session states: `UPLOADING → VALIDATING → PROFILING → CLEANING → CANONICALIZING → ANALYZING → READY`, with terminal `FAILED` and `EXPIRED`. Transitions are forward-only except terminal cleanup. `FAILED` retains only privacy-safe manifest/error metadata when the session cannot validly continue (raw + partial derived removed); a recoverable session keeps its immutable raw until reset/expiry.

## 2. Success / error envelope

Success (`200` / `202`):

```json
{
  "data": {},
  "meta": {
    "sessionId": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "appVersion": "0.1.0",
    "schemaVersion": "1",
    "generatedAt": "2026-09-24T00:00:00",
    "sessionState": "READY",
    "filters": {}
  },
  "error": null
}
```

Error (`4xx` / `5xx`):

```json
{
  "data": null,
  "meta": {
    "sessionId": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "appVersion": "0.1.0",
    "schemaVersion": "1",
    "generatedAt": "2026-09-24T00:00:00",
    "sessionState": "FAILED"
  },
  "error": {
    "code": "SCHEMA_MISSING_COLUMN",
    "stage": "VALIDATING",
    "message": "Required column 'Order Id' is missing.",
    "details": { "missing": ["Order Id"] }
  }
}
```

Rules: `error.stage` is always the pipeline stage that failed. `details` carries machine-readable facts (IDs, counts, field names) — never cell values or personal fields. Unexpected failures map to `INTERNAL_STAGE_ERROR` with the stage attached; they are never hidden behind empty results or zero KPIs.

## 3. Endpoints

| Method | Route | Purpose | Request | Success `data` | Error cases |
|---|---|---|---|---|---|
| `GET` | `/health` | Liveness + versions + limits | — | `{ appVersion, schemaVersion, maxUploadMB: 250 }` · `200` | `500 INTERNAL_STAGE_ERROR` |
| `POST` | `/sessions/uploads` | Create session, store immutable raw, run header guards | `multipart/form-data`: `file` (`.csv`, ≤250 MB) | `{ sessionId, statusUrl, filenameSafe, bytes, sha256, encoding }` · **`202`** | `400 EMPTY_FILE` / `INVALID_EXTENSION` / `MALFORMED_HEADER` / `DUPLICATE_HEADERS`; `413 FILE_TOO_LARGE`; `415 UNSUPPORTED_ENCODING`; `422 UNREADABLE_HEADER` |
| `GET` | `/sessions/{id}/status` | Poll pipeline state + progress | — | `{ state, stage, progress, startedAt, updatedAt, error }` · `200` | `404 SESSION_NOT_FOUND`; `410 SESSION_EXPIRED` |
| `GET` | `/sessions/{id}/schema` | Schema/mapping report | — | `{ sourceColumns[], mapping[{source, canonical, class}], missingCritical[] }` · `200` | `404` / `410`; `409 NOT_READY`; missing critical also surfaces as `422 SCHEMA_MISSING_COLUMN` once VALIDATING completes |
| `GET` | `/sessions/{id}/profile` | Read-only pre-cleaning profile | — | `{ rows, columns, grain, missingness[], cardinality[], duplicates{exact, keyDupes}, invarianceConflicts }` · `200` | `404` / `410` / `409` |
| `GET` | `/sessions/{id}/data-quality` | Issues by rule (`?severity=`) | query: `severity` | `{ summary, issues[{ruleId, severity, count, treatment, blockedStage}] }` · `200` | `404` / `410` / `409`; `422 INVALID_SEVERITY_FILTER` |
| `GET` | `/sessions/{id}/cleaning-report` | Audit log of transforms | — | `{ steps[{ruleId, field, detected, fixed, flagged, excluded, unchanged, reason}] }` · `200` | `404` / `410` / `409` |
| `GET` | `/sessions/{id}/kpis/overview` | Headline commercial + shipment KPIs | filters ( §5 ) | `{ kpis[{id, label, value, status, numerator, denominator, population, exclusions}], totals }` · `200` | `404` / `410` / `409`; `422 INVALID_FILTER_VALUE` (unknown enums rejected, never silently mapped) |
| `GET` | `/sessions/{id}/kpis/delivery` | Shipment breakdowns (`by=` grouping) | filters + `by` | `{ groups[], eligibleOrders, exclusions }` · `200` | same as above + `422 INVALID_GROUPING` |
| `GET` | `/sessions/{id}/kpis/commercial` | Value/profit/discount/units breakdowns | filters + `by` | `{ groups[], statusScope, weightedRates }` · `200` | same as above |
| `GET` | `/sessions/{id}/orders` | Paginated sanitized order drilldown | `limit` + `cursor` + filters | `{ rows[], page{nextCursor, total} }` · `200` | `404` / `410` / `409`; `422 INVALID_PAGINATION` |
| `POST` | `/sessions/{id}/exports` | Build an approved export artifact | `{ kind, filters? }`, kind ∈ `cleaned_items \| orders \| quality_report \| cleaning_report` | `{ exportId, filename, bytes, sha256 }` · `201` | `404` / `410` / `409`; `400 INVALID_EXPORT_KIND`; `422 EXPORT_BLOCKED` (privacy-gate failure) |
| `GET` | `/sessions/{id}/exports/{exportId}` | Download the artifact | — | file stream (`text/csv` / `application/json`) · `200` | `404 EXPORT_NOT_FOUND` / `410` |
| `DELETE` | `/sessions/{id}` | Explicit reset (delete tree) | — | `{ deleted: true }` · `200` (idempotent: already-gone → `200`) | — |

KPI endpoints require state `READY` for full results; filtered recomputation from cached canonical tables is synchronous (`200`) because it needs no re-ingestion. There is no ERROR-acknowledgement/waiver parameter anywhere: gated stages stay gated until the input is fixed or the file is replaced.

## 4. Error model / codes

| Code | HTTP | Stage | Meaning |
|---|---|---|---|
| `EMPTY_FILE` | 400 | VALIDATING | 0 bytes or header-only upload |
| `INVALID_EXTENSION` | 400 | VALIDATING | not a `.csv` upload (with MIME/parse evidence) |
| `MALFORMED_HEADER` / `UNREADABLE_HEADER` | 400 / 422 | VALIDATING | header cannot be parsed |
| `DUPLICATE_HEADERS` | 400 | VALIDATING | duplicate normalized header names |
| `FILE_TOO_LARGE` | 413 | VALIDATING | bytes exceed 250 MB |
| `UNSUPPORTED_ENCODING` | 415 | VALIDATING | neither UTF-8-SIG nor Latin-1 decodes |
| `MALFORMED_CSV` | 422 | VALIDATING/PROFILING | mid-file quoting/truncation error; partial derived removed |
| `SCHEMA_MISSING_COLUMN` | 422 | VALIDATING | required source column absent; blocks CANONICALIZING and ANALYZING |
| `DUPLICATE_ITEM_KEY` | 422 | CANONICALIZING | duplicate `Order Item Id`; blocks canonical build (no dedup) |
| `ORDER_INVARIANCE_CONFLICT` | 422 | CANONICALIZING | conflicting order attributes; blocks `orders` build (no first-row pick) |
| `NOT_READY` | 409 | any | required stage not complete; `data` carries current `state` |
| `INVALID_FILTER_VALUE` / `INVALID_GROUPING` / `INVALID_PAGINATION` / `INVALID_EXPORT_KIND` / `INVALID_SEVERITY_FILTER` | 422 / 400 | ANALYZING / serving | bad request shape; unknown enum filter values rejected, never mapped |
| `EXPORT_BLOCKED` | 422 | export | privacy header-allowlist gate failed |
| `SESSION_NOT_FOUND` | 404 | any | unknown UUID |
| `SESSION_EXPIRED` / `EXPORT_NOT_FOUND` (gone) | 410 | any | TTL/pressure eviction |
| `INTERNAL_STAGE_ERROR` | 500 | reported stage | unexpected failure; stage attached, no data leaked |

## 5. Filtering conventions

Query params: `from`, `to` (ISO dates on `order_timestamp`), `market`, `region`, `category`, `department`, `shipping_mode`, `order_status`, `shipment_outcome`, `customer_segment`, `by` (grouping), `limit`, `cursor`, `severity`. Rules: filters narrow the eligible population and are echoed in `meta.filters`; they never change a KPI formula, grain, or label. Unknown enum values → `422 INVALID_FILTER_VALUE`. Date range outside data → empty-result with unavailable KPIs, not an error. Every filtered response repeats the active population and exclusions.

## 6. Serialization

- **Money:** JSON strings with exactly 2 dp (e.g., `"33054402.38"`); CSV `0.00` fixed, no currency symbol, no thousands separator. Decimal-safe backend; rounding only at display/export boundaries.
- **Dates:** ISO-8601 timezone-naive (`YYYY-MM-DDTHH:MM:SS`); date-only fields `YYYY-MM-DD`.
- **Nulls:** JSON `null`; CSV empty field. Unavailable KPIs: `{ "value": null, "status": "unavailable", "reason": "empty-eligible-population | zero-denominator | missing-required-fields" }` — never `0` or `0%`. Cancelled shipments: `"is_late": null`. Missing values are never invented.
- **IDs:** always strings, even when numeric in source.
