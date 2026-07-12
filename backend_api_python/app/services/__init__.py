"""Lazy application service exports.

Importing a focused service must not eagerly load every market-data, AI, and
experiment dependency. Public package exports remain backward compatible and
are resolved only when requested.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "KlineService": ("app.services.kline", "KlineService"),
    "UnifiedBacktestService": ("app.services.unified_backtest", "UnifiedBacktestService"),
    "StrategyCompiler": ("app.services.strategy_compiler", "StrategyCompiler"),
    "FastAnalysisService": ("app.services.fast_analysis", "FastAnalysisService"),
    "ExperimentRunnerService": ("app.services.experiment", "ExperimentRunnerService"),
    "MarketRegimeService": ("app.services.experiment", "MarketRegimeService"),
    "StrategyEvolutionService": ("app.services.experiment", "StrategyEvolutionService"),
    "StrategyScoringService": ("app.services.experiment", "StrategyScoringService"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
