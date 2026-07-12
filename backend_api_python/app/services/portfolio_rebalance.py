"""Broker-neutral portfolio rebalance planning and persistence."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from app.services.portfolio_strategy_runtime import PortfolioConstraints, validate_target_weights
from app.services.strategy_runtime.order_intents import OrderIntentService
from app.services.strategy_runtime.pipeline import OrderIntentBuilder
from app.services.strategy_runtime.signals import StrategySignal
from app.utils.db import get_db_connection


SUPPORTED_EXECUTION_MODES = frozenset({"live", "notify_only"})


@dataclass(frozen=True)
class RebalancePlanConfig:
    commission_rate: float = 0.0005
    min_trade_value: float = 0.0
    allow_fractional: bool = True
    max_weight: float = 1.0


class PortfolioRebalancePlanner:
    """Translate target weights into deterministic sell-then-buy instructions."""

    def build(
        self,
        *,
        portfolio_id: str,
        universe_id: int,
        target_weights: Mapping[str, Any],
        current_quantities: Mapping[str, Any],
        prices: Mapping[str, Any],
        cash: float,
        signal_time: Any,
        execution_mode: str,
        config: Optional[RebalancePlanConfig] = None,
        instrument_contexts: Optional[Mapping[str, Mapping[str, Any]]] = None,
        universe_snapshot_id: str = "",
    ) -> dict:
        cfg = config or RebalancePlanConfig()
        mode = str(execution_mode or "").strip().lower()
        if mode not in SUPPORTED_EXECUTION_MODES:
            raise ValueError("portfolio.invalidExecutionMode")
        commission = _non_negative(cfg.commission_rate, "portfolio.invalidCommission")
        min_trade = _non_negative(cfg.min_trade_value, "portfolio.invalidMinTradeValue")
        clean_prices = {str(symbol).upper(): _price_or_zero(price) for symbol, price in prices.items()}
        quantities = {
            str(symbol).upper(): _non_negative(quantity, "portfolio.invalidQuantity")
            for symbol, quantity in current_quantities.items()
            if _number(quantity) > 1e-12
        }
        universe = set(clean_prices) | set(quantities) | {str(symbol).upper() for symbol in target_weights}
        targets = validate_target_weights(
            target_weights,
            universe=universe,
            constraints=PortfolioConstraints(
                long_only=True,
                max_weight=float(cfg.max_weight),
                gross_limit=1.0,
                net_limit=1.0,
            ),
        )
        clean_cash = _non_negative(cash, "portfolio.invalidCash")
        equity = clean_cash + sum(
            quantity * clean_prices.get(symbol, 0.0)
            for symbol, quantity in quantities.items()
        )
        if equity <= 0:
            raise ValueError("portfolio.invalidEquity")
        current_weights = {
            symbol: quantity * clean_prices.get(symbol, 0.0) / equity
            for symbol, quantity in sorted(quantities.items())
            if clean_prices.get(symbol, 0.0) > 0
        }
        timestamp = _timestamp(signal_time)
        group_seed = f"{portfolio_id}:{int(universe_id)}:{timestamp.isoformat()}"
        group_id = hashlib.sha256(group_seed.encode("utf-8")).hexdigest()[:32]
        plan_id = str(uuid.uuid4())
        contexts = instrument_contexts or {}
        diagnostics = []
        sells = []
        buys = []
        all_symbols = sorted(set(quantities) | set(targets.weights))

        for symbol in all_symbols:
            price = clean_prices.get(symbol, 0.0)
            if price <= 0:
                diagnostics.append({"symbol": symbol, "code": "portfolio.missingPrice"})
                continue
            current_quantity = quantities.get(symbol, 0.0)
            target_quantity = equity * targets.weights.get(symbol, 0.0) / price
            delta_quantity = target_quantity - current_quantity
            delta_notional = abs(delta_quantity) * price
            if delta_notional < min_trade or abs(delta_quantity) <= 1e-12:
                continue
            if delta_quantity < 0:
                quantity = _round_quantity(abs(delta_quantity), cfg.allow_fractional)
                if quantity > 0:
                    sells.append((symbol, quantity, price, target_quantity))
            else:
                buys.append((symbol, delta_quantity, price, target_quantity))

        orders = []
        projected_cash = clean_cash
        for symbol, quantity, price, target_quantity in sells:
            notional = quantity * price
            fee = notional * commission
            projected_cash += notional - fee
            orders.append(self._order(
                plan_id, group_id, symbol, "sell", quantity, price, fee,
                current_weights.get(symbol, 0.0), targets.weights.get(symbol, 0.0),
                quantities.get(symbol, 0.0), target_quantity, contexts.get(symbol),
            ))

        required_cash = sum(quantity * price * (1.0 + commission) for _, quantity, price, _ in buys)
        scale = min(1.0, projected_cash / required_cash) if required_cash > 0 else 0.0
        for symbol, requested_quantity, price, target_quantity in buys:
            quantity = _round_quantity(requested_quantity * scale, cfg.allow_fractional)
            notional = quantity * price
            fee = notional * commission
            if quantity <= 0 or notional < min_trade:
                diagnostics.append({"symbol": symbol, "code": "portfolio.insufficientCash"})
                continue
            projected_cash -= notional + fee
            orders.append(self._order(
                plan_id, group_id, symbol, "buy", quantity, price, fee,
                current_weights.get(symbol, 0.0), targets.weights.get(symbol, 0.0),
                quantities.get(symbol, 0.0), target_quantity, contexts.get(symbol),
            ))

        orders.sort(key=lambda item: (0 if item["side"] == "sell" else 1, item["symbol"]))
        return {
            "plan_id": plan_id,
            "portfolio_id": str(portfolio_id or ""),
            "universe_id": int(universe_id),
            "universe_snapshot_id": str(universe_snapshot_id or ""),
            "rebalance_group_id": group_id,
            "execution_mode": mode,
            "status": "planned",
            "signal_time": timestamp.isoformat(),
            "equity": round(equity, 8),
            "cash": round(clean_cash, 8),
            "projected_cash": round(max(0.0, projected_cash), 8),
            "current_weights": current_weights,
            "target_weights": dict(targets.weights),
            "orders": orders,
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _order(
        plan_id: str,
        group_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        current_weight: float,
        target_weight: float,
        current_quantity: float,
        target_quantity: float,
        context: Optional[Mapping[str, Any]],
    ) -> dict:
        action = (
            "open_long" if side == "buy" and current_quantity <= 1e-12
            else "add_long" if side == "buy"
            else "close_long" if target_quantity <= 1e-12
            else "reduce_long"
        )
        identity = f"{group_id}:{symbol}:{side}:{round(target_quantity, 12)}"
        market_context = context or {}
        return {
            "idempotency_key": f"portfolio:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"[:180],
            "plan_id": plan_id,
            "market": str(market_context.get("market") or ""),
            "symbol": symbol,
            "exchange_id": str(market_context.get("exchange_id") or ""),
            "market_type": str(market_context.get("market_type") or "spot"),
            "side": side,
            "action": action,
            "quantity": round(quantity, 12),
            "reference_price": round(price, 8),
            "estimated_notional": round(quantity * price, 8),
            "estimated_fee": round(fee, 8),
            "current_weight": round(current_weight, 12),
            "target_weight": round(target_weight, 12),
            "target_position_qty": round(target_quantity, 12),
            "status": "planned",
        }


class PortfolioRebalanceRepository:
    """Persist a plan and its instructions atomically."""

    def save(self, *, user_id: int, strategy_id: Optional[int], plan: dict) -> dict:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_portfolio_rebalance_plans
                  (plan_id, user_id, strategy_id, portfolio_id, universe_id,
                   universe_snapshot_id, rebalance_group_id, execution_mode,
                   status, signal_time, equity, cash, target_weights_json,
                   current_weights_json, diagnostics_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, strategy_id, rebalance_group_id) DO NOTHING
                """,
                (
                    plan["plan_id"], int(user_id), int(strategy_id) if strategy_id else None,
                    plan.get("portfolio_id") or "", int(plan.get("universe_id") or 0),
                    plan.get("universe_snapshot_id") or "", plan["rebalance_group_id"],
                    plan["execution_mode"], plan.get("status") or "planned",
                    plan["signal_time"], float(plan.get("equity") or 0),
                    float(plan.get("cash") or 0),
                    json.dumps(plan.get("target_weights") or {}, ensure_ascii=False),
                    json.dumps(plan.get("current_weights") or {}, ensure_ascii=False),
                    json.dumps(plan.get("diagnostics") or [], ensure_ascii=False),
                ),
            )
            cur.execute(
                """
                SELECT plan_id FROM qd_portfolio_rebalance_plans
                WHERE user_id = ? AND strategy_id IS NOT DISTINCT FROM ? AND rebalance_group_id = ?
                LIMIT 1
                """,
                (int(user_id), int(strategy_id) if strategy_id else None, plan["rebalance_group_id"]),
            )
            stored = cur.fetchone() or {}
            stored_plan_id = str(stored.get("plan_id") or plan["plan_id"])
            for order in plan.get("orders") or []:
                cur.execute(
                    """
                    INSERT INTO qd_portfolio_rebalance_orders
                      (plan_id, idempotency_key, market, symbol, exchange_id,
                       market_type, side, action, quantity, reference_price,
                       estimated_notional, estimated_fee, current_weight,
                       target_weight, status, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (
                        stored_plan_id, order["idempotency_key"], order.get("market") or "",
                        order["symbol"], order.get("exchange_id") or "",
                        order.get("market_type") or "spot", order["side"], order["action"],
                        float(order["quantity"]), float(order["reference_price"]),
                        float(order["estimated_notional"]), float(order["estimated_fee"]),
                        float(order["current_weight"]), float(order["target_weight"]),
                        json.dumps(order, ensure_ascii=False),
                    ),
                )
            db.commit()
            cur.close()
        saved = dict(plan)
        saved["plan_id"] = stored_plan_id
        return saved


class PortfolioRebalanceDispatcher:
    """Dispatch a persisted plan to notification or canonical live intents."""

    def __init__(
        self,
        repository: Optional[PortfolioRebalanceRepository] = None,
        pending_order_enqueue: Optional[Any] = None,
    ):
        self.repository = repository or PortfolioRebalanceRepository()
        self.pending_order_enqueue = pending_order_enqueue or self._default_pending_order_enqueue

    def dispatch(
        self,
        *,
        user_id: int,
        strategy_id: Optional[int],
        strategy_run_id: int,
        plan: dict,
        notification_channels: Optional[list[str]] = None,
    ) -> dict:
        saved = self.repository.save(user_id=user_id, strategy_id=strategy_id, plan=plan)
        if saved.get("execution_mode") == "notify_only":
            return self._notify(
                user_id=user_id,
                strategy_id=strategy_id,
                plan=saved,
                channels=notification_channels or ["browser"],
            )
        return self._create_live_intents(
            strategy_id=int(strategy_id or 0),
            strategy_run_id=int(strategy_run_id or 0),
            plan=saved,
        )

    @staticmethod
    def _notify(
        *,
        user_id: int,
        strategy_id: Optional[int],
        plan: dict,
        channels: list[str],
    ) -> dict:
        payload = {
            "event": "portfolio.rebalance",
            "title_i18n_key": "portfolio.notification.rebalanceTitle",
            "message_i18n_key": "portfolio.notification.rebalanceMessage",
            "plan": plan,
        }
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT notification_id, status FROM qd_portfolio_rebalance_plans WHERE plan_id = ?",
                (plan["plan_id"],),
            )
            existing = cur.fetchone() or {}
            notification_id = int(existing.get("notification_id") or 0)
            if notification_id <= 0:
                cur.execute(
                    """
                    INSERT INTO qd_strategy_notifications
                      (user_id, strategy_id, symbol, signal_type, channels,
                       title, message, payload_json, created_at)
                    VALUES (?, ?, '', 'portfolio_rebalance', ?, '', '', ?, NOW())
                    RETURNING id
                    """,
                    (
                        int(user_id), int(strategy_id) if strategy_id else None,
                        ",".join(sorted({str(channel) for channel in channels if channel})),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                row = cur.fetchone() or {}
                notification_id = int(row.get("id") or 0)
            cur.execute(
                """
                UPDATE qd_portfolio_rebalance_plans
                SET status = 'notified', notification_id = ?, updated_at = NOW()
                WHERE plan_id = ?
                """,
                (notification_id, plan["plan_id"]),
            )
            cur.execute(
                "UPDATE qd_portfolio_rebalance_orders SET status = 'notified', updated_at = NOW() WHERE plan_id = ?",
                (plan["plan_id"],),
            )
            db.commit()
            cur.close()
        result = dict(plan)
        result["status"] = "notified"
        result["notification_id"] = notification_id
        return result

    def _create_live_intents(self, *, strategy_id: int, strategy_run_id: int, plan: dict) -> dict:
        if strategy_id <= 0:
            raise ValueError("portfolio.strategyRequiredForLive")
        service = OrderIntentService(strategy_id=strategy_id, strategy_run_id=strategy_run_id)
        builder = OrderIntentBuilder(service)
        intent_rows = []
        failures = []
        for order in plan.get("orders") or []:
            signal = StrategySignal(
                timestamp=plan["signal_time"],
                strategy_id=strategy_id,
                strategy_run_id=strategy_run_id,
                symbol=order["symbol"],
                action=order["action"],
                market_type=order.get("market_type") or "spot",
                amount=float(order["quantity"]),
                quote_amount=float(order["estimated_notional"]),
                price_hint=float(order["reference_price"]),
                reason="portfolio_rebalance",
                source="portfolio_strategy",
                metadata={"order_type": "market", "execution_algo": "market"},
                portfolio_id=plan.get("portfolio_id") or "",
                universe_id=str(plan.get("universe_id") or ""),
                rebalance_group_id=plan["rebalance_group_id"],
                target_weight=float(order["target_weight"]),
                target_notional=float(plan["equity"]) * float(order["target_weight"]),
                target_position_qty=float(order["target_position_qty"]),
            )
            built = builder.build(signal=signal, idempotency_key=order["idempotency_key"])
            intent_id = int(built.intent.id if built.intent is not None else built.runtime_payload.get("order_intent_id") or 0)
            pending_order_id = 0
            if intent_id > 0:
                pending_order_id = int(self.pending_order_enqueue(
                    strategy_id=strategy_id,
                    strategy_run_id=strategy_run_id,
                    order=order,
                    order_intent_id=intent_id,
                    plan=plan,
                ) or 0)
            if intent_id <= 0 or pending_order_id <= 0:
                failures.append(order["symbol"])
            intent_rows.append((order["idempotency_key"], intent_id, pending_order_id))

        with get_db_connection() as db:
            cur = db.cursor()
            for key, intent_id, pending_order_id in intent_rows:
                cur.execute(
                    """
                    UPDATE qd_portfolio_rebalance_orders
                    SET order_intent_id = ?, pending_order_id = ?, status = ?, updated_at = NOW()
                    WHERE idempotency_key = ?
                    """,
                    (
                        intent_id,
                        pending_order_id,
                        "queued" if pending_order_id > 0 else "failed",
                        key,
                    ),
                )
            status = "queued" if not failures else "partial_failure"
            cur.execute(
                "UPDATE qd_portfolio_rebalance_plans SET status = ?, updated_at = NOW() WHERE plan_id = ?",
                (status, plan["plan_id"]),
            )
            db.commit()
            cur.close()
        result = dict(plan)
        result["status"] = status
        result["intent_count"] = len([row for row in intent_rows if row[1] > 0])
        result["queued_count"] = len([row for row in intent_rows if row[2] > 0])
        result["failed_symbols"] = failures
        return result

    @staticmethod
    def _default_pending_order_enqueue(
        *,
        strategy_id: int,
        strategy_run_id: int,
        order: dict,
        order_intent_id: int,
        plan: dict,
    ) -> int:
        from app import get_trading_executor

        executor = get_trading_executor()
        pending_id = executor._enqueue_pending_order(
            strategy_id=int(strategy_id),
            symbol=str(order["symbol"]),
            signal_type=str(order["action"]),
            amount=float(order["quantity"]),
            price=float(order["reference_price"]),
            signal_ts=int(_timestamp(plan["signal_time"]).timestamp()),
            market_type=str(order.get("market_type") or "spot"),
            leverage=1.0,
            execution_mode="live",
            extra_payload={
                "strategy_run_id": int(strategy_run_id),
                "order_intent_id": int(order_intent_id),
                "idempotency_key": str(order["idempotency_key"]),
                "execution_algo": "market",
                "portfolio_id": str(plan.get("portfolio_id") or ""),
                "universe_id": int(plan.get("universe_id") or 0),
                "rebalance_group_id": str(plan.get("rebalance_group_id") or ""),
                "target_weight": float(order.get("target_weight") or 0.0),
                "target_position_qty": float(order.get("target_position_qty") or 0.0),
            },
        )
        if not pending_id:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    "SELECT id FROM pending_orders WHERE idempotency_key = ? ORDER BY id DESC LIMIT 1",
                    (str(order["idempotency_key"]),),
                )
                row = cur.fetchone() or {}
                pending_id = int(row.get("id") or 0)
                cur.close()
        return int(pending_id or 0)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("portfolio.invalidSignalTime") from exc


def _round_quantity(value: float, fractional: bool) -> float:
    clean = max(0.0, float(value or 0.0))
    return math.floor(clean * 1e8) / 1e8 if fractional else float(math.floor(clean))


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _non_negative(value: Any, code: str) -> float:
    parsed = _number(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(code)
    return parsed


def _positive(value: Any, code: str) -> float:
    parsed = _non_negative(value, code)
    if parsed <= 0:
        raise ValueError(code)
    return parsed


def _price_or_zero(value: Any) -> float:
    parsed = _number(value)
    return parsed if math.isfinite(parsed) and parsed > 0 else 0.0
