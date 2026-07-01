# -*- coding: utf-8 -*-
"""Rate limiting and retry helpers for external market-data sources."""

from __future__ import annotations

import logging
import random
import time
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Type

from app.utils.resource_guard import (
    is_fd_exhaustion,
    mark_fd_exhausted,
    ResourceExhaustedError,
)

logger = logging.getLogger(__name__)


def _is_too_many_open_files(exc: BaseException) -> bool:
    """Return True when an exception chain indicates process FD exhaustion."""
    return is_fd_exhaustion(exc)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


def get_random_user_agent() -> str:
    """Return a random User-Agent."""
    return random.choice(USER_AGENTS)


def get_request_headers(referer: Optional[str] = None) -> dict:
    """Build request headers for external market-data calls."""
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def random_sleep(
    min_seconds: float = 1.0,
    max_seconds: float = 3.0,
    log: bool = False,
) -> None:
    """Sleep for a random jitter interval."""
    sleep_time = random.uniform(min_seconds, max_seconds)
    if log:
        logger.debug("Sleeping for %.2fs before external request", sleep_time)
    time.sleep(sleep_time)


class RateLimiter:
    """Simple process-local rate limiter with jitter."""

    def __init__(
        self,
        min_interval: float = 1.0,
        jitter_min: float = 0.5,
        jitter_max: float = 1.5,
    ):
        self.min_interval = min_interval
        self.jitter_min = jitter_min
        self.jitter_max = jitter_max
        self._last_request_time: Optional[float] = None

    def wait(self) -> float:
        """Wait until the next request is allowed and return slept seconds."""
        wait_time = 0.0
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                time.sleep(wait_time)

        jitter = random.uniform(self.jitter_min, self.jitter_max)
        time.sleep(jitter)
        wait_time += jitter
        self._last_request_time = time.time()
        return wait_time

    def reset(self) -> None:
        self._last_request_time = None


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """Retry a callable with exponential backoff.

    File-descriptor exhaustion is never retried because retries create more
    sockets and log writes, making the failure mode worse.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception: Optional[Exception] = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc

                    if _is_too_many_open_files(exc):
                        mark_fd_exhausted(exc)
                        logger.error(
                            "[retry] %s aborted: process file descriptors are exhausted: %s",
                            func.__name__,
                            exc,
                        )
                        raise ResourceExhaustedError(
                            f"{func.__name__} aborted: process file descriptors exhausted"
                        ) from exc

                    if attempt >= max_attempts:
                        logger.error(
                            "[retry] %s reached max attempts (%s); giving up",
                            func.__name__,
                            max_attempts,
                        )
                        raise

                    delay = min(
                        base_delay * (exponential_base ** (attempt - 1)),
                        max_delay,
                    )
                    delay *= random.uniform(0.8, 1.2)
                    logger.warning(
                        "[retry] %s failed %s/%s: %s; retrying in %.1fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )

                    if on_retry:
                        on_retry(attempt, exc)

                    time.sleep(delay)

            if last_exception is not None:
                raise last_exception
            return None

        return wrapper

    return decorator


_eastmoney_limiter = RateLimiter(min_interval=2.0, jitter_min=1.0, jitter_max=3.0)
_tencent_limiter = RateLimiter(min_interval=1.0, jitter_min=0.5, jitter_max=1.5)
_akshare_limiter = RateLimiter(min_interval=2.0, jitter_min=1.5, jitter_max=3.5)


def get_eastmoney_limiter() -> RateLimiter:
    """Return the Eastmoney rate limiter."""
    return _eastmoney_limiter


def get_tencent_limiter() -> RateLimiter:
    """Return the Tencent rate limiter."""
    return _tencent_limiter


def get_akshare_limiter() -> RateLimiter:
    """Return the AkShare rate limiter."""
    return _akshare_limiter
