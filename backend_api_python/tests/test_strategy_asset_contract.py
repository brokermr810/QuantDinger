import pytest

from app.services.strategy_assets import _is_live_only_bot_code
from app.services.strategy_snapshot import StrategySnapshotResolver
from app.services.unified_backtest import UnifiedBacktestService
from tests.helpers.backtest_stress_cases import make_synthetic_ohlcv


def test_script_template_snapshot_is_code_backed_script_contract():
    strategy = {
        "id": 101,
        "strategy_name": "Code-backed template",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": "def on_init(ctx):\n    pass\n\ndef on_bar(ctx, bar):\n    if ctx.position.is_flat():\n        ctx.open_long(amount=1, price=bar['close'])\n",
        "market_category": "Crypto",
        "trading_config": {
            "symbol": "BTC/USDT",
            "market_type": "swap",
            "timeframe": "1H",
        },
    }

    snapshot = StrategySnapshotResolver(user_id=1).resolve(strategy, {"trade_direction": "both"})

    assert snapshot["run_type"] == "strategy_script"
    assert snapshot["strategy_mode"] == "script"
    assert snapshot["code"].strip().startswith("def on_init")
    assert snapshot["market_type"] == "swap"
    assert snapshot["trade_direction"] == "both"


def test_empty_script_template_is_rejected_before_backtest():
    strategy = {
        "id": 102,
        "strategy_name": "Empty template",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": "",
        "market_category": "Crypto",
        "trading_config": {
            "symbol": "BTC/USDT",
            "market_type": "swap",
            "timeframe": "1H",
        },
    }

    with pytest.raises(ValueError, match="Strategy code is empty"):
        StrategySnapshotResolver(user_id=1).resolve(strategy, {})


def test_live_only_grid_template_is_not_a_backtestable_code_strategy():
    assert _is_live_only_bot_code("")
    assert _is_live_only_bot_code(
        "def on_init(ctx):\n"
        "    ctx.__live_only_template__ = '__QD_LIVE_ONLY_GRID_TEMPLATE__'\n"
        "    ctx.log('grid bot: live execution uses resting limit-order engine')\n"
    )
    assert not _is_live_only_bot_code(
        "def on_init(ctx):\n"
        "    pass\n\n"
        "def on_bar(ctx, bar):\n"
        "    ctx.open_long(amount=1, price=bar['close'])\n"
    )


def test_code_backed_script_template_runs_through_script_engine(monkeypatch):
    code = (
        "def on_init(ctx):\n"
        "    pass\n\n"
        "def on_bar(ctx, bar):\n"
        "    idx = int(ctx.current_index)\n"
        "    if idx == 5 and ctx.position.is_flat():\n"
        "        ctx.open_long(amount=1, price=bar['close'], reason='template_entry')\n"
        "    if idx == 15 and ctx.position.has_long():\n"
        "        ctx.close_long(price=bar['close'], reason='template_exit')\n"
    )
    strategy = {
        "id": 104,
        "strategy_name": "Code-backed executable template",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": code,
        "market_category": "Crypto",
        "trading_config": {
            "symbol": "BTC/USDT",
            "market_type": "swap",
            "timeframe": "1H",
            "initial_capital": 10000,
            "commission": 0.0005,
            "slippage": 0.0005,
        },
    }
    snapshot = StrategySnapshotResolver(user_id=1).resolve(
        strategy,
        {
            "trade_direction": "both",
            "strategy_config": {
                "execution": {
                    "signalTiming": "next_bar_open",
                    "intrabarMode": "conservative",
                }
            },
        },
    )

    df = make_synthetic_ohlcv(days=5, freq="1h", seed=104, base_price=100.0)
    start_date = df.index[0].to_pydatetime()
    end_date = df.index[-1].to_pydatetime()

    def fake_fetch(self, market, symbol, timeframe, start_date, end_date, **kwargs):
        out = df.loc[(df.index >= start_date) & (df.index <= end_date)].copy()
        out.attrs["timeframe"] = timeframe
        return out

    monkeypatch.setattr(UnifiedBacktestService, "_fetch_kline_data", fake_fetch)

    result = UnifiedBacktestService().run_strategy_snapshot(snapshot, start_date, end_date)

    assert result["engine"]["version"] == "quantdinger-script-backtest-v3"
    assert result["executionAssumptions"]["simulationMode"] == "script_strategy_engine"
    assert result["totalTrades"] == 1
    assert result["bestTrade"] != 0 or result["worstTrade"] != 0
