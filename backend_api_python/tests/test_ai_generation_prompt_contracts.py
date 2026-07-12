from app.services.ai_generation_contracts import (
    INDICATOR_SYSTEM_CONTRACT,
    INDICATOR_TO_STRATEGY_CONTRACT,
    SCRIPT_STRATEGY_REPAIR_REQUIREMENTS,
    SCRIPT_STRATEGY_SYSTEM_PROMPT,
)
from app.services.strategy_code_quality import analyze_strategy_code_quality


def _hint_codes(code: str) -> set[str]:
    return {
        str(hint.get("code") or "")
        for hint in analyze_strategy_code_quality(code)
        if hint.get("code")
    }


def test_strategy_prompt_distinguishes_direction_capability_from_run_direction():
    assert "A long exit or bearish warning is not a short entry" in SCRIPT_STRATEGY_SYSTEM_PROMPT
    assert "independent long-entry, long-exit, short-entry, and short-exit" in SCRIPT_STRATEGY_SYSTEM_PROMPT
    assert "ctx.available_capital" in SCRIPT_STRATEGY_SYSTEM_PROMPT


def test_indicator_conversion_prompt_preserves_event_parity_and_source_timeframe_boundary():
    assert "edge(A | B)" in INDICATOR_TO_STRATEGY_CONTRACT
    assert "complete previous composite" in INDICATOR_TO_STRATEGY_CONTRACT
    assert "chart timeframe supplied as UI context" in INDICATOR_TO_STRATEGY_CONTRACT
    assert "Remove visual-only parameters" in INDICATOR_TO_STRATEGY_CONTRACT
    assert "ctx.available_capital" in INDICATOR_TO_STRATEGY_CONTRACT
    assert "Preserve composite edge semantics exactly" in SCRIPT_STRATEGY_REPAIR_REQUIREMENTS


def test_indicator_prompt_requires_unambiguous_marker_meaning_without_signal_inflation():
    assert "Long Entry" in INDICATOR_SYSTEM_CONTRACT
    assert "generic `Sell` label" in INDICATOR_SYSTEM_CONTRACT
    assert "merely to manufacture more markers" in INDICATOR_SYSTEM_CONTRACT


def test_order_value_and_order_target_are_detected_as_explicit_order_intents():
    code = """
def on_init(ctx):
    ctx.allocation = ctx.param('allocation', 1.0)

def on_bar(ctx, bar):
    if ctx.position.is_flat():
        ctx.order_value(ctx.available_capital * ctx.allocation, side='long')
    else:
        ctx.order_target(0, side='long')
"""
    assert "NO_ORDER_INTENT" not in _hint_codes(code)


def test_fixed_initial_stake_sizing_is_reported_for_generated_strategy_review():
    code = """
def on_init(ctx):
    ctx.period = ctx.param('period', 20)

def on_bar(ctx, bar):
    if ctx.position.is_flat():
        ctx.order_value(ctx.investment_amount, side='long')
"""
    assert "INITIAL_STAKE_WITHOUT_DYNAMIC_CAPITAL" in _hint_codes(code)
