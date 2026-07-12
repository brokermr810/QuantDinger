"""Normalize experiment override maps for the unified strategy editor.

Structured tuning stores sweeps as flat dot paths such as
``indicator_params.sma_short`` or ``strategy_config.script_params.fast_period``.
The frontend needs a compact nested map on each candidate so it can preview,
apply, backtest, and persist the selected parameters without guessing which
strategy family produced the candidate.
"""

from __future__ import annotations

from typing import Any, Dict


def enrich_experiment_overrides(overrides: Dict[str, Any] | None) -> Dict[str, Any]:
    """Add normalized parameter nests expected by the unified frontend."""
    if not overrides or not isinstance(overrides, dict):
        return overrides or {}

    out = dict(overrides)
    ind: Dict[str, Any] = dict(out.get("indicatorParams") or {})
    script: Dict[str, Any] = dict(out.get("scriptParams") or {})
    params: Dict[str, Any] = dict(out.get("params") or {})
    risk: Dict[str, Any] = dict(out.get("riskParams") or {})

    for key, value in list(out.items()):
        k = str(key or "")
        if k.startswith("indicator_params."):
            name = k.split(".", 1)[1]
            if name:
                ind[name] = value
                params.setdefault(name, value)
        elif k.startswith("script_params."):
            name = k.split(".", 1)[1]
            if name:
                script[name] = value
                params.setdefault(name, value)
        elif k.startswith("params.") or k.startswith("paramOverrides."):
            name = k.split(".", 1)[1]
            if name:
                params[name] = value
        elif k.startswith("strategy_config.indicator_params.") or k.startswith("strategyConfig.indicator_params."):
            name = k.split(".")[-1]
            if name:
                ind[name] = value
                params.setdefault(name, value)
        elif k.startswith("strategy_config.script_params.") or k.startswith("strategyConfig.script_params."):
            name = k.split(".")[-1]
            if name:
                script[name] = value
                params.setdefault(name, value)
        elif k.startswith("strategy_config.params.") or k.startswith("strategyConfig.params.") or k.startswith("strategy_config.paramOverrides.") or k.startswith("strategyConfig.paramOverrides."):
            name = k.split(".")[-1]
            if name:
                params[name] = value
        elif k.startswith("strategy_config.risk.") or k.startswith("strategyConfig.risk."):
            sub = k.split(".")[-1]
            if sub in ("stopLossPct", "takeProfitPct", "trailingEnabled", "trailingStopPct", "trailingActivationPct"):
                risk[sub] = value
            elif sub == "trailing" and isinstance(value, dict):
                risk.setdefault("trailingStop", value)
        elif k.startswith("strategy_config.position.") or k.startswith("strategyConfig.position."):
            sub = k.split(".")[-1]
            if sub == "entryPct":
                risk["entryPct"] = value

    if ind:
        out["indicatorParams"] = ind
    if script:
        out["scriptParams"] = script
    if params:
        out["params"] = params
    if risk:
        out["riskParams"] = risk
    return out


def enrich_experiment_candidate(candidate: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Enrich overrides on a ranked strategy / bestStrategyOutput candidate."""
    if not candidate or not isinstance(candidate, dict):
        return candidate
    c = dict(candidate)
    if c.get("overrides"):
        c["overrides"] = enrich_experiment_overrides(c.get("overrides"))
    return c
