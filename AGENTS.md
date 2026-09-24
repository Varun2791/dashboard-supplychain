# AGENTS.md

## Repository purpose

Build a local-first supply-chain CSV analytics application that:

1. accepts a DataCo-compatible CSV upload;
2. preserves the source data unchanged;
3. profiles and validates the upload;
4. produces an auditable cleaning and data-quality report;
5. separates order and order-item grain;
6. calculates explicitly defined supply-chain KPIs; and
7. presents the results in an accessible interactive dashboard.

DataCo is the V1 reference dataset, not the application's permanent schema. Read `PLAN.md` for the execution sequence and `DECISIONS.md` for binding architectural and analytical decisions before changing code.

## Existing project-material rule

- Treat every file under `sources/` as read-only reference material.
- Do not edit, rename, move, or delete synced project files.
- Synced source files may be replaced when a new task is created from the ChatGPT project.
- Never commit raw datasets, uploaded files, generated extracts, credentials, environment files, or local caches.

## Source-of-truth order

When instructions conflict, use this order:

1. the user's current request;
2. this file;
3. accepted decisions in `DECISIONS.md`;
4. the current phase and acceptance criteria in `PLAN.md`;
5. tests and documented KPI contracts;
6. implementation details.

Do not silently override an accepted decision. Record a proposed change in `DECISIONS.md`, explain its consequences, and obtain approval before implementing it.

## Required agent workflow

Before starting work:

1. Read `AGENTS.md`, `PLAN.md`, and `DECISIONS.md` completely.
2. Identify the active phase and the exact unchecked task being addressed.
3. Inspect the existing implementation and tests before editing.
4. State any assumption that can materially change behavior, data meaning, or scope.

While working:

- Make the smallest coherent change that completes the selected task.
- Do not implement later phases early.
- Preserve unrelated user changes and avoid broad refactors.
- Add or update tests with behavioral changes.
- Keep raw ingestion, validation, cleaning, canonical transformation, analytics, and presentation as separate concerns.
- Update documentation when a schema, KPI, public behavior, or decision changes.
- Never mark a plan item complete merely because code exists.

Before declaring a task complete:

1. Run the relevant formatter, linter, type checks, and tests.
2. Validate affected KPI results against independent calculations or the DataCo reference controls.
3. Check empty, invalid, missing, duplicate, and zero-denominator cases.
4. Confirm that no uploaded data is transmitted externally or written to version control.
5. Confirm the phase acceptance criteria are actually satisfied.
6. Update `PLAN.md` accurately. Leave incomplete items unchecked.

## Scope discipline

V1 includes:

- local CSV upload;
- DataCo schema recognition and canonical mapping;
- dataset profiling and validation;
- transparent cleaning with a change log;
- order and order-item canonical tables;
- data-quality reporting;
- KPI calculation;
- overview, delivery, commercial, diagnostics, and data-quality views;
- filters and cleaned-data/report export;
- automated tests and portfolio documentation.

V1 does not include:

- arbitrary user-defined column mapping;
- authentication or multi-user accounts;
- cloud persistence;
- external AI analysis of uploaded data;
- forecasting or machine learning;
- supplier, procurement, inventory, warehouse, returns, freight-cost, or emissions analytics;
- Power BI integration;
- the tokenized access-log dataset;
- mobile-native applications.

Do not add excluded features without an approved decision and plan change.

## Data rules

### Raw-data preservation

- Treat every upload as immutable.
- Assign an internal upload/session identifier without modifying source identifiers.
- Never overwrite the raw upload with cleaned data.
- Cleaning output must be a new representation.
- Every mutation must record the field, rule, count, reason, and outcome.
- Distinguish `detected`, `fixed`, `flagged`, `excluded`, and `unchanged`.
- Never invent missing business values.

### Grain and keys

- A source row is an order item, not an order.
- `Order Item Id` is the source line key.
- `Order Id` is the order key and legitimately repeats.
- `Order Id + Product Id` is not unique and must not be used for deduplication.
- Delivery KPIs operate at order grain.
- Sales, discounts, units, and line profit originate at order-item grain.
- Order totals must be aggregated from order items exactly once.
- Category, product, customer, order, and item identifiers are strings in the canonical model even when the source stores them numerically.

### Cleaning policy

Safe automatic normalizations are limited to documented, reversible operations such as:

- canonical column naming;
- explicit date parsing;
- trimming leading/trailing whitespace in labels;
- converting identifiers and postal codes to strings;
- mapping exact source enums to documented canonical enums; and
- creating derived fields whose formulas are recorded.

Flag rather than silently repair:

- missing values without an authoritative replacement;
- invalid geography;
- extreme negative profit;
- contradictory business fields;
- unknown enum values;
- non-unique expected keys; and
- formula mismatches outside the defined tolerance.

Do not remove negative-profit rows, cancelled orders, suspected-fraud orders, or repeated order/product lines merely because they look undesirable.

### Privacy

- Do not expose or retain customer first name, last name, street, email, or password in analytical outputs.
- Do not ingest access-log IP addresses in V1.
- Customer analytics use only the sanitized customer identifier, segment, and approved coarse location fields.
- Do not send uploaded content to analytics, telemetry, AI, geocoding, or other external services.
- Logs must contain technical metadata and counts, not raw row contents or personal fields.

## Canonical-model boundaries

The canonical model contains, at minimum:

- `orders`: one row per order;
- `order_items`: one row per source line;
- `products`: one row per product ID;
- `customers_sanitized`: one row per customer ID without direct personal fields;
- `calendar`: derived date attributes; and
- `data_quality_issues`: rule outcomes and audit evidence.

Use the accepted field definitions in `DECISIONS.md`. Do not couple analytics directly to raw DataCo column labels.

## KPI rules

Every KPI contract must define:

- display name;
- canonical identifier;
- business meaning;
- grain;
- numerator and denominator;
- eligible population;
- exclusions;
- date basis;
- required fields;
- zero/missing behavior;
- formatting; and
- reference test value where available.

Binding terminology:

- Say `recorded net order value`, not recognized revenue.
- Say `on-schedule shipment rate`, not customer on-time delivery.
- Say `net order value associated with late shipments`, not sales lost because of lateness.
- Separate strict cancelled orders from suspected-fraud shipment blocks.
- Treat currency as unspecified unless an explicit demo assumption is displayed.
- Calculate aggregate margin as total profit divided by total net sales, never as an unweighted average of row ratios.

No dashboard component may independently redefine a KPI. The backend analytics contract is authoritative.

## Reference acceptance controls

For the unmodified DataCo main CSV, tests should reproduce these controls, subject only to documented decimal tolerances:

- rows/order items: `180519`;
- unique orders: `65752`;
- non-cancelled shipment orders: `62897`;
- customers: `20652`;
- products: `118`;
- units: `384079`;
- late eligible orders: `36048`;
- early eligible orders: `15127`;
- exactly on-schedule eligible orders: `11722`;
- shipping-cancelled orders: `2855`;
- strict cancelled orders: `1367`;
- suspected-fraud orders: `1488`;
- gross order value: `36784735.01`;
- discounts: `3730378.40`;
- net order value: `33054402.38`;
- recorded profit: `3966902.97`;
- late-shipment rate: approximately `57.3127%`; and
- on-schedule shipment rate: approximately `42.6873%`.

These are regression controls, not values to hardcode into production logic.

## Architecture rules

- Keep domain logic independent from HTTP routes and UI components.
- The frontend must consume typed API contracts rather than reproducing backend calculations.
- Validate file type, size, encoding, required columns, keys, and parsability before transformation.
- Use explicit schemas at system boundaries.
- Use decimal-safe handling for money and defined rounding at display/export boundaries.
- Dates remain timezone-naive because the source supplies no timezone.
- Use the supplied actual-shipping-days field for shipment KPIs; timestamp differences are validation evidence only.
- Temporary processing data must be session-scoped and removable.
- Fail with specific, actionable messages. Do not hide unexpected errors behind empty results or zero KPIs.
- Avoid adding dependencies without a concrete requirement and recorded justification.

## Frontend and UX rules

- Use the approved React/shadcn design system consistently.
- Build views around business questions, not around available chart types.
- Show active filters, KPI definitions, populations, and exclusions where users can find them.
- Data-quality warnings must remain visible and must not be converted into decorative success states.
- Charts require accessible labels, keyboard-reachable controls, readable contrast, and non-color-only distinctions.
- Tables require clear units, sorting behavior, empty states, and pagination or virtualization where needed.
- Never render raw personal fields.
- Avoid misleading precision; counts are whole numbers, rates normally use one decimal, and financial values use consistent rounding.

## Backend and analytics rules

- Parsing and validation must be deterministic and reproducible.
- Do not trust filenames, MIME types, headers, or inferred dtypes without validation.
- Reject malformed inputs safely and report the failing stage.
- Preserve row-level provenance through canonical transformation.
- Enforce order-level invariance before collapsing source rows into orders.
- Investigate conflicts instead of selecting an arbitrary first row.
- Use source net sales as authoritative; validate gross minus discount with tolerance.
- Use amount-weighted discount and profit calculations.
- Cancelled shipments have `is_late = null`, not `false`.
- Empty eligible populations return an unavailable KPI, not zero percent.

## Testing requirements

At minimum, maintain:

- unit tests for parsing, mapping, cleaning rules, and KPI formulas;
- schema-contract tests for API payloads;
- integration tests for upload through analytics output;
- golden/reference tests against the DataCo controls;
- adversarial fixtures for missing columns, duplicate item IDs, conflicting order attributes, invalid dates, new enum values, zero denominators, and malformed CSVs; and
- focused frontend tests for loading, error, empty, filter, and accessibility behavior.

Never use the full private upload as the only test fixture. Create small synthetic fixtures containing the edge cases DataCo does not contain.

## Git and change-management rules

- Do not create, push, merge, or rewrite commits unless the user requests it.
- Never use destructive Git commands on user work.
- Keep commits phase-focused and reviewable.
- Prefer conventional messages such as `feat(ingestion): validate DataCo CSV uploads`.
- Do not combine unrelated refactors, generated artifacts, and feature work.
- Suggested commit checkpoints appear in `PLAN.md`; they are not automatic authorization to commit.
- Record material architectural or analytical choices in `DECISIONS.md` in the same change that implements them.

## Definition of done

A task is done only when:

- its stated acceptance criteria pass;
- relevant automated checks pass;
- KPI and schema effects are documented;
- error and empty cases are handled;
- privacy and local-processing constraints are preserved;
- no out-of-scope feature was introduced; and
- `PLAN.md` accurately reflects the resulting state.

