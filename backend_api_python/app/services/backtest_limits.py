"""Backtest range policy shared by human and agent endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any, Dict, Iterable, Optional

from app.data_sources.factory import DataSourceFactory


_TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1H": 3600,
    "4H": 14400,
    "1D": 86400,
    "1W": 604800,
}

_TIMEFRAME_ALIASES = {key.lower(): key for key in _TIMEFRAME_SECONDS}


class BacktestRangeLimitError(ValueError):
    """Structured range rejection that routes can return to API clients."""

    def __init__(self, details: Dict[str, Any]) -> None:
        super().__init__("strategyV2.backtestRangeLimit")
        self.details = details


@dataclass(frozen=True)
class BacktestRangePolicy:
    max_days: int
    label: str
    reason: str


_DEFAULT_LIMITS: Dict[str, BacktestRangePolicy] = {
    "1m": BacktestRangePolicy(30, "1 month", "engine workload limit"),
    "3m": BacktestRangePolicy(30, "1 month", "engine workload limit"),
    "5m": BacktestRangePolicy(180, "6 months", "engine workload limit"),
    "15m": BacktestRangePolicy(365, "1 year", "engine workload limit"),
    "30m": BacktestRangePolicy(365, "1 year", "engine workload limit"),
    "1H": BacktestRangePolicy(1095, "3 years", "engine workload limit"),
    "4H": BacktestRangePolicy(1095, "3 years", "engine workload limit"),
    "1D": BacktestRangePolicy(1095, "3 years", "engine workload limit"),
    "1W": BacktestRangePolicy(1095, "3 years", "engine workload limit"),
}


_MARKET_LIMITS: Dict[str, Dict[str, BacktestRangePolicy]] = {
    # yfinance intraday endpoints are much narrower than daily/weekly history.
    # Keep the cap below the upstream hard edge so indicator warmup does not
    # push an apparently valid user window into an upstream 400.
    "USStock": {
        "1m": BacktestRangePolicy(7, "7 days", "US stock intraday data provider limit"),
        "3m": BacktestRangePolicy(7, "7 days", "US stock intraday data provider limit"),
        "5m": BacktestRangePolicy(60, "60 days", "US stock intraday data provider limit"),
        "15m": BacktestRangePolicy(60, "60 days", "US stock intraday data provider limit"),
        "30m": BacktestRangePolicy(60, "60 days", "US stock intraday data provider limit"),
        "1H": BacktestRangePolicy(700, "about 23 months", "US stock hourly data provider limit"),
        "4H": BacktestRangePolicy(700, "about 23 months", "US stock hourly data provider limit"),
        "1D": BacktestRangePolicy(3650, "10 years", "US stock daily data provider limit"),
        "1W": BacktestRangePolicy(3650, "10 years", "US stock weekly data provider limit"),
    },
    # Public forex fallbacks often cap output size or paid subscription depth.
    # These limits avoid silently requesting more bars than the configured
    # provider can return in one backtest run.
    "Forex": {
        "1m": BacktestRangePolicy(7, "7 days", "forex intraday data provider limit"),
        "3m": BacktestRangePolicy(30, "30 days", "forex intraday data provider limit"),
        "5m": BacktestRangePolicy(60, "60 days", "forex intraday data provider limit"),
        "15m": BacktestRangePolicy(60, "60 days", "forex intraday data provider limit"),
        "30m": BacktestRangePolicy(120, "120 days", "forex intraday data provider limit"),
        "1H": BacktestRangePolicy(365, "1 year", "forex hourly data provider limit"),
        "4H": BacktestRangePolicy(730, "2 years", "forex 4H data provider limit"),
        "1D": BacktestRangePolicy(1095, "3 years", "forex daily data provider limit"),
        "1W": BacktestRangePolicy(1095, "3 years", "forex weekly data provider limit"),
    },
}


def normalize_backtest_timeframe(timeframe: str) -> str:
    raw = str(timeframe or "1D").strip()
    return _TIMEFRAME_ALIASES.get(raw.lower(), raw)


def backtest_range_policy(market: str, timeframe: str) -> BacktestRangePolicy:
    normalized_market = DataSourceFactory.normalize_market(market or "")
    tf = normalize_backtest_timeframe(timeframe)
    return (
        _MARKET_LIMITS.get(normalized_market, {}).get(tf)
        or _DEFAULT_LIMITS.get(tf)
        or _DEFAULT_LIMITS["1D"]
    )


def backtest_warmup_calendar_days(timeframe: str, warmup_bars: int) -> int:
    bars = max(0, int(warmup_bars or 0))
    if bars == 0:
        return 0
    normalized = normalize_backtest_timeframe(timeframe).lower()
    if normalized.endswith("m") and normalized[:-1].isdigit():
        minutes = max(1, int(normalized[:-1]))
        return max(1, math.ceil(bars * minutes * 1.5 / 1440.0))
    if normalized.endswith("h") and normalized[:-1].isdigit():
        hours = max(1, int(normalized[:-1]))
        return max(1, math.ceil(bars * hours * 1.5 / 24.0))
    if normalized.endswith("d"):
        return max(2, math.ceil(bars * 7.0 / 5.0 * 1.35))
    if normalized.endswith("w"):
        return max(8, bars * 8)
    return max(1, math.ceil(bars * 1.5))


def backtest_range_policy_metadata(
    *,
    markets: Iterable[str],
    timeframe: str,
    warmup_bars: int = 0,
) -> Dict[str, Any]:
    """Return the strictest client-facing policy for a compiled strategy."""
    normalized_markets = list(dict.fromkeys(
        DataSourceFactory.normalize_market(market or "")
        for market in markets
    )) or [""]
    policies = [
        (market, backtest_range_policy(market, timeframe))
        for market in normalized_markets
    ]
    market, policy = min(policies, key=lambda item: item[1].max_days)
    normalized_timeframe = normalize_backtest_timeframe(timeframe)
    timeframe_seconds = _TIMEFRAME_SECONDS.get(normalized_timeframe, 86400)
    normalized_warmup_bars = max(0, int(warmup_bars or 0))
    warmup_days = backtest_warmup_calendar_days(normalized_timeframe, normalized_warmup_bars)
    return {
        "timeframe": normalized_timeframe,
        "market": market,
        "maxDays": policy.max_days,
        "maxSelectedDays": max(0, policy.max_days - warmup_days),
        "warmupBars": normalized_warmup_bars,
        "warmupDays": warmup_days,
        "timeframeSeconds": timeframe_seconds,
        "maxBars": max(1, (policy.max_days * 86400) // timeframe_seconds),
    }


def _date_limit_start(end_date: datetime, max_days: int, warmup_seconds: int) -> datetime:
    """Return a date-only friendly start that keeps the fetch window under max_days."""
    return end_date - timedelta(days=max(0, int(max_days) - 1)) + timedelta(seconds=warmup_seconds)


def _date_limit_end(fetch_start: datetime, max_days: int) -> datetime:
    """Return a date-only friendly end that keeps the fetch window under max_days."""
    return fetch_start + timedelta(days=max(0, int(max_days) - 1))


def validate_backtest_range(
    *,
    market: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    warmup_bars: int = 0,
    fetch_start: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Return a structured range error, or None when the request is allowed."""
    policy = backtest_range_policy(market, timeframe)
    normalized_timeframe = normalize_backtest_timeframe(timeframe)
    tf_seconds = _TIMEFRAME_SECONDS.get(normalized_timeframe, 86400)
    warmup_seconds = max(0, int(warmup_bars or 0)) * tf_seconds
    if fetch_start is None:
        fetch_start = start_date - timedelta(seconds=warmup_seconds)
    else:
        warmup_seconds = max(0, int((start_date - fetch_start).total_seconds()))
    selected_days = max(0, (end_date - start_date).days)
    fetch_days = max(0, (end_date - fetch_start).days)
    if fetch_days <= policy.max_days:
        return None

    warmup_note = ""
    if warmup_bars:
        warmup_note = f" including {int(warmup_bars)} warmup bars"
    warmup_days = int((warmup_seconds + 86399) // 86400)
    recommendation_available = warmup_seconds < policy.max_days * 86400
    recommended_start_str = None
    recommended_end_str = None
    recommendation_msg = (
        "Please shorten the date range or use a higher timeframe."
    )
    if recommendation_available:
        recommended_start = _date_limit_start(end_date, policy.max_days, warmup_seconds)
        if recommended_start > end_date:
            recommended_start = end_date
        recommended_end = _date_limit_end(fetch_start, policy.max_days)
        if recommended_end > end_date:
            recommended_end = end_date
        recommended_start_str = recommended_start.strftime("%Y-%m-%d")
        recommended_end_str = recommended_end.strftime("%Y-%m-%d")
        recommendation_msg = (
            f"Please shorten the date range or use a higher timeframe. "
            f"Suggested fix: use {recommended_start_str} to {end_date.strftime('%Y-%m-%d')} "
            f"to keep the current end date, or keep start date {start_date.strftime('%Y-%m-%d')} "
            f"and set end date to {recommended_end_str}."
        )
    elif warmup_bars:
        recommendation_msg = (
            "The indicator warmup alone exceeds this data provider limit. "
            "Reduce long lookback parameters, reduce warmup requirements, or use a higher timeframe."
        )
    msg = (
        f"Backtest range exceeds limit: {market}:{symbol} timeframe {timeframe} "
        f"supports up to {policy.label} ({policy.max_days} days) because of the "
        f"{policy.reason}, but this request needs {fetch_days} days{warmup_note}. "
        f"{recommendation_msg}"
    )
    return {
        "error_type": "BACKTEST_RANGE_LIMIT",
        "msg": msg,
        "market": DataSourceFactory.normalize_market(market or ""),
        "symbol": symbol,
        "timeframe": timeframe,
        "max_days": policy.max_days,
        "max_range": policy.label,
        "reason": policy.reason,
        "selected_days": selected_days,
        "fetch_days": fetch_days,
        "warmup_bars": int(warmup_bars or 0),
        "warmup_days": warmup_days,
        "fetch_start": fetch_start.strftime("%Y-%m-%d"),
        "requested_start": start_date.strftime("%Y-%m-%d"),
        "requested_end": end_date.strftime("%Y-%m-%d"),
        "recommendation_available": recommendation_available,
        "recommended_start": recommended_start_str,
        "recommended_end": recommended_end_str,
    }
