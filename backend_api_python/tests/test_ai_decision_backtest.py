import pandas as pd

from app.services.ai_decision import BacktestAIDecisionClient, LiveAIDecisionClient, _decision_from_payload
from app.services.portfolio_backtest import PortfolioBacktestConfig, PortfolioBacktestEngine


def test_backtest_ai_client_is_explicit_bypass_and_counts_calls():
    runtime = {}
    client = BacktestAIDecisionClient(runtime)
    result = client.evaluate(
        "review",
        profile="model-a",
        symbol="AAPL",
        inputs={"close": 100},
    )

    assert result.skipped is True
    assert result.available is False
    assert result.action == "bypass"
    assert result.allows(default_when_skipped=True) is True
    assert runtime["ai_decision_calls"] == 1


def test_portfolio_backtest_skips_ai_and_runs_base_signal():
    dates = pd.to_datetime(["2026-01-05", "2026-01-06"])
    frame = pd.DataFrame(
        {
            "open": [100, 100],
            "high": [100, 100],
            "low": [100, 100],
            "close": [100, 100],
            "volume": [1000, 1000],
        },
        index=dates,
    )
    code = """
def on_rebalance(ctx, panel):
    opinion = ctx.ask_ai("review", profile="model-a", symbol="AAPL", inputs={"close": 100})
    if opinion.allows(default_when_skipped=True):
        ctx.set_target_weights({"AAPL": 1.0})
"""
    result = PortfolioBacktestEngine(
        config=PortfolioBacktestConfig(
            initial_capital=10000,
            commission_rate=0,
            slippage_rate=0,
            rebalance_frequency="weekly",
            max_weight=1.0,
        ),
        code=code,
    ).run({"AAPL": frame})

    assert result["diagnostics"]["aiDecisions"] == "skipped_in_backtest"
    assert result["diagnostics"]["aiDecisionCalls"] == 1
    assert len([order for order in result["orders"] if order["status"] == "filled"]) == 1


class _Store:
    def __init__(self):
        self.rows = {}

    def get(self, *, user_id, strategy_id, decision_key):
        row = self.rows.get(decision_key)
        if row is None:
            return None
        return _decision_from_payload(
            row["output"],
            available=row["status"] == "success",
            error_code=row["error_code"],
            metadata={"cached": True},
        )

    def save(self, **kwargs):
        self.rows[kwargs["decision_key"]] = kwargs


def test_live_ai_decision_uses_selected_profile_scrubs_secrets_and_caches():
    store = _Store()
    calls = []
    billing = []

    def llm(**kwargs):
        calls.append(kwargs)
        return {
            "action": "buy",
            "score": 82,
            "confidence": 0.9,
            "horizon": "5d",
            "risk_level": "medium",
            "reason_codes": ["trend_confirmed"],
            "summary": "ok",
        }

    def charge(key):
        billing.append(key)
        return ""

    client = LiveAIDecisionClient(
        user_id=7,
        strategy_id=9,
        strategy_run_id=11,
        model_config={
            "profiles": {
                "stock-review": {
                    "model": "openai/test-model",
                    "temperature": 0.1,
                    "prompt_version": "3",
                }
            }
        },
        runtime={"current_time": "2026-01-05T16:00:00"},
        store=store,
        llm_callable=llm,
        billing_callable=charge,
    )
    first = client.evaluate(
        "review the stock",
        profile="stock-review",
        symbol="AAPL",
        inputs={"close": 100, "api_key": "must-not-leak"},
    )
    second = client.evaluate(
        "review the stock",
        profile="stock-review",
        symbol="AAPL",
        inputs={"close": 100, "api_key": "must-not-leak"},
    )

    assert first.available is True
    assert first.action == "buy"
    assert first.score == 82
    assert second.metadata["cached"] is True
    assert len(calls) == 1
    assert len(billing) == 1
    assert "must-not-leak" not in calls[0]["messages"][1]["content"]
    assert "[REDACTED]" in calls[0]["messages"][1]["content"]


def test_live_ai_decision_enforces_external_call_budget_per_run():
    calls = []
    runtime = {"current_time": "2026-01-05T16:00:00"}

    def llm(**kwargs):
        calls.append(kwargs)
        return {"action": "hold", "score": 0, "confidence": 0.5}

    client = LiveAIDecisionClient(
        user_id=7,
        strategy_id=9,
        strategy_run_id=11,
        model_config={"model": "openai/test-model", "prompt": "review", "max_calls_per_run": 1},
        runtime=runtime,
        store=_Store(),
        llm_callable=llm,
        billing_callable=lambda _: "",
    )
    first = client.evaluate(symbol="AAPL", inputs={"close": 100})
    second = client.evaluate(symbol="MSFT", inputs={"close": 200})

    assert first.available is True
    assert second.available is False
    assert second.error_code == "ai.callBudgetExceeded"
    assert len(calls) == 1
    assert runtime["ai_decision_external_calls"] == 1
