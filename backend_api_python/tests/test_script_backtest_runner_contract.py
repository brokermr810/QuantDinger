from __future__ import annotations

import pandas as pd

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner


def _df() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=6, freq="D")
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 105],
            "high": [102, 103, 104, 105, 106, 107],
            "low": [99, 100, 101, 102, 103, 104],
            "close": [101, 102, 103, 104, 105, 106],
            "volume": [1000] * 6,
        },
        index=idx,
    )


def _compound_df(second_price: float) -> pd.DataFrame:
    opens = [100, 100, second_price, second_price, second_price, second_price, second_price, second_price]
    idx = pd.date_range("2025-01-01", periods=len(opens), freq="D")
    return pd.DataFrame(
        {
            "open": opens,
            "high": [price + 1 for price in opens],
            "low": [price - 1 for price in opens],
            "close": opens,
            "volume": [1000] * len(opens),
        },
        index=idx,
    )


def test_script_runner_exposes_ctx_contract_and_value_orders():
    df = _df()
    code = """
# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: strategy

def on_init(ctx):
    ctx.state.set("ready", True)

def on_bar(ctx, bar):
    value = ctx.param("entry_value", 1000)
    if ctx.current_index == 0:
        ctx.log("ctx:" + str(ctx.current_dt) + ":" + str(ctx.available_cash) + ":" + str(ctx.positions["long"]["size"]))
        ctx.order_value(value, side="long", reason="contract_entry")
    if ctx.current_index == 3:
        ctx.order_target(0, side="long", reason="contract_exit")
"""
    cfg = BacktestConfig(
        initial_capital=10_000,
        commission=0.0,
        slippage=0.0,
        leverage=1.0,
        trade_direction="long",
        timeframe="1D",
        signal_timing="next_bar_open",
        market_type="spot",
    )

    result = ScriptBacktestRunner(
        config=cfg,
        code=code,
        params={"entry_value": 1000},
        runtime={"symbol": "BTC/USDT"},
    ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())

    assert result["engine"]["version"] == "quantdinger-script-backtest-v3"
    assert result["totalTrades"] == 1
    assert result["orders"][0]["scriptIntent"] == "open_long"
    assert result["orders"][0]["notional"] == 1000
    assert result["orders"][1]["scriptIntent"] == "close_long"
    assert result["logs"]
    assert result["logs"][0].startswith("ctx:")


def test_script_runner_caps_full_quote_order_for_entry_fees():
    df = _df()
    code = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.order_value(ctx.investment_amount, side="long", reason="full_quote_entry")
    if ctx.current_index == 3:
        ctx.order_target(0, side="long", reason="full_quote_exit")
"""
    cfg = BacktestConfig(
        initial_capital=10_000,
        commission=0.001,
        slippage=0.0,
        leverage=1.0,
        trade_direction="long",
        timeframe="1D",
        signal_timing="next_bar_open",
        market_type="swap",
    )

    result = ScriptBacktestRunner(
        config=cfg,
        code=code,
        params={},
        runtime={"symbol": "BTC/USDT"},
    ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())

    assert result["engine"]["rejectedOrderCount"] == 0
    assert result["totalTrades"] == 1
    assert result["orders"][0]["status"] == "filled"
    assert result["orders"][0]["filledQuantity"] > 0


def test_script_runner_caps_compounded_full_equity_entries_after_profit_and_loss():
    code = """
def on_bar(ctx, bar):
    if ctx.current_index in (0, 3):
        ctx.order_value(ctx.equity, side="long", reason="compound_full_equity_entry")
    if ctx.current_index in (2, 5):
        ctx.order_target(0, side="long", reason="compound_full_equity_exit")
"""

    for second_price in (110, 90):
        df = _compound_df(second_price)
        cfg = BacktestConfig(
            initial_capital=10_000,
            commission=0.001,
            slippage=0.0,
            leverage=1.0,
            trade_direction="long",
            timeframe="1D",
            signal_timing="next_bar_open",
            market_type="swap",
        )
        result = ScriptBacktestRunner(
            config=cfg,
            code=code,
            params={},
            runtime={"symbol": "BTC/USDT"},
        ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())
        entries = [order for order in result["orders"] if order["scriptIntent"] == "open_long"]

        assert result["engine"]["rejectedOrderCount"] == 0
        assert result["totalTrades"] == 2
        assert len(entries) == 2
        assert all(order["status"] == "filled" for order in entries)
