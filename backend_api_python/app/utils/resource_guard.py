"""Process-level guardrails for resource exhaustion.

When the process runs out of file descriptors, opening more sockets makes the
outage worse.  This module provides a small global circuit breaker so market
data and exchange calls can fail fast while the OS has time to close sockets.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_fd_exhausted_until = 0.0
_last_log_at = 0.0


class ResourceExhaustedError(RuntimeError):
    """Raised when a process-wide resource circuit breaker is active."""


def is_fd_exhaustion(exc: BaseException) -> bool:
    """Return True when an exception chain indicates process FD exhaustion."""
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and getattr(current, "errno", None) == 24:
            return True
        text = str(current or "").lower()
        if "too many open files" in text or "errno 24" in text:
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return False


def fd_cooldown_seconds() -> float:
    try:
        return max(30.0, float(os.getenv("RESOURCE_FD_COOLDOWN_SEC", "180")))
    except Exception:
        return 180.0


def mark_fd_exhausted(exc: BaseException | str | None = None, *, seconds: float | None = None) -> None:
    """Open the FD-exhaustion circuit breaker."""
    global _fd_exhausted_until, _last_log_at
    sec = float(seconds if seconds is not None else fd_cooldown_seconds())
    until = time.monotonic() + max(1.0, sec)
    now = time.monotonic()
    with _lock:
        _fd_exhausted_until = max(_fd_exhausted_until, until)
        should_log = now - _last_log_at > 10.0
        if should_log:
            _last_log_at = now
    if should_log:
        logger.error(
            "Process file descriptors exhausted; external requests paused for %.0fs. cause=%s",
            max(1.0, _fd_exhausted_until - time.monotonic()),
            str(exc or "")[:240],
        )


def fd_cooldown_remaining() -> float:
    with _lock:
        remaining = _fd_exhausted_until - time.monotonic()
    return max(0.0, remaining)


def is_fd_cooldown_active() -> bool:
    return fd_cooldown_remaining() > 0


def assert_fd_available(scope: str = "external request") -> None:
    remaining = fd_cooldown_remaining()
    if remaining > 0:
        raise ResourceExhaustedError(
            f"{scope} skipped: process file descriptors exhausted, retry after {remaining:.0f}s"
        )


def record_exception(exc: BaseException, *, scope: str = "external request") -> None:
    if is_fd_exhaustion(exc):
        mark_fd_exhausted(exc)
        raise ResourceExhaustedError(
            f"{scope} failed: process file descriptors exhausted"
        ) from exc
