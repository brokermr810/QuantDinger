"""Exchange-calendar scheduling for portfolio deployments."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd


CALENDAR_BY_MARKET = {
    "USStock": "XNYS",
    "HKStock": "XHKG",
    "AStock": "XSHG",
    "CNStock": "XSHG",
}


class MarketScheduleError(RuntimeError):
    pass


def latest_completed_session(
    market: str,
    now: Optional[datetime] = None,
    *,
    data_delay_minutes: int = 15,
) -> datetime:
    current = _utc(now)
    if _is_continuous_market(market):
        cutoff = current - timedelta(minutes=max(0, int(data_delay_minutes)))
        return datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=timezone.utc) - timedelta(days=1)
    calendar = _calendar(market)
    sessions = calendar.sessions_in_range(
        pd.Timestamp((current - timedelta(days=14)).date()),
        pd.Timestamp(current.date()),
    )
    delay = timedelta(minutes=max(0, int(data_delay_minutes)))
    completed = [session for session in sessions if _python_utc(calendar.session_close(session)) + delay <= current]
    if not completed:
        raise MarketScheduleError("portfolio.noCompletedMarketSession")
    return _python_utc(completed[-1]).replace(hour=0, minute=0, second=0, microsecond=0)


def next_rebalance_run(
    market: str,
    frequency: str,
    now: Optional[datetime] = None,
    *,
    data_delay_minutes: int = 15,
) -> datetime:
    current = _utc(now)
    clean_frequency = str(frequency or "weekly").strip().lower()
    if clean_frequency not in {"daily", "weekly", "monthly"}:
        raise MarketScheduleError("portfolio.invalidRebalanceFrequency")
    if _is_continuous_market(market):
        candidate = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        candidate += timedelta(minutes=max(0, int(data_delay_minutes)))
        if clean_frequency == "weekly":
            while candidate.weekday() != 0:
                candidate += timedelta(days=1)
        elif clean_frequency == "monthly":
            while candidate.day != 1:
                candidate += timedelta(days=1)
        return candidate.replace(tzinfo=None)

    calendar = _calendar(market)
    sessions = calendar.sessions_in_range(
        pd.Timestamp(current.date()),
        pd.Timestamp((current + timedelta(days=360)).date()),
    )
    delay = timedelta(minutes=max(0, int(data_delay_minutes)))
    for index, session in enumerate(sessions):
        run_at = _python_utc(calendar.session_close(session)) + delay
        if run_at <= current or not _is_period_end(sessions, index, clean_frequency):
            continue
        return run_at.replace(tzinfo=None)
    raise MarketScheduleError("portfolio.nextMarketSessionUnavailable")


def _is_period_end(sessions, index: int, frequency: str) -> bool:
    if frequency == "daily":
        return True
    current = sessions[index]
    if index + 1 >= len(sessions):
        return False
    following = sessions[index + 1]
    if frequency == "weekly":
        return current.isocalendar().week != following.isocalendar().week or current.year != following.year
    return current.month != following.month or current.year != following.year


def _calendar(market: str):
    try:
        import exchange_calendars as exchange_calendars
    except ImportError as exc:
        raise MarketScheduleError("portfolio.marketCalendarUnavailable") from exc
    code = CALENDAR_BY_MARKET.get(str(market or "").strip())
    if not code:
        raise MarketScheduleError("portfolio.marketCalendarUnsupported")
    return exchange_calendars.get_calendar(code)


def _is_continuous_market(market: str) -> bool:
    return str(market or "").strip() in {"Crypto", "Cryptocurrency"}


def _utc(value: Optional[datetime]) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _python_utc(value) -> datetime:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").to_pydatetime()
