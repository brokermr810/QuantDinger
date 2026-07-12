from datetime import datetime
import importlib

from app.services.unified_backtest import UnifiedBacktestService


def test_all_markets_retry_recent_candles_and_report_actual_range(monkeypatch):
    calls = []

    def fake_get_kline(**kwargs):
        calls.append(dict(kwargs))
        if kwargs.get("after_time") is not None:
            return []
        return [
            {"time": 1783814400, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0},
            {"time": 1783814460, "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 12.0},
        ]

    module = importlib.import_module("app.services.unified_backtest")
    monkeypatch.setattr(module.DataSourceFactory, "get_kline", fake_get_kline)

    frame = UnifiedBacktestService()._fetch_kline_data(
        "Crypto",
        "BTC/USDT",
        "1m",
        datetime(2026, 7, 10),
        datetime(2026, 7, 12, 23, 59),
        exchange_id="bitget",
        market_type="swap",
    )

    assert len(frame) == 2
    assert len(calls) == 2
    assert calls[0]["after_time"] is not None
    assert calls[1]["after_time"] is None
    assert frame.attrs["backtestActualRange"]["actualStart"]
    assert frame.attrs["backtestActualRange"]["actualEnd"]
