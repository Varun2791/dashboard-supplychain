"""Phase-4 ingestion guard matrix: every failure is safe and actionable.

Conventions under test (documented implementation interpretations):
- Latin-1 decodes every byte sequence, so `UNSUPPORTED_ENCODING` fires on
  text-plausibility (NUL bytes / control-character ratio), not decode errors.
- Duplicate detection normalizes by strip + BOM-drop + casefold only.
- A structurally valid CSV is never rejected for lacking DataCo columns.
- Every synchronous POST failure leaves no session tree behind.
"""

from __future__ import annotations

import asyncio
import io
import os
import uuid
from pathlib import Path

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from httpx import Response

from app.config import settings
from app.ingestion import (
    declared_size_exceeds,
    normalize_header_name,
    sanitize_filename,
    stream_upload_to_temp,
)
from app.ingestion_errors import IngestionError
from app.main import app


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


def assert_rejected(
    response: Response, session_root: str, code: str, http_status: int
) -> dict[str, object]:
    """Contract shape for failures plus the no-orphan guarantee."""
    assert response.status_code == http_status
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == code
    assert body["error"]["stage"] == "VALIDATING"
    assert body["error"]["message"]
    assert isinstance(body["error"]["details"], dict)
    # No session tree may survive a synchronous guard failure.
    if os.path.isdir(session_root):
        assert os.listdir(session_root) == []
    return body["error"]


def test_zero_byte_file_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "empty.csv", b"")
    assert_rejected(response, session_root, "EMPTY_FILE", 400)


def test_whitespace_only_file_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "blank.csv", b"   \n \t\n  ")
    assert_rejected(response, session_root, "EMPTY_FILE", 400)


def test_bom_only_file_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "bom.csv", b"\xef\xbb\xbf")
    assert_rejected(response, session_root, "EMPTY_FILE", 400)


def test_header_only_file_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "headers.csv", b"a,b,c\n")
    assert_rejected(response, session_root, "EMPTY_FILE", 400)


def test_header_plus_blank_lines_rejected(
    client: TestClient, session_root: str
) -> None:
    response = post_csv(client, "headers.csv", b"a,b\n\n   \n\n")
    assert_rejected(response, session_root, "EMPTY_FILE", 400)


def test_wrong_extension_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "data.txt", b"a,b\n1,2\n")
    error = assert_rejected(response, session_root, "INVALID_EXTENSION", 400)
    assert error["details"]["filenameSafe"] == "data.txt"


def test_missing_file_part_rejected(client: TestClient, session_root: str) -> None:
    response = client.post("/api/v1/sessions/uploads", files={})
    assert_rejected(response, session_root, "INVALID_EXTENSION", 400)


def test_uppercase_csv_extension_accepted(
    client: TestClient, session_root: str
) -> None:
    response = post_csv(client, "DATA.CSV", b"a,b\n1,2\n")
    assert response.status_code == 202


@pytest.mark.parametrize("mime", ["text/plain", "application/octet-stream"])
def test_generic_mime_types_accepted(
    client: TestClient, session_root: str, mime: str
) -> None:
    """Generic browser MIME evidence must not reject a valid CSV."""
    response = post_csv(client, "data.csv", b"a,b\n1,2\n", content_type=mime)
    assert response.status_code == 202


def test_suspicious_mime_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "data.csv", b"a,b\n1,2\n", "image/png")
    error = assert_rejected(response, session_root, "INVALID_EXTENSION", 400)
    assert error["details"]["mime"] == "image/png"


def test_malformed_header_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "bad.csv", b'a,"b\nc,d\n1,2,3\n')
    assert_rejected(response, session_root, "MALFORMED_HEADER", 400)


def test_header_without_usable_names_rejected(
    client: TestClient, session_root: str
) -> None:
    response = post_csv(client, "bad.csv", b",,,\n1,2,3\n")
    assert_rejected(response, session_root, "UNREADABLE_HEADER", 422)


def test_malformed_body_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "bad.csv", b'a,b\n1,"2\n')
    assert_rejected(response, session_root, "MALFORMED_CSV", 422)


def test_truncated_upload_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "cut.csv", b'a,b\n"unclosed quote,2\n')
    assert_rejected(response, session_root, "MALFORMED_CSV", 422)


def test_breakage_beyond_sniff_is_accepted_for_profiling(
    client: TestClient, session_root: str
) -> None:
    """Async-boundary proof: POST validates structure only within the sniff.

    A quoting break more than 1 MB into the file is accepted (202) because
    full-file parsing would contradict the cheap-guards contract (ADR-029).
    Mid-file integrity beyond the sniff is owned by profiling (DQ-FILE-005).
    """
    from app.ingestion import SNIFF_LIMIT_BYTES

    padding = b"1,2\n" * ((SNIFF_LIMIT_BYTES // 4) + 10)
    content = b"a,b\n" + padding + b'"unclosed quote,2\n'
    assert len(content) > SNIFF_LIMIT_BYTES
    response = post_csv(client, "late-break.csv", content)
    assert response.status_code == 202


def test_syntactic_empty_row_counts_as_record(
    client: TestClient, session_root: str
) -> None:
    """A present row with all-empty fields is not 'header-only' (accepted)."""
    response = post_csv(client, "empties.csv", b"a,b\n,\n")
    assert response.status_code == 202


def test_exact_duplicate_headers_rejected(
    client: TestClient, session_root: str
) -> None:
    response = post_csv(client, "dup.csv", b"a,b,a\n1,2,3\n")
    error = assert_rejected(response, session_root, "DUPLICATE_HEADERS", 400)
    assert "a" in error["details"]["duplicates"]


def test_whitespace_collision_headers_rejected(
    client: TestClient, session_root: str
) -> None:
    response = post_csv(client, "dup.csv", b"order_id, order_id \n1,2\n")
    assert_rejected(response, session_root, "DUPLICATE_HEADERS", 400)


def test_case_collision_headers_rejected(client: TestClient, session_root: str) -> None:
    response = post_csv(client, "dup.csv", b"Total,TOTAL\n1,2\n")
    assert_rejected(response, session_root, "DUPLICATE_HEADERS", 400)


def test_too_many_columns_rejected(client: TestClient, session_root: str) -> None:
    header = ",".join(f"c{i}" for i in range(201)).encode()
    response = post_csv(client, "wide.csv", header + b"\n1\n")
    error = assert_rejected(response, session_root, "MALFORMED_HEADER", 400)
    assert error["details"]["columnCount"] == 201


def test_binary_payload_rejected_as_unsupported_encoding(
    client: TestClient, session_root: str
) -> None:
    """Non-text bytes: UTF-8 fails and Latin-1 plausibility fails (NULs)."""
    binary = b"\x89PNG\r\n\x1a\n\x00\x00\x00\xff\xfe\x00binary"
    try:
        binary.decode("utf-8-sig")
        raise AssertionError("fixture must not decode as UTF-8")
    except UnicodeDecodeError:
        pass
    response = post_csv(client, "evil.csv", binary)
    assert_rejected(response, session_root, "UNSUPPORTED_ENCODING", 415)


def test_control_dense_payload_rejected_as_unsupported_encoding(
    client: TestClient, session_root: str
) -> None:
    """No NULs, but control density exceeds the plausibility threshold."""
    binary = b"a,b\n" + b"\x01" * 100 + b"\xff" * 100
    try:
        binary.decode("utf-8-sig")
        raise AssertionError("fixture must not decode as UTF-8")
    except UnicodeDecodeError:
        pass
    response = post_csv(client, "controls.csv", binary)
    assert_rejected(response, session_root, "UNSUPPORTED_ENCODING", 415)


@pytest.mark.parametrize(
    "filename",
    [
        "../../secret.csv",
        "..\\..\\secret.csv",
        "/absolute/path.csv",
        "C:\\Users\\name\\secret.csv",
        "normal.csv",
    ],
)
def test_traversal_filenames_cannot_escape_session_root(
    client: TestClient, session_root: str, filename: str, tmp_path: Path
) -> None:
    """Malicious names are accepted as data but collapse to a safe leaf."""
    before = set(os.listdir(tmp_path))
    response = post_csv(client, filename, b"a,b\n1,2\n")
    assert response.status_code == 202
    safe = response.json()["data"]["filenameSafe"]
    assert "/" not in safe and "\\" not in safe and ".." not in safe
    # Nothing was written outside the session root.
    assert set(os.listdir(tmp_path)) - before == {"sessions"}
    entries = os.listdir(session_root)
    assert len(entries) == 1
    assert uuid.UUID(entries[0], version=4)


def test_sanitize_filename_units() -> None:
    assert sanitize_filename("../../secret.csv") == "secret.csv"
    assert sanitize_filename("C:\\Users\\name\\secret.csv") == "secret.csv"
    assert sanitize_filename(None) == "upload.csv"
    assert sanitize_filename("  ") == "upload.csv"
    assert normalize_header_name(" Order Id ") == "order id"
    assert normalize_header_name("TOTAL") == "total"


def test_stream_enforces_exact_byte_boundary(tmp_path: Path) -> None:
    """Byte-limit semantics: exactly N bytes pass, N+1 fails with 413."""

    def drive(content: bytes, limit: int) -> object:
        async def run() -> object:
            upload = UploadFile(filename="x.csv", file=io.BytesIO(content))
            try:
                return await stream_upload_to_temp(
                    upload, str(tmp_path / "part.bin"), limit
                )
            finally:
                await upload.close()

        return asyncio.run(run())

    ok = drive(b"x" * 64, 64)
    assert ok.size_bytes == 64
    with pytest.raises(IngestionError) as exc_info:
        drive(b"x" * 65, 64)
    assert exc_info.value.code == "FILE_TOO_LARGE"
    assert exc_info.value.http_status == 413


def test_stream_reports_header_only_signal(tmp_path: Path) -> None:
    """The fused emptiness scan: data beyond line one, or not."""

    def drive(content: bytes) -> bool:
        async def run() -> bool:
            upload = UploadFile(filename="x.csv", file=io.BytesIO(content))
            try:
                streamed = await stream_upload_to_temp(
                    upload, str(tmp_path / "part.bin"), 1 << 20
                )
                return streamed.has_data
            finally:
                await upload.close()

        result = asyncio.run(run())
        assert isinstance(result, bool)
        return result

    assert drive(b"a,b\n1,2\n") is True
    assert drive(b"a,b\n,\n") is True  # syntactic row, even if empty-valued
    assert drive(b"a,b") is False  # single line: nothing beyond the header
    assert drive(b"a,b\n\n   \n") is False
    assert drive(b"\xef\xbb\xbf") is False  # BOM alone is not data


def test_declared_size_is_early_signal_only() -> None:
    assert declared_size_exceeds(None, 100) is False
    assert declared_size_exceeds(50, 100) is False
    assert declared_size_exceeds(100 + (1 << 20) + 1, 100) is True


def test_invalid_uuid_never_touches_filesystem(
    client: TestClient, session_root: str
) -> None:
    for bad in ["not-a-uuid", "3fa85f64", "3fa85f6457174562b3fc2c963f66afa6"]:
        status = client.get(f"/api/v1/sessions/{bad}/status")
        assert status.status_code == 404
        assert status.json()["error"]["code"] == "SESSION_NOT_FOUND"
    # Encoded traversal never resolves to a session: the client normalizes
    # it away from the route (plain 404) or it arrives as an unknown id
    # (contract 404). Either way there is no filesystem lookup.
    traversal = client.delete("/api/v1/sessions/..%2F..%2Fetc%2Fpasswd")
    assert traversal.status_code == 404
    if os.path.isdir(session_root):
        assert os.listdir(session_root) == []


def test_unknown_session_returns_404(client: TestClient, session_root: str) -> None:
    missing = str(uuid.uuid4())
    status = client.get(f"/api/v1/sessions/{missing}/status")
    assert status.status_code == 404
    assert status.json()["error"]["code"] == "SESSION_NOT_FOUND"
    delete = client.delete(f"/api/v1/sessions/{missing}")
    assert delete.status_code == 200
    assert delete.json()["data"] == {"deleted": True}
