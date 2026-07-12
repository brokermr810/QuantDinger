from __future__ import annotations

from app.services.strategy_runtime.pipeline import OrderIntentBuilder, PositionSizer, SignalGate
from app.services.strategy_runtime.signals import StrategySignal


class FakeOrderIntentService:
    def __init__(self):
        self.kwargs = None

    def build_signal_idempotency_key(self, **kwargs):
        return "idem-key"

    def create_intent(self, **kwargs):
        self.kwargs = kwargs
        return type("Intent", (), {"id": 42})()


def test_signal_gate_rejects_invalid_signal():
    signal = StrategySignal(timestamp=1, symbol="BTC/USDT", action="open_short", market_type="spot")

    try:
        SignalGate().validate(signal)
    except ValueError as exc:
        assert "spot market" in str(exc)
    else:
        raise AssertionError("spot short must be rejected")


def test_position_sizer_applies_swap_leverage_to_quote_amount():
    signal = StrategySignal(timestamp=1, symbol="BTC/USDT", action="open_long", quote_amount=100, market_type="swap")

    assert PositionSizer().notional(signal, leverage=5) == 500


def test_order_intent_builder_persists_canonical_signal_payload():
    service = FakeOrderIntentService()
    signal = StrategySignal(
        timestamp=123,
        strategy_id=7,
        strategy_run_id=11,
        symbol="ETH/USDT",
        action="close_short",
        amount=2,
        price_hint=100,
        reason="take_profit",
    )

    result = OrderIntentBuilder(service).build(signal=signal, leverage=3, extra_payload={"reason": "take_profit"})

    assert result.runtime_payload["order_intent_id"] == 42
    assert result.runtime_payload["idempotency_key"] == "idem-key"
    assert service.kwargs["side"] == "buy"
    assert service.kwargs["position_side"] == "short"
    assert service.kwargs["reduce_only"] is True
    assert service.kwargs["quantity"] == 2
    assert service.kwargs["notional"] == 600
    assert service.kwargs["payload"]["strategy_signal"]["action"] == "close_short"
