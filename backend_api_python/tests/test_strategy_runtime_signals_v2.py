from __future__ import annotations

import pandas as pd
import pytest

from app.services.strategy_runtime.signals import (
    StrategySignal,
    normalize_signal_action,
    signal_frame_events,
)
from app.services.strategy_script_runtime import StrategyScriptContext


def test_signal_action_contract_rejects_aliases():
    assert normalize_signal_action("open_long") == "open_long"
    assert normalize_signal_action("close_short") == "close_short"

    with pytest.raises(ValueError, match="Unsupported signal action"):
        normalize_signal_action("enter_long")


def test_strategy_signal_derives_order_intent_fields():
    signal = StrategySignal(
        timestamp=123,
        strategy_id=7,
        strategy_run_id=11,
        symbol="BTC/USDT",
        action="close_short",
        market_type="perpetual",
        amount=2,
        price_hint=100,
        reason="take_profit",
        portfolio_id="reserved",
        rebalance_group_id="future",
    )

    kwargs = signal.to_order_intent_kwargs(leverage=5)

    assert signal.action == "close_short"
    assert signal.side == "buy"
    assert signal.position_side == "short"
    assert signal.reduce_only is True
    assert signal.market_type == "swap"
    assert kwargs["order_type"] == "limit"
    assert kwargs["notional"] == 1000
    assert kwargs["payload"]["portfolio_id"] == "reserved"
    assert kwargs["payload"]["rebalance_group_id"] == "future"


def test_spot_short_signal_is_rejected_by_validation():
    signal = StrategySignal(timestamp=1, symbol="ETH/USDT", action="open_short", market_type="spot")

    with pytest.raises(ValueError, match="spot market"):
        signal.validate()


def test_script_order_converts_to_strategy_signal():
    signal = StrategySignal.from_script_order(
        {"action": "sell", "intent": "close_long", "amount": 1.5, "price": 99, "reason": "manual"},
        timestamp=99,
        strategy_id=1,
        symbol="SOL/USDT",
    )

    assert signal.action == "close_long"
    assert signal.side == "sell"
    assert signal.position_side == "long"
    assert signal.amount == 1.5
    assert signal.price_hint == 99
    assert signal.reason == "manual"


def test_signal_frame_events_extract_canonical_rows():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(index=idx)
    signals = {
        "open_long": pd.Series([False, True, False], index=idx),
        "open_long_quote_amount": pd.Series([0, 25, 0], index=idx),
        "open_long_price": pd.Series([0, 101, 0], index=idx),
    }

    events = signal_frame_events(df, signals, symbol="BTC/USDT", market_type="swap")

    assert len(events) == 1
    assert events[0].timestamp == idx[1]
    assert events[0].action == "open_long"
    assert events[0].quote_amount == 25
    assert events[0].price_hint == 101


def test_script_context_exposes_pending_strategy_signals():
    df = pd.DataFrame(
        {"open": [1], "high": [2], "low": [1], "close": [2], "volume": [100], "time": [1700000000]}
    )
    ctx = StrategyScriptContext(df, strategy_id=9, strategy_run_id=99, symbol="BTC/USDT")
    ctx.market_type = "swap"
    ctx.current_index = 0
    ctx.open_long(amount=0.5, price=20000, reason="breakout")

    signals = ctx.pending_signals()

    assert len(signals) == 1
    assert signals[0].timestamp == 1700000000
    assert signals[0].strategy_id == 9
    assert signals[0].strategy_run_id == 99
    assert signals[0].symbol == "BTC/USDT"
    assert signals[0].action == "open_long"
    assert signals[0].amount == 0.5
    assert signals[0].price_hint == 20000


def test_script_context_flush_signals_clears_order_buffer():
    ctx = StrategyScriptContext(strategy_id=1, symbol="ETH/USDT")
    ctx.close_short(amount=1, price=10)

    signals = ctx.flush_signals()

    assert signals[0].action == "close_short"
    assert ctx.pending_orders() == []
