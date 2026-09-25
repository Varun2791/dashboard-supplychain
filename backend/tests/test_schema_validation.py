"""Phase-5 compatibility, lifecycle, adversarial, and boundary tests.

All fixtures are synthetic and invented; no DataCo rows or personal data
enter the repository. A structurally valid non-DataCo CSV passes Phase 4
(202) and fails truthfully at Phase 5 — never the reverse.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response

import app.sessions as session_store
from app.config import settings
from app.main import app
from app.schema_validation import (
    recover_validating_sessions,
    run_schema_validation,
    validate_headers,
)

FIXTURE_BYTES = (
    Path(__file__).parent / "fixtures" / "v1_reference_synthetic.csv"
).read_bytes()

REQUIRED_SOURCE_HEADERS = [
    "Order Id",
    "Order Item Id",
    "Customer Id",
    "Product Card Id",
    "Product Category Id",
    "order date (DateOrders)",
    "shipping date (DateOrders)",
    "Sales",
    "Order Item Discount",
    "Order Item Total",
    "Benefit per order",
    "Order Item Product Price",
    "Order Item Quantity",
    "Days for shipping (real)",
    "Days for shipment (scheduled)",
    "Delivery Status",
    "Order Status",
    "Shipping Mode",
]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def post_csv(
    client: TestClient,
    filename: str,
    content: bytes,
    content_type: str = "text/csv",
) -> Response:
    return client.post(
        "/api/v1/sessions/uploads",
        files={"file": (filename, content, content_type)},
    )


def upload_ok(client: TestClient, content: bytes) -> str:
    response = post_csv(client, "data.csv", content)
    assert response.status_code == 202
    return response.json()["data"]["sessionId"]


def craft_validating_session(session_root: str, content: bytes) -> str:
    """A stored-but-unvalidated session: what POST persists pre-background."""
    session_id = str(uuid.uuid4())
    paths = session_store.session_paths(session_root, session_id)
    os.makedirs(paths.derived)
    os.makedirs(paths.exports)
    with open(paths.raw, "wb") as handle:
        handle.write(content)
    now = session_store.utcnow_naive_iso()
    manifest = session_store.build_manifest(
        session_id=session_id,
        filename_safe="data.csv",
        size_bytes=len(content),
        sha256_hex=hashlib.sha256(content).hexdigest(),
        encoding="utf-8",
        now=now,
    )
    session_store.write_manifest(paths, manifest)
    return session_id


def test_post_composes_202_before_validation_executes(
    client: TestClient, session_root: str
) -> None:
    """The 202 response is built pre-execution and claims VALIDATING."""
    response = post_csv(client, "dataco.csv", FIXTURE_BYTES)
    assert response.status_code == 202
    assert response.json()["meta"]["sessionState"] == "VALIDATING"


def test_validation_completes_without_any_polling(
    client: TestClient, session_root: str
) -> None:
    """Progress never depends on the browser: no GET was issued here."""
    session_id = upload_ok(client, FIXTURE_BYTES)
    manifest = session_store.read_manifest(
        session_store.session_paths(session_root, session_id)
    )
    assert manifest is not None
    assert manifest.state == "PROFILING"
    assert manifest.schemaArtifact is not None


def test_get_status_does_not_execute_validation(
    client: TestClient, session_root: str
) -> None:
    session_id = craft_validating_session(session_root, FIXTURE_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/status")
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "VALIDATING"
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    assert manifest.state == "VALIDATING"
    assert manifest.schemaArtifact is None
    assert not os.path.exists(os.path.join(paths.derived, "schema_report.json"))


def test_get_schema_pending_returns_409(client: TestClient, session_root: str) -> None:
    session_id = craft_validating_session(session_root, FIXTURE_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/schema")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "NOT_READY"
    assert body["error"]["stage"] == "VALIDATING"
    assert body["error"]["details"] == {"state": "VALIDATING"}
    assert body["meta"]["sessionState"] == "VALIDATING"
    # Still pending afterwards: the GET observed only.
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "VALIDATING"


def test_worker_noop_on_deleted_session(client: TestClient, session_root: str) -> None:
    """Reset-vs-validation race: a deleted session is never resurrected."""
    session_id = upload_ok(client, FIXTURE_BYTES)
    assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 200
    assert run_schema_validation(session_id) is None
    assert os.listdir(session_root) == []


def test_worker_rerun_is_harmless(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, FIXTURE_BYTES)
    manifest = run_schema_validation(session_id)
    assert manifest is not None
    assert manifest.state == "PROFILING"
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.isfile(os.path.join(paths.derived, "schema_report.json"))


def test_recover_validating_sessions_covers_crash_window(
    client: TestClient, session_root: str
) -> None:
    """Startup recovery runs ONLY the bounded Phase-5 step for leftovers."""
    from datetime import datetime, timedelta

    os.makedirs(session_root, exist_ok=True)
    good = craft_validating_session(session_root, FIXTURE_BYTES)
    bad = craft_validating_session(session_root, b"a,b\n1,2\n")
    stale = craft_validating_session(session_root, FIXTURE_BYTES)
    stale_paths = session_store.session_paths(session_root, stale)
    stale_manifest = session_store.read_manifest(stale_paths)
    assert stale_manifest is not None
    stale_manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=3)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(stale_paths, stale_manifest)
    decided = craft_validating_session(session_root, FIXTURE_BYTES)
    assert run_schema_validation(decided) is not None

    assert recover_validating_sessions(session_root) == 2
    good_manifest = session_store.read_manifest(
        session_store.session_paths(session_root, good)
    )
    assert good_manifest is not None and good_manifest.state == "PROFILING"
    bad_manifest = session_store.read_manifest(
        session_store.session_paths(session_root, bad)
    )
    assert bad_manifest is not None and bad_manifest.state == "FAILED"
    # Expired leftovers are the sweep's job, not recovery's.
    assert os.path.isdir(stale_paths.root)


def test_compatible_fixture_advances_to_profiling(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, FIXTURE_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"] == "PROFILING"
    assert data["stage"] == "PROFILING"
    assert data["progress"]["currentStage"] == "PROFILING"
    assert data["progress"]["completedStages"] == ["UPLOADING", "VALIDATING"]
    assert data["error"] is None
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.isfile(os.path.join(paths.derived, "schema_report.json"))
    assert os.path.isfile(paths.raw)  # compatible sessions keep raw


def test_schema_endpoint_returns_contract_shape(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, FIXTURE_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/status")
    assert response.status_code == 200
    schema = client.get(f"/api/v1/sessions/{session_id}/schema")
    assert schema.status_code == 200
    data = schema.json()["data"]
    assert set(data) == {"sourceColumns", "mapping", "missingCritical"}
    assert data["missingCritical"] == []
    by_source = {entry["source"]: entry for entry in data["mapping"]}
    assert by_source["Order Id"]["canonical"] == "order_id"
    assert by_source["Order Id"]["class"] == "required"
    assert by_source["Market"]["class"] == "optional"
    assert by_source["Order Customer Id"]["class"] == "redundant"
    assert by_source["Late_delivery_risk"]["class"] == "excluded"
    assert by_source["Warehouse Zone"]["class"] == "unknown"
    for entry in data["mapping"]:
        assert set(entry) == {"source", "canonical", "class"}


def test_schema_report_has_no_values_or_derivations(
    client: TestClient, session_root: str
) -> None:
    """The artifact carries headers and mapping facts, never body content."""
    session_id = upload_ok(client, FIXTURE_BYTES)
    client.get(f"/api/v1/sessions/{session_id}/status")
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "schema_report.json"), encoding="utf-8"
    ) as handle:
        payload = json.load(handle)
    text = json.dumps(payload)
    assert "SYN-ORDER-9001" not in text
    assert "SYN-CUST-901" not in text
    assert "is_late" not in text
    assert "shipment_outcome" not in text
    assert payload["sourceGrain"] == "order_item"
    assert payload["schemaReferenceId"] == "dataco-v1"
    assert payload["compatible"] is True
    assert payload["timestampContracts"]
    assert all(
        item["parse"] == "explicit month-first"
        for item in payload["timestampContracts"]
    )


def test_extra_column_does_not_reject(client: TestClient, session_root: str) -> None:
    lines = FIXTURE_BYTES.decode().splitlines()
    lines[0] += ",Loyalty Tier"
    lines[1] += ",Gold"
    lines[2] += ",Silver"
    session_id = upload_ok(client, "\n".join(lines).encode())
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "PROFILING"
    schema = client.get(f"/api/v1/sessions/{session_id}/schema")
    data = schema.json()["data"]
    assert data["missingCritical"] == []
    assert "Loyalty Tier" in [
        entry["source"] for entry in data["mapping"] if entry["class"] == "unknown"
    ]


def test_mapping_is_order_independent() -> None:
    """Same header set in any order yields the same canonical set (pure)."""
    headers = REQUIRED_SOURCE_HEADERS + ["Market", "Warehouse Zone"]
    forward = validate_headers(headers)
    backward = validate_headers(list(reversed(headers)))
    assert forward.compatible is True
    assert {(entry.source, entry.canonical) for entry in forward.mapping} == {
        (entry.source, entry.canonical) for entry in backward.mapping
    }
    assert forward.missingRequired == backward.missingRequired == []


def test_original_headers_preserved_case_variant_maps() -> None:
    """Governed normalization maps variants while keeping originals."""
    report = validate_headers(
        ["ORDER ID", "  Order Item Id  "]
        + [h for h in REQUIRED_SOURCE_HEADERS if h not in ("Order Id", "Order Item Id")]
    )
    assert report.compatible is True
    by_canonical = {
        entry.canonical: entry.source
        for entry in report.mapping
        if entry.canonical is not None
    }
    assert by_canonical["order_id"] == "ORDER ID"
    assert by_canonical["order_item_id"] == "  Order Item Id  "


def test_missing_one_required_field_fails(
    client: TestClient, session_root: str
) -> None:
    lines = FIXTURE_BYTES.decode().splitlines()
    header = lines[0].split(",")
    header.remove("Order Item Total")
    rows = [",".join(row.split(",")[: len(header)]) for row in lines[1:]]
    content = "\n".join([",".join(header), *rows]).encode()
    session_id = upload_ok(client, content)
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.status_code == 200
    data = status.json()["data"]
    assert data["state"] == "FAILED"
    assert data["error"]["code"] == "SCHEMA_MISSING_COLUMN"
    assert data["error"]["stage"] == "VALIDATING"
    assert "Order Item Total" in data["error"]["details"]["missing"]
    # ADR-028 terminal cleanup: raw and derived gone, manifest retained.
    paths = session_store.session_paths(session_root, session_id)
    assert not os.path.exists(paths.raw)
    assert os.listdir(paths.derived) == []
    manifest = session_store.read_manifest(paths)
    assert manifest is not None and manifest.state == "FAILED"


def test_missing_several_required_fields_lists_all(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, b"a,b\n1,2\n")
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "FAILED"
    missing = status.json()["data"]["error"]["details"]["missing"]
    assert set(REQUIRED_SOURCE_HEADERS) <= set(missing)


def test_schema_endpoint_surfaces_422_for_incompatible(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, b"a,b\n1,2\n")
    response = client.get(f"/api/v1/sessions/{session_id}/schema")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "SCHEMA_MISSING_COLUMN"
    assert "Order Id" in body["error"]["details"]["missing"]


def test_arbitrary_csv_passes_phase4_fails_phase5(
    client: TestClient, session_root: str
) -> None:
    """Phase boundary: structural validity (202) never implies compatibility."""
    upload = post_csv(client, "random.csv", b"foo,bar\n1,2\n")
    assert upload.status_code == 202
    session_id = upload.json()["data"]["sessionId"]
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "FAILED"
    assert status.json()["data"]["state"] != "PROFILING"


def test_incompatible_never_reaches_profiling_nor_artifact(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, b"a,b\n1,2\n")
    client.get(f"/api/v1/sessions/{session_id}/status")
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    assert manifest.schemaArtifact is None
    assert not os.path.exists(os.path.join(paths.derived, "schema_report.json"))


def test_error_details_carry_no_source_values(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, b"a,b\nSYN-SECRET-1,2\n")
    error = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["error"]
    assert "SYN-SECRET-1" not in json.dumps(error)
    assert set(error["details"]) <= {"missing", "recognized", "columnCount"}


def test_late_delivery_risk_never_becomes_is_late() -> None:
    report = validate_headers(REQUIRED_SOURCE_HEADERS + ["Late_delivery_risk"])
    assert report.compatible is True
    assert all(entry.canonical != "is_late" for entry in report.mapping)
    assert "is_late" not in report.model_dump_json()
    flagged = [e for e in report.mapping if e.source == "Late_delivery_risk"]
    assert len(flagged) == 1
    assert flagged[0].canonical is None
    assert flagged[0].fieldClass == "excluded"


def test_order_id_repetition_is_not_a_schema_error(
    client: TestClient, session_root: str
) -> None:
    """ADR-002: repeated Order Id values never fail schema validation."""
    lines = FIXTURE_BYTES.decode().splitlines()
    content = "\n".join([lines[0], lines[1], lines[1]]).encode()
    session_id = upload_ok(client, content)
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "PROFILING"


def test_path_like_header_is_unrecognized_and_safe(
    client: TestClient, session_root: str
) -> None:
    report = validate_headers(REQUIRED_SOURCE_HEADERS + ["../../etc/passwd"])
    assert report.compatible is True
    assert "../../etc/passwd" in report.unrecognized


def test_script_like_header_is_unrecognized(
    client: TestClient, session_root: str
) -> None:
    report = validate_headers(REQUIRED_SOURCE_HEADERS + ["<script>alert(1)</script>"])
    assert report.compatible is True
    assert "<script>alert(1)</script>" in report.unrecognized


def test_very_long_extra_header_accepted(client: TestClient, session_root: str) -> None:
    long_header = "X" * 5000
    report = validate_headers(REQUIRED_SOURCE_HEADERS + [long_header])
    assert report.compatible is True
    assert long_header in report.unrecognized


def test_privacy_like_headers_never_map() -> None:
    """Ungoverned personal-looking headers stay unmapped by construction."""
    report = validate_headers(
        REQUIRED_SOURCE_HEADERS + ["Customer Email", "First Name", "Customer Street"]
    )
    assert report.compatible is True
    assert all(
        entry.canonical is None
        for entry in report.mapping
        if entry.source in ("Customer Email", "First Name", "Customer Street")
    )
    assert "Customer Email" in report.unrecognized


def test_schema_unknown_and_expired_behaviour(
    client: TestClient, session_root: str
) -> None:
    from datetime import datetime, timedelta

    missing = str(uuid.uuid4())
    assert client.get(f"/api/v1/sessions/{missing}/schema").status_code == 404
    assert client.get("/api/v1/sessions/not-a-uuid/schema").status_code == 404
    session_id = upload_ok(client, FIXTURE_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    manifest = session_store.read_manifest(paths)
    assert manifest is not None
    manifest.lastAccessedAt = (
        (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    )
    session_store.write_manifest(paths, manifest)
    expired = client.get(f"/api/v1/sessions/{session_id}/schema")
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SESSION_EXPIRED"


def test_body_with_late_breakage_still_profiles(
    client: TestClient, session_root: str
) -> None:
    """Header-only proof: body content cannot influence schema recognition.

    A quoting break more than 1 MB into the body would fail any row-scanning
    validator, yet the session still reaches PROFILING: Phase 5 consumes
    headers only, and mid-file integrity is owned by profiling (DQ-FILE-005).
    """
    from app.ingestion import SNIFF_LIMIT_BYTES

    padding = b"9,9\n" * ((SNIFF_LIMIT_BYTES // 4) + 10)
    header = ",".join(REQUIRED_SOURCE_HEADERS).encode()
    content = header + b"\n" + padding + b'"unclosed quote,2\n'
    assert len(content) > SNIFF_LIMIT_BYTES
    session_id = upload_ok(client, content)
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "PROFILING"


def test_garbage_body_still_validates_schema(
    client: TestClient, session_root: str
) -> None:
    """Phase boundary: nonsensical values never fail header validation."""
    header = ",".join(REQUIRED_SOURCE_HEADERS)
    body = "not-a-date,abc,!!!,,,,,,,,,,,,,,,"
    session_id = upload_ok(client, f"{header}\n{body}\n".encode())
    status = client.get(f"/api/v1/sessions/{session_id}/status")
    assert status.json()["data"]["state"] == "PROFILING"


def test_raw_sha_stable_through_validation(
    client: TestClient, session_root: str
) -> None:
    """Schema recognition never rewrites the immutable raw bytes."""
    session_id = upload_ok(client, FIXTURE_BYTES)
    paths = session_store.session_paths(session_root, session_id)
    with open(paths.raw, "rb") as handle:
        before = handle.read()
    client.get(f"/api/v1/sessions/{session_id}/status")
    client.get(f"/api/v1/sessions/{session_id}/schema")
    with open(paths.raw, "rb") as handle:
        after = handle.read()
    assert before == after == FIXTURE_BYTES
    assert (
        hashlib.sha256(after).hexdigest() == hashlib.sha256(FIXTURE_BYTES).hexdigest()
    )
