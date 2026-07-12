"""Python ScriptStrategy runtime shared by backtests and live execution."""
from __future__ import annotations

# ScriptStrategy production contract:
# - implement on_init(ctx) and on_bar(ctx, bar)
# - declare strategy/risk parameters with ctx.param(...)
# - emit explicit intents: open_long/add_long/reduce_long/close_long/open_short/add_short/reduce_short/close_short
# - multi-entry scripts must call add_long/add_short after the first open intent

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.strategy_runtime.signals import StrategySignal
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(int(minimum), int(value))


class ScriptBar(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class ScriptPosition(dict):
    """Hedge-aware position container exposed to bot scripts as ``ctx.position``.

    Stores ``long_*`` and ``short_*`` legs independently so neutral grid bots
    can hold long and short exposure at the same time (mirrors Binance
    Futures hedge mode). The legacy ``side / size / entry_price / direction``
    keys are kept in sync as the *net* view so existing scripts that do
    ``if ctx.position > 0`` or ``if ctx.position == 0`` keep working unchanged.

    Numeric/bool dunders return the **net** direction (long_size - short_size),
    so ``ctx.position > 0`` means "net long", ``ctx.position == 0`` means flat
    on both legs.
    """

    def __init__(self):
        super().__init__()
        self.clear_position()

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __bool__(self) -> bool:
        return self._long_size() > 0 or self._short_size() > 0

    def __int__(self) -> int:
        net = self._long_size() - self._short_size()
        if net > 1e-12:
            return 1
        if net < -1e-12:
            return -1
        return 0

    def __float__(self) -> float:
        return float(int(self))

    def __eq__(self, other: Any) -> bool:
        try:
            return int(self) == int(other)
        except Exception:
            return dict.__eq__(self, other)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return id(self)

    def __lt__(self, other: Any) -> bool:
        return int(self) < int(other)

    def __le__(self, other: Any) -> bool:
        return int(self) <= int(other)

    def __gt__(self, other: Any) -> bool:
        return int(self) > int(other)

    def __ge__(self, other: Any) -> bool:
        return int(self) >= int(other)

    # ------------------------------------------------------------------ helpers

    def _long_size(self) -> float:
        try:
            return max(0.0, float(self.get('long_size') or 0.0))
        except Exception:
            return 0.0

    def _short_size(self) -> float:
        try:
            return max(0.0, float(self.get('short_size') or 0.0))
        except Exception:
            return 0.0

    def _long_entry(self) -> float:
        try:
            return max(0.0, float(self.get('long_entry') or 0.0))
        except Exception:
            return 0.0

    def _short_entry(self) -> float:
        try:
            return max(0.0, float(self.get('short_entry') or 0.0))
        except Exception:
            return 0.0

    def _refresh_legacy_view(self) -> None:
        """Recompute the deprecated single-leg fields from the hedge state."""
        long_size = self._long_size()
        short_size = self._short_size()
        long_entry = self._long_entry()
        short_entry = self._short_entry()
        net = long_size - short_size
        if net > 1e-12:
            side = 'long'
            size = long_size
            entry = long_entry
            direction = 1
        elif net < -1e-12:
            side = 'short'
            size = short_size
            entry = short_entry
            direction = -1
        else:
            side = ''
            size = 0.0
            entry = 0.0
            direction = 0
        self['side'] = side
        self['size'] = size
        self['entry_price'] = entry
        self['direction'] = direction
        self['amount'] = size
        self['long_size'] = long_size
        self['short_size'] = short_size
        self['long_entry'] = long_entry
        self['short_entry'] = short_entry

    # ------------------------------------------------------------------ hedge API

    @property
    def long_size(self) -> float:
        return self._long_size()

    @property
    def short_size(self) -> float:
        return self._short_size()

    @property
    def long_entry(self) -> float:
        return self._long_entry()

    @property
    def short_entry(self) -> float:
        return self._short_entry()

    def has_long(self) -> bool:
        return self._long_size() > 1e-12

    def has_short(self) -> bool:
        return self._short_size() > 1e-12

    def is_flat(self) -> bool:
        return not self.has_long() and not self.has_short()

    def is_long(self) -> bool:
        return self.has_long() and not self.has_short()

    def is_short(self) -> bool:
        return self.has_short() and not self.has_long()

    def open_long(self, entry_price: float, amount: float) -> None:
        amt = max(0.0, float(amount or 0.0))
        if amt <= 0:
            return
        self['long_size'] = self._long_size() + amt
        # Existing long leg keeps weighted-avg semantics with the new fill.
        old_size = self._long_size() - amt
        old_entry = self._long_entry()
        new_entry = float(entry_price or 0.0)
        if old_size > 0 and old_entry > 0 and new_entry > 0:
            blended = ((old_entry * old_size) + (new_entry * amt)) / (old_size + amt)
            self['long_entry'] = blended
        else:
            self['long_entry'] = new_entry
        self._refresh_legacy_view()

    def add_long(self, entry_price: float, amount: float) -> None:
        # Identical math to ``open_long``; separate name keeps callsites readable.
        self.open_long(entry_price, amount)

    def reduce_long(self, amount: float) -> tuple[float, float]:
        """Reduce the long leg by ``amount`` and return ``(closed_qty, avg_entry)``.

        Callers use the returned average entry price to compute matched-grid
        PnL against the fill price. Entry price of the remaining long leg is
        kept unchanged (FIFO-on-average semantics).
        """
        cur_size = self._long_size()
        if cur_size <= 0:
            return 0.0, 0.0
        reduce = max(0.0, float(amount or 0.0))
        if reduce <= 0:
            return 0.0, 0.0
        closed = min(reduce, cur_size)
        avg_entry = self._long_entry()
        remaining = cur_size - closed
        if remaining <= 1e-12:
            self['long_size'] = 0.0
            self['long_entry'] = 0.0
        else:
            self['long_size'] = remaining
        self._refresh_legacy_view()
        return closed, avg_entry

    def close_long(self) -> tuple[float, float]:
        return self.reduce_long(self._long_size())

    def open_short(self, entry_price: float, amount: float) -> None:
        amt = max(0.0, float(amount or 0.0))
        if amt <= 0:
            return
        self['short_size'] = self._short_size() + amt
        old_size = self._short_size() - amt
        old_entry = self._short_entry()
        new_entry = float(entry_price or 0.0)
        if old_size > 0 and old_entry > 0 and new_entry > 0:
            blended = ((old_entry * old_size) + (new_entry * amt)) / (old_size + amt)
            self['short_entry'] = blended
        else:
            self['short_entry'] = new_entry
        self._refresh_legacy_view()

    def add_short(self, entry_price: float, amount: float) -> None:
        self.open_short(entry_price, amount)

    def reduce_short(self, amount: float) -> tuple[float, float]:
        cur_size = self._short_size()
        if cur_size <= 0:
            return 0.0, 0.0
        reduce = max(0.0, float(amount or 0.0))
        if reduce <= 0:
            return 0.0, 0.0
        closed = min(reduce, cur_size)
        avg_entry = self._short_entry()
        remaining = cur_size - closed
        if remaining <= 1e-12:
            self['short_size'] = 0.0
            self['short_entry'] = 0.0
        else:
            self['short_size'] = remaining
        self._refresh_legacy_view()
        return closed, avg_entry

    def close_short(self) -> tuple[float, float]:
        return self.reduce_short(self._short_size())

    # ------------------------------------------------------------------ legacy API

    def clear_position(self) -> None:
        self.clear()
        self.update({
            'side': '',
            'size': 0.0,
            'entry_price': 0.0,
            'direction': 0,
            'amount': 0.0,
            'long_size': 0.0,
            'long_entry': 0.0,
            'short_size': 0.0,
            'short_entry': 0.0,
        })

    def open_position(self, side: str, entry_price: float, amount: float) -> None:
        """Legacy single-leg open. Routes to the matching hedge leg.

        Resets the *target* leg only; it does not touch the opposite leg, so a
        neutral-grid script can ``open_position('long', ...)`` while still
        holding a short leg from a previous bar.
        """
        s = (side or '').strip().lower()
        amt = max(0.0, float(amount or 0.0))
        if amt <= 0:
            return
        if s == 'long':
            self['long_size'] = amt
            self['long_entry'] = float(entry_price or 0.0)
        elif s == 'short':
            self['short_size'] = amt
            self['short_entry'] = float(entry_price or 0.0)
        self._refresh_legacy_view()

    def add_position(self, entry_price: float, amount: float) -> None:
        """Legacy add. Adds to the leg implied by the current net direction.

        When both legs are zero we cannot infer a direction, so this becomes a
        no-op (the script should call ``open_position`` or the new
        ``open_long``/``open_short`` explicitly).
        """
        direction = int(self)
        if direction > 0:
            self.add_long(entry_price, amount)
        elif direction < 0:
            self.add_short(entry_price, amount)

    def reduce_position(self, amount: float) -> None:
        """Legacy reduce. Reduces the leg matching the current net direction."""
        direction = int(self)
        if direction > 0:
            self.reduce_long(amount)
        elif direction < 0:
            self.reduce_short(amount)


class StrategyScriptContext:
    """Live script context with behavior aligned to ScriptBacktestContext."""

    def __init__(
        self,
        bars_df: Optional[pd.DataFrame] = None,
        initial_balance: float = 0.0,
        *,
        strategy_id: int = 0,
        strategy_run_id: int = 0,
        symbol: str = "",
    ):
        if bars_df is None:
            bars_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "time"])
        self._bars_df = bars_df
        self._params: Dict[str, Any] = {}
        self._orders: List[Dict[str, Any]] = []
        self._logs: List[str] = []
        self._max_bars_per_call = _env_int("STRATEGY_SCRIPT_MAX_BARS_PER_CALL", 1000, 1)
        self._max_logs_per_flush = _env_int("STRATEGY_SCRIPT_MAX_LOGS_PER_FLUSH", 50, 0)
        self._max_log_chars = _env_int("STRATEGY_SCRIPT_MAX_LOG_CHARS", 500, 1)
        self.current_index = -1
        self.current_dt = None
        self.is_warming_up = False
        self.is_ready = True
        self.startup_candle_count = 0
        self.warmup_bars_seen = 0
        self.position = ScriptPosition()
        self.positions: Dict[str, Dict[str, Any]] = {
            "long": {"side": "long", "size": 0.0, "entry_price": 0.0},
            "short": {"side": "short", "size": 0.0, "entry_price": 0.0},
        }
        self.balance = float(initial_balance)
        self.equity = float(initial_balance)
        self.initial_capital = float(initial_balance)
        self.available_cash = float(initial_balance)
        self.available_capital = float(initial_balance)
        self.available_margin = float(initial_balance)
        self.strategy_id = int(strategy_id or 0)
        self.strategy_run_id = int(strategy_run_id or 0)
        self.symbol = str(symbol or "")
        self._baskets: Dict[str, Any] = {}
        self.runtime: Dict[str, Any] = {}
        self.direction = "long"
        self.trade_direction = "long"
        self.market_type = "swap"
        self.leverage = 1.0
        self.investment_amount = float(initial_balance or 0.0)
        self.timeframe = "1m"
        self.tick_interval_sec = 10
        self.set_runtime_config({}, initial_balance=initial_balance)
        from app.services.ai_decision import UnavailableAIDecisionClient

        self.ai = UnavailableAIDecisionClient()
        self._bind_runtime_state()

    def _bind_runtime_state(self) -> None:
        try:
            from app.services.strategy_runtime.state import RuntimeStateProxy, RuntimeStateStore

            store = None
            if self.strategy_id > 0:
                store = RuntimeStateStore(
                    strategy_id=self.strategy_id,
                    strategy_run_id=self.strategy_run_id,
                    state_key="script",
                )
            self.state = RuntimeStateProxy(store=store)
        except Exception:
            # Keep scripts usable even if DB/runtime schema is unavailable.
            from app.services.strategy_runtime.state import RuntimeStateProxy

            self.state = RuntimeStateProxy()

    def bind_runtime(
        self,
        *,
        strategy_id: int = 0,
        strategy_run_id: int = 0,
        symbol: str = "",
        trading_config: Optional[Dict[str, Any]] = None,
        initial_balance: Optional[float] = None,
    ) -> None:
        self.strategy_id = int(strategy_id or 0)
        self.strategy_run_id = int(strategy_run_id or 0)
        if symbol:
            self.symbol = str(symbol or "")
        self._baskets = {}
        if trading_config is not None or initial_balance is not None:
            self.set_runtime_config(trading_config or {}, initial_balance=initial_balance)
        self._bind_runtime_state()

    def set_runtime_config(
        self,
        trading_config: Optional[Dict[str, Any]] = None,
        *,
        initial_balance: Optional[float] = None,
    ) -> None:
        tc = trading_config if isinstance(trading_config, dict) else {}

        def _float(value: Any, default: float) -> float:
            try:
                out = float(value)
                return out if np.isfinite(out) else default
            except Exception:
                return default

        direction = str(
            tc.get("trade_direction")
            or tc.get("tradeDirection")
            or tc.get("direction")
            or self.direction
            or "long"
        ).strip().lower()
        if direction not in ("long", "short", "both"):
            direction = "long"

        market_type = str(tc.get("market_type") or tc.get("marketType") or self.market_type or "swap").strip().lower()
        if market_type not in ("spot", "swap"):
            market_type = "swap"

        leverage = _float(tc.get("leverage", self.leverage), 1.0)
        if leverage < 1:
            leverage = 1.0

        fallback_amount = initial_balance if initial_balance is not None else self.balance
        investment_amount = _float(
            tc.get("investment_amount", tc.get("initial_capital", fallback_amount)),
            _float(fallback_amount, 0.0),
        )

        if market_type == "spot":
            leverage = 1.0
            if direction != "long":
                direction = "long"

        timeframe = str(tc.get("timeframe") or self.timeframe or "1m").strip() or "1m"
        tick_interval_sec = int(_float(tc.get("tick_interval_sec", self.tick_interval_sec), 10.0) or 10)
        if tick_interval_sec < 1:
            tick_interval_sec = 10

        self.direction = direction
        self.trade_direction = direction
        self.market_type = market_type
        self.leverage = leverage
        self.investment_amount = investment_amount
        self.initial_capital = investment_amount
        self.available_cash = float(self.balance)
        self.available_capital = investment_amount
        self.available_margin = investment_amount
        self.timeframe = timeframe
        self.tick_interval_sec = tick_interval_sec
        self.runtime = {
            "contract_version": str(tc.get("runtime_contract_version") or "simple_script_v1"),
            "symbol": str(tc.get("symbol") or self.symbol or ""),
            "direction": direction,
            "trade_direction": direction,
            "market_type": market_type,
            "leverage": leverage,
            "investment_amount": investment_amount,
            "available_cash": self.available_cash,
            "available_capital": self.available_capital,
            "available_margin": self.available_margin,
            "initial_capital": investment_amount,
            "timeframe": timeframe,
            "tick_interval_sec": tick_interval_sec,
            "execution_environment": str(tc.get("execution_environment") or "live"),
        }

    def param(self, name: str, default: Any = None) -> Any:
        if name not in self._params:
            self._params[name] = default
        return self._params[name]

    def bind_ai(self, client: Any) -> None:
        self.ai = client

    def ask_ai(self, prompt: str = "", **kwargs: Any):
        return self.ai.evaluate(prompt, **kwargs)

    def bars(self, n: int = 1):
        try:
            count = int(n)
        except Exception:
            count = 1
        if count < 1:
            count = 1
        if count > self._max_bars_per_call:
            count = self._max_bars_per_call
        start = max(0, self.current_index - count + 1)
        out = []
        for _, row in self._bars_df.iloc[start:self.current_index + 1].iterrows():
            out.append(ScriptBar(
                open=float(row.get('open') or 0),
                high=float(row.get('high') or 0),
                low=float(row.get('low') or 0),
                close=float(row.get('close') or 0),
                volume=float(row.get('volume') or 0),
                timestamp=row.get('time')
            ))
        return out

    def factor(self, factor_id: str, **params: Any) -> float:
        """Compute a CTA-compatible technical factor without future-bar access."""
        from app.services.factors import FactorError, get_factor, compute_factor

        definition = get_factor(factor_id)
        if "cta" not in definition.supported_contexts:
            raise FactorError("factor.contextNotSupported")
        end = min(max(self.current_index + 1, 0), len(self._bars_df))
        if end <= 0:
            raise FactorError("factor.noData")
        frame = self._bars_df.iloc[:end].copy()
        try:
            return compute_factor(factor_id, frame, params)
        except FactorError as exc:
            if exc.code in {"factor.insufficientHistory", "factor.noData"}:
                return float("nan")
            raise

    def log(self, message: Any):
        if self._max_logs_per_flush <= 0:
            return
        text = str(message)
        if len(text) > self._max_log_chars:
            text = text[:self._max_log_chars] + "... [truncated]"
        limit = self._max_logs_per_flush
        if len(self._logs) < max(0, limit - 1):
            self._logs.append(text)
        elif len(self._logs) == max(0, limit - 1):
            self._logs.append(f"ctx.log limit reached; further logs dropped (max={limit} per flush)")

    def flush_logs(self) -> List[str]:
        logs = self._logs.copy()
        self._logs = []
        return logs

    def flush_state(self) -> None:
        try:
            self.state.flush()
        except Exception:
            pass

    def pending_orders(self) -> List[Dict[str, Any]]:
        return [dict(order) for order in self._orders]

    def pending_signals(self) -> List[StrategySignal]:
        timestamp = self._current_signal_timestamp()
        out: List[StrategySignal] = []
        for order in self._orders:
            out.append(StrategySignal.from_script_order(
                order,
                timestamp=timestamp,
                strategy_id=self.strategy_id,
                strategy_run_id=self.strategy_run_id,
                symbol=self.symbol,
                market_type=self.market_type,
            ))
        return out

    def flush_orders(self) -> List[Dict[str, Any]]:
        out = self.pending_orders()
        self._orders.clear()
        return out

    def flush_signals(self) -> List[StrategySignal]:
        out = self.pending_signals()
        self._orders.clear()
        return out

    def _current_signal_timestamp(self) -> Any:
        try:
            if self.current_index >= 0 and self.current_index < len(self._bars_df):
                row = self._bars_df.iloc[self.current_index]
                return row.get("time") if hasattr(row, "get") else self.current_index
        except Exception:
            pass
        return self.current_index

    def _current_mark_price(self, fallback: Any = None) -> float:
        try:
            value = float(fallback)
            if np.isfinite(value) and value > 0:
                return value
        except Exception:
            pass
        try:
            if self.current_index >= 0 and self.current_index < len(self._bars_df):
                row = self._bars_df.iloc[self.current_index]
                for key in ("close", "open", "high", "low"):
                    value = float(row.get(key) or 0.0)
                    if np.isfinite(value) and value > 0:
                        return value
        except Exception:
            pass
        return 0.0

    def _normalize_side(self, side: Any) -> str:
        side_norm = str(side or "long").strip().lower()
        return "short" if side_norm == "short" else "long"

    def _side_size(self, side: str) -> float:
        try:
            return float(self.positions.get(side, {}).get("size") or 0.0)
        except Exception:
            return 0.0

    def _side_entry(self, side: str) -> float:
        try:
            return float(self.positions.get(side, {}).get("entry_price") or 0.0)
        except Exception:
            return 0.0

    def _append_quote_order(
        self,
        *,
        side: str,
        quote_amount: float,
        price: Any = None,
        reason: Optional[str] = None,
    ) -> None:
        quote = max(0.0, float(quote_amount or 0.0))
        if quote <= 0:
            return
        if side == "short":
            action = "sell"
            intent = "add_short" if self._side_size("short") > 0 else "open_short"
        else:
            action = "buy"
            intent = "add_long" if self._side_size("long") > 0 else "open_long"
        self._orders.append({
            "action": action,
            "price": price,
            "amount": None,
            "intent": intent,
            "reason": reason or f"script_order_value_{side}",
            "script_quote_amount": quote,
        })

    def _append_reduce_value_order(
        self,
        *,
        side: str,
        quote_amount: float,
        price: Any = None,
        reason: Optional[str] = None,
    ) -> None:
        quote = max(0.0, float(quote_amount or 0.0))
        mark = self._current_mark_price(price)
        if quote <= 0 or mark <= 0:
            return
        qty = min(self._side_size(side), quote / mark)
        if qty <= 0:
            return
        if side == "short":
            self.reduce_short(amount=qty, price=price, reason=reason or "script_order_value_short")
        else:
            self.reduce_long(amount=qty, price=price, reason=reason or "script_order_value_long")

    def basket(self, side: str = "long"):
        side_norm = "short" if str(side or "").strip().lower() == "short" else "long"
        if side_norm not in self._baskets:
            from app.services.strategy_runtime.basket import BasketRuntime
            from app.services.strategy_runtime.order_intents import OrderIntentService

            self._baskets[side_norm] = BasketRuntime(
                strategy_id=self.strategy_id,
                strategy_run_id=self.strategy_run_id,
                symbol=self.symbol,
                side=side_norm,
                order_intents=OrderIntentService(
                    strategy_id=self.strategy_id,
                    strategy_run_id=self.strategy_run_id,
                ),
                signal_sink=self._orders.append,
            )
        return self._baskets[side_norm]

    def configure_robot(self, robot_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        clean_type = str(robot_type or "").strip().lower()
        if clean_type not in {"grid", "dca", "martingale", "layered_martingale"}:
            raise ValueError("unsupported_robot_type")
        if not isinstance(config, dict):
            raise ValueError("robot_config_must_be_mapping")
        definition = {
            "robot_type": clean_type,
            "config": dict(config),
        }
        self.runtime["robot_definition"] = definition
        return definition

    def buy(self, price: Any = None, amount: Any = None, *, intent: str = 'open_long', reason: Optional[str] = None):
        self._orders.append({
            'action': 'buy',
            'price': price,
            'amount': amount,
            'intent': intent,
            'reason': reason,
        })

    def sell(self, price: Any = None, amount: Any = None, *, intent: str = 'open_short', reason: Optional[str] = None):
        self._orders.append({
            'action': 'sell',
            'price': price,
            'amount': amount,
            'intent': intent,
            'reason': reason,
        })

    def close_long(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'sell',
            'price': price,
            'amount': amount,
            'intent': 'close_long',
            'reason': reason or 'script_close_long',
        })

    def reduce_long(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'sell',
            'price': price,
            'amount': amount,
            'intent': 'reduce_long',
            'reason': reason or 'script_reduce_long',
        })

    def close_short(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'buy',
            'price': price,
            'amount': amount,
            'intent': 'close_short',
            'reason': reason or 'script_close_short',
        })

    def reduce_short(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'buy',
            'price': price,
            'amount': amount,
            'intent': 'reduce_short',
            'reason': reason or 'script_reduce_short',
        })

    def open_long(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'buy',
            'price': price,
            'amount': amount,
            'intent': 'open_long',
            'reason': reason,
        })

    def add_long(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'buy',
            'price': price,
            'amount': amount,
            'intent': 'add_long',
            'reason': reason or 'script_add_long',
        })

    def open_short(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'sell',
            'price': price,
            'amount': amount,
            'intent': 'open_short',
            'reason': reason,
        })

    def add_short(self, amount: Any = None, price: Any = None, reason: Optional[str] = None):
        self._orders.append({
            'action': 'sell',
            'price': price,
            'amount': amount,
            'intent': 'add_short',
            'reason': reason or 'script_add_short',
        })

    def order_value(self, value: Any, side: str = "long", price: Any = None, reason: Optional[str] = None):
        side_norm = self._normalize_side(side)
        try:
            quote_value = float(value or 0.0)
        except Exception:
            return
        if not np.isfinite(quote_value) or abs(quote_value) <= 1e-12:
            return
        if quote_value > 0:
            self._append_quote_order(
                side=side_norm,
                quote_amount=quote_value,
                price=price,
                reason=reason or "script_order_value",
            )
        else:
            self._append_reduce_value_order(
                side=side_norm,
                quote_amount=abs(quote_value),
                price=price,
                reason=reason or "script_order_value_reduce",
            )

    def order_target(self, target_value: Any, side: str = "long", price: Any = None, reason: Optional[str] = None):
        side_norm = self._normalize_side(side)
        try:
            target = max(0.0, float(target_value or 0.0))
        except Exception:
            return
        if not np.isfinite(target):
            return
        current_size = self._side_size(side_norm)
        mark = self._current_mark_price(price)
        if target <= 1e-12:
            if side_norm == "short":
                self.close_short(reason=reason or "script_order_target_close")
            else:
                self.close_long(reason=reason or "script_order_target_close")
            return
        if mark <= 0:
            return
        current_value = current_size * mark
        delta = target - current_value
        if abs(delta) <= max(1e-8, mark * 1e-12):
            return
        self.order_value(delta, side=side_norm, price=price, reason=reason or "script_order_target")

    def close_position(self):
        self._orders.append({'action': 'sell', 'intent': 'close_long'})
        self._orders.append({'action': 'buy', 'intent': 'close_short'})


def compile_strategy_script_handlers(code: str) -> Tuple[Optional[Callable], Optional[Callable]]:
    """Validate and compile a ScriptStrategy, returning ``(on_init, on_bar)``.

    ``on_bar`` is required; ``on_init`` is optional.
    """
    if not code or not str(code).strip():
        raise ValueError("Strategy script is empty")

    from app.utils.safe_exec import build_safe_builtins, safe_exec_with_validation

    exec_env = {
        '__builtins__': build_safe_builtins(),
        'np': np,
        'pd': pd,
    }

    exec_result = safe_exec_with_validation(
        code=code,
        exec_globals=exec_env,
        exec_locals=exec_env,
        timeout=60,
    )
    if not exec_result['success']:
        raise RuntimeError(f"Code execution failed: {exec_result.get('error')}")

    on_init = exec_env.get('on_init')
    on_bar = exec_env.get('on_bar')
    if not callable(on_bar):
        raise ValueError("Strategy script must define on_bar(ctx, bar)")
    if on_init is not None and not callable(on_init):
        on_init = None
    return (on_init if callable(on_init) else None), on_bar
