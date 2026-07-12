"""Live order adapters that wrap current exchange clients behind V2 contracts."""

from __future__ import annotations

from typing import Any, Dict

from app.services.live_trading.base import LiveOrderResult
from app.services.live_trading.contracts import FillSnapshot, OrderIntent, PositionSnapshot
from app.services.pending_orders.live_order_phases import (
    cancel_live_limit_order,
    place_live_limit_order,
    place_live_market_order,
    wait_live_order_fill,
)


class LiveOrderPhaseAdapter:
    """Adapter over existing live order phase helpers."""

    def __init__(
        self,
        *,
        client: Any,
        exchange_id: str,
        payload: Dict[str, Any],
        exchange_config: Dict[str, Any],
        order_mode: str = "market",
        ref_price: float = 0.0,
        spot_quote_amt: float = 0.0,
        spot_market_buy_uses_quote: bool = False,
    ):
        self.client = client
        self.exchange_id = str(exchange_id or "")
        self.payload = dict(payload or {})
        self.exchange_config = dict(exchange_config or {})
        self.order_mode = str(order_mode or "market")
        self.ref_price = float(ref_price or 0.0)
        self.spot_quote_amt = float(spot_quote_amt or 0.0)
        self.spot_market_buy_uses_quote = bool(spot_market_buy_uses_quote)

    def place_market_order(self, intent: OrderIntent) -> LiveOrderResult:
        return place_live_market_order(
            client=self.client,
            symbol=str(intent.symbol),
            side=str(intent.side),
            amount=float(intent.quantity or 0.0),
            reduce_only=bool(intent.reduce_only),
            pos_side=str(intent.pos_side or ""),
            client_order_id=str(intent.client_order_id or ""),
            market_type=str(intent.market_type or "swap"),
            payload=self.payload,
            exchange_config=self.exchange_config,
            leverage=float(intent.leverage or 1.0),
            ref_price=float(self.ref_price or 0.0),
            spot_quote_amt=float(self.spot_quote_amt or 0.0),
            spot_market_buy_uses_quote=bool(self.spot_market_buy_uses_quote),
        )

    def place_limit_order(self, intent: OrderIntent) -> LiveOrderResult:
        return place_live_limit_order(
            client=self.client,
            symbol=str(intent.symbol),
            side=str(intent.side),
            amount=float(intent.quantity or 0.0),
            price=float(intent.price or 0.0),
            reduce_only=bool(intent.reduce_only),
            pos_side=str(intent.pos_side or ""),
            client_order_id=str(intent.client_order_id or ""),
            market_type=str(intent.market_type or "swap"),
            payload=self.payload,
            exchange_config=self.exchange_config,
            leverage=float(intent.leverage or 1.0),
            order_mode=self.order_mode,
        )

    def cancel_order(self, intent: OrderIntent, *, order_id: str = "") -> Dict[str, Any]:
        result = cancel_live_limit_order(
            client=self.client,
            symbol=str(intent.symbol),
            order_id=str(order_id or ""),
            client_order_id=str(intent.client_order_id or ""),
            market_type=str(intent.market_type or "swap"),
            exchange_config=self.exchange_config,
        )
        return result if isinstance(result, dict) else {"raw": result}

    def wait_for_fill(
        self,
        intent: OrderIntent,
        *,
        order_id: str = "",
        max_wait_sec: float = 15.0,
    ) -> FillSnapshot:
        raw = wait_live_order_fill(
            client=self.client,
            symbol=str(intent.symbol),
            order_id=str(order_id or ""),
            client_order_id=str(intent.client_order_id or ""),
            market_type=str(intent.market_type or "swap"),
            exchange_config=self.exchange_config,
            max_wait_sec=float(max_wait_sec or 0.0),
            phase="market" if float(intent.price or 0.0) <= 0 else "limit",
        )
        return FillSnapshot(
            filled_qty=float((raw or {}).get("filled") or 0.0),
            avg_price=float((raw or {}).get("avg_price") or 0.0),
            status=str((raw or {}).get("status") or ""),
            raw=dict(raw or {}),
        )

    def query_position(self, intent: OrderIntent) -> PositionSnapshot:
        raise NotImplementedError("position queries are handled by the position sync service")
