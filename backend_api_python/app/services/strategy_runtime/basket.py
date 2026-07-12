"""Basket runtime primitives for layered stateful strategies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

from .events import append_runtime_event
from .order_intents import OrderIntent, OrderIntentService

logger = get_logger(__name__)


@dataclass
class BasketSnapshot:
    basket_id: str
    side: str
    status: str = "idle"
    current_layer: int = 0
    current_order_in_layer: int = 0
    total_qty: float = 0.0
    total_notional: float = 0.0
    avg_entry_price: float = 0.0
    next_entry_trigger: float = 0.0
    take_profit_price: float = 0.0

    @classmethod
    def from_row(cls, row: Dict[str, Any], *, basket_id: str, side: str) -> "BasketSnapshot":
        if not row:
            return cls(basket_id=basket_id, side=side)
        return cls(
            basket_id=str(row.get("basket_id") or basket_id),
            side=str(row.get("side") or side),
            status=str(row.get("status") or "idle"),
            current_layer=int(row.get("current_layer") or 0),
            current_order_in_layer=int(row.get("current_order_in_layer") or 0),
            total_qty=float(row.get("total_qty") or 0.0),
            total_notional=float(row.get("total_notional") or 0.0),
            avg_entry_price=float(row.get("avg_entry_price") or 0.0),
            next_entry_trigger=float(row.get("next_entry_trigger") or 0.0),
            take_profit_price=float(row.get("take_profit_price") or 0.0),
        )


class BasketRuntime:
    """Durable basket facade exposed through ``ctx.basket(side)``."""

    def __init__(
        self,
        *,
        strategy_id: int = 0,
        strategy_run_id: int = 0,
        symbol: str = "",
        side: str = "long",
        order_intents: OrderIntentService | None = None,
        signal_sink: Any = None,
    ):
        self.strategy_id = int(strategy_id or 0)
        self.strategy_run_id = int(strategy_run_id or 0)
        self.symbol = str(symbol or "")
        self.side = self._normalize_side(side)
        self.basket_id = f"{self.symbol or 'default'}:{self.side}"
        self._order_intents = order_intents or OrderIntentService(
            strategy_id=self.strategy_id,
            strategy_run_id=self.strategy_run_id,
        )
        self._signal_sink = signal_sink
        self._memory_snapshot = BasketSnapshot(self.basket_id, self.side)

    @staticmethod
    def _normalize_side(side: str) -> str:
        s = str(side or "long").strip().lower()
        return "short" if s == "short" else "long"

    def snapshot(self) -> BasketSnapshot:
        if self.strategy_id <= 0:
            return self._memory_snapshot
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM strategy_baskets
                    WHERE strategy_run_id = %s AND strategy_id = %s AND basket_id = %s
                    LIMIT 1
                    """,
                    (self.strategy_run_id, self.strategy_id, self.basket_id),
                )
                row = cur.fetchone() or {}
                cur.close()
            snap = BasketSnapshot.from_row(row, basket_id=self.basket_id, side=self.side)
            self._memory_snapshot = snap
            return snap
        except Exception as exc:
            logger.debug("basket snapshot load skipped: %s", exc)
            return self._memory_snapshot

    def is_idle(self) -> bool:
        return self.snapshot().status in ("idle", "closed", "")

    def is_active(self) -> bool:
        return self.snapshot().status in ("opening", "active", "closing")

    def checkpoint(
        self,
        *,
        status: Optional[str] = None,
        current_layer: Optional[int] = None,
        current_order_in_layer: Optional[int] = None,
        total_qty: Optional[float] = None,
        total_notional: Optional[float] = None,
        avg_entry_price: Optional[float] = None,
        next_entry_trigger: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        max_layer: int = 0,
        max_orders_per_layer: int = 0,
        risk_state: Dict[str, Any] | None = None,
    ) -> BasketSnapshot:
        snap = self.snapshot()
        data = {
            "status": status if status is not None else snap.status,
            "current_layer": current_layer if current_layer is not None else snap.current_layer,
            "current_order_in_layer": current_order_in_layer if current_order_in_layer is not None else snap.current_order_in_layer,
            "total_qty": total_qty if total_qty is not None else snap.total_qty,
            "total_notional": total_notional if total_notional is not None else snap.total_notional,
            "avg_entry_price": avg_entry_price if avg_entry_price is not None else snap.avg_entry_price,
            "next_entry_trigger": next_entry_trigger if next_entry_trigger is not None else snap.next_entry_trigger,
            "take_profit_price": take_profit_price if take_profit_price is not None else snap.take_profit_price,
        }
        if self.strategy_id <= 0:
            self._memory_snapshot = BasketSnapshot(
                basket_id=self.basket_id,
                side=self.side,
                **data,
            )
            return self._memory_snapshot
        try:
            safe_risk = json.loads(json.dumps(risk_state or {}, default=str))
        except Exception:
            safe_risk = {}
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO strategy_baskets
                    (basket_id, strategy_run_id, strategy_id, symbol, side, status,
                     current_layer, current_order_in_layer, total_qty, total_notional,
                     avg_entry_price, next_entry_trigger, take_profit_price,
                     max_layer, max_orders_per_layer, risk_state_json, created_at, updated_at)
                    VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT(strategy_run_id, strategy_id, basket_id)
                    DO UPDATE SET
                        status = excluded.status,
                        current_layer = excluded.current_layer,
                        current_order_in_layer = excluded.current_order_in_layer,
                        total_qty = excluded.total_qty,
                        total_notional = excluded.total_notional,
                        avg_entry_price = excluded.avg_entry_price,
                        next_entry_trigger = excluded.next_entry_trigger,
                        take_profit_price = excluded.take_profit_price,
                        max_layer = CASE WHEN excluded.max_layer > 0 THEN excluded.max_layer ELSE strategy_baskets.max_layer END,
                        max_orders_per_layer = CASE WHEN excluded.max_orders_per_layer > 0 THEN excluded.max_orders_per_layer ELSE strategy_baskets.max_orders_per_layer END,
                        risk_state_json = CASE WHEN excluded.risk_state_json <> '{}'::jsonb THEN excluded.risk_state_json ELSE strategy_baskets.risk_state_json END,
                        updated_at = NOW()
                    """,
                    (
                        self.basket_id,
                        self.strategy_run_id,
                        self.strategy_id,
                        self.symbol,
                        self.side,
                        str(data["status"] or "idle"),
                        int(data["current_layer"] or 0),
                        int(data["current_order_in_layer"] or 0),
                        float(data["total_qty"] or 0.0),
                        float(data["total_notional"] or 0.0),
                        float(data["avg_entry_price"] or 0.0),
                        float(data["next_entry_trigger"] or 0.0),
                        float(data["take_profit_price"] or 0.0),
                        int(max_layer or 0),
                        int(max_orders_per_layer or 0),
                        json.dumps(safe_risk, ensure_ascii=False),
                    ),
                )
                db.commit()
                cur.close()
            append_runtime_event(
                strategy_id=self.strategy_id,
                strategy_run_id=self.strategy_run_id,
                event_type="basket_checkpointed",
                message=f"Basket checkpointed: {self.basket_id}",
                payload=data,
            )
        except Exception as exc:
            logger.debug("basket checkpoint skipped: %s", exc)
        self._memory_snapshot = BasketSnapshot(basket_id=self.basket_id, side=self.side, **data)
        return self._memory_snapshot

    def open_child_order(
        self,
        *,
        layer: int,
        order: int,
        notional: float = 0.0,
        quantity: float = 0.0,
        price: float = 0.0,
        action: str = "open",
        execution_algo: str = "market",
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Create a durable basket child order and matching order intent."""
        action_norm = str(action or "open").strip().lower()
        if action_norm not in ("open", "add", "reduce", "close"):
            action_norm = "open"
        signal_type = {
            ("long", "open"): "open_long",
            ("long", "add"): "add_long",
            ("long", "reduce"): "reduce_long",
            ("long", "close"): "close_long",
            ("short", "open"): "open_short",
            ("short", "add"): "add_short",
            ("short", "reduce"): "reduce_short",
            ("short", "close"): "close_short",
        }.get((self.side, action_norm), f"{action_norm}_{self.side}")
        key = OrderIntentService.build_signal_idempotency_key(
            strategy_run_id=self.strategy_run_id,
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            signal_type=signal_type,
            signal_ts=0,
            basket_id=self.basket_id,
            layer_index=int(layer or 0),
            order_index=int(order or 0),
            action=action_norm,
        )
        basket_order_db_id = self._ensure_basket_order(
            layer=int(layer or 0),
            order=int(order or 0),
            action=action_norm,
            planned_price=float(price or 0.0),
            planned_qty=float(quantity or 0.0),
            planned_notional=float(notional or 0.0),
            idempotency_key=key,
            payload=payload or {},
        )
        if self.strategy_id <= 0:
            intent = OrderIntent(0, key, "ephemeral", existing=False)
        else:
            intent = self._order_intents.create_intent(
                idempotency_key=key,
                symbol=self.symbol,
                side=("buy" if self.side == "long" else "sell"),
                position_side=self.side,
                reduce_only=action_norm in ("reduce", "close"),
                quantity=float(quantity or 0.0),
                notional=float(notional or 0.0),
                limit_price=float(price or 0.0),
                execution_algo=str(execution_algo or "market"),
                basket_id=self.basket_id,
                basket_order_id=int(basket_order_db_id or 0),
                payload={
                    **(payload or {}),
                    "signal_type": signal_type,
                    "layer_index": int(layer or 0),
                    "order_index": int(order or 0),
                    "basket_id": self.basket_id,
                },
            )
        if intent.id > 0:
            self._mark_basket_order_intent(basket_order_db_id, intent.id)
        self._emit_script_order(
            signal_type=signal_type,
            action_norm=action_norm,
            quantity=float(quantity or 0.0),
            notional=float(notional or 0.0),
            price=float(price or 0.0),
            execution_algo=str(execution_algo or "market"),
            idempotency_key=key,
            order_intent_id=int(intent.id or 0),
            basket_order_id=int(basket_order_db_id or 0),
            layer=int(layer or 0),
            order=int(order or 0),
            payload=payload or {},
        )
        self.checkpoint(status="opening", current_layer=int(layer or 0), current_order_in_layer=int(order or 0))
        return {
            "basket_id": self.basket_id,
            "basket_order_id": basket_order_db_id,
            "order_intent_id": intent.id,
            "idempotency_key": key,
            "signal_type": signal_type,
            "existing": intent.existing,
        }

    def _emit_script_order(
        self,
        *,
        signal_type: str,
        action_norm: str,
        quantity: float,
        notional: float,
        price: float,
        execution_algo: str,
        idempotency_key: str,
        order_intent_id: int,
        basket_order_id: int,
        layer: int,
        order: int,
        payload: Dict[str, Any],
    ) -> None:
        if self._signal_sink is None:
            return
        action = "buy" if (self.side == "long") ^ (action_norm in ("reduce", "close")) else "sell"
        amount = quantity if quantity > 0 else notional
        extra: Dict[str, Any] = {}
        if notional > 0:
            # Basket templates express child sizing as quote stake/margin
            # before leverage. Keep that explicit so live and backtest sizing
            # do not fall back to legacy base-quantity semantics.
            extra["script_quote_amount"] = float(notional)
        elif quantity > 0:
            extra["script_base_qty"] = float(quantity)
        try:
            self._signal_sink(
                {
                    "action": action,
                    "price": price if price > 0 else None,
                    "amount": amount if amount > 0 else None,
                    "intent": signal_type,
                    "execution_algo": str(execution_algo or "market"),
                    "reason": str((payload or {}).get("reason") or f"basket_{action_norm}").strip(),
                    **extra,
                    "strategy_run_id": self.strategy_run_id,
                    "basket_id": self.basket_id,
                    "basket_order_db_id": basket_order_id,
                    "order_intent_id": order_intent_id,
                    "idempotency_key": idempotency_key,
                    "layer_index": layer,
                    "order_index": order,
                }
            )
        except Exception:
            pass

    def close_all(self, *, reason: str = "") -> Dict[str, Any]:
        snap = self.snapshot()
        out = self.open_child_order(
            layer=max(1, int(snap.current_layer or 1)),
            order=max(1, int(snap.current_order_in_layer or 1)) + 1,
            # Omit quantity for close-all intents. The executor/backtest closes
            # the live leg size it sees, which avoids stale basket snapshots
            # under-closing leveraged baskets.
            quantity=0.0,
            action="close",
            payload={"reason": str(reason or "basket_close_all")},
        )
        self.checkpoint(status="closing")
        return out

    def _ensure_basket_order(
        self,
        *,
        layer: int,
        order: int,
        action: str,
        planned_price: float,
        planned_qty: float,
        planned_notional: float,
        idempotency_key: str,
        payload: Dict[str, Any],
    ) -> int:
        if self.strategy_id <= 0:
            return 0
        try:
            safe_payload = json.loads(json.dumps(payload or {}, default=str))
        except Exception:
            safe_payload = {}
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO strategy_basket_orders
                    (basket_order_id, basket_id, strategy_run_id, strategy_id, symbol, side,
                     layer_index, order_index, action, planned_price, planned_qty,
                     planned_notional, status, extra_json, created_at, updated_at)
                    VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                     'planned', %s, NOW(), NOW())
                    ON CONFLICT(strategy_run_id, basket_id, side, layer_index, order_index, action)
                    DO NOTHING
                    """,
                    (
                        str(idempotency_key or "")[:128],
                        self.basket_id,
                        self.strategy_run_id,
                        self.strategy_id,
                        self.symbol,
                        self.side,
                        int(layer or 0),
                        int(order or 0),
                        str(action or "open"),
                        float(planned_price or 0.0),
                        float(planned_qty or 0.0),
                        float(planned_notional or 0.0),
                        json.dumps(safe_payload, ensure_ascii=False),
                    ),
                )
                row_id = int(cur.lastrowid or 0)
                if row_id <= 0:
                    cur.execute(
                        """
                        SELECT id
                        FROM strategy_basket_orders
                        WHERE strategy_run_id = %s AND basket_id = %s AND side = %s
                          AND layer_index = %s AND order_index = %s AND action = %s
                        LIMIT 1
                        """,
                        (self.strategy_run_id, self.basket_id, self.side, int(layer or 0), int(order or 0), str(action or "open")),
                    )
                    row = cur.fetchone() or {}
                    row_id = int(row.get("id") or 0)
                db.commit()
                cur.close()
                return row_id
        except Exception as exc:
            logger.debug("basket order create skipped: %s", exc)
            return 0

    def _mark_basket_order_intent(self, basket_order_id: int, intent_id: int) -> None:
        if int(basket_order_id or 0) <= 0 or int(intent_id or 0) <= 0:
            return
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    UPDATE strategy_basket_orders
                    SET order_intent_id = %s,
                        status = 'intent_created',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (int(intent_id), int(basket_order_id)),
                )
                db.commit()
                cur.close()
        except Exception as exc:
            logger.debug("basket order intent mark skipped: %s", exc)
