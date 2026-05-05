import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config.data_sources import CCXTConfig
from app.data_sources import asia_stock_kline
from app.data_sources.base import TIMEFRAME_SECONDS
from app.data_sources.us_stock import USStockDataSource


def test_three_minute_timeframe_is_registered_for_kline_sources():
    assert TIMEFRAME_SECONDS["3m"] == 180
    assert CCXTConfig.TIMEFRAME_MAP["3m"] == "3m"

    assert USStockDataSource.INTERVAL_MAP["3m"] == "1m"
    assert USStockDataSource.MERGE_FACTOR_MAP["3m"] == 3

    assert asia_stock_kline._TD_INTERVAL_MAP["3m"] == "1min"
    assert asia_stock_kline._YF_INTERVAL_MAP["3m"] == "1m"
    assert asia_stock_kline._minute_period_str("3m") == "1"
    assert asia_stock_kline._MERGE_FACTOR_MAP["3m"] == 3


def test_three_minute_us_stock_bars_merge_one_minute_bars():
    source = USStockDataSource()
    bars = [
        {"time": 60, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"time": 120, "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 150},
        {"time": 180, "open": 11, "high": 11.5, "low": 10.8, "close": 11.2, "volume": 200},
        {"time": 240, "open": 11.2, "high": 11.4, "low": 11, "close": 11.1, "volume": 50},
    ]

    merged = source._merge_every_n_sorted_bars(bars, 3)

    assert merged == [
        {"time": 60, "open": 10, "high": 12, "low": 9, "close": 11.2, "volume": 450}
    ]
