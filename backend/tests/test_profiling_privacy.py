"""Phase-6 privacy and security tests (all values invented for this repo).

Proves that invented PII-looking source values, unknown arbitrary values,
and hostile strings never surface in profiling artifacts, API payloads,
errors, or logs; that no raw sample rows are stored; and that path-like
source values stay inert.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app.config import settings
from app.main import app

REQUIRED_HEADER = [
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

INVENTED_SECRETS = [
    "Ava Rivera",
    "Rivera",
    "742 Evergreen Terrace",
    "ava.rivera@example.invalid",
    "s3cret-pw-9917",
    "37.7749",
    "-122.4194",
    "192.0.2.146",
    "=SUM(A1:A2)",
    "@evil-macro",
    "<script>alert(1)</script>",
    "../../etc/passwd",
]


def base_row() -> list[str]:
    return [
        "SYN-ORDER-9501",
        "SYN-ITEM-9501",
        "SYN-CUST-951",
        "SYN-PROD-951",
        "SYN-CAT-951",
        "03-15-2021 10:00",
        "03-18-2021 09:00",
        "29.98",
        "2.00",
        "27.98",
        "6.40",
        "14.99",
        "2",
        "3",
        "4",
        "Shipped",
        "COMPLETE",
        "Standard Class",
    ]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def upload_ok(client: TestClient, content: bytes) -> str:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    return response.json()["data"]["sessionId"]


def test_pii_looking_extras_never_enter_reports(
    client: TestClient, session_root: str
) -> None:
    header = REQUIRED_HEADER + [
        "First Name",
        "Last Name",
        "Customer Street",
        "Customer Email",
        "Customer Password",
        "Customer Latitude",
        "Customer Longitude",
        "Client IP",
    ]
    row = base_row() + INVENTED_SECRETS[:8]
    content = ("\n".join([",".join(header), ",".join(row)]) + "\n").encode()
    session_id = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()
    schema = client.get(f"/api/v1/sessions/{session_id}/schema").json()
    for secret in INVENTED_SECRETS[:8]:
        assert secret not in json.dumps(profile)
        assert secret not in json.dumps(quality)
    # Privacy rules counted the sensitive-like columns without naming values.
    by_rule = {i["ruleId"]: i for i in quality["data"]["issues"]}
    assert by_rule["DQ-PRIVACY-001"]["count"] >= 1
    assert by_rule["DQ-PRIVACY-002"]["count"] >= 1
    # Schema report names headers (governed Phase-5 behavior) but the
    # profiling artifact carries no unknown-header names at all.
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "profiling_report.json"), encoding="utf-8"
    ) as handle:
        artifact_text = handle.read()
    for extra in header[len(REQUIRED_HEADER) :]:
        assert extra not in artifact_text
    assert schema["data"]["missingCritical"] == []


def test_hostile_values_stay_inert_and_unreported(
    client: TestClient, session_root: str
) -> None:
    header = REQUIRED_HEADER + ["Product Name", "../../etc/passwd"]
    row = base_row() + ["=SUM(A1:A2)", "@evil-macro"]
    content = ("\n".join([",".join(header), ",".join(row)]) + "\n").encode()
    session_id = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "READY"
    )
    profile = client.get(f"/api/v1/sessions/{session_id}/profile").json()
    quality = client.get(f"/api/v1/sessions/{session_id}/data-quality").json()
    for hostile in ("=SUM(A1:A2)", "@evil-macro", "../../etc/passwd"):
        assert hostile not in json.dumps(profile)
        assert hostile not in json.dumps(quality)
    # The traversal-looking header is quarantined, never a path.
    paths = session_store.session_paths(session_root, session_id)
    assert os.path.dirname(paths.raw) == paths.root
    assert sorted(os.listdir(paths.root)) == [
        "derived",
        "exports",
        "manifest.json",
        "raw.csv",
    ]


def test_no_row_samples_or_values_in_artifact(
    client: TestClient, session_root: str
) -> None:
    content = (Path(__file__).parent / "fixtures" / "profiling_issues.csv").read_bytes()
    session_id = upload_ok(client, content)
    paths = session_store.session_paths(session_root, session_id)
    with open(
        os.path.join(paths.derived, "profiling_report.json"), encoding="utf-8"
    ) as handle:
        artifact = json.load(handle)
    assert set(artifact) == {
        "sessionId",
        "appVersion",
        "schemaVersion",
        "sourceSha256",
        "sourceRows",
        "mappedFields",
        "profile",
        "issues",
        "issueMessages",
        "ruleContext",
        "rulesEvaluated",
        "rulesDeferred",
        "profiledAt",
    }
    text = json.dumps(artifact)
    for probe in (
        "SYN-ITEM-DUP-01",
        "SYN-CUST-921",
        "not-a-date",
        "WEIRD_STATUS",
        "Rocket",
        "Platinum",
        "27.98",
    ):
        assert probe not in text


def test_error_payloads_carry_no_source_values(
    client: TestClient, session_root: str
) -> None:
    header = ",".join(REQUIRED_HEADER).encode()
    padding = b"SYN-SECRET-9,9\n" * 300
    content = header + b"\n" + padding + b'"unclosed quote,2\n'
    session_id = upload_ok(client, content)
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["error"]["code"] == "MALFORMED_CSV"
    assert "SYN-SECRET-9" not in json.dumps(status["error"])
    profile = client.get(f"/api/v1/sessions/{session_id}/profile")
    assert "SYN-SECRET-9" not in profile.text


def test_profiling_logs_carry_counts_only(
    client: TestClient, session_root: str, caplog: pytest.LogCaptureFixture
) -> None:
    content = (Path(__file__).parent / "fixtures" / "profiling_issues.csv").read_bytes()
    with caplog.at_level(logging.INFO, logger="app.profiling"):
        session_id = upload_ok(client, content)
    assert (
        client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]["state"]
        == "CANONICALIZING"
    )
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    for probe in ("SYN-ITEM-DUP-01", "WEIRD_STATUS", "not-a-date", "SYN-CUST-921"):
        assert probe not in log_text
