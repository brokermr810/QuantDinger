import pandas as pd
import pytest

from app.services.portfolio_strategy_runtime import (
    PortfolioConstraints,
    PortfolioContext,
    PortfolioStrategyError,
    compile_portfolio_strategy_handlers,
    rebalance_dates,
    validate_portfolio_strategy_code,
    validate_target_weights,
)


def test_long_only_target_weight_plan_preserves_cash():
    plan = validate_target_weights(
        {"AAPL": 0.4, "MSFT": 0.4},
        universe={"AAPL", "MSFT"},
        constraints=PortfolioConstraints(max_weight=0.5, gross_limit=1.0, net_limit=1.0),
    )

    assert plan.weights == {"AAPL": 0.4, "MSFT": 0.4}
    assert plan.gross_exposure == 0.8
    assert plan.net_exposure == 0.8
    assert plan.cash_weight == 0.2


@pytest.mark.parametrize(
    ("weights", "code"),
    [
        ({"TSLA": 0.2}, "portfolio.symbolOutsideUniverse"),
        ({"AAPL": -0.2}, "portfolio.negativeWeightInLongOnly"),
        ({"AAPL": 0.6}, "portfolio.maxWeightExceeded"),
        ({"AAPL": 0.5, "MSFT": 0.5, "NVDA": 0.5}, "portfolio.grossLimitExceeded"),
    ],
)
def test_target_weight_validation_rejects_unsafe_portfolios(weights, code):
    with pytest.raises(PortfolioStrategyError) as caught:
        validate_target_weights(
            weights,
            universe={"AAPL", "MSFT", "NVDA"},
            constraints=PortfolioConstraints(max_weight=0.5, gross_limit=1.0, net_limit=1.0),
        )
    assert caught.value.code == code


def test_context_top_n_is_deterministic_and_cannot_relax_risk_limits():
    ctx = PortfolioContext(
        universe={"AAPL", "MSFT", "NVDA"},
        constraints=PortfolioConstraints(max_weight=0.5, gross_limit=1.0, net_limit=1.0),
    )
    assert ctx.top_n({"MSFT": 1, "AAPL": 1, "NVDA": 2}, 2) == ["NVDA", "AAPL"]

    with pytest.raises(PortfolioStrategyError) as caught:
        ctx.set_target_weights({"AAPL": 0.5}, gross_limit=1.5)
    assert caught.value.code == "portfolio.grossLimitCannotRelax"


def test_weekly_and_monthly_rebalance_use_first_available_session():
    sessions = pd.to_datetime([
        "2026-01-02",
        "2026-01-05",
        "2026-01-06",
        "2026-02-02",
        "2026-02-03",
    ])

    assert rebalance_dates(sessions, "weekly") == [
        pd.Timestamp("2026-01-02"),
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-02-02"),
    ]
    assert rebalance_dates(sessions, "monthly") == [
        pd.Timestamp("2026-01-02"),
        pd.Timestamp("2026-02-02"),
    ]


def test_portfolio_contract_rejects_on_bar_and_direct_orders():
    with pytest.raises(PortfolioStrategyError) as on_bar:
        validate_portfolio_strategy_code("def on_bar(ctx, bar):\n    pass\n")
    assert on_bar.value.code == "portfolio.onRebalanceRequired"

    code = """
def on_rebalance(ctx, panel):
    ctx.open_long()
"""
    with pytest.raises(PortfolioStrategyError) as direct_order:
        validate_portfolio_strategy_code(code)
    assert direct_order.value.code == "portfolio.directOrderNotAllowed"


def test_compiled_portfolio_strategy_emits_top_n_target_weights():
    code = """
def on_init(ctx):
    ctx.top_count = int(ctx.param("top_n", 2))

def on_rebalance(ctx, panel):
    scores = {symbol: frame["close"].iloc[-1] for symbol, frame in panel.items()}
    ctx.long_only_top_n(scores, n=ctx.top_count, max_weight=0.5)
"""
    on_init, on_rebalance = compile_portfolio_strategy_handlers(code)
    ctx = PortfolioContext(
        universe={"AAPL", "MSFT", "NVDA"},
        params={"top_n": 2},
        constraints=PortfolioConstraints(max_weight=0.5),
    )
    panel = {
        "AAPL": pd.DataFrame({"close": [100.0]}),
        "MSFT": pd.DataFrame({"close": [200.0]}),
        "NVDA": pd.DataFrame({"close": [150.0]}),
    }

    on_init(ctx)
    ctx.reset_rebalance(pd.Timestamp("2026-01-05"))
    on_rebalance(ctx, panel)

    assert ctx.consume_plan().weights == {"MSFT": 0.5, "NVDA": 0.5}
