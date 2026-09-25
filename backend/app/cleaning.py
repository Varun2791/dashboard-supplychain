"""Phase-7 auditable cleaning: approved reversible transforms only.

Detection is NOT authorization to clean. Exactly one value transformation
exists here, governed by DQ-CAT-005 (INFO, catalogue treatment ``fixed``):
trim leading/trailing whitespace on the governed label fields
(``LABEL_FIELDS + ENUM_FIELDS`` from :mod:`app.profile_checks`, the same set
profiling reports under DQ-CAT-005). Everything else is retained and
flagged/excluded/unchanged per the rule matrix below.

Rule matrix (from ``docs/data-quality-rules.md``; severity never implies
authorization — only ``Auto-transform: yes`` does):

- TRANSFORM: DQ-CAT-005 (trim governed labels; count logged). The rule as
  written covers the whitespace aspect of every padded in-scope cell —
  including cells whose trimmed value stays outside a governed enum set.
  Whitespace (CAT-005, fixed) and domain membership (DQ-CAT-001/002/003,
  flagged) are independent findings with independent treatments on the same
  cell: trimming ``" Rocket "`` to ``"Rocket"`` removes whitespace without
  coercing the value into a known category (it stays unknown and flagged).
  No "unknown takes precedence" rule exists in governance. Profiling's
  bucketing (padded-known reported under CAT-005, padded-unknown under the
  enum rule) avoids double-counting detection root causes; cleaning acts on
  the whitespace aspect wherever padding exists. CAT-005 audit populations
  are therefore defined at clean time (cell grain), and may exceed the
  profiling CAT-005 row count — documented, not hidden.
- EXCLUDE (projection, not a mutation): DQ-PRIVACY-001/002 — personal and
  precise-geo columns never materialize in the cleaned representation; the
  raw keeps them. Unknown/redundant columns are likewise projected out
  (DQ-SCHEMA-003 treatment, header-level, no value change).
- FLAG ONLY (retained unresolved): DQ-KEY-001 (duplicate item IDs are never
  deduped — no keep-first/keep-last), DQ-DATE-001/002/003, DQ-NUM-001/002/003
  (net stays authoritative, negatives retained per ADR-017),
  DQ-CAT-001/002/003 (unknown enums never coerced — values retained exactly,
  whitespace trim aside), DQ-GRAIN-001 (no first-row pick),
  DQ-GRAIN-003/DQ-GRAIN-004 (no representative product/customer value,
  ADR-036),
  DQ-BUSINESS-002/003 (day fields authoritative per ADR-015;
  ``Late_delivery_risk`` audit-only per ADR-018/030).
- UNCHANGED (informational, no action): DQ-KEY-002/003, DQ-DATE-004.
  (DQ-NUM-004 and DQ-FILE-005 take no cleaning step: NUM-004 is deferred to
  KPI analysis and was never evaluated for this session; FILE-005 is the
  passed staging gate, not a data rule.)
- DEFERRED TO LATER STAGE (no cleaning step): DQ-SCHEMA-001/002 (header
  gates, already decided), DQ-SCHEMA-004 (no governed pairings),
  DQ-CAT-004 (delivery domain beyond the cancel signal ungoverned),
  DQ-GRAIN-002 and DQ-BUSINESS-001 (need built canonical tables),
  DQ-BUSINESS-004 (design review gate), DQ-PRIVACY-003 (export gate),
  DQ-NUM-004 (KPI-slice guard).

Deliberate non-transformations (PLAN Phase-7 tasks investigated, no-op):

- Identifier/postal string casts: staging already yields pyarrow-backed
  strings, so IDs stay strings with no change; there is no canonical postal
  field (destination ZIP excluded by privacy), hence nothing to cast.
- Exact enum mapping: exact-map happens at canonicalization (Phase 8).
  Cleaning only trims; unknown values stay unknown and byte-identical.
- Fully-null/constant columns and duplicate-semantic copies: profile
  statistics only, no governing DQ rule — exclusion from canonical output
  belongs to Phase 8, not cleaning.
- ``delivery_status`` whitespace: outside the profiling CAT-005 field set,
  so untouched here (governance gap noted in the final report, not guessed).
- Money/date/delivery/leakage fields: untouched (ADR-008/015/017/018).

Outputs (all under ``derived/``; ``raw.csv`` never written):

- ``cleaned.csv`` (internal derived working file, not a public contract):
  authorized by architecture section 4 ("Derived/working: rebuilt
  deterministically from raw + code version"). It carries governed
  required/optional columns in source order with original source headers
  (minimal transformation: CAT-005 cell trims plus column projection only),
  same row order and row count. It is never served over HTTP and no
  API/export contract names it; Phase 8 remains free to define its own
  canonical inputs. Provenance is positional correspondence with the raw
  (same order, same count — both asserted) plus recorded alignment metadata
  (``inputSourceRows == outputRows``, ``outputSha256``): sufficient for
  Phase 8 to verify index alignment before materializing its own
  ``source_row_number`` canonical field. No index column is invented here,
  and no business key is created.
- ``cleaning_report.json``: per-rule/field audit steps plus totals, money
  reconciliation (trim-only cleaning must not move totals), and output
  identity. The public ``GET cleaning-report`` projects ``steps`` exactly.

Lifecycle: success advances ``CLEANING -> CANONICALIZING`` and chains the
Phase-8 canonicalization worker inline, so cleaned sessions settle at
ANALYZING (or park at CANONICALIZING behind a governed quality gate).
Travelling ERRORs
(DQ-KEY-001, DQ-DATE-001, DQ-GRAIN-001, DQ-GRAIN-003, DQ-GRAIN-004) name the
exact downstream stage they gate and travel with the session; they do not
stop cleaning, mirroring the Phase-6 precedent. Terminal failure follows
ADR-028 (raw/derived removal, manifest-only error metadata).

Execution model: synchronous workers run through the existing
framework-local post-response runner (chained from profiling). Single
application process; an in-process guard prevents duplicate cleaning of one
session; atomic writes with unique temp names; CAS manifest touching.
Resource discipline (ADR-027): one governed-column staging read, one working
copy for the trim (documented — a copy is required to keep the pre-image
for reconciliation), vectorized masks, intermediates released. No chunking,
no new dependencies.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal

import pandas as pd

from app import sessions as session_store
from app.config import settings
from app.ingestion_errors import (
    INTERNAL_STAGE_ERROR,
    STAGE_CLEANING,
    IngestionError,
)
from app.profile_checks import (
    ENUM_FIELDS,
    LABEL_FIELDS,
    MONEY_FIELDS,
    RULES,
    ProfileInputs,
    stripped,
)
from app.profiling import build_profile_inputs, read_staged_frame, sha256_file
from app.schema_validation import read_source_headers, strip_session_payloads
from app.schemas import (
    STATE_CANONICALIZING,
    STATE_CLEANING,
    STATE_FAILED,
    ApiErrorModel,
    CleaningArtifact,
    CleaningStep,
    CleaningTotals,
    MoneyReconciliation,
    SessionManifest,
)

logger = logging.getLogger(__name__)

# Governed trim scope: the canonical-schema "string trimmed" labels plus the
# "trimmed, case-sensitive" enum fields (the profiling DQ-CAT-005 field set).
# Authority per field: destination_country/region/market, department_name,
# category_name, product_name ("string trimmed", canonical-schema section 1;
# "trimmed labels", section 9); order_status, shipping_mode,
# customer_segment ("mapped exactly (trimmed, case-sensitive)", section 7).
# delivery_status carries no "trimmed" annotation and profiling excludes it
# from CAT-005, so it is NOT trimmed here (governance gap noted, not guessed).
TRIM_SCOPE: tuple[str, ...] = LABEL_FIELDS + ENUM_FIELDS

# The exact enforced enum sets live in profile_checks (ORDER_STATUS_VALUES,
# SHIPPING_MODE_VALUES, CUSTOMER_SEGMENT_VALUES). Cleaning never consults
# them — whitespace is trimmed regardless of domain membership, and unknown
# values stay unknown and flagged under their CAT-001/002/003 rule.

# Cleaning dispositions for every PROFILING-evaluated data rule. Only
# DQ-CAT-005 transforms; privacy rules exclude by projection; the
# informational set is unchanged; everything else evaluated is flagged.
# DQ-FILE-005 (the passed staging read) takes no cleaning step.
_EXCLUDED_RULES: frozenset[str] = frozenset({"DQ-PRIVACY-001", "DQ-PRIVACY-002"})
_UNCHANGED_RULES: frozenset[str] = frozenset(
    {"DQ-KEY-002", "DQ-KEY-003", "DQ-DATE-004"}
)
_FIXED_RULES: frozenset[str] = frozenset({"DQ-CAT-005"})


def trim_scope(col_of: dict[str, str]) -> dict[str, None]:
    """Governed trim fields present in this session's mapping.

    Every padded non-missing cell in these fields is CAT-005 eligible,
    regardless of enum-domain membership (whitespace and domain findings are
    independent; see the module rule matrix).
    """
    return {canonical: None for canonical in TRIM_SCOPE if canonical in col_of}


def padding_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    """Cells with leading/trailing whitespace eligible for CAT-005 trimming.

    Whitespace is leading/trailing generic whitespace as removed by Python
    ``str.strip()`` (ASCII spaces, tabs, newlines, and other Unicode
    whitespace): governance says "leading/trailing whitespace" without an
    implementation-specific definition, and this is the documented reading.
    Whitespace-only cells are missing (not padded) and never touched;
    internal whitespace is never altered.
    """
    raw = frame[column].astype(str)
    vals = stripped(frame, column)
    return (vals != "") & (raw != vals)


def apply_trims(
    frame: pd.DataFrame, inputs: ProfileInputs
) -> tuple[pd.DataFrame, dict[str, int], int]:
    """Return (cleaned, fixed_cells_by_field, rows_fixed).

    One working copy is required to keep the pre-image for reconciliation
    and the no-touch proof on non-trim columns. Only in-scope padded cells
    change; internal whitespace, case, and every other column are preserved.
    """
    scope = trim_scope(inputs.col_of)
    masks = {
        canonical: padding_mask(frame, inputs.col_of[canonical]) for canonical in scope
    }
    cleaned = frame.copy(deep=True)
    fixed_by_field: dict[str, int] = {}
    for canonical, mask in masks.items():
        fixed_by_field[canonical] = int(mask.sum())
        if fixed_by_field[canonical]:
            column = inputs.col_of[canonical]
            cleaned.loc[mask, column] = stripped(frame, column)[mask]
    rows_fixed = 0
    if masks:
        combined = masks[next(iter(masks))].copy()
        for mask in list(masks.values())[1:]:
            combined = combined | mask
        rows_fixed = int(combined.sum())
    return cleaned, fixed_by_field, rows_fixed


def decimal_sums(frame: pd.DataFrame, inputs: ProfileInputs) -> dict[str, Decimal]:
    """Decimal sums of governed money fields over strictly valid values."""
    from app.profile_checks import parse_money_valid, to_decimal_or_none

    sums: dict[str, Decimal] = {}
    for canonical in MONEY_FIELDS:
        if canonical not in inputs.col_of:
            continue
        vals = stripped(frame, inputs.col_of[canonical])
        valid = parse_money_valid(vals)
        total = Decimal("0")
        for text in vals[valid].tolist():
            parsed = to_decimal_or_none(str(text).strip())
            if parsed is not None:
                total += parsed
        sums[canonical] = total
    return sums


def _money_str(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.00")), "f")


def build_steps(
    detected_by_rule: dict[str, int],
    evaluated: list[str],
    fixed_by_field: dict[str, int],
    col_of: dict[str, str],
) -> list[CleaningStep]:
    """Audit steps for every evaluated data rule (zeros where clean).

    Accounting invariant per step: detected == fixed + flagged + excluded +
    unchanged. Unaffected rows are never counted. CAT-005 steps are
    cell-grain (one per governed trim field); all other steps carry the
    profiling rule-level count in a single disposition.
    """
    _ = col_of  # field names come from the governed RULES catalogue.
    steps: list[CleaningStep] = []
    for rule_id in evaluated:
        if rule_id == "DQ-FILE-005":
            continue  # passed ingestion gate; no cleaning step.
        meta = RULES.get(rule_id)
        if meta is None:
            continue  # deferred rules take no cleaning step.
        detected = detected_by_rule.get(rule_id, 0)
        field = ",".join(meta.fields)
        if rule_id in _FIXED_RULES:
            for canonical in trim_scope(col_of):
                fixed = fixed_by_field.get(canonical, 0)
                # Per-field detected is recomputed at clean time (cell grain);
                # every padded in-scope cell is trimmed, so flagged is zero.
                steps.append(
                    CleaningStep(
                        ruleId=rule_id,
                        field=canonical,
                        detected=fixed,
                        fixed=fixed,
                        flagged=0,
                        excluded=0,
                        unchanged=0,
                        reason=(
                            f"Trimmed leading/trailing whitespace in governed "
                            f"label field '{canonical}'; {fixed} cell(s) "
                            f"changed. Internal whitespace and case preserved."
                            if fixed
                            else (
                                f"No leading/trailing whitespace in governed "
                                f"label field '{canonical}'; nothing changed."
                            )
                        ),
                    )
                )
            continue
        if rule_id in _EXCLUDED_RULES:
            steps.append(
                CleaningStep(
                    ruleId=rule_id,
                    field=field,
                    detected=detected,
                    fixed=0,
                    flagged=0,
                    excluded=detected,
                    unchanged=0,
                    reason=(
                        f"{detected} source column(s) excluded from the "
                        f"cleaned representation by projection; retained in "
                        f"immutable raw only. Values never read."
                        if detected
                        else "No excluded columns present; nothing projected out."
                    ),
                )
            )
            continue
        if rule_id in _UNCHANGED_RULES:
            steps.append(
                CleaningStep(
                    ruleId=rule_id,
                    field=field,
                    detected=detected,
                    fixed=0,
                    flagged=0,
                    excluded=0,
                    unchanged=detected,
                    reason=(
                        f"{detected} informational observation(s) intentionally "
                        f"leave the source value unchanged."
                        if detected
                        else "No such observation; nothing to retain."
                    ),
                )
            )
            continue
        blocked = (
            f" Blocks {meta.blocked_stage} until the input is fixed or replaced."
            if meta.blocked_stage is not None
            else ""
        )
        steps.append(
            CleaningStep(
                ruleId=rule_id,
                field=field,
                detected=detected,
                fixed=0,
                flagged=detected,
                excluded=0,
                unchanged=0,
                reason=(
                    f"{detected} observation(s) retained without change for "
                    f"investigation; no approved transformation exists."
                    f"{blocked}"
                    if detected
                    else "No issue detected; nothing flagged."
                ),
            )
        )
    return steps


def _fail_cleaning(
    paths: session_store.SessionPaths,
    manifest: SessionManifest,
    error: IngestionError,
    now_iso: str,
) -> SessionManifest:
    """Terminal cleaning failure: ADR-028 raw/derived removal, metadata kept."""
    strip_session_payloads(paths)
    transitioned = manifest.model_copy(
        update={
            "state": STATE_FAILED,
            "stage": STAGE_CLEANING,
            "error": ApiErrorModel(
                code=error.code,
                stage=error.stage,
                message=error.message,
                details=error.details,
            ),
            "updatedAt": now_iso,
            "lastAccessedAt": now_iso,
        }
    )
    try:
        session_store.write_manifest(paths, transitioned)
    except OSError:
        return manifest
    logger.info("cleaning_failed code=%s", error.code)
    return transitioned


def _artifact_matches_session(
    stored: CleaningArtifact,
    manifest: SessionManifest,
    paths: session_store.SessionPaths,
) -> bool:
    """Provenance gate before adopting an on-disk cleaning artifact.

    Stored metadata is never trusted on its own: the cleaned output SHA is
    recomputed and compared (a corrupt ``cleaned.csv`` fails adoption and
    falls through to a full recompute), and the live profiling artifact must
    match the recorded Phase-6 input identity (``profiledAt`` + source rows),
    so a stale foreign report cannot be adopted. App/schema versions pin the
    code whose rule set produced the artifact (no separate cleaning-rule
    version exists; the rule set is code, so the app version governs).
    """
    if not (
        stored.sessionId == manifest.sessionId
        and stored.sourceSha256 == manifest.sha256
        and stored.appVersion == settings.app_version
        and stored.schemaVersion == settings.schema_version
        and stored.outputRows == stored.inputSourceRows
        and session_store.read_schema_report(paths) is not None
        and os.path.isfile(paths.raw)
        and os.path.isfile(session_store.cleaned_path(paths))
    ):
        return False
    profile = session_store.read_profiling_report(paths)
    if (
        profile is None
        or profile.profiledAt != stored.inputProfiledAt
        or profile.sourceRows != stored.inputSourceRows
    ):
        return False
    try:
        if sha256_file(session_store.cleaned_path(paths)) != stored.outputSha256:
            return False
    except OSError:
        return False
    return True


def _write_cleaned_csv(frame: pd.DataFrame, final_path: str) -> None:
    """Write the cleaned frame atomically via a unique temp sibling."""
    tmp_path = f"{final_path}.{os.urandom(8).hex()}.tmp"
    try:
        frame.to_csv(tmp_path, index=False, encoding="utf-8", lineterminator="\n")
        os.replace(tmp_path, final_path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def ensure_cleaned(
    paths: session_store.SessionPaths, manifest: SessionManifest, now_iso: str
) -> SessionManifest:
    """Run Phase-7 cleaning once if still pending; otherwise return stored.

    Success parks the session at CANONICALIZING (no canonicalization runs).
    Travelling ERRORs gate their named downstream stage and do not stop
    cleaning. Never mutates raw; verified by SHA before and after.
    """
    if manifest.state != STATE_CLEANING or manifest.cleaningArtifact is not None:
        return manifest
    stored = session_store.read_cleaning_report(paths)
    if stored is not None and _artifact_matches_session(stored, manifest, paths):
        transitioned = manifest.model_copy(
            update={
                "state": STATE_CANONICALIZING,
                "stage": STATE_CANONICALIZING,
                "progress": session_store.make_canonicalizing_progress(),
                "cleaningArtifact": (
                    f"{session_store.DERIVED_DIRNAME}/"
                    f"{session_store.CLEANING_ARTIFACT_FILENAME}"
                ),
                # A torn manifest carrying a stale canonical pointer must
                # rebuild it, never adopt it.
                "canonicalArtifact": None,
                "kpiArtifact": None,
                "error": None,
                "updatedAt": now_iso,
                "lastAccessedAt": now_iso,
            }
        )
        try:
            session_store.write_manifest(paths, transitioned)
        except OSError:
            return manifest
        logger.info("cleaning_adopted")
        return transitioned

    report = session_store.read_schema_report(paths)
    profile_artifact = session_store.read_profiling_report(paths)
    if report is None or profile_artifact is None:
        return _fail_cleaning(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CLEANING,
                "The profiling evidence could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    if not os.path.isfile(paths.raw):
        return _fail_cleaning(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CLEANING,
                "The stored upload could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    sha_before = sha256_file(paths.raw)
    if sha_before != manifest.sha256:
        return _fail_cleaning(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CLEANING,
                "The stored upload failed its integrity check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    inputs = build_profile_inputs(report)
    governed = set(inputs.col_of.values())
    if inputs.audit_header is not None:
        governed.add(inputs.audit_header)
    try:
        staged_headers = read_source_headers(paths.raw, manifest.encoding)
    except OSError:
        logger.warning("cleaning_header_io_error")
        return _fail_cleaning(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CLEANING,
                "The stored upload could not be read. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    if staged_headers != report.sourceColumns:
        return _fail_cleaning(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CLEANING,
                "The stored upload failed its integrity check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    # Cleaned output carries governed required/optional columns only, in
    # source order with original headers. Audit-only, redundant, unknown,
    # and excluded columns stay raw-only (projection, not a mutation).
    cleaned_columns = [c for c in report.sourceColumns if c in inputs.col_of.values()]
    try:
        working = read_staged_frame(
            paths.raw,
            manifest.encoding,
            [c for c in report.sourceColumns if c in governed],
        )
    except IngestionError as exc:
        return _fail_cleaning(paths, manifest, exc, now_iso)
    try:
        sums_pre = decimal_sums(working, inputs)
        cleaned_full, fixed_by_field, rows_fixed = apply_trims(working, inputs)
        # Self-checks: only trim-scope cells may differ; money must reconcile.
        trim_columns = {inputs.col_of[c] for c in trim_scope(inputs.col_of)}
        untouched = [c for c in working.columns if c not in trim_columns]
        if not working[untouched].equals(cleaned_full[untouched]):
            raise ValueError("non-trim column changed during cleaning")
        sums_post = decimal_sums(cleaned_full, inputs)
        if sums_pre != sums_post:
            raise ValueError("money reconciliation mismatch after cleaning")
        cleaned = cleaned_full[cleaned_columns]
        del cleaned_full
        _write_cleaned_csv(cleaned, session_store.cleaned_path(paths))
        del cleaned
        # Raw immutability proof: SHA unchanged across the cleaning pass.
        if sha256_file(paths.raw) != manifest.sha256:
            raise ValueError("raw changed during cleaning")
    except ValueError:
        logger.warning("cleaning_self_check_failed")
        return _fail_cleaning(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CLEANING,
                "Cleaning failed its consistency check. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    except OSError:
        # Artifact write failure: leave the session rerunnable (no false claim).
        return manifest
    except Exception:  # never leak values; terminal per ADR-028
        logger.warning("cleaning_unexpected_error")
        return _fail_cleaning(
            paths,
            manifest,
            IngestionError(
                INTERNAL_STAGE_ERROR,
                STAGE_CLEANING,
                "The upload could not be cleaned. Upload the file again.",
                500,
                {},
            ),
            now_iso,
        )
    detected_by_rule = {issue.ruleId: issue.count for issue in profile_artifact.issues}
    steps = build_steps(
        detected_by_rule,
        list(profile_artifact.rulesEvaluated),
        fixed_by_field,
        inputs.col_of,
    )
    rows = int(len(working))
    del working
    cat_detected_rows = detected_by_rule.get("DQ-CAT-005", 0)
    output_path = session_store.cleaned_path(paths)
    artifact = CleaningArtifact(
        sessionId=manifest.sessionId,
        appVersion=settings.app_version,
        schemaVersion=settings.schema_version,
        sourceSha256=manifest.sha256,
        inputProfileArtifact=(
            f"{session_store.DERIVED_DIRNAME}/"
            f"{session_store.PROFILING_ARTIFACT_FILENAME}"
        ),
        inputProfiledAt=profile_artifact.profiledAt,
        inputSourceRows=profile_artifact.sourceRows,
        rulesEvaluated=list(profile_artifact.rulesEvaluated),
        steps=steps,
        totals=CleaningTotals(
            rows=rows,
            # Profiling population (padded-known/label rows; padded-unknown
            # enum cells are attributed to CAT-001/002/003 there). Cleaning
            # trims every padded in-scope cell, so rowsFixed may exceed it.
            rowsWithPaddingDetected=cat_detected_rows,
            rowsFixed=rows_fixed,
            cellsFixed=sum(fixed_by_field.values()),
            fieldsTrimmed=sum(1 for v in fixed_by_field.values() if v),
        ),
        reconciliation=MoneyReconciliation(
            grossPre=_money_str(sums_pre.get("gross_sales", Decimal("0"))),
            grossPost=_money_str(sums_post.get("gross_sales", Decimal("0"))),
            discountPre=_money_str(sums_pre.get("discount_amount", Decimal("0"))),
            discountPost=_money_str(sums_post.get("discount_amount", Decimal("0"))),
            netPre=_money_str(sums_pre.get("net_sales", Decimal("0"))),
            netPost=_money_str(sums_post.get("net_sales", Decimal("0"))),
            profitPre=_money_str(sums_pre.get("profit_amount", Decimal("0"))),
            profitPost=_money_str(sums_post.get("profit_amount", Decimal("0"))),
        ),
        outputArtifact=(
            f"{session_store.DERIVED_DIRNAME}/{session_store.CLEANED_FILENAME}"
        ),
        outputSha256=sha256_file(output_path),
        outputBytes=os.path.getsize(output_path),
        outputRows=rows,
        cleanedAt=now_iso,
    )
    try:
        session_store.write_cleaning_report(paths, artifact)
    except OSError:
        return manifest
    transitioned = manifest.model_copy(
        update={
            "state": STATE_CANONICALIZING,
            "stage": STATE_CANONICALIZING,
            "progress": session_store.make_canonicalizing_progress(),
            "cleaningArtifact": (
                f"{session_store.DERIVED_DIRNAME}/"
                f"{session_store.CLEANING_ARTIFACT_FILENAME}"
            ),
            # Fresh cleaning output invalidates any downstream build.
            "canonicalArtifact": None,
            "kpiArtifact": None,
            "error": None,
            "updatedAt": now_iso,
            "lastAccessedAt": now_iso,
        }
    )
    try:
        session_store.write_manifest(paths, transitioned)
    except OSError:
        return manifest
    logger.info(
        "cleaned rows=%d cells_fixed=%d",
        rows,
        sum(fixed_by_field.values()),
    )
    return transitioned


__all__ = [
    "apply_trims",
    "build_steps",
    "decimal_sums",
    "ensure_cleaned",
    "padding_mask",
    "recover_cleaning_sessions",
    "run_cleaning",
    "trim_scope",
]


_CLEANING_IN_PROGRESS: set[str] = set()


def run_cleaning(session_id: str) -> SessionManifest | None:
    """Execute one cleaning pass for a session (pipeline/recovery body).

    On success the Phase-8 canonicalization worker is chained inline (same
    framework-local runner, which in turn chains Phase-9 KPI analysis):
    cleaned sessions therefore settle at READY once all steps complete,
    or park at CANONICALIZING behind a governed quality gate. Safe against
    reset races: a deleted session (no manifest) is a no-op and is never
    resurrected. Returns the resulting manifest, or None when there was
    nothing to do.
    """
    if not session_store.is_valid_session_id(session_id):
        return None
    if session_id in _CLEANING_IN_PROGRESS:
        return None
    _CLEANING_IN_PROGRESS.add(session_id)
    try:
        paths = session_store.session_paths(settings.session_root, session_id)
        manifest = session_store.read_manifest(paths)
        if manifest is None:
            return None
        result = ensure_cleaned(paths, manifest, session_store.utcnow_naive_iso())
        if result.state == STATE_CANONICALIZING and result.cleaningArtifact is not None:
            # Local import: canonicalization owns the reverse dependency.
            from app.canonicalization import run_canonicalization

            canonicalized = run_canonicalization(session_id)
            return canonicalized if canonicalized is not None else result
        return result
    finally:
        _CLEANING_IN_PROGRESS.discard(session_id)


def recover_cleaning_sessions(session_root: str) -> int:
    """Startup recovery: clean leftover CLEANING sessions, count them.

    Covers the crash window between profiling success and cleaning
    completion. Only leftover CLEANING sessions are picked up here; the
    pipeline chain continues through the implemented downstream workers,
    expired trees are left to the sweep, and valid resumable sessions are
    never deleted.
    """
    from datetime import datetime

    recovered = 0
    try:
        entries = sorted(os.listdir(session_root))
    except FileNotFoundError:
        return 0
    for entry in entries:
        if not session_store.is_valid_session_id(entry):
            continue
        paths = session_store.session_paths(session_root, entry)
        manifest = session_store.read_manifest(paths)
        if (
            manifest is None
            or manifest.state != STATE_CLEANING
            or manifest.cleaningArtifact is not None
        ):
            continue
        if session_store.read_cleaning_report(paths) is not None:
            continue
        if session_store.is_expired(manifest, datetime.now()):
            continue
        run_cleaning(entry)
        recovered += 1
    if recovered:
        logger.info("cleaning_recovery_cleaned=%d", recovered)
    return recovered
