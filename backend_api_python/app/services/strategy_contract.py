"""Canonical parsing for ScriptStrategy code and runtime parameters."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.indicator_params import StrategyConfigParser
from app.services.strategy_warmup import resolve_startup_candle_count


SCRIPT_PARAMETER_KEYS = (
    "script_template_params",
    "script_params",
    "params",
    "paramOverrides",
    "bot_params",
    "indicator_params",
)


def collect_script_parameters(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge all supported parameter containers with later keys taking priority."""
    source = config if isinstance(config, dict) else {}
    merged: Dict[str, Any] = {}
    for key in SCRIPT_PARAMETER_KEYS:
        values = source.get(key)
        if isinstance(values, dict):
            merged.update(values)
    return merged


def resolve_script_strategy_contract(
    code: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse one canonical contract shared by snapshots, backtests, and live runs."""
    raw = str(code or "")
    params = collect_script_parameters(config)
    return {
        "headers": StrategyConfigParser.parse_contract_headers(raw),
        "codeConfig": StrategyConfigParser.build_nested_cfg_from_code(raw),
        "parameters": params,
        "startupCandleCount": resolve_startup_candle_count(raw, params),
    }
