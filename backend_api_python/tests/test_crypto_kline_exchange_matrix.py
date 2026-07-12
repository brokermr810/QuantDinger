from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from app.data_sources.crypto import (
    PUBLIC_KLINE_EXCHANGE_IDS,
    CryptoDataSource,
    resolve_ccxt_for_live_trading,
)


@pytest.mark.parametrize(
    ("exchange_id", "market_type", "expected_ccxt_id", "expected_default_type"),
    [
        ("binance", "spot", "binance", None),
        ("binance", "swap", "binanceusdm", None),
        ("bitget", "spot", "bitget", "spot"),
        ("bitget", "swap", "bitget", "swap"),
        ("bybit", "spot", "bybit", "spot"),
        ("bybit", "swap", "bybit", "linear"),
        ("okx", "spot", "okx", "spot"),
        ("okx", "swap", "okx", "swap"),
        ("gate", "spot", "gate", "spot"),
        ("gate", "swap", "gate", "swap"),
        ("htx", "spot", "htx", "spot"),
        ("htx", "swap", "htx", "swap"),
    ],
)
def test_public_kline_exchange_mapping(
    exchange_id,
    market_type,
    expected_ccxt_id,
    expected_default_type,
):
    ccxt_id, options = resolve_ccxt_for_live_trading(exchange_id, market_type)

    assert ccxt_id == expected_ccxt_id
    assert options.get("defaultType") == expected_default_type


def test_public_kline_exchange_list_is_stable():
    assert PUBLIC_KLINE_EXCHANGE_IDS == (
        "binance",
        "bitget",
        "bybit",
        "okx",
        "gate",
        "htx",
    )


def test_swap_symbol_uses_settlement_suffix():
    source = object.__new__(CryptoDataSource)
    source._scoped_market_type = "swap"
    source.exchange = SimpleNamespace(id="okx")
    source._markets_loaded = True
    source._markets_cache = {"BTC/USDT": {"active": True}}

    assert source._symbol_for_scoped_market("BTC/USDT") == "BTC/USDT:USDT"


def test_gate_long_range_fetch_is_clamped_to_recent_candle_limit():
    now_s = int(datetime.now(timezone.utc).timestamp())
    requested_since_s = now_s - 30 * 24 * 60 * 60
    calls = []

    def fetch_ohlcv(symbol, timeframe, since, limit):
        calls.append({"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit})
        return [[now_s * 1000, 100.0, 101.0, 99.0, 100.5, 10.0]]

    source = object.__new__(CryptoDataSource)
    source.exchange = SimpleNamespace(id="gate", enableRateLimit=True, fetch_ohlcv=fetch_ohlcv)

    rows = source._fetch_ohlcv(
        "BTC/USDT:USDT",
        "1m",
        50000,
        now_s,
        "1m",
        requested_since_s,
    )

    assert rows
    assert calls
    earliest_supported_ms = now_s * 1000 - (10000 - 1) * 60 * 1000
    assert calls[0]["since"] >= earliest_supported_ms


def test_any_exchange_falls_back_to_recent_candles_when_requested_window_is_rejected():
    now_s = int(datetime.now(timezone.utc).timestamp())
    calls = []

    def fetch_ohlcv(symbol, timeframe, since=None, limit=None):
        calls.append(since)
        if since is not None:
            raise RuntimeError("requested history window is unavailable")
        return [[now_s * 1000, 100.0, 101.0, 99.0, 100.5, 10.0]]

    source = object.__new__(CryptoDataSource)
    source.exchange = SimpleNamespace(id="bitget", enableRateLimit=True, fetch_ohlcv=fetch_ohlcv)

    rows = source._fetch_ohlcv(
        "BTC/USDT:USDT",
        "1m",
        50000,
        now_s,
        "1m",
        now_s - 30 * 24 * 60 * 60,
    )

    assert rows
    assert calls[-1] is None
