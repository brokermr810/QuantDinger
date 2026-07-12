import pytest

from app.services.portfolio_rebalance import PortfolioRebalancePlanner, RebalancePlanConfig


def test_full_allocation_reserves_commission_and_scales_buys_proportionally():
    plan = PortfolioRebalancePlanner().build(
        portfolio_id="portfolio-1",
        universe_id=7,
        target_weights={"AAPL": 0.5, "MSFT": 0.5},
        current_quantities={},
        prices={"AAPL": 100, "MSFT": 200},
        cash=10_000,
        signal_time="2026-01-05T16:00:00",
        execution_mode="notify_only",
        config=RebalancePlanConfig(commission_rate=0.001, max_weight=0.5),
    )

    assert len(plan["orders"]) == 2
    assert plan["projected_cash"] >= 0
    notionals = [order["estimated_notional"] for order in plan["orders"]]
    assert notionals[0] == pytest.approx(notionals[1], rel=1e-7)
    assert sum(notionals) < 10_000


def test_rebalance_orders_sell_before_buy_and_keep_stable_idempotency_keys():
    kwargs = dict(
        portfolio_id="portfolio-1",
        universe_id=7,
        target_weights={"AAPL": 0.0, "MSFT": 1.0},
        current_quantities={"AAPL": 100},
        prices={"AAPL": 100, "MSFT": 200},
        cash=0,
        signal_time="2026-01-05T16:00:00",
        execution_mode="live",
        config=RebalancePlanConfig(commission_rate=0.001, max_weight=1.0),
    )
    first = PortfolioRebalancePlanner().build(**kwargs)
    second = PortfolioRebalancePlanner().build(**kwargs)

    assert [order["side"] for order in first["orders"]] == ["sell", "buy"]
    assert first["orders"][0]["action"] == "close_long"
    assert first["orders"][1]["action"] == "open_long"
    assert [order["idempotency_key"] for order in first["orders"]] == [
        order["idempotency_key"] for order in second["orders"]
    ]


def test_missing_price_is_diagnostic_and_never_becomes_an_order():
    plan = PortfolioRebalancePlanner().build(
        portfolio_id="portfolio-1",
        universe_id=7,
        target_weights={"AAPL": 0.5, "MSFT": 0.5},
        current_quantities={},
        prices={"AAPL": 100, "MSFT": 0},
        cash=10_000,
        signal_time="2026-01-05T16:00:00",
        execution_mode="notify_only",
        config=RebalancePlanConfig(max_weight=0.5),
    )

    assert [order["symbol"] for order in plan["orders"]] == ["AAPL"]
    assert plan["diagnostics"] == [{"symbol": "MSFT", "code": "portfolio.missingPrice"}]
