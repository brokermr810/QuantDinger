"""Tests for @strategy annotations and code-owned risk config."""

from app.services.indicator_params import StrategyConfigParser
from app.services.strategy_config import apply_code_strategy_config_from_script_code


USER_SAMPLE_CODE = """
# @strategy entryPct 1
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.0025
# @strategy trailingActivationPct 0.0037
# @strategy tradeDirection both
# @strategy stopLossPct 0.15
# @strategy takeProfitPct 0.25
"""

CODE_OWNED_EXIT_CODE = """
# signal_form: four_way
# exit_owner: indicator
# flip_mode: R1
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.0003
# @strategy trailingActivationPct 0.0009
"""


def test_normalize_entry_ratio():
    assert StrategyConfigParser.normalize_entry_ratio(1) == 1.0
    assert StrategyConfigParser.normalize_entry_ratio(0.5) == 0.5
    assert StrategyConfigParser.normalize_entry_ratio(25) == 0.25


def test_to_trading_config_risk_flat_user_sample():
    flat = StrategyConfigParser.to_trading_config_risk_flat(USER_SAMPLE_CODE)
    assert flat["entry_pct"] == 1.0
    assert flat["stop_loss_pct"] == 0.15
    assert flat["take_profit_pct"] == 0.25
    assert flat["trailing_stop_pct"] == 0.0025
    assert flat["trailing_activation_pct"] == 0.0037
    assert flat["trailing_enabled"] is True
    assert "trade_direction" not in flat


def test_code_strategy_config_is_attached_without_flat_risk_fields():
    trading_config = {
        "trade_direction": "short",
        "stop_loss_pct": 1.0,
    }
    source_config = {
        "script_code": USER_SAMPLE_CODE,
    }

    merged = apply_code_strategy_config_from_script_code(trading_config, source_config)

    assert merged["trade_direction"] == "short"
    assert merged["stop_loss_pct"] == 1.0
    assert "take_profit_pct" not in merged
    assert merged["_strategy_cfg_from_code"]["risk"]["takeProfitPct"] == 0.25


def test_to_trading_config_risk_flat_sub_one_percent():
    code = "# @strategy stopLossPct 0.001\n# @strategy entryPct 1\n"
    flat = StrategyConfigParser.to_trading_config_risk_flat(code)
    assert flat["stop_loss_pct"] == 0.001
    assert flat["entry_pct"] == 1.0


def test_build_nested_cfg_from_code_user_sample():
    cfg = StrategyConfigParser.build_nested_cfg_from_code(USER_SAMPLE_CODE)
    assert cfg["position"]["entryPct"] == 1.0
    assert cfg["risk"]["stopLossPct"] == 0.15
    assert cfg["risk"]["takeProfitPct"] == 0.25
    assert cfg["risk"]["trailing"]["pct"] == 0.0025
    assert cfg["risk"]["trailing"]["activationPct"] == 0.0037
    assert cfg["risk"]["trailing"]["enabled"] is True
    assert "tradeDirection" not in cfg


def test_exit_owner_header_is_parsed_into_flat_and_nested_config():
    flat = StrategyConfigParser.to_trading_config_risk_flat(CODE_OWNED_EXIT_CODE)
    assert flat["exit_owner"] == "indicator"
    assert flat["trailing_enabled"] is True

    cfg = StrategyConfigParser.build_nested_cfg_from_code(CODE_OWNED_EXIT_CODE)
    assert cfg["exitOwner"] == "indicator"
    assert cfg["risk"]["trailing"]["enabled"] is True


def test_contract_headers_can_share_one_comment_line():
    code = "# signal_form: four_way    exit_owner: indicator    flip_mode: R1\n"
    headers = StrategyConfigParser.parse_contract_headers(code)
    assert headers["signal_form"] == "four_way"
    assert headers["exit_owner"] == "indicator"
    assert headers["flip_mode"] == "R1"


def test_contract_headers_accept_three_minute_timeframe():
    headers = StrategyConfigParser.parse_contract_headers("# timeframe: 3m\n")
    assert headers["timeframe"] == "3m"
