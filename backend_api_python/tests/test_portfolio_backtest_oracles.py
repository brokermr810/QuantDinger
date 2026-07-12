"""Deterministic portfolio backtest oracles with independently calculated results."""

import pandas as pd
import pytest

from app.services.portfolio_backtest import PortfolioBacktestConfig, PortfolioBacktestEngine
from app.services.portfolio_strategy_examples import list_portfolio_strategy_examples


def _frame(dates, values, closes=None):
    closes = values if closes is None else closes
    return pd.DataFrame(
        {
            "open": values,
            "high": [max(open_price, close_price) for open_price, close_price in zip(values, closes)],
            "low": [min(open_price, close_price) for open_price, close_price in zip(values, closes)],
            "close": closes,
            "volume": [1_000_000] * len(dates),
        },
        index=pd.to_datetime(dates),
    )


def _example(key):
    return next(item for item in list_portfolio_strategy_examples() if item["template_key"] == key)


def _run(panel, code, **config):
    params = config.pop("params", {"top_n": 2, "lookback": 2})
    return PortfolioBacktestEngine(
        config=PortfolioBacktestConfig(
            initial_capital=config.pop("initial_capital", 10_000),
            commission_rate=config.pop("commission_rate", 0),
            slippage_rate=config.pop("slippage_rate", 0),
            rebalance_frequency=config.pop("rebalance_frequency", "weekly"),
            max_weight=config.pop("max_weight", 1),
            trading_start=config.pop("trading_start", "2026-01-05"),
            **config,
        ),
        code=code,
        params=params,
    ).run(panel)


def test_momentum_rotation_matches_selection_orders_positions_and_equity_oracle():
    dates = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-12", "2026-01-13"]
    panel = {
        "AAA": _frame(dates, [90, 95, 100, 100, 120, 110, 110], [90, 95, 100, 120, 120, 110, 110]),
        "BBB": _frame(dates, [190, 195, 200, 200, 190, 200, 200], [190, 195, 200, 190, 190, 200, 200]),
        "CCC": _frame(dates, [100, 95, 90, 90, 80, 100, 100], [100, 95, 90, 80, 80, 100, 100]),
    }

    result = _run(
        panel,
        _example("portfolio_momentum_top_n")["code"],
        max_weight=0.5,
    )

    assert result["rebalances"][0]["target_weights"] == {"AAA": 0.5, "BBB": 0.5}
    assert result["rebalances"][1]["target_weights"] == {"BBB": 0.5, "CCC": 0.5}
    assert [
        (order["side"], order["symbol"], order["quantity"], order["price"])
        for order in result["orders"]
    ] == [
        ("buy", "AAA", 50.0, 100.0),
        ("buy", "BBB", 25.0, 200.0),
        ("sell", "AAA", 50.0, 110.0),
        ("buy", "BBB", 1.25, 200.0),
        ("buy", "CCC", 52.5, 100.0),
    ]
    final_positions = result["holdings"][-1]["positions"]
    assert [(item["symbol"], item["quantity"], item["weight"]) for item in final_positions] == [
        ("BBB", 26.25, 0.5),
        ("CCC", 52.5, 0.5),
    ]
    assert result["equityCurve"][-1] == {
        "time": "2026-01-13T00:00:00",
        "equity": 10_500.0,
        "value": 10_500.0,
        "cash": 0.0,
    }
    assert result["metrics"]["total_return"] == pytest.approx(0.05)


def test_low_volatility_and_mean_reversion_examples_select_expected_symbols():
    dates = ["2025-12-31", "2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]
    panel = {
        "AAA": _frame(dates, [100, 100, 100, 100, 100]),
        "BBB": _frame(dates, [100, 110, 90, 120, 120]),
        "CCC": _frame(dates, [100, 98, 96, 94, 94]),
    }

    low_vol = _run(
        panel,
        _example("portfolio_low_volatility_top_n")["code"],
        max_weight=1,
        params={"top_n": 1, "lookback": 2},
    )
    mean_reversion = _run(
        panel,
        _example("portfolio_mean_reversion_top_n")["code"],
        max_weight=1,
        params={"top_n": 1, "lookback": 2},
    )

    assert low_vol["rebalances"][0]["target_weights"] == {"AAA": 1.0}
    assert [(item["symbol"], item["side"]) for item in low_vol["orders"]] == [("AAA", "buy")]
    assert mean_reversion["rebalances"][0]["target_weights"] == {"CCC": 1.0}
    assert [(item["symbol"], item["side"]) for item in mean_reversion["orders"]] == [("CCC", "buy")]


def test_full_investment_cost_reserve_matches_independent_cash_oracle():
    dates = ["2026-01-05", "2026-01-06"]
    code = """
def on_rebalance(ctx, panel):
    ctx.set_target_weights({"AAA": 1.0})
"""
    result = _run(
        {"AAA": _frame(dates, [100, 110])},
        code,
        commission_rate=0.01,
        slippage_rate=0.01,
        max_weight=1,
    )

    order = result["orders"][0]
    assert order["quantity"] == 89.11782267
    assert order["reference_price"] == 110.0
    assert order["price"] == 111.1
    assert order["notional"] == pytest.approx(9_900.990098637, abs=1e-8)
    assert order["commission"] == pytest.approx(99.00990098637, abs=1e-8)
    assert result["equityCurve"][-1]["cash"] >= 0


def test_small_cap_example_selects_lowest_point_in_time_market_cap():
    dates = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]
    panel = {
        "LARGE": _frame(dates, [100, 100, 100, 100]),
        "MID": _frame(dates, [100, 100, 100, 100]),
        "SMALL": _frame(dates, [100, 100, 100, 100]),
    }
    panel["LARGE"]["market_cap"] = [1_000, 1_000, 1_000, 1_000]
    panel["MID"]["market_cap"] = [500, 500, 500, 500]
    panel["SMALL"]["market_cap"] = [100, 100, 100, 100]

    result = _run(
        panel,
        _example("portfolio_small_cap_top_n")["code"],
        max_weight=1,
        params={"top_n": 1},
    )

    assert result["rebalances"][0]["target_weights"] == {"SMALL": 1.0}
    assert [(item["symbol"], item["side"]) for item in result["orders"]] == [("SMALL", "buy")]
