from __future__ import annotations

import pandas as pd
import pytest

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner


def _frame(opens, highs=None, lows=None, closes=None) -> pd.DataFrame:
    closes = closes or opens
    highs = highs or [max(o, c) + 5 for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) - 5 for o, c in zip(opens, closes)]
    idx = pd.date_range("2026-02-01", periods=len(opens), freq="D")
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


def test_swap_next_open_quote_order_matches_manual_oracle():
    code = """
def on_init(ctx):
    ctx.entry_value = ctx.param("entry_value", 1000)

def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.order_value(ctx.entry_value, side="long", reason="oracle_entry")
    if ctx.current_index == 2:
        ctx.order_target(0, side="long", reason="oracle_exit")
"""
    frame = _frame([100, 110, 120, 130, 140])
    config = BacktestConfig(
        initial_capital=10_000,
        commission=0.0,
        slippage=0.0,
        leverage=2,
        trade_direction="long",
        timeframe="1D",
        market_type="swap",
        signal_timing="next_bar_open",
    )

    result = ScriptBacktestRunner(config=config, code=code, params={}, runtime={"symbol": "BTC/USDT"}).run(
        df=frame,
        start_date=frame.index[0].to_pydatetime(),
        end_date=frame.index[-1].to_pydatetime(),
    )

    entry_price = 110.0
    exit_price = 130.0
    qty = 1000.0 * 2.0 / entry_price
    expected_profit = (exit_price - entry_price) * qty
    expected_final_equity = 10_000.0 + expected_profit

    assert result["engine"]["orderCount"] == 2
    assert result["orders"][0]["submittedBar"] == 1
    assert result["orders"][0]["avgFillPrice"] == pytest.approx(entry_price)
    assert result["orders"][0]["filledQuantity"] == pytest.approx(qty)
    assert result["orders"][1]["submittedBar"] == 3
    assert result["orders"][1]["avgFillPrice"] == pytest.approx(exit_price)
    assert result["orders"][1]["filledQuantity"] == pytest.approx(qty)
    assert result["closedTrades"][0]["profit"] == pytest.approx(round(expected_profit, 2))
    assert result["finalEquity"] == pytest.approx(round(expected_final_equity, 2))


def test_spot_next_open_fee_and_slippage_matches_manual_oracle():
    code = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.order_value(1000, side="long", reason="spot_entry")
    if ctx.current_index == 2:
        ctx.order_target(0, side="long", reason="spot_exit")
"""
    frame = _frame(
        [100, 100, 110, 120, 130],
        highs=[106, 106, 116, 126, 136],
        lows=[94, 94, 104, 114, 124],
        closes=[100, 105, 110, 125, 130],
    )
    config = BacktestConfig(
        initial_capital=10_000,
        commission=0.001,
        slippage=0.01,
        leverage=1,
        trade_direction="long",
        timeframe="1D",
        market_type="spot",
        signal_timing="next_bar_open",
    )

    result = ScriptBacktestRunner(config=config, code=code, params={}, runtime={"symbol": "BTC/USDT"}).run(
        df=frame,
        start_date=frame.index[0].to_pydatetime(),
        end_date=frame.index[-1].to_pydatetime(),
    )

    entry_fill = 100.0 * 1.01
    exit_fill = 120.0 * 0.99
    qty = 1000.0 / entry_fill
    entry_fee = qty * entry_fill * 0.001
    exit_fee = qty * exit_fill * 0.001
    expected_cash = 10_000.0 - (qty * entry_fill) - entry_fee + (qty * exit_fill) - exit_fee
    expected_profit = (exit_fill - entry_fill) * qty - exit_fee

    assert result["orders"][0]["avgFillPrice"] == pytest.approx(entry_fill)
    assert result["orders"][0]["filledQuantity"] == pytest.approx(qty)
    assert result["orders"][0]["fee"] == pytest.approx(entry_fee)
    assert result["orders"][1]["avgFillPrice"] == pytest.approx(exit_fill)
    assert result["orders"][1]["filledQuantity"] == pytest.approx(qty)
    assert result["orders"][1]["fee"] == pytest.approx(exit_fee)
    assert result["closedTrades"][0]["profit"] == pytest.approx(round(expected_profit, 2))
    assert result["finalEquity"] == pytest.approx(round(expected_cash, 2))
    assert result["totalCommission"] == pytest.approx(round(entry_fee + exit_fee, 8))
