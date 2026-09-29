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
the order in §§18/22; each stage preserves working behavior and full regression.

## 1. Product character

The Supply Chain Analytics Dashboard is a serious local operational
analytics application — a working tool for a supply-chain / logistics /
operations analyst, and a portfolio demonstration of analytics engineering.

Visual character:

- dark predominant analytical workspace;
- near-black background, never indiscriminate pure black;
- off-white readable typography;
- subtle layered surfaces;
- restrained neutral borders with stronger structural edges;
- light-blue analytical accent;
- high information density;
- crisp technical character;
- minimal decoration.

Target direction (evidence-backed, 2026-09-29 rendered pass): restrained
industrial / data brutalism — NOT loud neo-brutalism. Technical, precise,
operational, structured, dense, deliberate, credible, distinctive. Brutalism
applies to structure, geometry, borders, hierarchy, typographic contrast,
spacing, and data framing — never to reducing data readability. It must
improve hierarchy, not produce card soup with thicker borders.

Explicitly rejected: marketing SaaS styling, fintech-terminal imitation,
sci-fi/cyberpunk styling, fake terminal styling, glassmorphism, gradients,
decorative blobs, neon glow, large shadow stacks, giant hard-offset shadows,
8px novelty borders everywhere, random thick outlines, fake paper/card
collage, giant KPI numerals, floating-card soup, rainbow chart palettes,
decorative animation, information-density reduction for aesthetics alone,
loud novelty neo-brutalism, gaming UI, terminal cosplay, intentionally
difficult or visually noisy presentation, medals/leaderboard styling,
unnecessary animation, hidden governed information, and mobile data removal
for aesthetics, generic component-engine refactors, router migration for
visual work, and AI-generated fake insights/data.

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
equivalents are not adopted merely because they exist. Recorded 2026-09-29
read-only research outcome: separator POTENTIALLY USEFUL (section dividers);
badge, table, scroll-area, tooltip, collapsible UNNECESSARY (native
semantics and existing shells already satisfy the need); button + theme
tokens remain USE EXISTING. Nothing installed by this decision.

## 2b. Explicitly preserved (governance checklist)

shadcn foundation; Recharts; Geist + JetBrains Mono hybrid; top navigation
with existing labels/order and no sidebar; exact eight-filter semantics;
backend KPI ownership with approved labels; chart data-table fallbacks;
negative-profit semantics; DQ detected/fixed/flagged/excluded/unchanged
vocabulary; severity semantics; lifecycle honesty (no fake percentages);
association-only Diagnostics; privacy boundaries; local-first framing;
reduced-motion support; visible focus; dense analytical layout. No visual
work may weaken any item above; conflicts resolve per the authority order
at the top of this document.

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

Rendered verdict 2026-09-29 (desktop + 375px READY sessions): existing blue
KEEP — charts, active nav, and analytical accents render coherently; no
replacement justified. Never pure `#000` workspaces, never pure `#fff`
borders, never full monochrome: semantic hues and the slate secondary stay.

Structural roles: `border-strong` marks true structural edges (shell frame,
strip boundaries, table-sheet frames, section rules); `border` marks
internal dividers only. A restrained `eyebrow` treatment (muted mono,
≤12px, uppercase allowed here only) labels sections; prose and KPI labels
outside eyebrows keep normal case discipline per §4.

## 4. Typography (hybrid — locked)

Geist Variable remains the primary reading/prose face: paragraphs,
methodology text, Data Quality explanations, help and disclosure copy.

JetBrains Mono (open source, OFL) is authorized for: KPI values, table
numerics, IDs, hashes, session/provenance metadata, compact status
information, and selected compact labels where readability remains good.
Use tabular numerals wherever numeric comparison benefits.

JetBrains Mono must not become body text. The font dependency itself is
added at implementation time, not by this document. Uppercase is restricted
to small technical eyebrows/metadata (≤12px mono); no giant all-caps prose.
Headings take `text-wrap: balance` where supported. The full application is
never all-monospace: industrial ≠ terminal.

## 5. Spacing / shape / elevation

Compact 4px-based spacing scale: 4 / 8 / 12 / 16 / 24 / 32.

- Controls: small square-ish radius (≈4px).
- Analytical sheets (tables, strips, toolbars): near-square (≈6px max).
- Badges/pills: full radius only for the session status dot and
  semantically equivalent markers.
- Section separation prefers border-top rules with eyebrow labels over
  nested cards; no large consumer-style rounded containers.

Geometry policy (data-brutalist): square or near-square everywhere, visible
structural edges in `border-strong`, clear containment, little/no decorative
elevation. Borders and surface hierarchy are the primary elevation
mechanism. Shadows are reserved for true overlays (tooltips, popovers) —
never hard-offset novelty shadows.

Nesting doctrine: page → section boundary → analytical content. A card is
justified only as a semantically meaningful container (one KPI strip, one
table sheet, one toolbar); card-in-card nesting and per-item floating cards
are removed in favor of shared boundaries with internal dividers.

Frame budget (binding, Impeccable-adjudicated 2026-09-29): at most three
frame types per view — toolbar strip, KPI strip, table sheet. Charts get a
calm plotting area under a section rule, never a second card around a
chart+table pair. Definitions disclosures get a rule, never a border.
Interior dividers must not double-draw (no combined `divide-x divide-y`
joints; per-cell single-edge borders only). If every section keeps a border
and gains a rule on top, the hierarchy has failed — specify which
containers lose their border entirely.

Novelty tripwire (reviewer checklist — any two together mean the design has
slipped into novelty neo-brutalism): hard-offset/drop shadows outside
overlays; >1px borders on non-structural edges; numbered nav labels;
all-mono body copy; round status dots forced square; accent blue used for
severity states; chart frames bolder than data marks; uppercase beyond
≤12px eyebrows; entrance choreography, count-ups, or pulsing stages;
per-KPI floating cards reintroduced for emphasis.

## 6. Information density

This is an analytical application: density is a feature when structured
correctly. Do not create whitespace merely to appear premium or modern.
Prefer alignment, consistent columns, compact spacing, typographic
hierarchy, numeric alignment, and section rhythm over large empty areas.
Analytical content may run wider than the current `max-w-6xl` where useful
(e.g. up to ~80rem for dense tables and chart grids).

Density doctrine: compact vertical rhythm, tight related groups, clear
section breaks, consistent row heights. Page sections breathe through rules
and eyebrows, not hero whitespace. KPI tiles stay compact readouts (never
oversized, never tiny targets — 375px keeps the 2-column strip with full
readability). Tables keep compact rows with internal scroll (verified at
375px: page never overflows; `.analytical-table.overflow-x-auto` contains
wide tables; nav scrolls horizontally by design).

## 7. Navigation

Retain the current information architecture and top navigation: Upload,
Data Quality, Overview, Delivery, Commercial, Diagnostics. No sidebar by
default; no IA change without concrete usability evidence from
implementation. No mandated numbered labels — operational character comes
from the design system, not fake-terminal conventions.

Direction: compact top bar with product title, local-only note, and a mono
session status line; view tabs with a restrained active treatment
(accent underline and/or tinted surface); state-colored session dot
(READY ok, pending muted/amber, FAILED error). Rendered evidence confirms
the underline/block active treatment and dot-plus-text session badge
(non-color-only) already carry the industrial tone — evolve, don't replace.
No sidebar, no hamburger for aesthetics, no numbered nav labels, no logo
redesign. At 375px the tab row scrolls horizontally and every view stays
reachable.

## 8. KPI system

Compact KPI strip/grid: small label, prominent-but-restrained mono value
(large enough to scan, never hero-sized), population/context line.
Tabular numerals. No giant hero metrics, no invented deltas, no frontend
arithmetic. Target framing: ONE shared strip boundary with column dividers
and baseline-aligned mono values — a dense analytical readout, not floating
stat cards. Rendered baseline already uses a single divided strip at all
viewports (2 columns at 375px); the redesign sharpens its edges and rhythm,
not its structure. KPI labels are governed explanatory strings, not
eyebrows: normal case, 12–13px medium weight, wrapping (never `truncate`,
never `uppercase`); uppercase mono is reserved for the strip eyebrow above
them. Populations wrap to two lines maximum with tabular numerics.

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
framework is explicitly out of scope. The shell contract (Impeccable-
adjudicated): thead with strong bottom border in `border-strong`; small
mono uppercase headers; right-aligned mono tabular numerics; subtle row
dividers; `:hover` / `:focus-visible` row tint; sticky thead as an opt-in
class for long drilldown tables (first-column stickiness likewise opt-in,
never default). Header hierarchy and sticky behavior must not live only in
prose.

## 11. Filter system

The exact 8-filter semantics, request tokens, and persistence behavior are
untouchable: no `customer_segment` filter, no query builder. Visually, one
compact analytical toolbar: small mono labels, compact selects, obvious
active state (e.g. accent-tinted chip with clear action), obvious Reset,
usable narrow layouts (wrapping grid, never scrolled-off controls).
Toolbar framing is a single strip with technical grouping — brutalist
styling must never make filters look disabled or command-line-only.
Active state must be presentationally unmistakable without changing
semantics: an accent edge or tint on every non-default field (not dates
only) plus a compact read-only active-summary line derived from existing
state ("Market: X · From: Y"). "Filtered" without "by what" is a
wrong-scope misreading risk; the summary fixes recall without adding,
removing, or redefining any filter.

## 12. Data Quality (differentiating surface)

Exact vocabulary preserved: detected / fixed / flagged / excluded /
unchanged; ERROR / WARNING / INFO with severity color used only for
severity meaning. Stronger hierarchy around rule ID (mono anchor),
severity, affected count (mono), treatment, and blocked stage. A compact
treatment ledger per cleaning step is permitted. Target register:
inspection sheet / audit ledger / QA console — rule IDs as row anchors,
counts in mono columns, severity as text-plus-color (never color alone).
Never: quality score, grade, waiver, fake remediation, fake terminal
chrome, or raw privacy values. Privacy exclusions stay understandable as
counts-only panels.

## 13. Upload / lifecycle

The pipeline may be shown as Upload → Profile → Validate → Clean →
Analyze → Dashboard, mapped honestly onto existing lifecycle states only.
No invented percentages. Static status distinction: complete / active /
pending / blocked-or-failed. Pulsing or animated active stages are not
required. Process-line rendering (Impeccable-adjudicated): border-divided
segments (never text-arrow glyphs that break mid-wrap), current step with
accent edge plus `aria-current="step"`, done steps muted with check marks;
terminal FAILED / EXPIRED states render as a separate status line, never as
a further pipeline step.

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

Rendered adjudication 2026-09-29: a source-only heuristic flagged nav
buttons as missing `focus-visible:ring-*`, but live measurement shows
focusing a nav button produces a visible inset accent underline via
box-shadow (custom visible focus, not `outline: none` without replacement).
Not a defect. Implementation must still verify the `focus-ring` token role
(§3) against measured contrast and keyboard traversal; heuristics never
override rendered evidence. No router/URL-state migration: state-based
navigation is binding architecture, and the guidelines' deep-link advice is
subordinate to it.

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

## 20. Rendered baseline audit (2026-09-29, READY synthetic session)

Dataset: locally generated synthetic CSV (200 lines, 120 orders, invented
SYN- IDs, no personal data) uploaded through the real UI in an isolated
browser; reference 95.9 MB file deliberately NOT used. Viewports 1440×900,
768×1024, 375×812 via Playwright MCP; screenshots kept outside Git.

Card-soup classification: filter toolbar (A useful containment, restyle as
strip); headline KPI strip (A, already one shared boundary); per-section
chart+table cards (B redundant nesting + C visually repetitive — same
radius/border/weight for every section, weakest hierarchy in the app);
per-view definitions disclosures (D semantically meaningful, keep);
cancellation-context mini-strip (E removable as separate card — fold into
adherence section as context rows). Target hierarchy: workspace → section
rule + eyebrow → analytical content (strip / table sheet / chart frame).

Observed strengths to keep: question-led section copy; status-scope lines
under every headline; chart+table fallback pairing with honest
unavailable-gap handling; 2-column KPI strip and internally-scrolling
tables at 375px with zero page-level horizontal overflow; dot-plus-text
session badge; association-only Diagnostics caveats; native
select/details/table semantics throughout.

## 21. Component targets (KEEP / CHANGE / DO NOT CHANGE)

- AppShell / navigation / session badge: KEEP structure and semantics;
  CHANGE surface treatment only (structural edges, hard geometry,
  active-state rule). DO NOT CHANGE labels, order, top-nav architecture.
- UploadSession / SessionLifecycle: KEEP honest pipeline semantics and
  literal backend states; CHANGE intake framing toward a technical panel
  (file spec, 250 MB limit, local-only note stay prominent). DO NOT CHANGE
  state names or invent percentages.
- KpiStrip: KEEP selection-by-ID, labels, values, definitions,
  unavailable/negative-profit semantics, role=status; CHANGE frame to one
  sharp-edged strip with dividers and tighter label/value rhythm.
- FilterBar: DO NOT CHANGE the eight-filter semantics, tokens, or
  persistence; CHANGE toolbar surface only.
- Charts (Recharts): DO NOT CHANGE library, series semantics, or fallbacks;
  CHANGE frame treatment (calm plotting area, low-noise grid, technical
  tooltip, visible labels); primary stays light-blue, secondary slate.
- AnalyticalTable / ScrollTable: DO NOT CHANGE columns, sorting, or
  overflow behavior; CHANGE header/frame sharpness. The thin shared shell
  (§10) covers both existing patterns — no new table engine.
- DataQualityView / DiagnosticsView / ExportSection: KEEP all vocabulary,
  caveats, and the four export kinds; CHANGE toward ledger/inspection-sheet
  register (§12) and flatter context grouping.

building-components assessment: YES — the redesign implements through
tokens, classes, and thin presentation changes within existing boundaries
(AppShell, KpiStrip, FilterBar, AnalyticalTable, DataQualityView,
SessionLifecycle). No compound-component or engine refactor without a
demonstrated need; the one consolidation (ScrollTable duplication) is
already authorized in §10.

## 22. Implementation slices (plan only, not executed)

- Slice A: tokens + shell + typography/geometry foundation (§§3–5).
- Slice B: KPI strip + filters + controls (§§8, 11).
- Slice C: charts + analytical tables (§§9–10).
- Slice D: Data Quality + lifecycle (§§12–13).
- Slice E: Diagnostics + exports + upload (§§13–14 targets in §21).
- Slice F: rendered acceptance at 1440/768/375 + minimal fixes (§16).
Each slice stays reviewable, preserves behavior and full regression, and
introduces no semantic change or broad refactor.

## 23. Pass record and adjudication

Tools: Playwright MCP (primary rendered evidence, all viewports + focus
and overflow measurement); web-design-guidelines (fresh fetch, applied to
AppShell/KpiStrip — two disagreements recorded and resolved under
governance in §16); building-components (boundary assessment: YES);
Graft (structural context: existing shells/boundaries confirmed); shadcn
MCP read-only (four primitives classified, nothing installed).

Impeccable adjudication 2026-09-29 (recovery pass): official integration
confirmed at impeccable.style (OpenCode supported via `npx skills add
pbakaus/impeccable`, installed v4.4.0 machine-global to
`~/.agents/skills/impeccable`, repo untouched, telemetry/update checks
disabled via DO_NOT_TRACK=1). Assessment A (isolated expert review via
subagent, Operate mode, 25/40 heuristics) challenged every candidate
decision and produced five adjudicated findings, all incorporated above:
binding frame budget + novelty tripwire (§5), KPI label case/wrap rule (§8),
table-shell class contract (§10), active-filter summary (§11), segmented
lifecycle rendering (§13). Assessment B (local `impeccable detect` on
frontend components) returned zero findings; alleged uppercase/truncate
instances were verified by direct source read and scoped by the §8 rule.
Privacy: local-only critique (rendered evidence + presentation source +
contract text); no DataCo bytes, session data, or screenshots transmitted —
Impeccable's own network surface (version check, catalog roll, choice
reporting) was disabled or never invoked. OPEN DECISION from the prior pass
is CLOSED: the substitute critique is superseded by this real one; Slice A
may proceed subject to normal review.
