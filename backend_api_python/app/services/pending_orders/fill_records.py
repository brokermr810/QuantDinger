"""Fill persistence helpers used by pending order execution."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.utils.db import get_db_connection
from app.services.live_trading.leg_context import resolve_leg_context
from app.services.live_trading.records import (
    apply_fill_to_local_position,
    record_trade,
)
from app.services.pending_orders.position_sync_cache import invalidate_position_sync_snapshot_for_exchange
from app.utils.logger import get_logger
from app.utils.trade_close_reason import is_exit_trade_type

logger = get_logger(__name__)


def persist_strategy_fill(
    *,
    strategy_id: int,
    symbol: str,
    signal_type: str,
    filled: float,
    avg_price: float,
    exchange_config: Dict[str, Any],
    market_type: str,
    order_id: int = 0,
    fill_source: str = "worker",
    commission: float = 0.0,
    commission_ccy: str = "",
    profit: Optional[float] = None,
    close_reason: str = "",
    matched_entry_price: Optional[float] = None,
    grid_matched_profit: Optional[float] = None,
    inst_id: str = "",
    strategy_run_id: int = 0,
    order_intent_id: int = 0,
    basket_id: str = "",
    exchange_id: str = "",
    exchange_order_id: str = "",
    raw_fill: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Apply a fill to local positions and append a trade row."""
    filled_qty = float(filled or 0.0)
    avg_px = float(avg_price or 0.0)
    if abs(filled_qty) <= 1e-12:
        logger.info(
            "Skip zero-sized strategy fill: strategy_id=%s symbol=%s signal=%s order_id=%s source=%s",
            strategy_id,
            symbol,
            signal_type,
            order_id,
            fill_source,
        )
        return profit, matched_entry_price

    leg = resolve_leg_context(
        strategy_id=int(strategy_id),
        symbol=str(symbol or ""),
        exchange_config=exchange_config,
        market_type=str(market_type or "swap"),
        inst_id=str(inst_id or ""),
        fill_source=str(fill_source or "worker"),
        pending_order_id=int(order_id or 0),
    )
    profit_out, _pos, matched_entry = apply_fill_to_local_position(
        strategy_id=int(strategy_id),
        symbol=str(symbol or ""),
        signal_type=str(signal_type or ""),
        filled=filled_qty,
        avg_price=avg_px,
        leg=leg,
    )
    if profit is None:
        profit = profit_out
    if matched_entry_price is None:
        matched_entry_price = matched_entry

    record_trade(
        strategy_id=int(strategy_id),
        symbol=str(symbol or ""),
        trade_type=str(signal_type or ""),
        price=avg_px,
        amount=filled_qty,
        commission=float(commission or 0.0),
        commission_ccy=str(commission_ccy or ""),
        profit=profit,
        close_reason=str(close_reason or ""),
        matched_entry_price=matched_entry_price,
        grid_matched_profit=grid_matched_profit if grid_matched_profit is not None else profit,
        leg=leg,
        strategy_run_id=int(strategy_run_id or 0),
        order_intent_id=int(order_intent_id or 0),
    )

    _record_runtime_fill(
        strategy_id=int(strategy_id),
        strategy_run_id=int(strategy_run_id or 0),
        order_intent_id=int(order_intent_id or 0),
        basket_id=str(basket_id or ""),
        signal_type=str(signal_type or ""),
        price=avg_px,
        quantity=filled_qty,
        fee=float(commission or 0.0),
        fee_ccy=str(commission_ccy or ""),
        exchange_id=str(exchange_id or (exchange_config or {}).get("exchange_id") or ""),
        exchange_order_id=str(exchange_order_id or ""),
        raw_fill=raw_fill or {},
    )
    _apply_fill_to_basket_checkpoint(
        strategy_id=int(strategy_id),
        strategy_run_id=int(strategy_run_id or 0),
        basket_id=str(basket_id or ""),
        signal_type=str(signal_type or ""),
        quantity=filled_qty,
        price=avg_px,
    )

    try:
        from app.services.live_trading.records import _get_user_id_from_strategy

        invalidate_position_sync_snapshot_for_exchange(
            user_id=_get_user_id_from_strategy(int(strategy_id)),
            exchange_id=str(exchange_config.get("exchange_id") or "").strip().lower(),
            market_type=str(market_type or "swap"),
            exchange_config=exchange_config if isinstance(exchange_config, dict) else {},
        )
    except Exception:
        pass
    return profit, matched_entry_price


def _record_runtime_fill(
    *,
    strategy_id: int,
    strategy_run_id: int,
    order_intent_id: int,
    basket_id: str,
    signal_type: str,
    price: float,
    quantity: float,
    fee: float,
    fee_ccy: str,
    exchange_id: str,
    exchange_order_id: str,
    raw_fill: Dict[str, Any],
) -> None:
    if strategy_run_id <= 0 and order_intent_id <= 0:
        return
    import json

    sig = str(signal_type or "").lower()
    pos_side = "short" if "short" in sig else "long" if "long" in sig else ""
    side = "buy" if sig in ("open_long", "add_long", "close_short", "reduce_short") else "sell"
    try:
        safe_raw = json.loads(json.dumps(raw_fill or {}, default=str))
    except Exception:
        safe_raw = {}
    try:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO strategy_order_fills
                (order_intent_id, strategy_run_id, strategy_id, basket_id,
                 exchange_id, exchange_order_id, exchange_fill_id,
                 side, position_side, price, quantity, notional, fee, fee_ccy,
                 filled_at, raw_json)
                VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                """,
                (
                    int(order_intent_id or 0),
                    int(strategy_run_id or 0),
                    int(strategy_id or 0),
                    str(basket_id or ""),
                    str(exchange_id or ""),
                    str(exchange_order_id or ""),
                    str(safe_raw.get("fill_id") or safe_raw.get("trade_id") or ""),
                    side,
                    pos_side,
                    float(price or 0.0),
                    float(quantity or 0.0),
                    float(price or 0.0) * float(quantity or 0.0),
                    float(fee or 0.0),
                    str(fee_ccy or ""),
                    json.dumps(safe_raw, ensure_ascii=False),
                ),
            )
            if int(order_intent_id or 0) > 0:
                cur.execute(
                    """
                    UPDATE strategy_order_intents
                    SET status = CASE WHEN %s > 0 THEN 'partially_filled' ELSE status END,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (float(quantity or 0.0), int(order_intent_id or 0)),
                )
            db.commit()
            cur.close()
    except Exception as exc:
        logger.debug("runtime fill record skipped: %s", exc)


def _apply_fill_to_basket_checkpoint(
    *,
    strategy_id: int,
    strategy_run_id: int,
    basket_id: str,
    signal_type: str,
    quantity: float,
    price: float,
) -> None:
    if not basket_id or strategy_id <= 0:
        return
    sig = str(signal_type or "").strip().lower()
    qty = float(quantity or 0.0)
    px = float(price or 0.0)
    if qty <= 0 or px <= 0:
        return
    try:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT total_qty, total_notional
                FROM strategy_baskets
                WHERE strategy_run_id = %s AND strategy_id = %s AND basket_id = %s
                LIMIT 1
                """,
                (int(strategy_run_id or 0), int(strategy_id), str(basket_id)),
            )
            row = cur.fetchone() or {}
            total_qty = float(row.get("total_qty") or 0.0)
            total_notional = float(row.get("total_notional") or 0.0)
            if sig.startswith("open_") or sig.startswith("add_"):
                total_qty += qty
                total_notional += qty * px
            elif sig.startswith("close_") or sig.startswith("reduce_"):
                close_qty = min(total_qty, qty)
                avg = total_notional / total_qty if total_qty > 0 else 0.0
                total_qty = max(0.0, total_qty - close_qty)
                total_notional = max(0.0, total_notional - close_qty * avg)
            avg_entry = total_notional / total_qty if total_qty > 0 else 0.0
            status = "active" if total_qty > 0 else "closed"
            cur.execute(
                """
                UPDATE strategy_baskets
                SET total_qty = %s,
                    total_notional = %s,
                    avg_entry_price = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE strategy_run_id = %s AND strategy_id = %s AND basket_id = %s
                """,
                (
                    total_qty,
                    total_notional,
                    avg_entry,
                    status,
                    int(strategy_run_id or 0),
                    int(strategy_id),
                    str(basket_id),
                ),
            )
            db.commit()
            cur.close()
    except Exception as exc:
        logger.debug("basket fill checkpoint skipped: %s", exc)


def trade_close_reason_from_payload(payload: Dict[str, Any], signal_type: str) -> str:
    """Return the close reason only for exit-like trade types."""
    if is_exit_trade_type(str(signal_type or "")):
        return str((payload or {}).get("reason") or "").strip()
    return ""
