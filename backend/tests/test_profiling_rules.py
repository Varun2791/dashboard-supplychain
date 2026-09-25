"""Phase-6 DQ rule contract tests (synthetic data only).

Every PROFILING-stage rule from `docs/data-quality-rules.md` gets a
pass case and a triggering case with its governed severity, treatment,
blocked stage, count semantics, safe message, affected fields, and grain.
The implementation must not drift from the rule catalogue: severities,
treatments, blocked stages, fields, and grain are asserted against the
catalogue metadata, not hardcoded twice.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.sessions as session_store
from app.config import settings
from app.main import app
from app.profile_checks import RULE_ORDER, RULES, RULES_DEFERRED

CLEAN_BYTES = (Path(__file__).parent / "fixtures" / "profiling_clean.csv").read_bytes()
ISSUES_BYTES = (
    Path(__file__).parent / "fixtures" / "profiling_issues.csv"
).read_bytes()

EXPECTED_TRIGGERED = {
    "DQ-KEY-001": ("ERROR", "flagged", "CANONICALIZATION", 2),
    "DQ-KEY-002": ("INFO", "unchanged", None, 2),
    "DQ-KEY-003": ("INFO", "unchanged", None, 2),
    "DQ-DATE-001": ("ERROR", "flagged", "KPI_ANALYSIS", 1),
    "DQ-DATE-002": ("WARNING", "flagged", None, 1),
    "DQ-DATE-003": ("WARNING", "flagged", None, 1),
    "DQ-DATE-004": ("INFO", "unchanged", None, 1),
    "DQ-NUM-001": ("WARNING", "flagged", None, 1),
    "DQ-NUM-002": ("WARNING", "flagged", None, 1),
    "DQ-NUM-003": ("WARNING", "flagged", None, 1),
    "DQ-CAT-001": ("WARNING", "flagged", None, 1),
    "DQ-CAT-002": ("WARNING", "flagged", None, 1),
    "DQ-CAT-003": ("WARNING", "flagged", None, 1),
    "DQ-CAT-005": ("INFO", "detected", None, 1),
    "DQ-GRAIN-001": ("ERROR", "flagged", "CANONICALIZATION", 1),
    "DQ-BUSINESS-002": ("WARNING", "flagged", None, 1),
    "DQ-BUSINESS-003": ("WARNING", "flagged", None, 1),
    "DQ-PRIVACY-001": ("INFO", "excluded", None, 1),
    "DQ-PRIVACY-002": ("INFO", "excluded", None, 1),
}


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


def quality_issues(client: TestClient, session_id: str) -> tuple[dict, dict, dict]:
    response = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert response.status_code == 200
    data = response.json()["data"]
    by_rule = {issue["ruleId"]: issue for issue in data["issues"]}
    paths = session_store.session_paths(settings.session_root, session_id)
    with open(
        os.path.join(paths.derived, "profiling_report.json"), encoding="utf-8"
    ) as handle:
        artifact = json.load(handle)
    return by_rule, artifact, data["summary"]


def test_clean_pass_case_triggers_only_privacy_info(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, CLEAN_BYTES)
    by_rule, artifact, summary = quality_issues(client, session_id)
    assert set(by_rule) == {"DQ-PRIVACY-001", "DQ-PRIVACY-002"}
    assert summary["errors"] == 0
    assert summary["warnings"] == 0
    assert summary["infos"] == 2
    assert summary["blockingIssues"] == 0
    assert {line.split(":")[0] for line in artifact["rulesDeferred"]} == {
        line.split(":")[0] for line in RULES_DEFERRED
    }


def test_each_triggered_rule_matches_catalogue(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    by_rule, artifact, summary = quality_issues(client, session_id)
    assert set(by_rule) == set(EXPECTED_TRIGGERED)
    for rule_id, (severity, treatment, blocked, count) in EXPECTED_TRIGGERED.items():
        issue = by_rule[rule_id]
        assert issue["severity"] == severity, rule_id
        assert issue["treatment"] == treatment, rule_id
        assert issue["blockedStage"] == blocked, rule_id
        assert issue["count"] == count, rule_id
        # Catalogue parity: the public issue reproduces RULES metadata, and
        # the internal context carries title/fields/grain/population.
        meta = RULES[rule_id]
        assert meta.severity == severity, rule_id
        assert meta.treatment == treatment, rule_id
        assert meta.blocked_stage == blocked, rule_id
        context = artifact["ruleContext"][rule_id]
        assert context["title"] == meta.title, rule_id
        assert tuple(context["fields"]) == meta.fields, rule_id
        assert context["grain"] == meta.grain, rule_id
        assert context["population"] == meta.population, rule_id
        message = artifact["issueMessages"][rule_id]
        assert str(count) in message, rule_id
    assert summary["rulesTriggered"] == len(EXPECTED_TRIGGERED)
    assert summary["errors"] == 3
    assert summary["warnings"] == 10
    assert summary["infos"] == 6
    assert summary["blockingIssues"] == 3


def test_rule_order_is_catalogue_order(client: TestClient, session_root: str) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    by_rule, artifact, _ = quality_issues(client, session_id)
    assert artifact["rulesEvaluated"][0] == "DQ-FILE-005"
    assert artifact["rulesEvaluated"][1:] == list(RULE_ORDER)


def test_no_rule_claims_fixed_and_no_values_leak_into_messages(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    _, artifact, _ = quality_issues(client, session_id)
    for message in artifact["issueMessages"].values():
        assert "SYN-ITEM-DUP-01" not in message
        assert "WEIRD_STATUS" not in message
        assert "not-a-date" not in message
    for issue in artifact["issues"]:
        assert issue["treatment"] != "fixed"


def test_deferred_rules_are_reported_not_silently_added(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    _, artifact, _ = quality_issues(client, session_id)
    deferred_ids = {line.split(":")[0] for line in artifact["rulesDeferred"]}
    assert deferred_ids == {
        "DQ-SCHEMA-004",
        "DQ-GRAIN-002",
        "DQ-BUSINESS-001",
        "DQ-BUSINESS-004",
        "DQ-NUM-004",
        "DQ-CAT-004",
        "DQ-PRIVACY-003",
    }
    triggered = {issue["ruleId"] for issue in artifact["issues"]}
    assert not (triggered & deferred_ids)


def test_grain_rule_counts_orders_not_lines(
    client: TestClient, session_root: str
) -> None:
    session_id = upload_ok(client, ISSUES_BYTES)
    response = client.get(f"/api/v1/sessions/{session_id}/profile")
    invariance = response.json()["data"]["invarianceConflicts"]
    assert invariance["conflictingOrders"] == 1
    assert invariance["ordersChecked"] == 16
    by_field = {
        item["field"]: item["conflictingOrders"] for item in invariance["byField"]
    }
    assert by_field["order_status"] == 1
