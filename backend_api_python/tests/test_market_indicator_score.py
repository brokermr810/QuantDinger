"""Regression tests for marketplace backtest KPI aggregation.

Marketplace script assets summarise successful backtest runs into a
representative score value. Internally this calls StrategyScoringService and
keeps the best scoring run so card metrics and equity curves stay aligned.
"""

import json

from app.services.community_kpis import summarise_backtest_runs
from app.services.experiment.scoring import StrategyScoringService


def _make_run(
    run_id: int,
    *,
    total_return: float,
    sharpe: float,
    drawdown: float,
    win_rate: float,
    profit_factor: float,
    total_trades: int,
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
) -> dict:
    """Build a fake qd_backtest_runs row with the payload the scorer consumes."""
    payload = {
        "totalReturn": total_return,
        "annualReturn": total_return,
        "sharpeRatio": sharpe,
        "maxDrawdown": drawdown,
        "winRate": win_rate,
        "profitFactor": profit_factor,
        "totalTrades": total_trades,
        "equityCurve": [
            {"value": 100.0},
            {"value": 100.0 + total_return / 2},
            {"value": 100.0 + total_return},
        ],
    }
    return {
        "id": run_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "result_json": json.dumps(payload),
    }


def test_composite_score_is_nonzero_for_good_backtests():
    runs = [
        _make_run(1, total_return=40, sharpe=1.8, drawdown=-12, win_rate=58, profit_factor=2.1, total_trades=40),
        _make_run(2, total_return=35, sharpe=1.6, drawdown=-15, win_rate=55, profit_factor=1.9, total_trades=35),
        _make_run(3, total_return=45, sharpe=2.0, drawdown=-10, win_rate=60, profit_factor=2.3, total_trades=50),
    ]

    summary = summarise_backtest_runs(runs)

    assert summary["score"] > 0
    assert summary["sample_size"] == 3
    assert summary["best_run_id"] in {1, 2, 3}
    assert "BTC/USDT" in summary["symbols"]
    assert "1h" in summary["timeframes"]


def test_composite_score_matches_best_underlying_scorer():
    runs = [
        _make_run(11, total_return=20, sharpe=1.2, drawdown=-15, win_rate=52, profit_factor=1.5, total_trades=30),
        _make_run(12, total_return=10, sharpe=0.8, drawdown=-22, win_rate=48, profit_factor=1.2, total_trades=20),
        _make_run(13, total_return=50, sharpe=2.2, drawdown=-8, win_rate=62, profit_factor=2.5, total_trades=60),
    ]
    scorer = StrategyScoringService()
    expected_best = max(float(scorer.score_result(json.loads(r["result_json"]))["overallScore"]) for r in runs)

    summary = summarise_backtest_runs(runs)

    assert abs(summary["score"] - round(expected_best, 2)) < 0.05


def test_summary_handles_empty_runs():
    summary = summarise_backtest_runs([])

    assert summary["score"] == 0.0
    assert summary["sample_size"] == 0
    assert summary["best_run_id"] is None


def test_summary_skips_invalid_result_json():
    runs = [
        {"id": 1, "symbol": "ETH/USDT", "timeframe": "4h", "result_json": "this is not json"},
        {"id": 2, "symbol": "ETH/USDT", "timeframe": "4h", "result_json": None},
    ]

    summary = summarise_backtest_runs(runs)

    assert summary["score"] == 0.0
    assert summary["sample_size"] == 0
