"""Stdlib-only benchmark measurement primitives (ADR-042).

Timing uses ``time.perf_counter`` elapsed durations. HTTP/TestClient timing
is end-to-end local request elapsed time, never pure server compute. RSS
uses ``resource.getrusage`` with macOS-bytes / Linux-KiB normalization and
is always reported as process high-water RSS — never per-stage memory.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import time
from types import TracebackType

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX platforms
    resource = None  # type: ignore[assignment]


class Timer:
    """Elapsed-duration timer (context manager, seconds as float)."""

    def __init__(self) -> None:
        self.elapsed: float = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.elapsed = time.perf_counter() - self._start


def normalize_ru_maxrss(raw_maxrss: int, platform_name: str) -> int | None:
    """Normalize ``ru_maxrss`` to bytes.

    macOS reports bytes; Linux reports KiB. Any other platform returns
    ``None`` (unavailable) so callers record a reason instead of guessing.
    """
    if platform_name == "darwin":
        return raw_maxrss
    if platform_name == "linux":
        return raw_maxrss * 1024
    return None


def peak_rss_bytes() -> tuple[int | None, str | None]:
    """Return (process high-water RSS bytes, unavailable reason or None)."""
    if resource is None:
        return None, "resource.getrusage unavailable on this platform"
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    normalized = normalize_ru_maxrss(int(raw), sys.platform)
    if normalized is None:
        return None, f"ru_maxrss unit unknown on platform '{sys.platform}'"
    return normalized, None


def node_version() -> tuple[str | None, str | None]:
    """Return (node version, unavailable reason or None); never fails."""
    if shutil.which("node") is None:
        return None, "node executable not found"
    try:
        completed = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"node --version failed: {exc}"
    version = completed.stdout.strip()
    if completed.returncode != 0 or not version:
        return None, "node --version returned no version"
    return version, None


def collect_environment() -> dict[str, str | None]:
    """Collect reproducibility environment metadata (values only)."""
    node, _ = node_version()
    return {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "pythonVersion": platform.python_version(),
        "nodeVersion": node,
    }


def git_revision(
    cwd: str,
) -> tuple[str | None, bool | None, str | None]:
    """Return (HEAD sha, working-tree dirty flag, unavailable reason).

    Never raises and never includes diff content — the dirty flag is a
    boolean only. A dirty tree does not block benchmarking; it is recorded.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd,
        )
        if head.returncode != 0:
            return None, None, "git rev-parse HEAD failed"
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=cwd,
        )
        if status.returncode != 0:
            return head.stdout.strip(), None, "git status failed"
        return head.stdout.strip(), bool(status.stdout.strip()), None
    except (OSError, subprocess.SubprocessError) as exc:
        return None, None, f"git invocation failed: {exc}"
