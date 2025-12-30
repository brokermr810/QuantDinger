"""
Background worker for automated reflection verification.

This replaces the need for an external cron job in local deployments.
It periodically runs ReflectionService.run_verification_cycle().

Controls (env):
- ENABLE_REFLECTION_WORKER=true/false (default: false)
- REFLECTION_WORKER_INTERVAL_SEC (default: 86400)
"""

from __future__ import annotations

import os
import time
import threading
from typing import Optional

from app.utils.logger import get_logger
from .reflection import ReflectionService

logger = get_logger(__name__)


class ReflectionWorker:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return

        interval = int(os.getenv("REFLECTION_WORKER_INTERVAL_SEC", "86400") or 86400)
        interval = max(60, interval)  # at least 1 minute

        def _run():
            logger.info(f"Reflection worker started (interval={interval}s)")
            svc = ReflectionService()
            # Initial small delay to avoid fighting startup spikes
            time.sleep(3)
            while not self._stop.is_set():
                try:
                    svc.run_verification_cycle()
                except Exception as e:
                    logger.error(f"Reflection worker cycle failed: {e}")
                # Sleep in small steps to react to stop quickly
                remaining = interval
                while remaining > 0 and not self._stop.is_set():
                    step = min(5, remaining)
                    time.sleep(step)
                    remaining -= step
            logger.info("Reflection worker stopped")

        self._thread = threading.Thread(target=_run, name="ReflectionWorker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            try:
                t.join(timeout=5)
            except Exception:
                pass


