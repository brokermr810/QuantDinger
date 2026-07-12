from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from .broker import BrokerSimulator
from .models import BacktestConfig


class SignalStrategyAdapter:
    """Adapter for QuantDinger ScriptStrategy signal dictionaries.

    The adapter converts QuantDinger's canonical signal contract into explicit
    broker orders. Strategy code emits intent only; execution semantics live in
    the broker simulator.
    """

    def __init__(self, df: pd.DataFrame, signals: Dict[str, Any], config: BacktestConfig):
        self.df = df
        self.config = config
        self.signals = self._normalize_signals(signals)
        self.arrays = self._build_arrays()

    def before_orders(self, broker: BrokerSimulator, bar_index: int, timestamp: Any, row: pd.Series) -> None:
        self._run_risk_controls(broker, bar_index, timestamp, row)

    def submit_bar_orders(self, broker: BrokerSimulator, bar_index: int, timestamp: Any, row: pd.Series) -> None:
        close = _price(row.get("close"), row.get("open"))
        open_ = _price(row.get("open"), close)
        default_price = open_ if self.config.strict_bar_fill else close
        direction = self.config.trade_direction

        if self.arrays["close_long"][bar_index] and broker.long.is_open():
            broker.submit(
                side="sell",
                order_type="market",
                position_side="long",
                reduce_only=True,
                quantity=broker.long.size,
                reason="signal_close",
                metadata={"fill_on_close": not self.config.strict_bar_fill},
            )
        if self.arrays["close_short"][bar_index] and broker.short.is_open():
            broker.submit(
                side="buy",
                order_type="market",
                position_side="short",
                reduce_only=True,
                quantity=broker.short.size,
                reason="signal_close",
                metadata={"fill_on_close": not self.config.strict_bar_fill},
            )

        if self.arrays["reduce_long"][bar_index] and not self.arrays["close_long"][bar_index] and broker.long.is_open():
            qty = self._reduce_size_for("reduce_long", bar_index, default_price, broker.long.size)
            if qty > 0:
                broker.submit(
                    side="sell",
                    order_type=self._order_type_for("reduce_long", bar_index),
                    position_side="long",
                    reduce_only=True,
                    quantity=qty,
                    limit_price=self._limit_price_for("reduce_long", bar_index),
                    stop_price=self._stop_price_for("reduce_long", bar_index),
                    reason="reduce_position",
                    metadata={"fill_on_close": not self.config.strict_bar_fill},
                )

        if self.arrays["reduce_short"][bar_index] and not self.arrays["close_short"][bar_index] and broker.short.is_open():
            qty = self._reduce_size_for("reduce_short", bar_index, default_price, broker.short.size)
            if qty > 0:
                broker.submit(
                    side="buy",
                    order_type=self._order_type_for("reduce_short", bar_index),
                    position_side="short",
                    reduce_only=True,
                    quantity=qty,
                    limit_price=self._limit_price_for("reduce_short", bar_index),
                    stop_price=self._stop_price_for("reduce_short", bar_index),
                    reason="reduce_position",
                    metadata={"fill_on_close": not self.config.strict_bar_fill},
                )

        if self.arrays["open_long"][bar_index] and direction in ("long", "both"):
            if direction == "both" and broker.short.is_open():
                broker.submit(
                    side="buy",
                    order_type="market",
                    position_side="short",
                    reduce_only=True,
                    quantity=broker.short.size,
                    reason="reverse",
                    metadata={"fill_on_close": not self.config.strict_bar_fill},
                )
            qty, notional, explicit_quote = self._size_for("open_long", bar_index, default_price, broker)
            broker.submit(
                side="buy",
                order_type=self._order_type_for("open_long", bar_index),
                position_side="long",
                quantity=qty,
                notional=notional,
                limit_price=self._limit_price_for("open_long", bar_index),
                stop_price=self._stop_price_for("open_long", bar_index),
                reason="open_long",
                metadata={"fill_on_close": not self.config.strict_bar_fill, "explicit_quote_amount": explicit_quote},
            )

        if self.arrays["open_short"][bar_index] and direction in ("short", "both"):
            if direction == "both" and broker.long.is_open():
                broker.submit(
                    side="sell",
                    order_type="market",
                    position_side="long",
                    reduce_only=True,
                    quantity=broker.long.size,
                    reason="reverse",
                    metadata={"fill_on_close": not self.config.strict_bar_fill},
                )
            qty, notional, explicit_quote = self._size_for("open_short", bar_index, default_price, broker)
            broker.submit(
                side="sell",
                order_type=self._order_type_for("open_short", bar_index),
                position_side="short",
                quantity=qty,
                notional=notional,
                limit_price=self._limit_price_for("open_short", bar_index),
                stop_price=self._stop_price_for("open_short", bar_index),
                reason="open_short",
                metadata={"fill_on_close": not self.config.strict_bar_fill, "explicit_quote_amount": explicit_quote},
            )

        if self.arrays["add_long"][bar_index] and direction in ("long", "both"):
            qty, notional, explicit_quote = self._size_for("add_long", bar_index, default_price, broker)
            broker.submit(
                side="buy",
                order_type=self._order_type_for("add_long", bar_index),
                position_side="long",
                quantity=qty,
                notional=notional,
                limit_price=self._limit_price_for("add_long", bar_index),
                stop_price=self._stop_price_for("add_long", bar_index),
                reason="add_position",
                metadata={"fill_on_close": not self.config.strict_bar_fill, "explicit_quote_amount": explicit_quote},
            )

        if self.arrays["add_short"][bar_index] and direction in ("short", "both"):
            qty, notional, explicit_quote = self._size_for("add_short", bar_index, default_price, broker)
            broker.submit(
                side="sell",
                order_type=self._order_type_for("add_short", bar_index),
                position_side="short",
                quantity=qty,
                notional=notional,
                limit_price=self._limit_price_for("add_short", bar_index),
                stop_price=self._stop_price_for("add_short", bar_index),
                reason="add_position",
                metadata={"fill_on_close": not self.config.strict_bar_fill, "explicit_quote_amount": explicit_quote},
            )

    def _normalize_signals(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(signals, dict):
            raise ValueError("signals must be a dict")
        if not all(k in signals for k in ("open_long", "close_long", "open_short", "close_short")):
            raise ValueError(
                "signals dict must contain canonical signal keys: "
                "open_long, close_long, open_short, close_short."
            )
        out = {
            "open_long": signals.get("open_long"),
            "close_long": signals.get("close_long"),
            "open_short": signals.get("open_short"),
            "close_short": signals.get("close_short"),
            "add_long": signals.get("add_long"),
            "add_short": signals.get("add_short"),
            "reduce_long": signals.get("reduce_long"),
            "reduce_short": signals.get("reduce_short"),
        }

        for key in ("open_long", "close_long", "open_short", "close_short", "add_long", "add_short", "reduce_long", "reduce_short"):
            out[key] = self._series(out.get(key), False).fillna(False).astype(bool)
        for key in (
            "open_long_quote_amount",
            "open_short_quote_amount",
            "add_long_quote_amount",
            "add_short_quote_amount",
            "reduce_long_quote_amount",
            "reduce_short_quote_amount",
            "open_long_base_qty",
            "open_short_base_qty",
            "add_long_base_qty",
            "add_short_base_qty",
            "reduce_long_base_qty",
            "reduce_short_base_qty",
            "reduce_long_pct",
            "reduce_short_pct",
            "open_long_price",
            "open_short_price",
            "add_long_price",
            "add_short_price",
            "reduce_long_price",
            "reduce_short_price",
            "open_long_stop_price",
            "open_short_stop_price",
            "add_long_stop_price",
            "add_short_stop_price",
            "reduce_long_stop_price",
            "reduce_short_stop_price",
        ):
            out[key] = self._series(signals.get(key), 0.0).fillna(0.0).astype(float)
        return out

    def _build_arrays(self) -> Dict[str, np.ndarray]:
        out: Dict[str, np.ndarray] = {}
        shift = self.config.strict_bar_fill
        for key, value in self.signals.items():
            arr = value.to_numpy()
            if shift:
                fill = False if arr.dtype == bool else 0.0
                arr = np.insert(arr[:-1], 0, fill)
            out[key] = arr
        if self.config.trade_direction == "long":
            out["open_short"] = np.zeros(len(self.df), dtype=bool)
            out["close_short"] = np.zeros(len(self.df), dtype=bool)
            out["add_short"] = np.zeros(len(self.df), dtype=bool)
            out["reduce_short"] = np.zeros(len(self.df), dtype=bool)
        elif self.config.trade_direction == "short":
            out["open_long"] = np.zeros(len(self.df), dtype=bool)
            out["close_long"] = np.zeros(len(self.df), dtype=bool)
            out["add_long"] = np.zeros(len(self.df), dtype=bool)
            out["reduce_long"] = np.zeros(len(self.df), dtype=bool)
        return out

    def _series(self, value: Any, default: Any) -> pd.Series:
        if hasattr(value, "reindex"):
            return value.reindex(self.df.index, fill_value=default)
        return pd.Series(default, index=self.df.index)

    def _size_for(self, prefix: str, bar_index: int, price: float, broker: BrokerSimulator) -> tuple[float, float, bool]:
        base = _arr_float(self.arrays.get(f"{prefix}_base_qty"), bar_index)
        quote = _arr_float(self.arrays.get(f"{prefix}_quote_amount"), bar_index)
        if base > 0:
            return base, 0.0, False
        if quote > 0:
            return 0.0, quote, True
        notional = broker.available_entry_notional(price) * self.config.entry_pct
        return 0.0, notional, False

    def _reduce_size_for(self, prefix: str, bar_index: int, price: float, position_size: float) -> float:
        pos = max(0.0, float(position_size or 0.0))
        if pos <= 0:
            return 0.0
        base = _arr_float(self.arrays.get(f"{prefix}_base_qty"), bar_index)
        if base > 0:
            return min(pos, base)
        quote = _arr_float(self.arrays.get(f"{prefix}_quote_amount"), bar_index)
        if quote > 0 and price > 0:
            leverage = 1.0 if self.config.market_type == "spot" else max(1.0, self.config.leverage)
            return min(pos, quote * leverage / float(price))
        pct = _arr_float(self.arrays.get(f"{prefix}_pct"), bar_index)
        if pct <= 0:
            pct = 0.5
        if pct > 1:
            pct = pct / 100.0
        return min(pos, pos * max(0.0, min(1.0, pct)))

    def _order_type_for(self, prefix: str, bar_index: int) -> str:
        limit_price = self._limit_price_for(prefix, bar_index)
        stop_price = self._stop_price_for(prefix, bar_index)
        if limit_price > 0 and stop_price > 0:
            return "stop_limit"
        if limit_price > 0:
            return "limit"
        if stop_price > 0:
            return "stop"
        return "market"

    def _limit_price_for(self, prefix: str, bar_index: int) -> float:
        return _arr_float(self.arrays.get(f"{prefix}_price"), bar_index)

    def _stop_price_for(self, prefix: str, bar_index: int) -> float:
        return _arr_float(self.arrays.get(f"{prefix}_stop_price"), bar_index)

    def _run_risk_controls(self, broker: BrokerSimulator, bar_index: int, timestamp: Any, row: pd.Series) -> None:
        open_ = _price(row.get("open"), row.get("close"))
        high = _price(row.get("high"), row.get("close"))
        low = _price(row.get("low"), row.get("close"))
        if broker.long.is_open():
            if self._max_holding_reached(broker.long.opened_bar, bar_index):
                broker.execute_immediate(
                    side="sell",
                    position_side="long",
                    quantity=broker.long.size,
                    price=open_ * (1 - self.config.slippage),
                    reason="max_holding_bars",
                    timestamp=timestamp,
                    bar_index=bar_index,
                    reduce_only=True,
                    high=high,
                    low=low,
                )
            if broker.long.is_open():
                broker.long.mark_extremes(high, low)
                trigger = self._long_exit_trigger(broker, open_, high, low)
                if trigger:
                    reason, price = trigger
                    broker.execute_immediate(
                        side="sell",
                        position_side="long",
                        quantity=broker.long.size,
                        price=price * (1 - self.config.slippage),
                        reason=reason,
                        timestamp=timestamp,
                        bar_index=bar_index,
                        reduce_only=True,
                        high=high,
                        low=low,
                    )
        if broker.short.is_open():
            if self._max_holding_reached(broker.short.opened_bar, bar_index):
                broker.execute_immediate(
                    side="buy",
                    position_side="short",
                    quantity=broker.short.size,
                    price=open_ * (1 + self.config.slippage),
                    reason="max_holding_bars",
                    timestamp=timestamp,
                    bar_index=bar_index,
                    reduce_only=True,
                    high=high,
                    low=low,
                )
            if broker.short.is_open():
                broker.short.mark_extremes(high, low)
                trigger = self._short_exit_trigger(broker, open_, high, low)
                if trigger:
                    reason, price = trigger
                    broker.execute_immediate(
                        side="buy",
                        position_side="short",
                        quantity=broker.short.size,
                        price=price * (1 + self.config.slippage),
                        reason=reason,
                        timestamp=timestamp,
                        bar_index=bar_index,
                        reduce_only=True,
                        high=high,
                        low=low,
                    )

    def _max_holding_reached(self, opened_bar: int, bar_index: int) -> bool:
        max_bars = int(self.config.max_holding_bars or 0)
        return max_bars > 0 and opened_bar >= 0 and (bar_index - opened_bar) >= max_bars

    def _long_exit_trigger(self, broker: BrokerSimulator, open_: float, high: float, low: float) -> tuple[str, float] | None:
        entry = broker.long.avg_price
        candidates = []
        if self.config.stop_loss_pct > 0:
            price = entry * (1 - self.config.stop_loss_pct)
            if low <= price:
                candidates.append({"reason": "stop_loss", "price": price, "kind": "loss"})
        if self.config.trailing_enabled and self.config.trailing_pct > 0:
            active = True
            if self.config.trailing_activation_pct > 0:
                active = broker.long.highest >= entry * (1 + self.config.trailing_activation_pct)
            price = broker.long.highest * (1 - self.config.trailing_pct)
            if active and low <= price:
                kind = "profit" if price > entry else "loss"
                candidates.append({"reason": "trailing_stop", "price": price, "kind": kind})
        elif self.config.take_profit_pct > 0:
            price = entry * (1 + self.config.take_profit_pct)
            if high >= price:
                candidates.append({"reason": "take_profit", "price": price, "kind": "profit"})
        if not candidates:
            return None
        chosen = self._choose_intrabar_exit(candidates, open_)
        return chosen["reason"], chosen["price"]

    def _short_exit_trigger(self, broker: BrokerSimulator, open_: float, high: float, low: float) -> tuple[str, float] | None:
        entry = broker.short.avg_price
        candidates = []
        if self.config.stop_loss_pct > 0:
            price = entry * (1 + self.config.stop_loss_pct)
            if high >= price:
                candidates.append({"reason": "stop_loss", "price": price, "kind": "loss"})
        if self.config.trailing_enabled and self.config.trailing_pct > 0:
            active = True
            if self.config.trailing_activation_pct > 0:
                active = broker.short.lowest <= entry * (1 - self.config.trailing_activation_pct)
            price = broker.short.lowest * (1 + self.config.trailing_pct)
            if active and high >= price:
                kind = "profit" if price < entry else "loss"
                candidates.append({"reason": "trailing_stop", "price": price, "kind": kind})
        elif self.config.take_profit_pct > 0:
            price = entry * (1 - self.config.take_profit_pct)
            if low <= price:
                candidates.append({"reason": "take_profit", "price": price, "kind": "profit"})
        if not candidates:
            return None
        chosen = self._choose_intrabar_exit(candidates, open_)
        return chosen["reason"], chosen["price"]

    def _choose_intrabar_exit(self, candidates: list[dict], open_: float) -> dict:
        if len(candidates) == 1:
            return candidates[0]
        mode = self.config.intrabar_mode
        if mode == "aggressive":
            return sorted(candidates, key=lambda item: 0 if item.get("kind") == "profit" else 1)[0]
        if mode == "balanced":
            return sorted(candidates, key=lambda item: abs(float(item.get("price") or 0.0) - float(open_ or 0.0)))[0]
        return sorted(candidates, key=lambda item: 0 if item.get("kind") == "loss" else 1)[0]


def _arr_float(arr: Any, idx: int) -> float:
    try:
        value = arr[idx]
        out = float(value or 0.0)
        return out if np.isfinite(out) else 0.0
    except Exception:
        return 0.0


def _price(value: Any, default: Any = 0.0) -> float:
    try:
        out = float(value)
        if np.isfinite(out):
            return out
    except Exception:
        pass
    try:
        return float(default or 0.0)
    except Exception:
        return 0.0
