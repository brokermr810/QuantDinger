import pandas as pd

from app.routes.backtest_center import _merge_backtest_fees
from app.services.backtest_execution import merge_strict_mode_into_strategy_config
from app.services.strategy_snapshot import StrategySnapshotResolver
from app.services.unified_backtest import UnifiedBacktestService


def test_official_default_execution_is_next_bar_open():
    cfg = merge_strict_mode_into_strategy_config({}, True)

    assert cfg["strictMode"] is True
    assert cfg["execution"]["signalTiming"] == "next_bar_open"


def test_spot_backtest_funding_is_forced_to_zero():
    cfg = _merge_backtest_fees(
        {"market_type": "spot"},
        {
            "marketType": "spot",
            "fundingRateAnnual": 0.25,
            "fundingIntervalHours": 1,
        },
    )

    assert cfg["fees"]["fundingRateAnnual"] == 0.0
    assert cfg["fees"]["fundingIntervalHours"] == 8.0


def test_spot_snapshot_forces_long_only_and_one_x_leverage():
    strategy = {
        "id": 201,
        "strategy_name": "Spot contract guard",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": (
            "def on_init(ctx):\n"
            "    pass\n\n"
            "def on_bar(ctx, bar):\n"
            "    ctx.open_long(amount=1, price=bar['close'])\n"
        ),
        "market_category": "Crypto",
        "trading_config": {
            "symbol": "BTC/USDT",
            "market_type": "spot",
            "timeframe": "1H",
            "leverage": 25,
            "trade_direction": "both",
        },
    }

    snapshot = StrategySnapshotResolver(user_id=1).resolve(
        strategy,
        {
            "market_type": "spot",
            "leverage": 50,
            "trade_direction": "short",
        },
    )

    assert snapshot["market_type"] == "spot"
    assert snapshot["leverage"] == 1
    assert snapshot["trade_direction"] == "long"


def test_script_template_has_no_dedicated_backtest_run_type():
    strategy = {
        "id": 202,
        "strategy_name": "Template is script preset",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": (
            "def on_init(ctx):\n"
            "    pass\n\n"
            "def on_bar(ctx, bar):\n"
            "    if ctx.position.is_flat():\n"
            "        ctx.open_long(amount=1, price=bar['close'])\n"
        ),
        "market_category": "Crypto",
        "trading_config": {
            "symbol": "BTC/USDT",
            "market_type": "swap",
            "timeframe": "1H",
        },
    }

    snapshot = StrategySnapshotResolver(user_id=1).resolve(strategy, {})

    assert snapshot["strategy_mode"] == "script"
    assert snapshot["run_type"] == "strategy_script"


def test_script_backtest_accepts_epoch_second_time_column(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=8, freq="1D")
    prices = [100, 102, 104, 106, 108, 107, 109, 111]

    def fake_fetch(self, market, symbol, timeframe, start_date, end_date, **kwargs):
        out = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
                "time": [int(ts.timestamp()) for ts in idx],
            },
            index=idx,
        )
        out.attrs["timeframe"] = timeframe
        return out

    monkeypatch.setattr(UnifiedBacktestService, "_fetch_kline_data", fake_fetch)
    snapshot = {
        "strategy_id": 203,
        "strategy_name": "Epoch seconds smoke",
        "run_type": "strategy_script",
        "code": (
            "def on_bar(ctx, bar):\n"
            "    i = int(ctx.current_index)\n"
            "    if i == 1 and ctx.position.is_flat():\n"
            "        ctx.open_long(amount=1, price=bar['close'], reason='entry')\n"
            "    if i == 4 and ctx.position.has_long():\n"
            "        ctx.close_long(price=bar['close'], reason='exit')\n"
        ),
        "market": "Crypto",
        "symbol": "BTC/USDT",
        "timeframe": "1D",
        "market_type": "swap",
        "initial_capital": 10000,
        "trade_direction": "long",
        "strategy_config": {"execution": {"signalTiming": "next_bar_open"}},
    }

    result = UnifiedBacktestService().run_strategy_snapshot(
        snapshot,
        idx[0].to_pydatetime(),
        idx[-1].to_pydatetime(),
    )

    assert result["signalDiagnostics"]["entrySignals"] == 1
    assert result["signalDiagnostics"]["exitSignals"] == 1


def test_script_backtest_ctx_sees_filled_position_on_next_bar(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=5, freq="1D")
    prices = [100, 110, 120, 130, 140]

    def fake_fetch(self, market, symbol, timeframe, start_date, end_date, **kwargs):
        out = pd.DataFrame(
            {
                "open": prices,
                "high": [p + 1 for p in prices],
                "low": [p - 1 for p in prices],
                "close": prices,
                "volume": [1000] * len(prices),
            },
            index=idx,
        )
        out.attrs["timeframe"] = timeframe
        return out

    monkeypatch.setattr(UnifiedBacktestService, "_fetch_kline_data", fake_fetch)
    snapshot = {
        "strategy_id": 204,
        "strategy_name": "Position visibility",
        "run_type": "strategy_script",
        "code": (
            "def on_bar(ctx, bar):\n"
            "    i = int(ctx.current_index)\n"
            "    if i == 0 and ctx.position.is_flat():\n"
            "        ctx.open_long(amount=1, price=bar['close'], reason='entry')\n"
            "    if i == 1 and ctx.position.has_long():\n"
            "        ctx.close_long(reason='exit')\n"
        ),
        "market": "Crypto",
        "symbol": "BTC/USDT",
        "timeframe": "1D",
        "market_type": "swap",
        "initial_capital": 10000,
        "trade_direction": "long",
        "strategy_config": {"execution": {"signalTiming": "next_bar_open"}},
    }

    result = UnifiedBacktestService().run_strategy_snapshot(
        snapshot,
        idx[0].to_pydatetime(),
        idx[-1].to_pydatetime(),
    )

    assert result["totalTrades"] == 1
    assert result["closedTrades"][0]["entry_price"] == 110
    assert result["closedTrades"][0]["exit_price"] == 120
    assert result["closedTrades"][0]["profit"] == 10


def test_script_backtest_rejects_orders_when_margin_is_insufficient(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=3, freq="1D")
    prices = [100, 100, 100]

    def fake_fetch(self, market, symbol, timeframe, start_date, end_date, **kwargs):
        out = pd.DataFrame(
            {
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1000] * len(prices),
            },
            index=idx,
        )
        out.attrs["timeframe"] = timeframe
        return out

    monkeypatch.setattr(UnifiedBacktestService, "_fetch_kline_data", fake_fetch)
    snapshot = {
        "strategy_id": 205,
        "strategy_name": "Insufficient margin",
        "run_type": "strategy_script",
        "code": (
            "def on_bar(ctx, bar):\n"
            "    if int(ctx.current_index) == 0:\n"
            "        ctx.open_long(amount=1000, price=bar['close'], reason='too_big')\n"
        ),
        "market": "Crypto",
        "symbol": "BTC/USDT",
        "timeframe": "1D",
        "market_type": "swap",
        "initial_capital": 1000,
        "leverage": 1,
        "trade_direction": "long",
        "strategy_config": {"execution": {"signalTiming": "next_bar_open"}},
    }

    result = UnifiedBacktestService().run_strategy_snapshot(
        snapshot,
        idx[0].to_pydatetime(),
        idx[-1].to_pydatetime(),
    )

    assert result["totalTrades"] == 0
    assert result["signalDiagnostics"]["rejectedOrderCount"] == 1
    assert result["orders"][0]["status"] == "rejected"
    assert result["orders"][0]["rejectReason"] == "insufficient_margin"
