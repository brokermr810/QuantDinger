"""Runtime pipeline from StrategySignal to OrderIntent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.services.strategy_runtime.order_intents import OrderIntent, OrderIntentService
from app.services.strategy_runtime.signals import StrategySignal


@dataclass(frozen=True)
class IntentBuildResult:
    intent: Optional[OrderIntent]
    idempotency_key: str
    runtime_payload: Dict[str, Any]


class SignalGate:
    """Validate canonical strategy signals before they enter execution."""

    def validate(self, signal: StrategySignal) -> None:
        signal.validate()


class PositionSizer:
    """Resolve notional and quantity from canonical signal fields."""

    def notional(self, signal: StrategySignal, *, leverage: float = 1.0) -> float:
        notional = abs(float(signal.quote_amount or 0.0))
        if notional <= 0 and signal.amount > 0 and signal.price_hint > 0:
            notional = abs(float(signal.amount or 0.0) * float(signal.price_hint or 0.0))
        if signal.market_type != "spot" and notional > 0:
            notional *= max(1.0, float(leverage or 1.0))
        return float(notional or 0.0)


class OrderIntentBuilder:
    """Create persisted order intents from validated StrategySignal objects."""

    def __init__(self, service: OrderIntentService):
        self.service = service
        self.gate = SignalGate()
        self.sizer = PositionSizer()

    def build(
        self,
        *,
        signal: StrategySignal,
        leverage: float = 1.0,
        idempotency_key: str = "",
        basket_id: str = "",
        basket_order_id: int = 0,
        layer_index: int = 0,
        order_index: int = 0,
        existing_order_intent_id: int = 0,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> IntentBuildResult:
        self.gate.validate(signal)
        key = str(idempotency_key or "").strip()
        if not key:
            key = self.service.build_signal_idempotency_key(
                strategy_run_id=int(signal.strategy_run_id or 0),
                strategy_id=int(signal.strategy_id or 0),
                symbol=str(signal.symbol or ""),
                signal_type=str(signal.action or ""),
                signal_ts=_signal_ts(signal.timestamp),
                basket_id=str(basket_id or ""),
                layer_index=int(layer_index or 0),
                order_index=int(order_index or 0),
                action=str(signal.action or ""),
            )
        runtime_payload = {
            "strategy_run_id": int(signal.strategy_run_id or 0),
            "order_intent_id": int(existing_order_intent_id or 0),
            "idempotency_key": key,
            "basket_id": str(basket_id or ""),
            "basket_order_db_id": int(basket_order_id or 0),
            "layer_index": int(layer_index or 0),
            "order_index": int(order_index or 0),
        }
        if int(existing_order_intent_id or 0) > 0:
            return IntentBuildResult(intent=None, idempotency_key=key, runtime_payload=runtime_payload)
        payload = {
            **(extra_payload or {}),
            "strategy_signal": signal.to_signal_dict(),
            "signal_type": signal.action,
            "signal_ts": _signal_ts(signal.timestamp),
            "source": signal.source,
        }
        intent = self.service.create_intent(
            idempotency_key=key,
            symbol=signal.symbol,
            side=signal.side,
            market_type=signal.market_type,
            position_side=signal.position_side,
            reduce_only=signal.reduce_only,
            order_type=signal.order_type,
            quantity=abs(float(signal.amount or 0.0)),
            notional=self.sizer.notional(signal, leverage=leverage),
            limit_price=float(signal.price_hint or 0.0) if signal.order_type == "limit" else 0.0,
            execution_algo=signal.execution_algo,
            basket_id=str(basket_id or ""),
            basket_order_id=int(basket_order_id or 0),
            payload=payload,
            portfolio_id=signal.portfolio_id,
            universe_id=signal.universe_id,
            rebalance_group_id=signal.rebalance_group_id,
            target_weight=signal.target_weight,
            target_notional=signal.target_notional,
            target_position_qty=signal.target_position_qty,
        )
        runtime_payload["order_intent_id"] = int(intent.id or 0)
        return IntentBuildResult(intent=intent, idempotency_key=key, runtime_payload=runtime_payload)


def _signal_ts(value: Any) -> int:
    try:
        if hasattr(value, "timestamp"):
            return int(value.timestamp())
        return int(value or 0)
    except Exception:
        return 0
