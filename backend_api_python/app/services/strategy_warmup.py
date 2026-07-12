"""Shared ScriptStrategy warmup contract for backtest and live runtimes."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.services.indicator_params import IndicatorParamsParser, StrategyConfigParser


MAX_STARTUP_CANDLES = 5000


def resolve_startup_candle_count(
    code: str,
    params: Optional[Dict[str, Any]] = None,
) -> int:
    """Resolve declared startup candles, falling back to conservative inference."""
    headers = StrategyConfigParser.parse_contract_headers(code or "")
    declared_count = headers.get("startup_candle_count")
    if declared_count is not None:
        try:
            return max(0, min(MAX_STARTUP_CANDLES, int(declared_count)))
        except (TypeError, ValueError):
            pass

    merged: Dict[str, Any] = {}
    try:
        declared = IndicatorParamsParser.parse_params(code or "")
        merged = IndicatorParamsParser.merge_params(declared, params or {})
    except Exception:
        merged = dict(params or {})

    ctx_param_re = re.compile(
        r"ctx\.param\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([-+]?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    for name, default_value in ctx_param_re.findall(code or ""):
        merged.setdefault(name, default_value)

    period_name_re = re.compile(
        r"(len|length|period|window|lookback|ema|sma|rsi|adx|atr|vol|ma)$",
        re.IGNORECASE,
    )
    recursive_name_re = re.compile(r"(ema|rsi|adx|atr|macd|wilder)", re.IGNORECASE)
    max_period = 0
    max_recursive_period = 0
    for key, value in merged.items():
        name = str(key or "")
        try:
            period = int(float(value))
        except (TypeError, ValueError):
            continue
        if period <= 1 or period > 10000:
            continue
        if period_name_re.search(name) or name.endswith("_n"):
            max_period = max(max_period, period)
            if recursive_name_re.search(name):
                max_recursive_period = max(max_recursive_period, period)

    if max_period <= 0:
        return 0
    if max_recursive_period > 0:
        inferred = max(max_period + 50, max_recursive_period * 5)
    else:
        inferred = max_period + max(20, math.ceil(max_period * 0.5))
    return int(min(MAX_STARTUP_CANDLES, inferred))


def warmup_start_date(
    start_date: datetime,
    timeframe: str,
    warmup_bars: int,
    market: str = "Crypto",
) -> datetime:
    """Estimate a fetch start that contains enough sessions for warmup bars."""
    if warmup_bars <= 0:
        return start_date

    timeframe_seconds = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1H": 3600,
        "4H": 14400,
        "1D": 86400,
        "1W": 604800,
    }.get(str(timeframe or "1D"), 86400)
    market_key = str(market or "").strip().lower()
    if market_key in {"crypto", "cryptocurrency"}:
        return start_date - timedelta(seconds=timeframe_seconds * warmup_bars)

    if timeframe_seconds >= 604800:
        return start_date - timedelta(days=math.ceil(warmup_bars * 7 * 1.2) + 14)

    session_hours = 6.5
    if market_key in {"cnstock", "a-share", "ashare"}:
        session_hours = 4.0
    elif market_key in {"hkstock", "hongkongstock"}:
        session_hours = 5.5
    bars_per_session = max(1, int((session_hours * 3600) // timeframe_seconds))
    trading_days = math.ceil(warmup_bars / bars_per_session)
    calendar_days = math.ceil(trading_days * 1.65) + 14
    return start_date - timedelta(days=calendar_days)


def required_live_history_limit(configured_limit: int, startup_candles: int) -> int:
    """Return a live fetch size including one forming candle."""
    return max(2, int(configured_limit or 0), max(0, int(startup_candles or 0)) + 1)


def live_warmup_status(received_candles: int, startup_candles: int) -> Dict[str, Any]:
    """Describe whether a live candle feed has enough completed history."""
    received = max(0, int(received_candles or 0))
    required = max(0, int(startup_candles or 0))
    completed = max(0, received - 1)
    return {
        "required": required,
        "completed": completed,
        "missing": max(0, required - completed),
        "ready": received >= 2 and completed >= required,
    }
