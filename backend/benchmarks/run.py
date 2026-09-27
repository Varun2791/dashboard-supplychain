"""Benchmark run driver (ADR-042; measurement only).

Developer command::

    cd backend && uv run python -m benchmarks.run --tier small

Drives the real production pipeline (direct ``ensure_*`` stage chain plus
TestClient HTTP endpoints) against deterministic synthetic data, times each
observable stage externally with ``perf_counter``, and writes a JSON report
under ``.tmp/benchmarks/reports/``. Production modules are never modified;
per-stage timings live only in the report. No numeric thresholds asserted.

Only the ``small`` tier is executed in the measurement-infrastructure pass;
other tiers resolve as definitions.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import uuid
from pathlib import Path

from benchmarks.generator import (
    GENERATOR_VERSION,
    TIERS,
    GeneratedDataset,
    generate_dataset,
)
from benchmarks.measure import (
    Timer,
    collect_environment,
    git_revision,
    peak_rss_bytes,
)
from benchmarks.report import (
    build_report,
    default_reports_dir,
    default_scratch_dir,
    ensure_within_scratch,
    write_bytes_atomic,
    write_report,
)

DEFAULT_SEED = 20260926
RUN_LABEL = "DEVELOPMENT-SCALE OBSERVATION — NOT PHASE-17 ACCEPTANCE RESULT"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a synthetic benchmark tier.")
    parser.add_argument("--tier", default="small", choices=sorted(TIERS))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--profile", default="valid")
    parser.add_argument("--rows", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--keep-sessions", action="store_true")
    return parser.parse_args(argv)


def _drive_stage_chain(
    content: bytes, session_dir: str, filename: str
) -> tuple[str, dict[str, float]]:
    """Run the production stage chain; return (session_id, stage_seconds)."""
    import app.sessions as session_store
    from app.canonicalization import ensure_canonicalized
    from app.cleaning import ensure_cleaned
    from app.config import settings
    from app.kpis import ensure_kpis_analyzed
    from app.profiling import ensure_profiled
    from app.schema_validation import ensure_schema_validated

    settings.session_root = session_dir
    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_dir, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    with open(paths.raw, "wb") as handle:
        handle.write(content)
    now = session_store.utcnow_naive_iso()
    manifest = session_store.build_manifest(
        session_id=session_id,
        filename_safe=filename,
        size_bytes=len(content),
        sha256_hex=hashlib.sha256(content).hexdigest(),
        encoding="utf-8",
        now=now,
    )
    session_store.write_manifest(paths, manifest)

    stages: dict[str, float] = {}
    with Timer() as total:
        with Timer() as timer:
            manifest = ensure_schema_validated(paths, manifest, now)
        stages["validationDurationSeconds"] = timer.elapsed
        if manifest.state != "PROFILING":
            raise RuntimeError(
                f"Schema validation did not park at PROFILING: {manifest.state}"
            )
        with Timer() as timer:
            manifest = ensure_profiled(paths, manifest, now)
        stages["profilingDurationSeconds"] = timer.elapsed
        if manifest.state != "CLEANING":
            raise RuntimeError(f"Profiling did not park at CLEANING: {manifest.state}")
        with Timer() as timer:
            manifest = ensure_cleaned(paths, manifest, now)
        stages["cleaningDurationSeconds"] = timer.elapsed
        if manifest.state != "CANONICALIZING":
            raise RuntimeError(
                f"Cleaning did not park at CANONICALIZING: {manifest.state}"
            )
        with Timer() as timer:
            manifest = ensure_canonicalized(paths, manifest, now)
        stages["canonicalizationDurationSeconds"] = timer.elapsed
        if manifest.state != "ANALYZING":
            raise RuntimeError(
                f"Canonicalization did not park at ANALYZING: {manifest.state}"
            )
        with Timer() as timer:
            manifest = ensure_kpis_analyzed(paths, manifest, now)
        stages["kpiDurationSeconds"] = timer.elapsed
        if manifest.state != "READY":
            raise RuntimeError(f"KPI analysis did not reach READY: {manifest.state}")
    stages["readyDurationSeconds"] = total.elapsed
    return session_id, stages


def _get(client: object, url: str) -> tuple[int, float]:
    """GET via TestClient; return (status_code, elapsed seconds)."""
    from typing import cast

    from fastapi.testclient import TestClient

    test_client = cast(TestClient, client)
    with Timer() as timer:
        response = test_client.get(url)
    return response.status_code, timer.elapsed


def _cleanup_sessions(
    client: object | None, session_dir: str, session_ids: list[str]
) -> None:
    """Remove benchmark session trees best-effort; never raises."""
    if client is not None:
        from typing import cast

        from fastapi.testclient import TestClient

        test_client = cast(TestClient, client)
        for sid in session_ids:
            try:
                test_client.delete(f"/api/v1/sessions/{sid}")
            except Exception:  # noqa: BLE001 - best-effort scratch cleanup
                pass
    leftover = Path(session_dir)
    if leftover.is_dir():
        shutil.rmtree(leftover, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output_dir) if args.output_dir else default_scratch_dir()
    try:
        output_dir = ensure_within_scratch(output_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)

    with Timer() as timer:
        dataset: GeneratedDataset = generate_dataset(
            tier=args.tier, seed=args.seed, profile=args.profile, rows=args.rows
        )
    generation_seconds = timer.elapsed
    csv_name = (
        f"{dataset.config.tier}-seed{dataset.config.seed}-{dataset.config.profile}.csv"
    )
    csv_path = output_dir / csv_name
    try:
        ensure_within_scratch(csv_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    write_bytes_atomic(csv_path, dataset.content)

    session_dir = str(output_dir / "sessions")
    session_ids: list[str] = []
    client: object | None = None
    try:
        session_id, stages = _drive_stage_chain(dataset.content, session_dir, csv_name)
        session_ids.append(session_id)

        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        with Timer() as timer:
            upload_response = client.post(
                "/api/v1/sessions/uploads",
                files={"file": (csv_name, dataset.content, "text/csv")},
            )
        upload_post_seconds = timer.elapsed
        if upload_response.status_code != 202:
            print(
                f"error: upload returned {upload_response.status_code}",
                file=sys.stderr,
            )
            return 1
        upload_session_id = upload_response.json()["data"]["sessionId"]
        session_ids.append(upload_session_id)

        base = f"/api/v1/sessions/{session_id}"
        http_seconds: dict[str, float] = {}
        for metric, url in (
            ("overviewRequestDurationSeconds", f"{base}/kpis/overview"),
            ("deliveryRequestDurationSeconds", f"{base}/kpis/delivery"),
            ("commercialRequestDurationSeconds", f"{base}/kpis/commercial"),
            ("filterOptionsRequestDurationSeconds", f"{base}/filter-options"),
            ("ordersPageRequestDurationSeconds", f"{base}/orders"),
        ):
            status, elapsed = _get(client, url)
            if status != 200:
                print(f"error: {url} returned {status}", file=sys.stderr)
                return 1
            http_seconds[metric] = elapsed

        with Timer() as timer:
            export_response = client.post(f"{base}/exports", json={"kind": "orders"})
        export_generation_seconds = timer.elapsed
        if export_response.status_code != 201:
            print(
                f"error: export build returned {export_response.status_code}",
                file=sys.stderr,
            )
            return 1
        export_id = export_response.json()["data"]["exportId"]
        with Timer() as timer:
            download_response = client.get(f"{base}/exports/{export_id}")
        export_download_seconds = timer.elapsed
        if download_response.status_code != 200:
            print(
                f"error: export download returned {download_response.status_code}",
                file=sys.stderr,
            )
            return 1
        export_bytes = len(download_response.content)

        rss, rss_reason = peak_rss_bytes()
        environment = collect_environment()
        revision, dirty, git_reason = git_revision(
            str(Path(__file__).resolve().parents[2])
        )
        unavailable: dict[str, str] = {
            "diagnosticsRequestDurationSeconds": (
                "No dedicated backend diagnostics endpoint exists; diagnostic "
                "ranking is frontend presentation over delivery/commercial groups."
            ),
            "frontendBundleBytes": (
                "Frontend bundle measurement deferred; no browser-performance "
                "machinery in this pass and the harness must not conflate bundle "
                "bytes with runtime responsiveness."
            ),
        }
        if rss is None:
            unavailable["peakProcessRssBytes"] = rss_reason or "RSS unavailable"

        report = build_report(
            identity={
                "generatorVersion": GENERATOR_VERSION,
                "seed": dataset.config.seed,
                "tier": dataset.config.tier,
                "profile": dataset.config.profile,
                "requestedRows": dataset.config.rows,
                "actualRows": dataset.actual_rows,
                "sourceBytes": len(dataset.content),
                "sourceSha256": dataset.sha256,
            },
            environment={
                "appRevision": revision,
                "workingTreeDirty": dirty,
                "platform": environment["platform"],
                "architecture": environment["architecture"],
                "pythonVersion": environment["pythonVersion"],
                "nodeVersion": environment["nodeVersion"],
            },
            measurements={
                "generationDurationSeconds": generation_seconds,
                "uploadPostTestClientDurationSeconds": upload_post_seconds,
                "validationDurationSeconds": stages["validationDurationSeconds"],
                "profilingDurationSeconds": stages["profilingDurationSeconds"],
                "cleaningDurationSeconds": stages["cleaningDurationSeconds"],
                "canonicalizationDurationSeconds": stages[
                    "canonicalizationDurationSeconds"
                ],
                "kpiDurationSeconds": stages["kpiDurationSeconds"],
                "readyDurationSeconds": stages["readyDurationSeconds"],
                "overviewRequestDurationSeconds": http_seconds[
                    "overviewRequestDurationSeconds"
                ],
                "deliveryRequestDurationSeconds": http_seconds[
                    "deliveryRequestDurationSeconds"
                ],
                "commercialRequestDurationSeconds": http_seconds[
                    "commercialRequestDurationSeconds"
                ],
                "filterOptionsRequestDurationSeconds": http_seconds[
                    "filterOptionsRequestDurationSeconds"
                ],
                "ordersPageRequestDurationSeconds": http_seconds[
                    "ordersPageRequestDurationSeconds"
                ],
                "diagnosticsRequestDurationSeconds": None,
                "exportGenerationDurationSeconds": export_generation_seconds,
                "exportDownloadDurationSeconds": export_download_seconds,
                "peakProcessRssBytes": rss,
                "exportBytes": export_bytes,
                "frontendBundleBytes": None,
            },
            unavailable_reasons=unavailable,
            notes=[
                RUN_LABEL,
                "uploadPostTestClientDurationSeconds is the TestClient POST "
                "elapsed observation: the TestClient executes Starlette "
                "BackgroundTasks in this benchmark context, including the "
                "downstream pipeline, before returning. It does not measure "
                "production upload handling in a deployed server context.",
                "Individual stage durations are direct elapsed time around the "
                "production ensure_* functions; readyDurationSeconds is the "
                "wall elapsed around the direct ensure_* pipeline chain on its "
                "own session. Direct measurements exclude BackgroundTasks "
                "scheduling, threadpool dispatch, and status polling/request "
                "overhead, and must not be read as worker scheduling latency.",
                "HTTP endpoint timings are end-to-end local request elapsed time, "
                "not pure server compute.",
                "peakProcessRssBytes is process high-water RSS (ru_maxrss); it is "
                "environment-dependent and inter-stage deltas must not be read as "
                "per-stage memory consumption.",
                f"Stage chain ran in-process against production ensure_* functions; "
                f"no production timing fields were added. git: {revision} "
                f"(dirty={dirty}" + (f"; {git_reason}" if git_reason else "") + ").",
            ],
            request_config={
                "upload": {
                    "route": "/sessions/uploads",
                    "covers": "accept-through-READY-under-TestClient",
                    "notRealWorldAcceptLatency": True,
                },
                "overview": {"route": "/kpis/overview", "params": {}},
                "delivery": {"route": "/kpis/delivery", "params": {}},
                "commercial": {"route": "/kpis/commercial", "params": {}},
                "filterOptions": {"route": "/filter-options", "params": {}},
                "ordersPage": {"route": "/orders", "params": {"limit": "default"}},
                "export": {"route": "/exports", "kind": "orders", "filters": {}},
            },
        )
        reports_dir = default_reports_dir()
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = write_report(
            report,
            reports_dir
            / f"{dataset.config.tier}-seed{dataset.config.seed}.report.json",
        )

        print(f"rows={dataset.actual_rows} bytes={len(dataset.content)}")
        print(f"sha={dataset.sha256}")
        print(
            f"ready={stages['readyDurationSeconds']:.2f}s rss={rss} "
            f"report={report_path}"
        )
        return 0
    finally:
        if not args.keep_sessions:
            _cleanup_sessions(client, session_dir, session_ids)


if __name__ == "__main__":
    raise SystemExit(main())
