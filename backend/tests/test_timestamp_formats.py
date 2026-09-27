"""Slash timestamp-grammar compatibility tests (synthetic values only).

The DataCo reference source uses month-first slash timestamps
(`%m/%d/%Y %H:%M`, components not necessarily zero-padded). These tests pin
the explicit-format contract: slash grammar accepted, dash grammars retained,
malformed/impossible/day-first values rejected, one shared parser everywhere.
No reference bytes, no PII.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.canonicalization as canonicalization
import app.profiling as profiling
from app.config import settings
from app.main import app
from app.profile_checks import TIMESTAMP_FORMATS, parse_timestamps

CLEAN_BYTES = (Path(__file__).parent / "fixtures" / "profiling_clean.csv").read_bytes()

_DATE_CELL = re.compile(r"(\d{2})-(\d{2})-(\d{4}) (\d{2}):(\d{2})")


def _depadded_slash(text: str) -> str:
    """Rewrite dash date cells as non-zero-padded slash cells (same instants)."""

    def swap(match: re.Match[str]) -> str:
        month, day, year, hour, minute = match.groups()
        return f"{int(month)}/{int(day)}/{year} {int(hour)}:{minute}"

    return _DATE_CELL.sub(swap, text)


def series(*values: str) -> pd.Series:
    return pd.Series(list(values), dtype="string")


def test_slash_grammar_accepted() -> None:
    parsed = parse_timestamps(series("3/15/2021 10:00"))
    assert parsed.notna().all()
    assert parsed.iloc[0] == pd.Timestamp(2021, 3, 15, 10, 0)


def test_non_padded_month_day_hour_accepted() -> None:
    parsed = parse_timestamps(series("1/5/2021 9:05", "12/6/2020 3:07"))
    assert parsed.notna().all()
    assert parsed.iloc[0] == pd.Timestamp(2021, 1, 5, 9, 5)
    assert parsed.iloc[1] == pd.Timestamp(2020, 12, 6, 3, 7)


def test_existing_dash_grammars_retained() -> None:
    assert "%m-%d-%Y %H:%M:%S" in TIMESTAMP_FORMATS
    assert "%m-%d-%Y %H:%M" in TIMESTAMP_FORMATS
    assert "%m-%d-%Y" in TIMESTAMP_FORMATS
    parsed = parse_timestamps(
        series("03-15-2021 10:00:05", "03-15-2021 10:00", "03-15-2021")
    )
    assert parsed.notna().all()
    assert parsed.iloc[0] == pd.Timestamp(2021, 3, 15, 10, 0, 5)
    assert parsed.iloc[1] == pd.Timestamp(2021, 3, 15, 10, 0)
    assert parsed.iloc[2] == pd.Timestamp(2021, 3, 15)


def test_malformed_and_impossible_rejected() -> None:
    parsed = parse_timestamps(
        series("not-a-date", "13/01/2021 10:00", "02/30/2021 10:00", "")
    )
    assert parsed.isna().all()


def test_ambiguous_slash_follows_month_first() -> None:
    parsed = parse_timestamps(series("03/04/2021 10:00"))
    assert parsed.iloc[0] == pd.Timestamp(2021, 3, 4, 10, 0)


def test_no_day_first_fallback() -> None:
    """A day-first reading of an ambiguous value must never parse as such."""
    parsed = parse_timestamps(series("04/03/2021 10:00"))
    assert parsed.iloc[0] == pd.Timestamp(2021, 4, 3, 10, 0)


def test_shared_parser_contract() -> None:
    assert profiling.parse_timestamps is parse_timestamps
    assert canonicalization.parse_timestamps is parse_timestamps


def test_deterministic_result() -> None:
    values = series("3/5/2021 9:05", "03-15-2021 10:00")
    first = parse_timestamps(values)
    second = parse_timestamps(values)
    pd.testing.assert_series_equal(first, second)


def test_only_exact_slash_minute_grammar_added() -> None:
    assert TIMESTAMP_FORMATS == (
        "%m-%d-%Y %H:%M:%S",
        "%m-%d-%Y %H:%M",
        "%m-%d-%Y",
        "%m/%d/%Y %H:%M",
    )


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def session_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = str(tmp_path / "sessions")
    monkeypatch.setattr(settings, "session_root", root)
    return root


def _upload(client: TestClient, content: bytes) -> str:
    response = client.post(
        "/api/v1/sessions/uploads",
        files={"file": ("data.csv", content, "text/csv")},
    )
    assert response.status_code == 202
    return response.json()["data"]["sessionId"]


def _rule_ids(client: TestClient, session_id: str) -> set[str]:
    response = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert response.status_code == 200
    return {issue["ruleId"] for issue in response.json()["data"]["issues"]}


def test_slash_clean_source_triggers_no_date_rules(
    client: TestClient, session_root: str
) -> None:
    """A valid slash-format source passes the systemic date gate."""
    text = _depadded_slash(CLEAN_BYTES.decode("utf-8-sig"))
    assert "/" in text
    session_id = _upload(client, text.encode("utf-8"))
    rules = _rule_ids(client, session_id)
    assert "DQ-DATE-001" not in rules
    assert "DQ-DATE-002" not in rules
    status = client.get(f"/api/v1/sessions/{session_id}/status").json()["data"]
    assert status["state"] not in ("CANONICALIZING", "FAILED")


def test_invalid_timestamp_still_triggers_date_rule(
    client: TestClient, session_root: str
) -> None:
    """Genuinely invalid timestamps remain governed DQ findings."""
    import csv
    import io

    text = _depadded_slash(CLEAN_BYTES.decode("utf-8-sig"))
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    order_idx = header.index("order date (DateOrders)")
    rows[1][order_idx] = "not-a-date"
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    session_id = _upload(client, buffer.getvalue().encode("utf-8"))
    response = client.get(f"/api/v1/sessions/{session_id}/data-quality")
    assert response.status_code == 200
    by_rule = {issue["ruleId"]: issue for issue in response.json()["data"]["issues"]}
    assert by_rule["DQ-DATE-001"]["count"] == 1
