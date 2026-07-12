from typing import Any, Dict, Optional


def apply_default_strict_mode(trading_config: Dict[str, Any]) -> Dict[str, Any]:
    """Default new strategies to strict, backtest-aligned live execution."""
    config = dict(trading_config or {})
    if "strict_mode" not in config and "strictMode" not in config:
        config["strict_mode"] = True
    return config


def strip_legacy_risk_pct_basis(trading_config: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the legacy risk-basis toggle from incoming payloads."""
    config = dict(trading_config or {})
    config.pop("risk_pct_basis", None)
    config.pop("riskPctBasis", None)
    return config


def apply_code_strategy_config_from_script_code(
    trading_config: Dict[str, Any],
    source_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Attach the code-owned strategy contract to ``trading_config``.

    Runtime forms must not persist independent risk controls. Backtest and live
    execution both consume this parsed code contract instead.
    """
    config = source_config if isinstance(source_config, dict) else {}
    code = config.get("script_code") or config.get("indicator_code") or ""
    if not str(code).strip():
        return dict(trading_config or {})

    from app.services.indicator_params import StrategyConfigParser

    code_cfg = StrategyConfigParser.build_nested_cfg_from_code(str(code))
    trading = dict(trading_config or {})
    if code_cfg:
        trading["_strategy_cfg_from_code"] = code_cfg
        if code_cfg.get("exitOwner"):
            trading["exit_owner"] = code_cfg.get("exitOwner")
    return trading


def apply_code_strategy_config_from_indicator_code(
    trading_config: Dict[str, Any],
    source_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compatibility wrapper for older callers."""
    return apply_code_strategy_config_from_script_code(trading_config, source_config)
