from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .models import (
    BacktestConfig,
    Execution,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class BrokerSimulator:
    """Candle-level broker simulator with explicit order lifecycle.

    It is intentionally exchange-agnostic. Swap backtests use PnL-style cash
    accounting, while spot long backtests reserve cash for the purchased asset
    and value the account as cash plus marked position value.
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.cash = float(config.initial_capital or 0.0)
        self.total_commission = 0.0
        self.orders: List[Order] = []
        self._active_orders: List[Order] = []
        self.executions: List[Execution] = []
        self.trades: List[Dict[str, Any]] = []
        self.closed_trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.total_funding = 0.0
        self._next_funding_ts: Optional[int] = None
        self.long = Position("long")
        self.short = Position("short")
        self._next_order_id = 1
        self._current_bar_index = -1
        self._current_time: Any = None

    @property
    def equity(self) -> float:
        return self._account_value(self._last_price or 0.0)

    @property
    def _last_price(self) -> float:
        if not self.equity_curve:
            return 0.0
        try:
            return float(self.equity_curve[-1].get("_mark_price") or 0.0)
        except Exception:
            return 0.0

    def submit(
        self,
        *,
        side: str,
        order_type: str = "market",
        position_side: str = "",
        reduce_only: bool = False,
        quantity: float = 0.0,
        notional: float = 0.0,
        limit_price: float = 0.0,
        stop_price: float = 0.0,
        reason: str = "",
        oco_group: str = "",
        valid_until_bar: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Order:
        side_norm = OrderSide.SELL if str(side).lower() == "sell" else OrderSide.BUY
        try:
            typ = OrderType(str(order_type or "market").lower())
        except Exception:
            typ = OrderType.MARKET
        order = Order(
            id=self._next_order_id,
            side=side_norm,
            order_type=typ,
            position_side=str(position_side or "").lower(),
            reduce_only=bool(reduce_only),
            quantity=max(0.0, float(quantity or 0.0)),
            notional=max(0.0, float(notional or 0.0)),
            limit_price=max(0.0, float(limit_price or 0.0)),
            stop_price=max(0.0, float(stop_price or 0.0)),
            submitted_bar=max(0, int(self._current_bar_index)),
            created_time=self._current_time,
            reason=str(reason or ""),
            status=OrderStatus.SUBMITTED,
            oco_group=str(oco_group or ""),
            valid_until_bar=valid_until_bar,
            metadata=dict(metadata or {}),
        )
        self._next_order_id += 1
        self.orders.append(order)
        order.status = OrderStatus.ACCEPTED
        self._active_orders.append(order)
        return order

    def process_bar(self, bar_index: int, timestamp: Any, row: pd.Series) -> None:
        self._current_bar_index = int(bar_index)
        self._current_time = timestamp
        open_ = _price(row.get("open"), row.get("close"))
        high = _price(row.get("high"), open_)
        low = _price(row.get("low"), open_)
        close = _price(row.get("close"), open_)
        volume = _price(row.get("volume"), 0.0)

        self.long.mark_extremes(high, low)
        self.short.mark_extremes(high, low)

        for order in list(self._active_orders):
            if order.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIAL):
                self._deactivate_order(order)
                continue
            if order.valid_until_bar is not None and bar_index > order.valid_until_bar:
                order.status = OrderStatus.EXPIRED
                self._deactivate_order(order)
                continue
            fill_price = self._match_order(order, open_, high, low, close)
            if fill_price is None:
                continue
            qty = self._resolve_quantity(order, fill_price)
            if qty <= 0:
                order.status = OrderStatus.REJECTED
                order.metadata.setdefault(
                    "reject_reason",
                    "insufficient_margin" if self._is_entry_order(order) else "invalid_quantity",
                )
                self._deactivate_order(order)
                continue
            max_qty = self._volume_cap(order, qty, volume)
            if max_qty <= 0:
                continue
            self._execute(order, max_qty, fill_price, timestamp, bar_index)
            if order.oco_group and order.status == OrderStatus.FILLED:
                self.cancel_oco(order.oco_group, exclude_id=order.id)

        self._apply_funding(timestamp, close)
        self.record_equity(timestamp, close)

    def execute_immediate(
        self,
        *,
        side: str,
        position_side: str,
        quantity: float,
        price: float,
        reason: str,
        timestamp: Any,
        bar_index: int,
        reduce_only: bool = False,
        high: Optional[float] = None,
        low: Optional[float] = None,
    ) -> Optional[Execution]:
        if quantity <= 0 or price <= 0:
            return None
        self._current_bar_index = int(bar_index)
        self._current_time = timestamp
        price = _bound_price(price, high=high, low=low)
        order = self.submit(
            side=side,
            order_type="market",
            position_side=position_side,
            reduce_only=reduce_only,
            quantity=quantity,
            reason=reason,
            metadata={"force_price": True},
        )
        return self._execute(order, quantity, price, timestamp, bar_index)

    def cancel_oco(self, group: str, *, exclude_id: int = 0) -> None:
        for order in list(self._active_orders):
            if order.id == exclude_id:
                continue
            if order.oco_group == group and order.status in (OrderStatus.ACCEPTED, OrderStatus.PARTIAL):
                order.status = OrderStatus.CANCELLED
                self._deactivate_order(order)

    def cancel_all(self) -> None:
        for order in list(self._active_orders):
            if order.status in (OrderStatus.ACCEPTED, OrderStatus.PARTIAL):
                order.status = OrderStatus.CANCELLED
                self._deactivate_order(order)

    def close_all(self, *, price: float, timestamp: Any, bar_index: int, reason: str = "end_of_backtest") -> None:
        if self.long.is_open():
            self.execute_immediate(
                side="sell",
                position_side="long",
                quantity=self.long.size,
                price=price * (1 - self.config.slippage),
                reason=reason,
                timestamp=timestamp,
                bar_index=bar_index,
                reduce_only=True,
            )
        if self.short.is_open():
            self.execute_immediate(
                side="buy",
                position_side="short",
                quantity=self.short.size,
                price=price * (1 + self.config.slippage),
                reason=reason,
                timestamp=timestamp,
                bar_index=bar_index,
                reduce_only=True,
            )
        self.cancel_all()

    def unrealized_pnl(self, mark_price: float) -> float:
        mark = float(mark_price or 0.0)
        pnl = 0.0
        if self.long.is_open() and mark > 0:
            pnl += (mark - self.long.avg_price) * self.long.size
        if self.short.is_open() and mark > 0:
            pnl += (self.short.avg_price - mark) * self.short.size
        return pnl

    def _account_value(self, mark_price: float) -> float:
        mark = float(mark_price or 0.0)
        if self.config.market_type == "spot":
            value = self.cash
            if self.long.is_open() and mark > 0:
                value += self.long.size * mark
            return value
        return self.cash + self.unrealized_pnl(mark)

    def _swap_position_notional(self, mark_price: float) -> float:
        if self.config.market_type == "spot":
            return 0.0
        mark = float(mark_price or 0.0)
        if mark <= 0:
            return 0.0
        notional = 0.0
        if self.long.is_open():
            notional += self.long.size * mark
        if self.short.is_open():
            notional += self.short.size * mark
        return notional

    def _used_margin(self, mark_price: float) -> float:
        if self.config.market_type == "spot":
            return 0.0
        leverage = max(1.0, float(self.config.leverage or 1.0))
        return self._swap_position_notional(mark_price) / leverage

    def _available_margin(self, mark_price: float) -> float:
        if self.config.market_type == "spot":
            return max(0.0, self.cash)
        return max(0.0, self._account_value(mark_price) - self._used_margin(mark_price))

    def available_entry_notional(self, mark_price: float) -> float:
        mark = max(0.0, float(mark_price or 0.0))
        if mark <= 0:
            return 0.0
        commission_rate = max(0.0, float(self.config.commission or 0.0))
        if self.config.market_type == "spot":
            return self._available_margin(mark) / (1.0 + commission_rate)
        leverage = max(1.0, float(self.config.leverage or 1.0))
        return self._available_margin(mark) / (1.0 + leverage * commission_rate)

    def _apply_funding(self, timestamp: Any, mark_price: float) -> None:
        if self.config.market_type != "swap":
            return
        rate_annual = float(self.config.funding_rate_annual or 0.0)
        if abs(rate_annual) <= 1e-12:
            return
        if not self.long.is_open() and not self.short.is_open():
            return
        try:
            ts = int(pd.to_datetime(timestamp).timestamp())
        except Exception:
            return
        interval = int(max(1.0, float(self.config.funding_interval_hours or 8.0)) * 3600)
        if self._next_funding_ts is None:
            self._next_funding_ts = ((ts // interval) + 1) * interval
            return
        periods_per_year = (365.25 * 24.0) / max(1.0, float(self.config.funding_interval_hours or 8.0))
        rate_per_period = rate_annual / periods_per_year
        while self._next_funding_ts is not None and ts >= self._next_funding_ts:
            mark = float(mark_price or 0.0)
            if mark > 0:
                charge = 0.0
                if self.long.is_open():
                    charge += self.long.size * mark * rate_per_period
                if self.short.is_open():
                    charge -= self.short.size * mark * rate_per_period
                self.cash -= charge
                self.total_funding += charge
            self._next_funding_ts += interval

    def record_equity(self, timestamp: Any, mark_price: float) -> None:
        value = self._account_value(mark_price)
        self.equity_curve.append({
            "time": _format_time(timestamp),
            "value": round(max(0.0, value), 2),
            "_mark_price": float(mark_price or 0.0),
        })

    def check_liquidation(
        self,
        *,
        timestamp: Any,
        bar_index: int,
        high: float,
        low: float,
    ) -> None:
        if self.config.market_type != "swap":
            return
        maintenance = max(0.0, float(self.config.maintenance_margin_rate or 0.0))
        if self.long.is_open():
            quantity = float(self.long.size)
            denominator = quantity * max(1e-12, 1.0 - maintenance)
            threshold = ((quantity * self.long.avg_price) - self.cash) / denominator
            if threshold > 0 and float(low or 0.0) <= threshold:
                self._liquidate_leg(
                    side="long",
                    price=_bound_price(threshold, high=high, low=low),
                    timestamp=timestamp,
                    bar_index=bar_index,
                )
        if self.short.is_open():
            quantity = float(self.short.size)
            denominator = quantity * (1.0 + maintenance)
            threshold = (self.cash + (quantity * self.short.avg_price)) / max(1e-12, denominator)
            if threshold > 0 and float(high or 0.0) >= threshold:
                self._liquidate_leg(
                    side="short",
                    price=_bound_price(threshold, high=high, low=low),
                    timestamp=timestamp,
                    bar_index=bar_index,
                )

    def _liquidate_leg(
        self,
        *,
        side: str,
        price: float,
        timestamp: Any,
        bar_index: int,
    ) -> None:
        position = self.long if side == "long" else self.short
        if not position.is_open() or price <= 0:
            return
        execution = self.execute_immediate(
            side="sell" if side == "long" else "buy",
            position_side=side,
            quantity=position.size,
            price=price,
            reason="liquidation",
            timestamp=timestamp,
            bar_index=bar_index,
            reduce_only=True,
        )
        fee_rate = max(0.0, float(self.config.liquidation_fee_rate or 0.0))
        if execution is not None and execution.quantity > 0 and fee_rate > 0:
            liquidation_fee = execution.quantity * execution.price * fee_rate
            self.cash -= liquidation_fee
            execution.fee += liquidation_fee
            self.total_commission += liquidation_fee
            if self.trades:
                self.trades[-1]["commission"] = round(float(self.trades[-1].get("commission") or 0.0) + liquidation_fee, 8)
                self.trades[-1]["balance"] = round(max(0.0, self.cash), 2)
            if self.closed_trades:
                self.closed_trades[-1]["commission"] = round(float(self.closed_trades[-1].get("commission") or 0.0) + liquidation_fee, 8)
                self.closed_trades[-1]["balance"] = round(max(0.0, self.cash), 2)

    def _match_order(self, order: Order, open_: float, high: float, low: float, close: float) -> Optional[float]:
        if order.order_type == OrderType.MARKET:
            if order.metadata.get("fill_on_close"):
                price = close
            elif order.metadata.get("force_price"):
                price = order.limit_price or order.stop_price or close
            else:
                price = open_
            return self._apply_slippage(order.side, price, high=high, low=low)

        if order.order_type == OrderType.LIMIT:
            limit_price = order.limit_price
            if limit_price <= 0:
                return None
            if order.side == OrderSide.BUY and low <= limit_price:
                if open_ <= limit_price and self.config.intrabar_mode != "conservative":
                    return min(open_, limit_price)
                return limit_price
            if order.side == OrderSide.SELL and high >= limit_price:
                if open_ >= limit_price and self.config.intrabar_mode != "conservative":
                    return max(open_, limit_price)
                return limit_price
            return None

        if order.order_type == OrderType.STOP:
            stop_price = order.stop_price
            if stop_price <= 0:
                return None
            if order.side == OrderSide.BUY and high >= stop_price:
                return self._apply_slippage(order.side, max(open_, stop_price), high=high, low=low)
            if order.side == OrderSide.SELL and low <= stop_price:
                return self._apply_slippage(order.side, min(open_, stop_price), high=high, low=low)
            return None

        if order.order_type == OrderType.STOP_LIMIT:
            stop_price = order.stop_price
            limit_price = order.limit_price
            if stop_price <= 0 or limit_price <= 0:
                return None
            triggered = (
                (order.side == OrderSide.BUY and high >= stop_price)
                or (order.side == OrderSide.SELL and low <= stop_price)
            )
            if not triggered:
                return None
            order.order_type = OrderType.LIMIT
            return self._match_order(order, open_, high, low, close)
        return None

    def _apply_slippage(
        self,
        side: OrderSide,
        price: float,
        *,
        high: Optional[float] = None,
        low: Optional[float] = None,
    ) -> float:
        slip = max(0.0, float(self.config.slippage or 0.0))
        if side == OrderSide.BUY:
            slipped = float(price) * (1 + slip)
        else:
            slipped = float(price) * (1 - slip)
        return _bound_price(slipped, high=high, low=low)

    def _resolve_quantity(self, order: Order, price: float) -> float:
        target_quantity = float(order.metadata.get("target_quantity") or 0.0)
        if target_quantity <= 0 and order.quantity > 0:
            target_quantity = order.quantity
        if target_quantity <= 0 and order.notional > 0 and price > 0:
            leverage = 1.0 if self.config.market_type == "spot" else max(1.0, self.config.leverage)
            stake = float(order.notional or 0.0)
            if self._is_entry_order(order):
                available_stake = self.available_entry_notional(price)
                if available_stake <= 0:
                    return 0.0
                initial_capital = max(0.0, float(self.config.initial_capital or 0.0))
                account_equity = max(0.0, float(self._account_value(price)))
                is_full_account_order = any(
                    reference > 0 and reference * 0.999 <= stake <= reference * 1.001
                    for reference in (initial_capital, account_equity)
                )
                if is_full_account_order or not bool(order.metadata.get("explicit_quote_amount")):
                    stake = min(stake, available_stake)
            target_quantity = stake * leverage / price
        if target_quantity <= 0:
            return 0.0
        order.metadata["target_quantity"] = target_quantity
        return max(0.0, target_quantity - float(order.filled_quantity or 0.0))

    def _volume_cap(self, order: Order, quantity: float, volume: float) -> float:
        participation = order.metadata.get("volume_participation")
        try:
            participation = float(participation)
        except Exception:
            participation = 0.0
        if participation <= 0 or volume <= 0:
            return quantity
        return min(quantity, max(0.0, volume * participation))

    def _execute(self, order: Order, quantity: float, price: float, timestamp: Any, bar_index: int) -> Execution:
        qty = max(0.0, float(quantity or 0.0))
        fill_price = max(0.0, float(price or 0.0))
        commission_rate = max(0.0, float(self.config.commission or 0.0))
        fee = qty * fill_price * commission_rate
        pnl = 0.0
        action = self._infer_action(order)
        position_side = order.position_side or ("long" if order.side == OrderSide.BUY else "short")
        is_close = action.startswith("close")
        holding_bars = self._holding_bars(position_side, bar_index) if is_close else 0
        source_position = self.long if position_side == "long" else self.short if position_side == "short" else None
        entry_time = source_position.opened_time if is_close and source_position is not None else None
        entry_bar = source_position.opened_bar if is_close and source_position is not None else -1
        entry_price = source_position.avg_price if is_close and source_position is not None else 0.0

        if position_side == "long":
            if order.side == OrderSide.BUY and not order.reduce_only:
                if self.config.market_type == "spot":
                    required_cash = qty * fill_price + fee
                    if required_cash > max(0.0, self.cash) + 1e-9:
                        return self._reject_order(order, timestamp, bar_index, action, position_side, "insufficient_cash")
                    self._increase_position(self.long, qty, fill_price, timestamp, bar_index)
                    self.cash -= (qty * fill_price) + fee
                else:
                    if not self._has_margin_for(qty, fill_price, fee):
                        return self._reject_order(order, timestamp, bar_index, action, position_side, "insufficient_margin")
                    self._increase_position(self.long, qty, fill_price, timestamp, bar_index)
                    self.cash -= fee
            else:
                closed, avg = self._reduce_position(self.long, qty)
                if closed <= 0:
                    return self._reject_order(order, timestamp, bar_index, action, position_side, "no_position")
                qty = closed
                fee = qty * fill_price * commission_rate
                if entry_price <= 0:
                    entry_price = avg
                pnl = (fill_price - avg) * closed if closed > 0 else 0.0
                if self.config.market_type == "spot":
                    self.cash += (fill_price * closed) - fee
                else:
                    self.cash += pnl - fee
        elif position_side == "short":
            if order.side == OrderSide.SELL and not order.reduce_only:
                if not self._has_margin_for(qty, fill_price, fee):
                    return self._reject_order(order, timestamp, bar_index, action, position_side, "insufficient_margin")
                self._increase_position(self.short, qty, fill_price, timestamp, bar_index)
                self.cash -= fee
            else:
                closed, avg = self._reduce_position(self.short, qty)
                if closed <= 0:
                    return self._reject_order(order, timestamp, bar_index, action, position_side, "no_position")
                qty = closed
                fee = qty * fill_price * commission_rate
                if entry_price <= 0:
                    entry_price = avg
                pnl = (avg - fill_price) * closed if closed > 0 else 0.0
                self.cash += pnl - fee
        else:
            return self._reject_order(order, timestamp, bar_index, action, position_side, "invalid_position_side")

        self.total_commission += fee
        order.filled_quantity += qty
        if order.filled_quantity > 0:
            old_qty = order.filled_quantity - qty
            if old_qty > 0 and order.avg_fill_price > 0:
                order.avg_fill_price = ((order.avg_fill_price * old_qty) + (fill_price * qty)) / order.filled_quantity
            else:
                order.avg_fill_price = fill_price
        order.fee += fee
        target_quantity = float(order.metadata.get("target_quantity") or order.filled_quantity or 0.0)
        source_is_closed = (
            is_close
            and (
                (position_side == "long" and not self.long.is_open())
                or (position_side == "short" and not self.short.is_open())
            )
        )
        if source_is_closed or order.filled_quantity >= target_quantity - 1e-12:
            order.status = OrderStatus.FILLED
            self._deactivate_order(order)
        else:
            order.status = OrderStatus.PARTIAL

        execution = Execution(
            order_id=order.id,
            time=timestamp,
            bar_index=int(bar_index),
            side=order.side.value,
            position_side=position_side,
            quantity=qty,
            price=fill_price,
            fee=fee,
            pnl=pnl,
            balance=self.cash,
            reason=order.reason,
            action=action,
        )
        self.executions.append(execution)
        realized_profit = round(pnl - (fee if pnl != 0 else 0.0), 2) if is_close else 0
        self.trades.append({
            "time": _format_time(timestamp),
            "bar_time": _format_time(timestamp),
            "type": action,
            "price": round(fill_price, 8),
            "amount": round(qty, 8),
            "profit": realized_profit,
            "balance": round(max(0.0, self.cash), 2),
            "commission": round(fee, 8),
            "order_id": order.id,
            "order_type": order.order_type.value,
            "order_status": order.status.value,
            "side": order.side.value,
            "position_side": position_side,
            "reason": order.reason,
            "close_reason": order.reason if is_close else "",
            "holding_bars": holding_bars,
        })
        if is_close and qty > 0:
            self.closed_trades.append({
                "id": len(self.closed_trades) + 1,
                "tradeNo": len(self.closed_trades) + 1,
                "type": action,
                "side": position_side,
                "position_side": position_side,
                "entry_time": _format_time(entry_time),
                "exit_time": _format_time(timestamp),
                "entry_price": round(float(entry_price or 0.0), 8),
                "exit_price": round(fill_price, 8),
                "quantity": round(qty, 8),
                "amount": round(qty, 8),
                "profit": realized_profit,
                "pnl": realized_profit,
                "balance": round(max(0.0, self.cash), 2),
                "commission": round(fee, 8),
                "order_id": order.id,
                "order_type": order.order_type.value,
                "reason": order.reason,
                "close_reason": order.reason,
                "holding_bars": holding_bars,
                "entry_bar": int(entry_bar or -1),
                "exit_bar": int(bar_index),
            })
        return execution

    def _has_margin_for(self, quantity: float, price: float, fee: float) -> bool:
        if self.config.market_type == "spot":
            return True
        leverage = max(1.0, float(self.config.leverage or 1.0))
        required_margin = max(0.0, float(quantity or 0.0)) * max(0.0, float(price or 0.0)) / leverage
        required_cash = required_margin + max(0.0, float(fee or 0.0))
        return required_cash <= self._available_margin(price) + 1e-9

    def _reject_order(
        self,
        order: Order,
        timestamp: Any,
        bar_index: int,
        action: str,
        position_side: str,
        reason: str,
    ) -> Execution:
        order.status = OrderStatus.REJECTED
        order.metadata["reject_reason"] = reason
        self._deactivate_order(order)
        return self._rejected_execution(order, timestamp, bar_index, action, position_side)

    def _rejected_execution(
        self,
        order: Order,
        timestamp: Any,
        bar_index: int,
        action: str,
        position_side: str,
    ) -> Execution:
        execution = Execution(
            order_id=order.id,
            time=timestamp,
            bar_index=int(bar_index),
            side=order.side.value,
            position_side=position_side,
            quantity=0.0,
            price=0.0,
            fee=0.0,
            pnl=0.0,
            balance=self.cash,
            reason=order.reason,
            action=action,
        )
        self.executions.append(execution)
        return execution

    def _deactivate_order(self, order: Order) -> None:
        if order in self._active_orders:
            self._active_orders.remove(order)

    def _infer_action(self, order: Order) -> str:
        if order.position_side == "long":
            return "close_long" if order.reduce_only or order.side == OrderSide.SELL else "open_long"
        if order.position_side == "short":
            return "close_short" if order.reduce_only or order.side == OrderSide.BUY else "open_short"
        return "buy" if order.side == OrderSide.BUY else "sell"

    def _is_entry_order(self, order: Order) -> bool:
        if order.reduce_only:
            return False
        if order.position_side == "long":
            return order.side == OrderSide.BUY
        if order.position_side == "short":
            return order.side == OrderSide.SELL
        return False

    def _increase_position(self, pos: Position, qty: float, price: float, timestamp: Any, bar_index: int) -> None:
        if qty <= 0:
            return
        old = pos.size
        if old > 0 and pos.avg_price > 0:
            pos.avg_price = ((pos.avg_price * old) + (price * qty)) / (old + qty)
        else:
            pos.avg_price = price
            pos.opened_bar = int(bar_index)
            pos.opened_time = timestamp
            pos.highest = price
            pos.lowest = price
        pos.size = old + qty

    def _reduce_position(self, pos: Position, qty: float) -> tuple[float, float]:
        if qty <= 0 or not pos.is_open():
            return 0.0, 0.0
        closed = min(qty, pos.size)
        avg = pos.avg_price
        pos.size -= closed
        if pos.size <= 1e-12:
            pos.reset()
        return closed, avg

    def _holding_bars(self, side: str, bar_index: int) -> int:
        pos = self.long if side == "long" else self.short
        if pos.opened_bar < 0:
            return 0
        return max(0, int(bar_index) - int(pos.opened_bar))


def _price(value: Any, default: Any = 0.0) -> float:
    try:
        out = float(value)
        if out == out:
            return out
    except Exception:
        pass
    try:
        return float(default or 0.0)
    except Exception:
        return 0.0


def _bound_price(price: float, *, high: Optional[float], low: Optional[float]) -> float:
    out = float(price or 0.0)
    hi = _price(high, 0.0) if high is not None else 0.0
    lo = _price(low, 0.0) if low is not None else 0.0
    if hi > 0:
        out = min(out, hi)
    if lo > 0:
        out = max(out, lo)
    return out


def _format_time(value: Any) -> str:
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value or "")
