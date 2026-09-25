"""Phase-4 synchronous ingestion guards (no supply-chain semantics).

Pipeline for `POST /sessions/uploads`:

1. cheap transport checks (presence, extension, MIME evidence, declared size)
2. bounded streaming of the upload to a session temp file (byte counting +
   incremental SHA-256; never loads the whole request into memory)
3. encoding detection (UTF-8-SIG, then Latin-1 with text-plausibility checks)
4. header-first parsing (column cap, duplicate detection on normalized names)
5. sniff-bounded structural validation (strict quoting within the ≤1 MB
   sniff only; mid-file integrity beyond the sniff belongs to profiling
   per DQ-FILE-005, not to the synchronous upload path)
6. on success the caller atomically promotes the temp file to `raw.csv`

The only O(file) work before 202 is the unavoidable persistence stream
(byte copy + count + SHA-256 + a byte-level emptiness scan fused into the
same chunks). All CSV parsing is O(sniff). A second full-file parse pass
would contradict the accepted async contract (ADR-029: POST runs only cheap
synchronous guards and returns 202 immediately), so it must not be added
here even though it would catch mid-file breakage earlier.

Every failure raises `IngestionError` with a contract code. No function here
interprets supply-chain columns: Phase 5 owns schema recognition, so a
structurally valid CSV is never rejected for lacking DataCo columns.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass

from fastapi import UploadFile

from app.ingestion_errors import (
    DUPLICATE_HEADERS,
    EMPTY_FILE,
    FILE_TOO_LARGE,
    MALFORMED_CSV,
    MALFORMED_HEADER,
    STAGE_VALIDATING,
    UNREADABLE_HEADER,
    UNSUPPORTED_ENCODING,
    IngestionError,
)

# Resource bounds (ADR-027, docs/architecture.md section 3).
CHUNK_BYTES = 1 << 20  # 1 MB streaming chunks; upload never fully in memory
SNIFF_LIMIT_BYTES = 1 << 20  # header/encoding sniff region (<= 1 MB)
MAX_HEADER_COLUMNS = 200  # blunt CSV-bomb headers
MAX_CELL_BYTES = 1 << 20  # per-field cap via csv.field_size_limit
MULTIPART_OVERHEAD_ALLOWANCE_BYTES = 1 << 20  # declared-size early signal
CONTROL_CHAR_RATIO_LIMIT = 0.30  # Latin-1 text-plausibility threshold

# MIME types observed for legitimate browser CSV uploads. MIME is evidence,
# never proof: generic types are accepted and parsing decides.
CSV_PLAUSIBLE_MIME_TYPES = frozenset(
    {
        "",
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "text/plain",
        "application/octet-stream",
    }
)

# Cap the csv module's field size so a single pathological cell cannot exhaust
# memory during structural iteration. Set once at import for this process.
csv.field_size_limit(MAX_CELL_BYTES)


@dataclass(frozen=True)
class StreamedUpload:
    """Outcome of bounded streaming: size, SHA-256, and emptiness signal.

    `has_data` is true when any non-whitespace byte exists beyond the first
    physical line break. It answers "header-only?" exactly for realistic
    inputs without a second file pass. Safe-direction limits: a quoted
    newline inside the header row can read as "data" (accepted; profiling
    owns it), while whitespace-only lines never count as records.
    """

    size_bytes: int
    sha256_hex: str
    has_data: bool


# Whitespace for the byte-level emptiness scan (operates on raw bytes so it
# stays fused into the persistence stream at C speed).
_SCAN_WHITESPACE = b" \t\r\n\x0b\x0c"


@dataclass(frozen=True)
class EncodingResult:
    """Detected encoding plus the decoded sniff text used for header parse."""

    name: str  # "utf-8-sig" | "utf-8" | "latin-1"
    text: str


@dataclass(frozen=True)
class HeaderResult:
    """Original header names, preserved exactly as parsed (Phase 5 maps them)."""

    names: list[str]


def sanitize_filename(raw_name: str | None) -> str:
    """Return a filesystem-safe display name; never usable as a path.

    Strips directory components (POSIX and Windows separators), keeps a
    conservative allow-list of characters, truncates, and falls back to
    ``upload.csv`` when nothing safe remains.
    """
    if not raw_name:
        return "upload.csv"
    # Split on both separators so traversal attempts and absolute Windows
    # paths collapse to their final component.
    leaf = raw_name.replace("\\", "/").split("/")[-1].strip()
    cleaned = "".join(
        ch for ch in leaf if ch.isalnum() or ch in ("-", "_", ".", " ")
    ).strip(" .")
    if not cleaned:
        return "upload.csv"
    return cleaned[:120]


def has_csv_extension(filename: str) -> bool:
    """Case-insensitive `.csv` extension check on the sanitized name."""
    return filename.lower().endswith(".csv")


def mime_is_csv_plausible(content_type: str | None) -> bool:
    """MIME evidence check: plausible CSV types pass, obvious non-CSV fails."""
    if content_type is None:
        return True
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in CSV_PLAUSIBLE_MIME_TYPES


def declared_size_exceeds(content_length: int | None, byte_limit: int) -> bool:
    """Early over-limit signal from the declared request size.

    `Content-Length` covers the whole multipart body, so a small allowance is
    added before failing fast. The streamed on-disk count stays authoritative.
    """
    if content_length is None:
        return False
    return content_length > byte_limit + MULTIPART_OVERHEAD_ALLOWANCE_BYTES


async def stream_upload_to_temp(
    upload_file: UploadFile, dest_path: str, byte_limit: int
) -> StreamedUpload:
    """Write the upload incrementally; fail fast past the hard byte cap.

    Reads in 1 MB chunks, counts actual bytes, and hashes incrementally, so a
    lying `Content-Length` cannot bypass enforcement and memory stays flat.
    The same chunks feed a byte-level emptiness scan (any non-whitespace
    byte beyond the first line break), so header-only detection costs no
    second pass. Raises `FILE_TOO_LARGE` (413) the moment the cap is exceeded.
    Only the multipart-decoded file bytes are counted: envelope overhead
    never counts toward the limit.
    """
    digest = hashlib.sha256()
    written = 0
    seen_newline = False
    has_data = False
    limit_mb = byte_limit // (1024 * 1024)
    with open(dest_path, "wb") as handle:
        while True:
            chunk = await upload_file.read(CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > byte_limit:
                raise IngestionError(
                    FILE_TOO_LARGE,
                    STAGE_VALIDATING,
                    f"The file exceeds the {limit_mb} MB upload limit. "
                    "Choose a smaller file and try again.",
                    413,
                    {"bytesReceived": written, "maxBytes": byte_limit},
                )
            digest.update(chunk)
            handle.write(chunk)
            seen_newline, chunk_has_data = _scan_chunk(chunk, seen_newline)
            has_data = has_data or chunk_has_data
    return StreamedUpload(
        size_bytes=written, sha256_hex=digest.hexdigest(), has_data=has_data
    )


def _scan_chunk(chunk: bytes, seen_newline: bool) -> tuple[bool, bool]:
    """Fold one stream chunk into the emptiness scan (C-speed, no parsing).

    Returns the updated `seen_newline` flag and whether this chunk holds a
    non-whitespace byte beyond the first physical line break.
    """
    rest = chunk
    if not seen_newline:
        newline_at = min(
            (index for index in (chunk.find(b"\n"), chunk.find(b"\r")) if index >= 0),
            default=-1,
        )
        if newline_at == -1:
            return False, False
        seen_newline = True
        rest = chunk[newline_at + 1 :]
    return seen_newline, bool(rest.strip(_SCAN_WHITESPACE))


def _looks_binary(text: str) -> bool:
    """Text-plausibility check for the Latin-1 fallback path.

    Latin-1 decodes every byte sequence, so decoding success alone cannot rule
    out binary payloads. NUL bytes or a high control-character ratio mean the
    input is not plausibly text (implementation interpretation documented in
    tests: see `test_upload_guards.py`). Residual limitation, stated openly:
    binary without NULs and with few control characters that also happens to
    parse as CSV can pass as Latin-1 text; later schema stages own it, and
    nothing here executes or interprets the bytes.
    """
    if "\x00" in text:
        return True
    if not text:
        return False
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in ("\t", "\n", "\r"))
    return (controls / len(text)) > CONTROL_CHAR_RATIO_LIMIT


def detect_encoding(sniff: bytes) -> EncodingResult:
    """Detect UTF-8-SIG/UTF-8, else Latin-1 with plausibility, else fail.

    Raises `UNSUPPORTED_ENCODING` (415) when bytes decode as neither UTF-8
    variant nor plausible Latin-1 text.
    """
    try:
        text = sniff.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = sniff.decode("latin-1")
        if _looks_binary(text):
            raise IngestionError(
                UNSUPPORTED_ENCODING,
                STAGE_VALIDATING,
                "The file is not UTF-8 or Latin-1 text. "
                "Resave it as CSV in UTF-8 or Latin-1 encoding and try again.",
                415,
                {"triedEncodings": ["utf-8-sig", "latin-1"]},
            ) from None
        return EncodingResult(name="latin-1", text=text)
    name = "utf-8-sig" if sniff.startswith(b"\xef\xbb\xbf") else "utf-8"
    return EncodingResult(name=name, text=text)


def normalize_header_name(name: str) -> str:
    """Duplicate-detection normalization only: strip, drop BOM, casefold.

    Phase 4 preserves original header names untouched; this function exists
    solely so collisions like `"a"` vs `" a "` vs `"A"` are caught
    deterministically. No semantic aliases are invented here.
    """
    return name.replace("\ufeff", "").strip().casefold()


def parse_header(text: str) -> HeaderResult:
    """Parse the first non-blank row as the header (bounded sniff text).

    Raises `EMPTY_FILE` when no header row exists, `MALFORMED_HEADER` (400)
    when strict parsing fails on the header row or the column cap is
    exceeded, `UNREADABLE_HEADER` (422) when the header row carries no usable
    names, and `MALFORMED_CSV` (422) when breakage appears in body rows
    *within the sniff*. Breakage beyond the sniff is owned by profiling
    (DQ-FILE-005), never by this bounded synchronous path.
    """
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        names: list[str] | None = None
        rest_has_rows = False
        for row in reader:
            if not row:
                continue  # tolerate leading blank lines
            if names is None:
                names = list(row)
                continue
            if row and any(field.strip() != "" for field in row):
                rest_has_rows = True
                break
    except csv.Error as exc:
        if names is not None:
            # The header row parsed; the breakage is in the body.
            raise IngestionError(
                MALFORMED_CSV,
                STAGE_VALIDATING,
                "The CSV body is malformed "
                "(broken quoting or a truncated file). "
                "Fix the file structure and try again.",
                422,
                {},
            ) from exc
        raise IngestionError(
            MALFORMED_HEADER,
            STAGE_VALIDATING,
            "The CSV header row is malformed (unbalanced quoting). "
            "Fix the first row and try again.",
            400,
            {},
        ) from exc
    if names is None:
        raise IngestionError(
            EMPTY_FILE,
            STAGE_VALIDATING,
            "The file is empty or contains no header row. "
            "Upload a CSV with a header row and at least one data row.",
            400,
            {},
        )
    if len(names) > MAX_HEADER_COLUMNS:
        raise IngestionError(
            MALFORMED_HEADER,
            STAGE_VALIDATING,
            "The CSV header has too many columns. "
            f"Found {len(names)}, limit is {MAX_HEADER_COLUMNS}.",
            400,
            {"columnCount": len(names), "maxColumns": MAX_HEADER_COLUMNS},
        )
    if not any(name.replace("\ufeff", "").strip() for name in names):
        if not rest_has_rows:
            raise IngestionError(
                EMPTY_FILE,
                STAGE_VALIDATING,
                "The file contains no header row or data (blank input). "
                "Upload a CSV with a header row and at least one data row.",
                400,
                {},
            )
        raise IngestionError(
            UNREADABLE_HEADER,
            STAGE_VALIDATING,
            "The CSV header row has no usable column names. "
            "Add column names to the first row and try again.",
            422,
            {"columnCount": len(names)},
        )
    return HeaderResult(names=names)


def check_duplicate_headers(names: list[str]) -> None:
    """Reject duplicate normalized header names (empty names included)."""
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for original in names:
        normalized = normalize_header_name(original)
        if normalized in seen:
            if normalized not in duplicates:
                duplicates.append(normalized)
        else:
            seen[normalized] = original
    if duplicates:
        raise IngestionError(
            DUPLICATE_HEADERS,
            STAGE_VALIDATING,
            "The CSV header has duplicate column names "
            f"({', '.join(duplicates)}). Rename them and try again.",
            400,
            {"duplicates": duplicates, "columnCount": len(names)},
        )
