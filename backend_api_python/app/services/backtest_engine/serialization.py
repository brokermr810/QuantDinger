"""Serialization helpers shared by backtest runners."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .models import Order


def serialize_orders(orders: Iterable[Order]) -> List[Dict[str, Any]]:
    return [
        {
            "id": order.id,
            "side": order.side.value,
            "type": order.order_type.value,
            "positionSide": order.position_side,
            "reduceOnly": order.reduce_only,
            "quantity": round(order.quantity, 8),
            "notional": round(order.notional, 8),
            "limitPrice": round(order.limit_price, 8),
            "stopPrice": round(order.stop_price, 8),
            "status": order.status.value,
            "filledQuantity": round(order.filled_quantity, 8),
            "avgFillPrice": round(order.avg_fill_price, 8),
            "fee": round(order.fee, 8),
            "reason": order.reason,
            "rejectReason": order.metadata.get("reject_reason", ""),
            "scriptIntent": order.metadata.get("script_intent", ""),
            "submittedBar": order.submitted_bar,
            "ocoGroup": order.oco_group,
        }
        for order in orders
    ]
