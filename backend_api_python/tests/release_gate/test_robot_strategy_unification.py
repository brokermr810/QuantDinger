from __future__ import annotations

import pandas as pd

from app.services.backtest_engine.models import BacktestConfig
from app.services.backtest_engine.script_strategy import ScriptStrategyBacktestRunner
from app.services.strategy_runtime.executors import build_executor_strategy_payload
from app.services.strategy_script_runtime import compile_strategy_script_handlers


def _payload(executor_type: str) -> dict:
    base = {
        "executor_type": executor_type,
        "symbol": "BTC/USDT",
        "market_type": "swap",
        "side": "long",
        "initial_capital": 1000,
        "take_profit_pct": 0.02,
    }
    if executor_type == "grid":
        base.update({
            "start_price": 90,
            "end_price": 110,
            "grid_count": 4,
            "total_amount_quote": 400,
        })
    elif executor_type == "layered_martingale":
        base.update({
            "entry_price": 100,
            "layer_count": 2,
            "orders_per_layer": 2,
            "base_order_size": 50,
        })
    else:
        base.update({
            "entry_price": 100,
            "base_order_size": 50,
            "safety_order_size": 60,
            "max_layers": 3,
        })
    return build_executor_strategy_payload(base, user_id=1)


def test_visual_robot_builder_generates_editable_script_contracts():
    for executor_type in ("grid", "dca", "martingale", "layered_martingale"):
        payload = _payload(executor_type)
        on_init, on_bar = compile_strategy_script_handlers(payload["strategy_code"])
        assert callable(on_init)
        assert callable(on_bar)
        assert payload["trading_config"]["strategy_family"] == "executor"
        assert payload["trading_config"]["executor_type"] == executor_type
        assert payload["strategy_name"] in payload["strategy_code"]


def test_generated_grid_strategy_runs_through_unified_backtest():
    payload = _payload("grid")
    index = pd.date_range("2026-01-01", periods=12, freq="5min")
    closes = [112, 108, 104, 99, 94, 91, 96, 101, 106, 109, 103, 98]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [value + 4 for value in closes],
            "low": [value - 4 for value in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=index,
    )
    config = BacktestConfig(
        initial_capital=1000,
        commission=0,
        slippage=0,
        timeframe="5m",
        market_type="swap",
        trade_direction="long",
        signal_timing="current_close",
    )
    result = ScriptStrategyBacktestRunner(
        config=config,
        code=payload["strategy_code"],
        runtime={"symbol": "BTC/USDT"},
    ).run(
        df=frame,
        start_date=index[0].to_pydatetime(),
        end_date=index[-1].to_pydatetime(),
    )
    assert result["orders"]
    assert result["trades"]
    assert result["engine"]["version"] == "quantdinger-script-backtest-v3"
