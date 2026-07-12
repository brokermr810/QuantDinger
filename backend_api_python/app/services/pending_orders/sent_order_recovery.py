"""Pure helpers for durable submitted-order reconciliation."""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple


def normalize_live_order_status(status: str) -> str:
    normalized = str(status or "").strip().lower().replace("_", "")
    if normalized in ("filled", "complete", "completed"):
        return "filled"
    if normalized in ("cancelled", "canceled", "apicancelled", "inactive", "expired", "rejected"):
        return "cancelled"
    if normalized in ("partiallyfilled", "partial", "partialfill"):
        return "partial"
    if normalized in ("submitted", "presubmitted", "pendingsubmit", "pendingcancel", "open", "new"):
        return "open"
    return "unknown"


def tracked_fill_baseline(
    row: Dict[str, Any],
    *,
    exchange_order_id: str,
    previous_filled: float,
    previous_avg: float,
) -> Tuple[float, float]:
    """Return the cumulative baseline for the currently tracked exchange leg."""
    tracked_filled = max(0.0, float(previous_filled or 0.0))
    tracked_avg = max(0.0, float(previous_avg or 0.0))
    try:
        previous_response = json.loads(str(row.get("exchange_response_json") or "{}")) or {}
        sync_state = previous_response.get("live_fill_sync") or {}
        if isinstance(sync_state, dict) and "tracked_filled" in sync_state:
            return (
                max(0.0, float(sync_state.get("tracked_filled") or 0.0)),
                max(0.0, float(sync_state.get("tracked_avg_price") or 0.0)),
            )
        executor_raw = ((previous_response.get("phases") or {}).get("executor") or {})
        market_summary = executor_raw.get("market_summary") or {}
        if (
            isinstance(market_summary, dict)
            and str(market_summary.get("exchange_order_id") or "") == str(exchange_order_id or "")
        ):
            return (
                max(0.0, float(market_summary.get("filled_qty") or 0.0)),
                max(0.0, float(market_summary.get("avg_price") or 0.0)),
            )
    except Exception:
        pass
    return tracked_filled, tracked_avg
