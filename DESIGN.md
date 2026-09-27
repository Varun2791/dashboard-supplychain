# DESIGN.md — V1 Frontend Visual / Design-System Authority

Presentation only. This document governs how the application looks, never
what it means or computes.

Authority order (binding):

1. safety / security / privacy
2. `AGENTS.md` / accepted ADRs / contracts
3. correctness / auditability
4. phase acceptance
5. tests
6. **this document (visual rules)**
7. implementation minimalism
8. cosmetics

On any conflict between this document and 1–5, 1–5 win and this document
must be amended. Visual improvement never compensates for semantic
regression: the redesign succeeds only if the application looks
substantially more intentional **and** all governed behavior remains
correct.

Status: visual contract for the V1 frontend redesign. Implementation follows
the order in §20; each stage preserves working behavior and full regression.

## 1. Product character

The Supply Chain Analytics Dashboard is a serious local operational
analytics application — a working tool for a supply-chain / logistics /
operations analyst, and a portfolio demonstration of analytics engineering.

Visual character:

- dark predominant analytical workspace;
- near-black background, never indiscriminate pure black;
- off-white readable typography;
- subtle layered surfaces;
- restrained neutral borders;
- light-blue analytical accent;
- high information density;
- crisp technical character;
- minimal decoration.

Explicitly rejected: marketing SaaS styling, fintech-terminal imitation,
sci-fi/cyberpunk styling, fake terminal styling, glassmorphism, gradients,
decorative blobs, neon glow, large shadow stacks, giant KPI numerals,
floating-card soup, rainbow chart palettes, decorative animation, and
information-density reduction for aesthetics alone.

## 2. Preserved foundations (non-negotiable)

- React + TypeScript architecture retained; no framework migration.
- shadcn component foundation retained; no replacement for visual novelty.
- Recharts retained; no visualization-library migration.
- Native accessible controls (`select`, `details`/`summary`, `button`)
  retained where they already work.
- No business logic moves into frontend presentation. The backend remains
  the sole owner of every KPI, classification, filter semantic, and privacy
  boundary.

A new shadcn primitive must solve a demonstrated UI/accessibility problem;
equivalents are not adopted merely because they exist.

## 3. Color tokens

Semantic roles, not scattered component colors. Values are oklch starting
points; contrast must be measured during implementation (§18) before any
compliance claim.

| Role | Value |
|---|---|
| `background` | near-black `oklch(0.16 0 0)` |
| `surface` | `oklch(0.20 0 0)` |
| `surface-elevated` | `oklch(0.24 0 0)` (popovers, tooltips, open menus) |
| `border` | white at 8% |
| `border-strong` | white at 14% |
| `text-primary` | off-white `oklch(0.93 0 0)` |
| `text-secondary` | `oklch(0.72 0 0)` |
| `text-muted` | `oklch(0.55 0 0)` |
| `accent` | light blue `oklch(0.72 0.12 250)` — analytical/data use only |
| `accent-hover` | `oklch(0.78 0.12 250)` |
| `focus-ring` | accent blue at 60% with 2px offset, always visible |
| `chart-grid` | white at 8% |
| `chart-secondary` | desaturated slate-blue `oklch(0.62 0.05 250)` |
| `selection` | accent-tinted surface plus accent edge rule |

Semantic states keep dedicated hues — blue must never replace them:

| Role | Value |
|---|---|
| `error` | `oklch(0.68 0.19 25)` |
| `warning` | `oklch(0.78 0.15 80)` |
| `success/info` | governed green / teal |

## 4. Typography (hybrid — locked)

Geist Variable remains the primary reading/prose face: paragraphs,
methodology text, Data Quality explanations, help and disclosure copy.

JetBrains Mono (open source, OFL) is authorized for: KPI values, table
numerics, IDs, hashes, session/provenance metadata, compact status
information, and selected compact labels where readability remains good.
Use tabular numerals wherever numeric comparison benefits.

JetBrains Mono must not become body text. The font dependency itself is
added at implementation time, not by this document.

## 5. Spacing / shape / elevation

Compact 4px-based spacing scale: 4 / 8 / 12 / 16 / 24 / 32.

- Controls and tables: small radius (≈6px).
- Analytical surfaces: moderate radius (≈8px).
- Badges/pills: full radius only when semantically appropriate.
- No large consumer-style rounded containers.

Borders and surface hierarchy are the primary elevation mechanism. Shadows
are reserved for true overlays (tooltips, popovers).

## 6. Information density

This is an analytical application: density is a feature when structured
correctly. Do not create whitespace merely to appear premium or modern.
Prefer alignment, consistent columns, compact spacing, typographic
hierarchy, numeric alignment, and section rhythm over large empty areas.
Analytical content may run wider than the current `max-w-6xl` where useful
(e.g. up to ~80rem for dense tables and chart grids).

## 7. Navigation

Retain the current information architecture and top navigation: Upload,
Data Quality, Overview, Delivery, Commercial, Diagnostics. No sidebar by
default; no IA change without concrete usability evidence from
implementation. No mandated numbered labels — operational character comes
from the design system, not fake-terminal conventions.

Direction: compact top bar with product title, local-only note, and a mono
session status line; view tabs with a restrained active treatment
(accent underline and/or tinted surface); state-colored session dot
(READY ok, pending muted/amber, FAILED error).

## 8. KPI system

Compact KPI strip/grid: small label, prominent-but-restrained mono value
(large enough to scan, never hero-sized), population/context line.
Tabular numerals. No giant hero metrics, no invented deltas, no frontend
arithmetic.

Unavailable remains visually and semantically distinct from zero (muted
block with reason, identical geometry — no layout shift). Negative
recorded profit is valid data, never rendered as an application error.

Reduce repeated per-card definition chrome: one shared per-view
definitions/populations disclosure is permitted, provided every existing
explanatory string and the keyboard-accessible disclosure semantics are
preserved.

## 9. Chart system

Recharts is mandatory. Primary analytical series: light-blue solid.
Secondary/comparison series: restrained slate/blue-neutral with dash/shape
distinction — never color-alone encoding. Semantic loss/error representation
may use semantic colors only where contractually appropriate (e.g. loss).

Standardize grid (dashed, grid token), axes, 11–12px muted ticks,
dark-elevated tooltips with mono values, small legends with shape swatches,
honest empty/unavailable states (never zero-filled gaps), and chart
data-table fallbacks (retained). No 3D, no rainbow palette, no fake data,
no decorative animation.

## 10. Table system

Dense and analytical: compact rows, strong header hierarchy (small
mono uppercase headers over a strong bottom border), right-aligned numeric
cells in JetBrains Mono with tabular numerals, subtle row dividers, clear
hover/focus states, horizontal scrolling when necessary. Never hide
governed columns for narrow screenshots. Sticky headers allowed where they
materially improve long-table use (e.g. order drilldown).

A thin shared visual table shell over the existing duplicated
`ScrollTable` pattern is allowed. A generic schema/config-driven table
framework is explicitly out of scope.

## 11. Filter system

The exact 8-filter semantics, request tokens, and persistence behavior are
untouchable: no `customer_segment` filter, no query builder. Visually, one
compact analytical toolbar: small mono labels, compact selects, obvious
active state (e.g. accent-tinted chip with clear action), obvious Reset,
usable narrow layouts (wrapping grid, never scrolled-off controls).

## 12. Data Quality (differentiating surface)

Exact vocabulary preserved: detected / fixed / flagged / excluded /
unchanged; ERROR / WARNING / INFO with severity color used only for
severity meaning. Stronger hierarchy around rule ID (mono anchor),
severity, affected count (mono), treatment, and blocked stage. A compact
treatment ledger per cleaning step is permitted. Never: quality score,
grade, waiver, fake remediation, or raw privacy values. Privacy exclusions
stay understandable as counts-only panels.

## 13. Upload / lifecycle

The pipeline may be shown as Upload → Profile → Validate → Clean →
Analyze → Dashboard, mapped honestly onto existing lifecycle states only.
No invented percentages. Static status distinction: complete / active /
pending / blocked-or-failed. Pulsing or animated active stages are not
required.

## 14. Motion

Motion is optional, never a goal: only subtle interaction/state
transitions that aid comprehension. No entrance choreography, count-up
animation, bouncy cards, parallax, glowing cursors, or continuous chart
animation. Respect `prefers-reduced-motion` throughout.

## 15. Responsive

Design explicitly for ~375px narrow layouts. Protect filter usability,
table access (scroll, never column-hiding), KPI readability, chart legends,
long hashes/provenance (wrap or truncate with full value available), and
touch targets. Governed analytical content is never hidden for mobile
aesthetics.

## 16. Accessibility (implementation acceptance)

Native semantics and axe-tested patterns are preserved and extended.
Implementation must verify and measure: text contrast, visible focus,
keyboard traversal, touch targets, chart/table alternatives,
reduced-motion behavior, async/live-region behavior, and narrow layouts.
No WCAG compliance claim until measured.

## 17. Refactoring boundary

This redesign is not authorization for broad frontend architecture
cleanup. Do not automatically introduce: a generic `useReports` hook, a
generic KPI-selection abstraction, a config-driven view renderer, a new
state-management layer, a new chart framework, a generic table engine, or
wrapper-component proliferation. Allowed: the thin visual table shell
(§10), shared visual chart tokens/config, and design-token changes.
Business/request lifecycle abstractions require separate justification.

## 18. Implementation order (approximate)

1. tokens + dark theme + typography; 2. shell/navigation; 3. shared visual
primitives only; 4. filters; 5. KPI presentation; 6. chart conventions;
7. table presentation; 8. Upload lifecycle presentation; 9. Data Quality
presentation; 10. responsive/accessibility refinement; 11. complete
regression. Each stage preserves working behavior.

## 19. Ponytail boundary (future review input)

Future Ponytail review targets: wrapper proliferation, duplicate
style-only components, duplicated chart configuration, unnecessary
variants, animation complexity, and generic abstractions introduced solely
by the redesign. Ponytail must not simplify away: session lifecycle
protections, stale-request protection, DQ semantics, KPI contracts,
canonical grain distinctions, privacy boundaries, filter semantics, or
accessibility behavior.
