from __future__ import annotations

from app.services.unified_backtest import UnifiedBacktestService
from app.services.strategy_snapshot import StrategySnapshotResolver
from app.services.strategy_contract import resolve_script_strategy_contract


CODE_OWNED_RISK = """
# @strategy entryPct 1
# @strategy stopLossPct 0.04
# @strategy takeProfitPct 0.08
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.015
# @strategy trailingActivationPct 0.03
# @strategy maxHoldingBars 12
# exit_owner: engine
"""


def test_backtest_snapshot_uses_code_owned_risk_contract():
    resolver = StrategySnapshotResolver(user_id=1)
    cfg = resolver._build_strategy_config_from_contract(
        {
            "stop_loss_pct": 99,
            "take_profit_pct": 99,
            "trailing_enabled": False,
            "max_holding_bars": 999,
            "entry_pct": 5,
        },
        resolve_script_strategy_contract(CODE_OWNED_RISK)["codeConfig"],
    )

    assert cfg["risk"]["stopLossPct"] == 0.04
    assert cfg["risk"]["takeProfitPct"] == 0.08
    assert cfg["risk"]["trailing"]["enabled"] is True
    assert cfg["risk"]["trailing"]["pct"] == 0.015
    assert cfg["risk"]["trailing"]["activationPct"] == 0.03
    assert cfg["risk"]["maxHoldingBars"] == 12
    assert cfg["position"]["entryPct"] == 1.0
    assert cfg["exitOwner"] == "engine"


def test_backtest_snapshot_ignores_runtime_risk_without_code_contract():
    resolver = StrategySnapshotResolver(user_id=1)
    cfg = resolver._build_strategy_config_from_contract(
        {
            "stop_loss_pct": 4,
            "take_profit_pct": 8,
            "trailing_enabled": True,
            "trailing_stop_pct": 1.5,
            "trailing_activation_pct": 3,
            "max_holding_bars": 12,
            "entry_pct": 50,
        },
        {},
    )

    assert "risk" not in cfg
    assert cfg["position"]["entryPct"] == 1.0
    assert cfg["execution"]["signalTiming"] == "next_bar_open"


def test_strategy_code_timeframe_overrides_saved_config():
    strategy = {
        "id": 300,
        "strategy_name": "Code timeframe",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": "# timeframe: 1H\n\ndef on_bar(ctx, bar):\n    pass\n",
        "market_category": "Crypto",
        "trading_config": {
            "symbol": "BTC/USDT",
            "market_type": "swap",
            "timeframe": "1D",
            "trade_direction": "both",
        },
    }

    snapshot = StrategySnapshotResolver(user_id=1).resolve(strategy, {"timeframe": "5m"})

    assert snapshot["timeframe"] == "1H"


def test_strategy_code_headers_override_execution_timing():
    strategy = {
        "id": 301,
        "strategy_name": "Code timing",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": "# kline_timeframe: 4H\n# signal_timing: same_bar_close\n\ndef on_bar(ctx, bar):\n    pass\n",
        "market_category": "Crypto",
        "trading_config": {
            "symbol": "BTC/USDT",
            "market_type": "swap",
            "timeframe": "1D",
            "trade_direction": "both",
            "strict_mode": True,
        },
    }

    snapshot = StrategySnapshotResolver(user_id=1).resolve(strategy, {})

    assert snapshot["timeframe"] == "4H"
    assert snapshot["strategy_config"]["execution"]["signalTiming"] == "same_bar_close"


def test_script_runtime_params_use_code_native_values():
    svc = UnifiedBacktestService()

    params = svc._sanitize_strategy_params(
        {
            "order_pct": 0.06,
            "spacing_pct": 0.008,
            "take_profit_pct": 0.006,
            "hard_stop_pct": 22,
            "min_atr_pct": 0.006,
            "atr_mult": 2.2,
            "add_atr": 0.5,
            "fast_ema": 21,
            "atr_period": 14,
            "max_orders": 8,
        }
    )

    assert params["order_pct"] == 0.06
    assert params["spacing_pct"] == 0.008
    assert params["take_profit_pct"] == 0.006
    assert params["hard_stop_pct"] == 22
    assert params["min_atr_pct"] == 0.006
    assert params["atr_mult"] == 2.2
    assert params["add_atr"] == 0.5
    assert params["fast_ema"] == 21
    assert params["atr_period"] == 14
    assert params["max_orders"] == 8


def test_script_runtime_param_schema_does_not_convert_values():
    svc = UnifiedBacktestService()

    param_schema = {
        "params": [
            {"name": "total_budget_pct", "type": "percent", "default": 1, "min": 0, "max": 1},
            {"name": "first_order_pct", "type": "percent", "default": 0.05, "min": 0.001, "max": 1},
            {"name": "spacing_pct", "type": "percent", "default": 0.008, "min": 0.0005, "max": 0.5},
            {"name": "take_profit_pct", "type": "percent", "default": 0.006, "min": 0.0005, "max": 0.5},
            {"name": "hard_stop_pct", "type": "percent", "default": 0.22, "min": 0.01, "max": 0.9},
        ]
    }

    params = svc._sanitize_strategy_params(
        {
            "total_budget_pct": 1,
            "first_order_pct": 0.05,
            "spacing_pct": 0.008,
            "take_profit_pct": 0.006,
            "hard_stop_pct": 0.22,
        },
        param_schema,
    )

    assert params["total_budget_pct"] == 1
    assert params["first_order_pct"] == 0.05
    assert params["spacing_pct"] == 0.008
    assert params["take_profit_pct"] == 0.006
    assert params["hard_stop_pct"] == 0.22

    raw_values_are_preserved = svc._sanitize_strategy_params(
        {
            "first_order_pct": 5,
            "spacing_pct": 0.8,
            "take_profit_pct": 0.6,
            "hard_stop_pct": 22,
        },
        param_schema,
    )
    assert raw_values_are_preserved["first_order_pct"] == 5
    assert raw_values_are_preserved["spacing_pct"] == 0.8
    assert raw_values_are_preserved["take_profit_pct"] == 0.6
    assert raw_values_are_preserved["hard_stop_pct"] == 22
