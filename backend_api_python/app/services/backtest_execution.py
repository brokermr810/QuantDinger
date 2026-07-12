"""Backtest execution semantics aligned with live ``strict_mode``."""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_COMMISSION = 0.0005
DEFAULT_SLIPPAGE = 0.0005


def parse_strict_mode(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if value is None:
        return default
    return bool(value)


def merge_strict_mode_into_strategy_config(
    strategy_config: Optional[Dict[str, Any]],
    strict_mode: bool,
) -> Dict[str, Any]:
    """Map live strict_mode to backtest signalTiming under the single contract."""
    cfg = dict(strategy_config or {})
    exec_cfg = dict(cfg.get("execution") or {})
    exec_cfg["signalTiming"] = "next_bar_open" if strict_mode else "same_bar_close"
    cfg["execution"] = exec_cfg
    cfg["strictMode"] = bool(strict_mode)
    return cfg


def _non_negative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return max(0.0, parsed)
    except (TypeError, ValueError):
        return default


def default_commission_if_missing(commission: Any) -> float:
    if commission in (None, ""):
        return DEFAULT_COMMISSION
    return _non_negative_float(commission, DEFAULT_COMMISSION)


def default_slippage_if_missing(slippage: Any) -> float:
    if slippage in (None, ""):
        return DEFAULT_SLIPPAGE
    return _non_negative_float(slippage, DEFAULT_SLIPPAGE)


def parse_rate(value: Any, *, pct_value: Any = None, default: float = 0.0) -> float:
    """Parse a fee/rate field.

    Public API contract:
    - ``value`` is already a fraction, e.g. 0.0005 means 0.05%.
    - ``pct_value`` is a UI percentage, e.g. 0.05 means 0.05%.
    """
    raw = pct_value if pct_value not in (None, "") else value
    if raw in (None, ""):
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    return parsed / 100.0 if pct_value not in (None, "") else parsed


def precision_info_for_run(
    *,
    strict_mode: bool,
    strategy_timeframe: str,
    mtf_active: bool = False,
    exec_timeframe: Optional[str] = None,
    fallback_reason: Optional[str] = None,
) -> Dict[str, Any]:
    if strict_mode:
        return {
            "enabled": False,
            "mode": "strict",
            "timeframe": strategy_timeframe,
            "precision": "strict_bar",
            "message": "Strict mode: confirmed closed-bar signals are filled at the next bar open.",
        }
    if mtf_active and exec_timeframe:
        return {
            "enabled": True,
            "mode": "aggressive_1m",
            "timeframe": exec_timeframe,
            "strategyTimeframe": strategy_timeframe,
            "precision": "aggressive_1m",
            "message": (
                f"Aggressive mode: {strategy_timeframe} signals are approximated "
                f"with {exec_timeframe} intrabar candles."
            ),
        }
    if fallback_reason:
        return {
            "enabled": False,
            "mode": "aggressive_bar",
            "timeframe": strategy_timeframe,
            "fallback_reason": fallback_reason,
            "precision": "aggressive_bar",
            "message": (
                "Aggressive mode: same-bar close fill on the strategy timeframe; "
                "intrabar candles are unavailable."
            ),
        }
    return {
        "enabled": False,
        "mode": "aggressive_bar",
        "timeframe": strategy_timeframe,
        "precision": "aggressive_bar",
        "message": "Aggressive mode: same-bar close fill on the strategy timeframe.",
    }
