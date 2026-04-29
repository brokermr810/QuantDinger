"""Unit tests for the MOEX (Moscow Exchange) data source.

These tests do not hit the real ISS API — they mock the HTTP layer.
A separate verification script (scripts/verify_moex.py) exercises the live API.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.data_sources.factory import DataSourceFactory
from app.data_sources.moex import INTERVAL_MAP, MOEXDataSource


def _candle_payload(rows):
    """Build a minimal MOEX ISS /candles.json payload."""
    return {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": rows,
        }
    }


def test_factory_recognizes_moex():
    assert DataSourceFactory.normalize_market("moex") == "MOEX"
    assert DataSourceFactory.normalize_market("MOEX") == "MOEX"
    assert DataSourceFactory.normalize_market("RuStocks") == "MOEX"
    src = DataSourceFactory.get_source("MOEX")
    assert isinstance(src, MOEXDataSource)


def test_normalize_symbol_strips_suffixes():
    assert MOEXDataSource._normalize_symbol("sber") == "SBER"
    assert MOEXDataSource._normalize_symbol("SBER.ME") == "SBER"
    assert MOEXDataSource._normalize_symbol("gazp.MOEX") == "GAZP"
    assert MOEXDataSource._normalize_symbol("LKOH:MOEX") == "LKOH"
    assert MOEXDataSource._normalize_symbol(" SBER ") == "SBER"


def test_interval_map_covers_all_quantdinger_timeframes():
    expected = {"1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W"}
    assert expected.issubset(set(INTERVAL_MAP.keys()))
    # Native ISS intervals
    assert INTERVAL_MAP["1m"] == 1
    assert INTERVAL_MAP["1H"] == 60
    assert INTERVAL_MAP["1D"] == 24
    assert INTERVAL_MAP["1W"] == 7


def test_moex_dt_to_unix_treats_naive_as_moscow():
    # MSK is UTC+3 (year-round, no DST since 2014).
    # 2025-01-10 12:00:00 MSK == 2025-01-10 09:00:00 UTC == 1736499600
    ts = MOEXDataSource._moex_dt_to_unix("2025-01-10 12:00:00")
    assert ts == 1736499600


def test_get_kline_native_daily_parses_payload():
    src = MOEXDataSource()
    rows = [
        # open, close, high, low, value, volume, begin,            end
        [100.0, 101.0, 102.0, 99.0, 1000.0, 500.0, "2025-01-10 00:00:00", "2025-01-10 23:59:59"],
        [101.0, 103.0, 104.0, 100.5, 1500.0, 700.0, "2025-01-13 00:00:00", "2025-01-13 23:59:59"],
        [103.0, 102.0, 103.5, 101.0, 1100.0, 400.0, "2025-01-14 00:00:00", "2025-01-14 23:59:59"],
    ]
    with patch.object(src, "_http_get", return_value=_candle_payload(rows)):
        out = src.get_kline("SBER", "1D", limit=10)
    assert len(out) == 3
    assert all({"time", "open", "high", "low", "close", "volume"} <= set(k.keys()) for k in out)
    # Sorted ascending by time
    assert out[0]["time"] < out[1]["time"] < out[2]["time"]
    # First candle: 2025-01-10 00:00:00 MSK == 2025-01-09 21:00:00 UTC
    assert out[0]["open"] == 100.0 and out[0]["close"] == 101.0


def test_get_kline_resamples_15m_from_1m():
    src = MOEXDataSource()
    # Build 30 contiguous 1-minute candles starting at 2025-01-10 10:00:00 MSK
    base = MOEXDataSource._moex_dt_to_unix("2025-01-10 10:00:00")
    rows = []
    for i in range(30):
        ts = base + i * 60
        # Construct begin string in MSK local time
        from datetime import datetime, timedelta, timezone
        msk = timezone(timedelta(hours=3))
        begin = datetime.fromtimestamp(ts, tz=msk).strftime("%Y-%m-%d %H:%M:%S")
        end = datetime.fromtimestamp(ts + 59, tz=msk).strftime("%Y-%m-%d %H:%M:%S")
        rows.append([
            100.0 + i, 100.5 + i, 101.0 + i, 99.5 + i, 10.0, 5.0, begin, end
        ])

    with patch.object(src, "_http_get", return_value=_candle_payload(rows)):
        out = src.get_kline("SBER", "15m", limit=10)
    # 30 minutes resampled into 15m buckets should yield exactly 2 bars
    assert len(out) == 2
    # Each 15m bar aggregates 15 1m bars
    assert out[0]["volume"] == round(5.0 * 15, 2)
    # Open of first bucket == open of first 1m candle; close == close of 15th
    assert out[0]["open"] == 100.0
    assert out[0]["close"] == 100.5 + 14


def test_get_kline_returns_empty_on_http_failure():
    src = MOEXDataSource()
    with patch.object(src, "_http_get", return_value=None):
        out = src.get_kline("UNKNOWN", "1D", limit=5)
    assert out == []


def test_get_kline_unsupported_timeframe_falls_back_to_daily():
    src = MOEXDataSource()
    rows = [
        [100.0, 101.0, 102.0, 99.0, 1000.0, 500.0, "2025-01-10 00:00:00", "2025-01-10 23:59:59"],
    ]
    with patch.object(src, "_http_get", return_value=_candle_payload(rows)):
        out = src.get_kline("SBER", "2D", limit=5)
    assert len(out) == 1


def test_resample_handles_empty():
    assert MOEXDataSource._resample([], 900) == []


def test_get_ticker_parses_marketdata():
    src = MOEXDataSource()
    payload = {
        "marketdata": {
            "columns": ["LAST", "LCLOSEPRICE", "OPEN", "HIGH", "LOW"],
            "data": [[310.5, 305.0, 306.0, 312.0, 304.0]],
        }
    }
    with patch.object(src, "_http_get", return_value=payload):
        t = src.get_ticker("SBER")
    assert t["last"] == 310.5
    assert t["previousClose"] == 305.0
    assert t["change"] == 5.5
    # 5.5 / 305 * 100 ≈ 1.8
    assert abs(t["changePercent"] - 1.8) < 0.05


def test_live_trading_blocked_for_moex():
    """The strategy service source must reject MOEX as a live-trading market_category.

    Read the file directly rather than importing it — importing pulls heavy
    optional deps (yfinance, etc.) that aren't required for offline tests.
    """
    import os
    import app
    app_pkg_dir = os.path.dirname(app.__file__)
    strat_path = os.path.join(app_pkg_dir, "services", "strategy.py")
    with open(strat_path, "r", encoding="utf-8") as f:
        src = f.read()
    # The guard appears in create / batch / update strategy paths.
    assert src.count("market_category == 'MOEX'") >= 3
    assert "Live order placement on MOEX is not implemented" in src
