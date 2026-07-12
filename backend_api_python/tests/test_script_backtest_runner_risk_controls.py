from __future__ import annotations

import pandas as pd
import pytest

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner


ENTRY_ONLY_CODE = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.order_value(1000, side="long", reason="risk_entry")
"""


def _frame(opens, highs, lows, closes) -> pd.DataFrame:
    idx = pd.date_range("2026-03-01", periods=len(opens), freq="D")
    return pd.DataFrame(
        {
            "open": [float(v) for v in opens],
            "high": [float(v) for v in highs],
            "low": [float(v) for v in lows],
            "close": [float(v) for v in closes],
            "volume": [10_000.0] * len(opens),
        },
        index=idx,
    )


def _run(df: pd.DataFrame, **risk_kwargs) -> dict:
    config = BacktestConfig(
        initial_capital=10_000,
        commission=0.0,
        slippage=0.0,
        leverage=1.0,
        trade_direction="long",
        timeframe="1D",
        signal_timing="next_bar_open",
        market_type="swap",
        **risk_kwargs,
    )
    return ScriptBacktestRunner(
        config=config,
        code=ENTRY_ONLY_CODE,
        params={},
        runtime={"symbol": "BTC/USDT"},
    ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())


def _close_trade(result: dict) -> dict:
    closes = [trade for trade in result["trades"] if trade["type"] == "close_long"]
    assert closes
    return closes[0]


def test_script_runner_engine_stop_loss_triggers_from_bar_low():
    df = _frame(
        opens=[100, 100, 100, 100],
        highs=[101, 101, 102, 103],
        lows=[99, 99, 94, 98],
        closes=[100, 100, 96, 100],
    )

    result = _run(df, stop_loss_pct=0.05)

    close = _close_trade(result)
    assert close["reason"] == "stop_loss"
    assert close["price"] == pytest.approx(95.0)
    assert result["orders"][1]["reason"] == "stop_loss"


def test_script_runner_engine_take_profit_triggers_from_bar_high():
    df = _frame(
        opens=[100, 100, 100, 100],
        highs=[101, 101, 108, 103],
        lows=[99, 99, 99, 98],
        closes=[100, 100, 106, 100],
    )

    result = _run(df, take_profit_pct=0.05)

    close = _close_trade(result)
    assert close["reason"] == "take_profit"
    assert close["price"] == pytest.approx(105.0)
    assert result["orders"][1]["reason"] == "take_profit"


def test_script_runner_engine_trailing_stop_arms_then_closes_on_retracement():
    df = _frame(
        opens=[100, 100, 100, 100, 100],
        highs=[101, 101, 110, 108, 103],
        lows=[99, 99, 99, 102, 98],
        closes=[100, 100, 108, 104, 100],
    )

    result = _run(df, trailing_enabled=True, trailing_pct=0.04, trailing_activation_pct=0.05)

    close = _close_trade(result)
    assert close["reason"] == "trailing_stop"
    assert close["price"] == pytest.approx(105.6)
    assert result["orders"][1]["reason"] == "trailing_stop"


def test_script_runner_trailing_takes_priority_over_fixed_take_profit_when_enabled():
    df = _frame(
        opens=[100, 100, 100, 100],
        highs=[101, 101, 110, 103],
        lows=[99, 99, 99, 98],
        closes=[100, 100, 108, 100],
    )

    result = _run(
        df,
        take_profit_pct=0.05,
        trailing_enabled=True,
        trailing_pct=0.04,
        trailing_activation_pct=0.05,
    )

    close = _close_trade(result)
    assert close["reason"] == "trailing_stop"
    assert close["price"] == pytest.approx(105.6)
