"""Shared lazy service accessors for strategy route modules."""

from app.services.strategy import StrategyService


_strategy_service: StrategyService | None = None


def get_strategy_service() -> StrategyService:
    global _strategy_service
    if _strategy_service is None:
        _strategy_service = StrategyService()
    return _strategy_service
