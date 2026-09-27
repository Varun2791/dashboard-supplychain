"""Reporting tests: schema, privacy, normalization, determinism of identity."""

from __future__ import annotations

import json

import pytest

from benchmarks.generator import GENERATOR_VERSION
from benchmarks.measure import normalize_ru_maxrss, peak_rss_bytes
from benchmarks.report import (
    ENVIRONMENT_FIELDS,
    IDENTITY_FIELDS,
    MEASUREMENT_FIELDS,
    build_report,
    scan_report_text,
    write_report,
)


def make_identity() -> dict[str, object]:
    return {
        "generatorVersion": GENERATOR_VERSION,
        "seed": 20260926,
        "tier": "small",
        "profile": "valid",
        "requestedRows": 5000,
        "actualRows": 5000,
        "sourceBytes": 123456,
        "sourceSha256": "ab" * 32,
    }


def make_environment() -> dict[str, object]:
    return {
        "appRevision": "rev",
        "workingTreeDirty": False,
        "platform": "Darwin",
        "architecture": "arm64",
        "pythonVersion": "3.12.0",
        "nodeVersion": None,
    }


def make_measurements() -> dict[str, float | int | None]:
    return {
        "generationDurationSeconds": 0.5,
        "uploadPostTestClientDurationSeconds": 1.5,
        "validationDurationSeconds": 0.1,
        "profilingDurationSeconds": 0.2,
        "cleaningDurationSeconds": 0.2,
        "canonicalizationDurationSeconds": 0.3,
        "kpiDurationSeconds": 0.1,
        "readyDurationSeconds": 1.0,
        "overviewRequestDurationSeconds": 0.05,
        "deliveryRequestDurationSeconds": 0.05,
        "commercialRequestDurationSeconds": 0.05,
        "filterOptionsRequestDurationSeconds": 0.02,
        "ordersPageRequestDurationSeconds": 0.03,
        "diagnosticsRequestDurationSeconds": None,
        "exportGenerationDurationSeconds": 0.2,
        "exportDownloadDurationSeconds": 0.01,
        "peakProcessRssBytes": 123456789,
        "exportBytes": 999,
        "frontendBundleBytes": None,
    }


def make_reasons() -> dict[str, str]:
    return {
        "diagnosticsRequestDurationSeconds": "no dedicated endpoint",
        "frontendBundleBytes": "deferred",
    }


def test_report_shape_is_structurally_fixed() -> None:
    report = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=make_measurements(),
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    assert set(report) == {
        "schemaVersion",
        "identity",
        "environment",
        "measurements",
        "unavailableReasons",
        "requestConfig",
        "notes",
    }
    assert set(report["identity"]) == set(IDENTITY_FIELDS)  # type: ignore[union-attr]
    assert set(report["environment"]) == set(ENVIRONMENT_FIELDS)  # type: ignore[union-attr]
    assert set(report["measurements"]) == set(MEASUREMENT_FIELDS)  # type: ignore[union-attr]


def test_report_rejects_missing_and_bad_metrics() -> None:
    identity = make_identity()
    identity.pop("seed")
    with pytest.raises(KeyError):
        build_report(
            identity=identity,
            environment=make_environment(),
            measurements=make_measurements(),
            unavailable_reasons=make_reasons(),
            notes=[],
            request_config={},
        )
    measurements = make_measurements()
    measurements.pop("diagnosticsRequestDurationSeconds")
    with pytest.raises(KeyError):
        build_report(
            identity=make_identity(),
            environment=make_environment(),
            measurements=measurements,
            unavailable_reasons=make_reasons(),
            notes=[],
            request_config={},
        )
    bad = make_measurements()
    bad["readyDurationSeconds"] = -1.0
    with pytest.raises(ValueError):
        build_report(
            identity=make_identity(),
            environment=make_environment(),
            measurements=bad,
            unavailable_reasons=make_reasons(),
            notes=[],
            request_config={},
        )


def test_report_scans_clean_for_rows_and_pii() -> None:
    report = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=make_measurements(),
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    forbidden = ["SYN-ITEM-", "SYN-ORDER-", "@example.invalid", "password", "buyer"]
    assert scan_report_text(report, forbidden) == []
    assert scan_report_text(report, ["small", "rev"]) != []


def test_rss_normalization() -> None:
    assert normalize_ru_maxrss(123, "darwin") == 123
    assert normalize_ru_maxrss(123, "linux") == 123 * 1024
    assert normalize_ru_maxrss(123, "win32") is None


def test_peak_rss_shape() -> None:
    rss, reason = peak_rss_bytes()
    if rss is None:
        assert isinstance(reason, str) and reason
    else:
        assert rss >= 0 and reason is None


def test_identity_stable_volatile_not_pinned() -> None:
    first_measurements = make_measurements()
    second_measurements = make_measurements()
    second_measurements["readyDurationSeconds"] = 9.99
    first = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=first_measurements,
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    second = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=second_measurements,
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    assert first["identity"] == second["identity"]
    assert first["measurements"] != second["measurements"]


def test_write_report_deterministic_and_scratch_guarded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=make_measurements(),
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    first_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    second_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    assert first_text == second_text
    with pytest.raises(ValueError):
        write_report(report, tmp_path / "outside.json")


def _scratch_monkeypatched(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import benchmarks.report as report_module

    monkeypatch.setattr(report_module, "default_scratch_dir", lambda: tmp_path)
    return tmp_path


def test_write_report_round_trips_valid_json(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _scratch_monkeypatched(tmp_path, monkeypatch)
    report = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=make_measurements(),
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    path = write_report(report, tmp_path / "reports" / "ok.report.json")
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert list(tmp_path.rglob("*.tmp")) == []


def _nan_measurements() -> dict[str, float | int | None]:
    measurements = make_measurements()
    measurements["readyDurationSeconds"] = float("nan")
    return measurements


def test_write_report_rejects_nan(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _scratch_monkeypatched(tmp_path, monkeypatch)
    report = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=_nan_measurements(),
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    with pytest.raises(ValueError):
        write_report(report, tmp_path / "reports" / "nan.report.json")


def test_write_report_rejects_infinities(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _scratch_monkeypatched(tmp_path, monkeypatch)
    positive = make_measurements()
    positive["readyDurationSeconds"] = float("inf")
    report = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=positive,
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    with pytest.raises(ValueError):
        write_report(report, tmp_path / "reports" / "inf.report.json")
    negative = make_measurements()
    negative["readyDurationSeconds"] = float("-inf")
    with pytest.raises(ValueError):
        build_report(
            identity=make_identity(),
            environment=make_environment(),
            measurements=negative,
            unavailable_reasons=make_reasons(),
            notes=[],
            request_config={},
        )


def test_failed_write_preserves_previous_valid_report(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _scratch_monkeypatched(tmp_path, monkeypatch)
    valid = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=make_measurements(),
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    path = write_report(valid, tmp_path / "reports" / "stable.report.json")
    before = path.read_bytes()
    invalid = build_report(
        identity=make_identity(),
        environment=make_environment(),
        measurements=_nan_measurements(),
        unavailable_reasons=make_reasons(),
        notes=[],
        request_config={},
    )
    with pytest.raises(ValueError):
        write_report(invalid, path)
    assert path.read_bytes() == before
    assert list(tmp_path.rglob("*.tmp")) == []


def test_write_bytes_atomic_round_trip(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from benchmarks.report import write_bytes_atomic

    _scratch_monkeypatched(tmp_path, monkeypatch)
    path = write_bytes_atomic(tmp_path / "data" / "bench.csv", b"a,b\n1,2\n")
    assert path.read_bytes() == b"a,b\n1,2\n"
    assert list(tmp_path.rglob("*.tmp")) == []
