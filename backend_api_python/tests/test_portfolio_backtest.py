import pandas as pd
import pytest

from app.services.portfolio_backtest import PortfolioBacktestConfig, PortfolioBacktestEngine


def _frame(dates, opens, closes=None):
    closes = closes or opens
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes)],
            "low": [min(o, c) for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1_000_000] * len(dates),
        },
        index=pd.to_datetime(dates),
    )


EQUAL_WEIGHT_CODE = """
def on_rebalance(ctx, panel):
    ctx.equal_weight(panel.keys(), max_weight=0.5)
"""


def test_portfolio_backtest_executes_next_open_and_reserves_costs_inward():
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    panel = {
        "AAPL": _frame(dates, [100, 110, 110]),
        "MSFT": _frame(dates, [200, 220, 220]),
    }
    result = PortfolioBacktestEngine(
        config=PortfolioBacktestConfig(
            initial_capital=10_000,
            commission_rate=0.001,
            slippage_rate=0.001,
            rebalance_frequency="weekly",
            max_weight=0.5,
        ),
        code=EQUAL_WEIGHT_CODE,
    ).run(panel)

    fills = [order for order in result["orders"] if order["status"] == "filled"]
    assert len(fills) == 2
    assert {order["execution_date"][:10] for order in fills} == {"2026-01-06"}
    assert all(order["price"] > order["reference_price"] for order in fills)
    assert fills[0]["notional"] == pytest.approx(fills[1]["notional"], rel=1e-6)
    assert result["equityCurve"][1]["cash"] >= 0
    assert result["metrics"]["total_commission"] > 0
    assert result["diagnostics"]["aiDecisions"] == "skipped_in_backtest"


def test_portfolio_strategy_only_sees_data_available_at_signal_time():
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    panel = {
        "AAPL": _frame(dates, [100, 100, 100], closes=[100, 100, 100]),
        "MSFT": _frame(dates, [90, 200, 200], closes=[90, 200, 200]),
    }
    code = """
def on_rebalance(ctx, panel):
    scores = {symbol: frame["close"].iloc[-1] for symbol, frame in panel.items()}
    ctx.long_only_top_n(scores, n=1, max_weight=1.0)
"""
    result = PortfolioBacktestEngine(
        config=PortfolioBacktestConfig(
            initial_capital=10_000,
            commission_rate=0,
            slippage_rate=0,
            rebalance_frequency="weekly",
            max_weight=1.0,
        ),
        code=code,
    ).run(panel)

    fills = [order for order in result["orders"] if order["status"] == "filled"]
    assert len(fills) == 1
    assert fills[0]["symbol"] == "AAPL"
    assert fills[0]["reference_price"] == 100


def test_missing_next_session_price_is_rejected_without_fake_fill():
    panel = {
        "AAPL": _frame(["2026-01-05", "2026-01-06"], [100, 100]),
        "MSFT": _frame(["2026-01-05", "2026-01-07"], [200, 200]),
    }
    result = PortfolioBacktestEngine(
        config=PortfolioBacktestConfig(
            initial_capital=10_000,
            commission_rate=0,
            slippage_rate=0,
            rebalance_frequency="weekly",
            max_weight=0.5,
        ),
        code=EQUAL_WEIGHT_CODE,
    ).run(panel)

    rejected = [order for order in result["orders"] if order["status"] == "rejected"]
    fills = [order for order in result["orders"] if order["status"] == "filled"]
    assert any(order["symbol"] == "MSFT" and order["reason"] == "portfolio.missingExecutionPrice" for order in rejected)
    assert [order["symbol"] for order in fills] == ["AAPL"]


def test_final_session_rebalance_is_diagnostic_not_same_bar_fill():
    dates = ["2026-01-05", "2026-01-06"]
    panel = {"AAPL": _frame(dates, [100, 100])}
    result = PortfolioBacktestEngine(
        config=PortfolioBacktestConfig(
            initial_capital=10_000,
            commission_rate=0,
            slippage_rate=0,
            rebalance_frequency="daily",
            max_weight=1.0,
        ),
        code="""
def on_rebalance(ctx, panel):
    ctx.set_target_weights({"AAPL": 1.0})
""",
    ).run(panel)

    assert len([order for order in result["orders"] if order["status"] == "filled"]) == 1
    assert result["diagnostics"]["warnings"][-1]["code"] == "portfolio.noNextSessionForRebalance"
