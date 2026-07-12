from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from app.services.strategy_script_runtime import (
    ScriptBar,
    ScriptPosition,
    StrategyScriptContext,
    compile_strategy_script_handlers,
)

from .analyzers import PerformanceAnalyzer
from .broker import BrokerSimulator
from .models import BacktestConfig, Order, OrderStatus
from .signals import SignalStrategyAdapter
from .serialization import serialize_orders


class ScriptStrategyBacktestRunner:
    """Event-driven runner for ctx ScriptStrategy code."""

    VERSION = "quantdinger-script-backtest-v3"

    def __init__(
        self,
        *,
        config: BacktestConfig,
        code: str,
        params: Optional[Dict[str, Any]] = None,
        runtime: Optional[Dict[str, Any]] = None,
    ):
        self.config = config
        self.code = str(code or "")
        self.params = dict(params or {})
        self.runtime = dict(runtime or {})
        self.broker = BrokerSimulator(config)
        self.script_logs: List[str] = []
        self._pending_orders: List[Dict[str, Any]] = []
        self._risk_adapter: Optional[SignalStrategyAdapter] = None

    def run(
        self,
        *,
        df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        if df is None or df.empty:
            raise ValueError("No candle data available in the backtest date range")
        if not all(col in df.columns for col in ("open", "high", "low", "close")):
            raise ValueError("Backtest data must include open/high/low/close columns")

        df_exec = self._prepare_script_frame(df)
        on_init, on_bar = compile_strategy_script_handlers(self.code)
        ctx = StrategyScriptContext(
            df_exec,
            self.config.initial_capital,
            strategy_id=int(self.runtime.get("strategy_id") or 0),
            strategy_run_id=int(self.runtime.get("strategy_run_id") or 0),
            symbol=str(self.runtime.get("symbol") or ""),
        )
        ctx.set_runtime_config(self._runtime_config(), initial_balance=self.config.initial_capital)
        from app.services.ai_decision import BacktestAIDecisionClient

        ctx.bind_ai(BacktestAIDecisionClient(ctx.runtime))
        ctx._params.update(self.params)
        if ctx.direction in ("long", "short", "both"):
            ctx._params.setdefault("direction", ctx.direction)
        if callable(on_init):
            on_init(ctx)

        trading_start = pd.Timestamp(self.runtime.get("trading_start") or start_date)
        startup_candle_count = max(0, int(self.runtime.get("startup_candle_count") or 0))
        warmup_bars_seen = 0
        for bar_index, (timestamp, row) in enumerate(df.iterrows()):
            is_warming_up = pd.Timestamp(timestamp) < trading_start
            ctx._bars_df = df_exec.iloc[:bar_index + 1]
            self._sync_context(ctx, bar_index, timestamp, row)
            ctx.is_warming_up = bool(is_warming_up)
            ctx.is_ready = not is_warming_up
            ctx.startup_candle_count = startup_candle_count
            ctx.warmup_bars_seen = warmup_bars_seen + (1 if is_warming_up else 0)
            ctx.runtime.update({
                "is_warming_up": ctx.is_warming_up,
                "is_ready": ctx.is_ready,
                "startup_candle_count": startup_candle_count,
                "warmup_bars_seen": ctx.warmup_bars_seen,
                "trading_start": trading_start,
            })
            if is_warming_up:
                warmup_bars_seen += 1
                continue

            self._submit_pending_orders(timestamp, bar_index)
            self.broker.process_bar(bar_index, timestamp, row)
            self._run_risk_controls(df, bar_index, timestamp, row)
            self.broker.check_liquidation(
                timestamp=timestamp,
                bar_index=bar_index,
                high=_price(row.get("high"), row.get("close")),
                low=_price(row.get("low"), row.get("close")),
            )
            self._refresh_latest_equity(timestamp, row)
            self._sync_context(ctx, bar_index, timestamp, row)
            ctx.is_warming_up = False
            ctx.is_ready = True
            ctx.warmup_bars_seen = warmup_bars_seen
            ctx.runtime.update({
                "is_warming_up": False,
                "is_ready": True,
                "warmup_bars_seen": warmup_bars_seen,
            })
            ctx._orders.clear()
            on_bar(ctx, self._script_bar(row, timestamp))
            orders = ctx.flush_orders()
            if self.config.strict_bar_fill:
                self._pending_orders.extend(orders)
            else:
                self._execute_same_bar_orders(orders, timestamp, bar_index, row)
                self._refresh_latest_equity(timestamp, row)
            self.script_logs.extend(ctx.flush_logs())

        if not df.empty:
            last_ts = df.index[-1]
            last_row = df.iloc[-1]
            last_close = _price(last_row.get("close"), last_row.get("open"))
            self.broker.close_all(
                price=last_close,
                timestamp=last_ts,
                bar_index=len(df) - 1,
                reason="end_of_backtest",
            )
            self._refresh_latest_equity(last_ts, last_row)

        equity_curve = [
            {k: v for k, v in item.items() if not str(k).startswith("_")}
            for item in self.broker.equity_curve
        ]
        closed_trades = list(self.broker.closed_trades)
        analyzer = PerformanceAnalyzer(
            initial_capital=self.config.initial_capital,
            timeframe=self.config.timeframe,
            start_date=start_date,
            end_date=end_date,
            total_commission=self.broker.total_commission,
        )
        metrics = analyzer.analyze(equity_curve, closed_trades)
        return {
            **metrics,
            "equityCurve": equity_curve,
            "trades": list(self.broker.trades),
            "closedTrades": closed_trades,
            "tradeRecords": closed_trades,
            "orders": serialize_orders(self.broker.orders),
            "logs": list(self.script_logs),
            "totalCommission": round(float(self.broker.total_commission or 0.0), 8),
            "total_commission": round(float(self.broker.total_commission or 0.0), 8),
            "totalFundingPaid": round(float(self.broker.total_funding or 0.0), 6),
            "engine": {
                "version": self.VERSION,
                "brokerVersion": "quantdinger-backtest-engine-v2",
                "intrabarMode": self.config.intrabar_mode,
                "signalTiming": self.config.signal_timing,
                "totalFundingPaid": round(float(self.broker.total_funding or 0.0), 6),
                "orderCount": len(self.broker.orders),
                "fillCount": len([order for order in self.broker.orders if order.status.value == "filled"]),
                "rejectedOrderCount": len([order for order in self.broker.orders if order.status.value == "rejected"]),
                "pendingOrderCount": len([
                    order for order in self.broker.orders
                    if order.status.value in ("accepted", "partial_filled")
                ]),
                "startupCandleCount": startup_candle_count,
                "warmupBarsProcessed": warmup_bars_seen,
                "tradingStart": str(trading_start),
                "aiDecisions": "skipped_in_backtest",
                "aiDecisionCalls": int(ctx.runtime.get("ai_decision_calls") or 0),
            },
        }

    def _prepare_script_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy().reset_index(drop=False)
        if "time" not in out.columns:
            out.rename(columns={out.columns[0]: "time"}, inplace=True)
        return out

    def _runtime_config(self) -> Dict[str, Any]:
        strategy_config = self.runtime.get("strategy_config")
        if not isinstance(strategy_config, dict):
            strategy_config = {}
        return {
            **strategy_config,
            "initial_capital": self.config.initial_capital,
            "investment_amount": self.config.initial_capital,
            "leverage": self.config.leverage,
            "trade_direction": self.config.trade_direction,
            "direction": self.config.trade_direction,
            "symbol": self.runtime.get("symbol") or strategy_config.get("symbol"),
            "market_type": self.config.market_type,
            "timeframe": self.config.timeframe,
            "execution_environment": "backtest",
        }

    def _sync_context(
        self,
        ctx: StrategyScriptContext,
        bar_index: int,
        timestamp: Any,
        row: pd.Series,
    ) -> None:
        close = _price(row.get("close"), row.get("open"))
        ctx.current_index = int(bar_index)
        ctx.current_dt = timestamp
        position = ScriptPosition()
        if self.broker.long.is_open():
            position.open_long(self.broker.long.avg_price, self.broker.long.size)
        if self.broker.short.is_open():
            position.open_short(self.broker.short.avg_price, self.broker.short.size)
        ctx.position = position
        ctx.positions = {
            "long": {
                "side": "long",
                "size": float(self.broker.long.size),
                "entry_price": float(self.broker.long.avg_price if self.broker.long.is_open() else 0.0),
            },
            "short": {
                "side": "short",
                "size": float(self.broker.short.size),
                "entry_price": float(self.broker.short.avg_price if self.broker.short.is_open() else 0.0),
            },
        }
        ctx.balance = float(self.broker.cash)
        ctx.equity = float(self.broker._account_value(close))
        ctx.initial_capital = float(self.config.initial_capital)
        ctx.available_cash = float(self.broker.cash)
        ctx.available_margin = float(self.broker._available_margin(close))
        ctx.available_capital = float(self.broker.available_entry_notional(close))
        ctx.runtime.update({
            "balance": ctx.balance,
            "equity": ctx.equity,
            "initial_capital": ctx.initial_capital,
            "available_cash": ctx.available_cash,
            "available_margin": ctx.available_margin,
            "available_capital": ctx.available_capital,
            "current_index": int(bar_index),
            "current_time": timestamp,
            "current_dt": timestamp,
            "positions": ctx.positions,
        })

    def _script_bar(self, row: pd.Series, timestamp: Any) -> ScriptBar:
        return ScriptBar(
            open=_price(row.get("open"), row.get("close")),
            high=_price(row.get("high"), row.get("close")),
            low=_price(row.get("low"), row.get("close")),
            close=_price(row.get("close"), row.get("open")),
            volume=_price(row.get("volume"), 0.0),
            timestamp=timestamp,
        )

    def _submit_pending_orders(self, timestamp: Any, bar_index: int) -> None:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        for item in orders:
            self._submit_order(item, timestamp=timestamp, bar_index=bar_index, fill_on_close=False)

    def _execute_same_bar_orders(
        self,
        orders: List[Dict[str, Any]],
        timestamp: Any,
        bar_index: int,
        row: pd.Series,
    ) -> None:
        for item in orders:
            order = self._submit_order(item, timestamp=timestamp, bar_index=bar_index, fill_on_close=True)
            if order is not None:
                self._try_execute_current_bar_order(order, timestamp, bar_index, row)

    def _try_execute_current_bar_order(
        self,
        order: Order,
        timestamp: Any,
        bar_index: int,
        row: pd.Series,
    ) -> None:
        if order.status not in (OrderStatus.ACCEPTED, OrderStatus.PARTIAL):
            return
        open_ = _price(row.get("open"), row.get("close"))
        high = _price(row.get("high"), open_)
        low = _price(row.get("low"), open_)
        close = _price(row.get("close"), open_)
        volume = _price(row.get("volume"), 0.0)
        fill_price = self.broker._match_order(order, open_, high, low, close)
        if fill_price is None:
            return
        qty = self.broker._resolve_quantity(order, fill_price)
        if qty <= 0:
            order.status = OrderStatus.REJECTED
            order.metadata.setdefault(
                "reject_reason",
                "insufficient_margin" if self.broker._is_entry_order(order) else "invalid_quantity",
            )
            self.broker._deactivate_order(order)
            return
        max_qty = self.broker._volume_cap(order, qty, volume)
        if max_qty <= 0:
            return
        self.broker._execute(order, max_qty, fill_price, timestamp, bar_index)

    def _submit_order(
        self,
        order: Dict[str, Any],
        *,
        timestamp: Any,
        bar_index: int,
        fill_on_close: bool,
    ) -> Optional[Order]:
        intent = str(order.get("intent") or "").strip().lower()
        if not intent:
            return None
        side, position_side, reduce_only = self._intent_to_order(intent, order)
        if not side or not position_side:
            return None
        if position_side == "long" and self.config.trade_direction == "short":
            return None
        if position_side == "short" and self.config.trade_direction == "long":
            return None

        order_type = str(order.get("execution_algo") or order.get("order_type") or "market").strip().lower()
        if order_type not in ("market", "limit", "stop", "stop_limit"):
            order_type = "market"
        limit_price = _positive_float(order.get("limit_price") or order.get("price"))
        stop_price = _positive_float(order.get("stop_price"))
        if order_type == "limit" and limit_price <= 0:
            order_type = "market"
        if order_type == "stop" and stop_price <= 0:
            order_type = "market"
        if order_type == "market":
            limit_price = 0.0
            stop_price = 0.0

        quantity, notional, explicit_quote = self._order_size(intent, order, position_side)
        if reduce_only and quantity <= 0:
            quantity = self.broker.long.size if position_side == "long" else self.broker.short.size

        self.broker._current_bar_index = int(bar_index)
        self.broker._current_time = timestamp
        return self.broker.submit(
            side=side,
            order_type=order_type,
            position_side=position_side,
            reduce_only=reduce_only,
            quantity=quantity,
            notional=notional,
            limit_price=limit_price,
            stop_price=stop_price,
            reason=str(order.get("reason") or intent),
            metadata={
                "fill_on_close": fill_on_close,
                "explicit_quote_amount": explicit_quote,
                "script_intent": intent,
            },
        )

    def _intent_to_order(self, intent: str, order: Dict[str, Any]) -> tuple[str, str, bool]:
        if intent in ("open_long", "add_long"):
            return "buy", "long", False
        if intent in ("close_long", "reduce_long"):
            return "sell", "long", True
        if intent in ("open_short", "add_short"):
            return "sell", "short", False
        if intent in ("close_short", "reduce_short"):
            return "buy", "short", True
        action = str(order.get("action") or "").strip().lower()
        if action == "buy":
            return "buy", "long", False
        if action == "sell":
            return "sell", "short", False
        return "", "", False

    def _order_size(self, intent: str, order: Dict[str, Any], position_side: str) -> tuple[float, float, bool]:
        base_qty = _positive_float(order.get("script_base_qty"))
        quote_amount = _positive_float(order.get("script_quote_amount"))
        raw_amount = _positive_float(order.get("amount"))
        if base_qty > 0:
            return base_qty, 0.0, False
        if quote_amount > 0:
            return 0.0, quote_amount, True
        if intent in ("reduce_long", "reduce_short") and raw_amount > 0:
            pos_size = self.broker.long.size if position_side == "long" else self.broker.short.size
            return min(pos_size, raw_amount), 0.0, False
        if raw_amount > 0:
            return raw_amount, 0.0, False
        if intent in ("open_long", "add_long", "open_short", "add_short"):
            mark = self.broker._last_price
            notional = self.broker.available_entry_notional(mark) * self.config.entry_pct
            return 0.0, notional, False
        return 0.0, 0.0, False

    def _run_risk_controls(self, df: pd.DataFrame, bar_index: int, timestamp: Any, row: pd.Series) -> None:
        if self._risk_adapter is None:
            self._risk_adapter = SignalStrategyAdapter(df, _blank_signals(df), self.config)
        self._risk_adapter._run_risk_controls(self.broker, bar_index, timestamp, row)

    def _refresh_latest_equity(self, timestamp: Any, row: pd.Series) -> None:
        if not self.broker.equity_curve:
            self.broker.record_equity(timestamp, _price(row.get("close"), row.get("open")))
            return
        close = _price(row.get("close"), row.get("open"))
        self.broker.equity_curve[-1]["value"] = round(max(0.0, self.broker._account_value(close)), 2)
        self.broker.equity_curve[-1]["_mark_price"] = close

def _blank_signals(df: pd.DataFrame) -> Dict[str, pd.Series]:
    return {
        "open_long": pd.Series(False, index=df.index),
        "close_long": pd.Series(False, index=df.index),
        "open_short": pd.Series(False, index=df.index),
        "close_short": pd.Series(False, index=df.index),
        "add_long": pd.Series(False, index=df.index),
        "add_short": pd.Series(False, index=df.index),
        "reduce_long": pd.Series(False, index=df.index),
        "reduce_short": pd.Series(False, index=df.index),
    }


BacktestContext = StrategyScriptContext
ScriptBacktestRunner = ScriptStrategyBacktestRunner


def _positive_float(value: Any) -> float:
    try:
        out = float(value or 0.0)
        return out if out > 0 else 0.0
    except Exception:
        return 0.0


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
