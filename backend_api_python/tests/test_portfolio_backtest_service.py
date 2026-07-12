import pandas as pd
import pytest

from app.services.portfolio_backtest_service import PortfolioBacktestRequestError, PortfolioBacktestService


class _UniverseService:
    def get_universe(self, user_id, universe_id):
        return {
            "id": universe_id,
            "code": "manual-test",
            "market": "USStock",
            "universe_type": "manual",
        }

    def candidate_members(self, user_id, universe_id, *, start, end):
        return [
            {"market": "USStock", "symbol": "AAPL", "exchange_id": "", "market_type": "spot", "instrument_id": ""},
            {"market": "USStock", "symbol": "MSFT", "exchange_id": "", "market_type": "spot", "instrument_id": ""},
        ]

    def resolve_members(self, user_id, universe_id, *, as_of):
        return self.candidate_members(user_id, universe_id, start=as_of, end=as_of)

    def create_snapshot(self, user_id, universe_id, *, as_of):
        return {
            "snapshot_id": f"snapshot-{as_of}",
            "as_of": str(as_of),
            "content_hash": "a" * 64,
            "member_count": 2,
        }


class _UnifiedService:
    def __init__(self):
        self.persisted = None

    def persist_run(self, **kwargs):
        self.persisted = kwargs
        return 42


def _fetcher(market, symbol, timeframe, start, end, **kwargs):
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    base = 100 if symbol == "AAPL" else 200
    return pd.DataFrame(
        {
            "open": [base, base, base],
            "high": [base, base, base],
            "low": [base, base, base],
            "close": [base, base, base],
            "volume": [1000, 1000, 1000],
        },
        index=dates,
    )


def test_portfolio_backtest_service_resolves_snapshots_and_persists_run():
    unified = _UnifiedService()
    service = PortfolioBacktestService(
        universe_service=_UniverseService(),
        unified_service=unified,
        frame_fetcher=_fetcher,
    )
    run_id, result = service.run(
        user_id=7,
        payload={
            "assetType": "portfolio_strategy",
            "universeId": 9,
            "startDate": "2026-01-05",
            "endDate": "2026-01-07",
            "rebalanceFrequency": "weekly",
            "initialCapital": 10000,
            "commission": 0.001,
            "slippage": 0,
            "maxWeight": 0.5,
            "strategyName": "Equal Weight",
            "code": """
def on_rebalance(ctx, panel):
    ctx.equal_weight(panel.keys(), max_weight=0.5)
""",
        },
    )

    assert run_id == 42
    assert result["runType"] == "portfolio_strategy"
    assert result["diagnostics"]["symbolsRequested"] == 2
    assert result["diagnostics"]["universeSnapshots"]
    assert unified.persisted["run_type"] == "portfolio_strategy"
    assert unified.persisted["asset_type"] == "portfolio_strategy"
    assert unified.persisted["symbol"] == "universe:9"


def test_portfolio_backtest_rejects_mixed_market_calendar_until_synchronized_execution_exists():
    universe = _UniverseService()
    universe.candidate_members = lambda *args, **kwargs: [
        {"market": "USStock", "symbol": "AAPL"},
        {"market": "Crypto", "symbol": "BTC/USDT"},
    ]
    service = PortfolioBacktestService(
        universe_service=universe,
        unified_service=_UnifiedService(),
        frame_fetcher=_fetcher,
    )

    with pytest.raises(PortfolioBacktestRequestError) as exc_info:
        service.run(
            user_id=7,
            payload={
                "universeId": 9,
                "startDate": "2026-01-05",
                "endDate": "2026-01-07",
                "code": "def on_rebalance(ctx, panel):\n    ctx.set_target_weights({})",
            },
        )

    assert exc_info.value.code == "portfolio.mixedMarketUniverseNotSupported"
