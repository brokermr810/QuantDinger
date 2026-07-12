"""Independent semantic runner for Python ScriptStrategy code.

This module intentionally does not use the backtest engine or trading
executor. It only executes a script against supplied bars, records emitted
order intents, and applies a minimal position state so later bars can observe
whether the script is flat or in-position.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from app.services.strategy_script_runtime import (
    ScriptBar,
    StrategyScriptContext,
    compile_strategy_script_handlers,
)


@dataclass
class SemanticOrder:
    bar_index: int
    timestamp: Any
    intent: str
    action: str
    price: float
    amount: float
    reason: str


@dataclass
class SemanticRunResult:
    orders: List[SemanticOrder]
    ctx: StrategyScriptContext

    def intents(self) -> List[str]:
        return [order.intent for order in self.orders]

    def reasons(self) -> List[str]:
        return [order.reason for order in self.orders]

    def first(self, intent: str) -> Optional[SemanticOrder]:
        return next((order for order in self.orders if order.intent == intent), None)


def _bars_df(bars: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(list(bars))
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "time"])
    if "time" not in df.columns:
        df["time"] = pd.date_range("2026-01-01", periods=len(df), freq="min")
    for column in ("open", "high", "low", "close", "volume"):
        if column not in df.columns:
            df[column] = df.get("close", 0.0)
    return df[["open", "high", "low", "close", "volume", "time"]]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _apply_order_to_position(ctx: StrategyScriptContext, order: Dict[str, Any], fallback_price: float) -> None:
    intent = str(order.get("intent") or "").lower()
    price = _float(order.get("price"), fallback_price)
    amount = _float(order.get("amount"), 0.0)

    if intent in ("open_long", "add_long"):
        ctx.position.open_long(price, amount)
        return
    if intent in ("open_short", "add_short"):
        ctx.position.open_short(price, amount)
        return
    if intent == "close_long":
        ctx.position.close_long()
        return
    if intent == "close_short":
        ctx.position.close_short()
        return
    if intent == "reduce_long":
        ctx.position.reduce_long(amount or ctx.position.long_size)
        return
    if intent == "reduce_short":
        ctx.position.reduce_short(amount or ctx.position.short_size)


def run_script_semantics(
    code: str,
    bars: Iterable[Dict[str, Any]],
    *,
    params: Optional[Dict[str, Any]] = None,
    runtime_config: Optional[Dict[str, Any]] = None,
    initial_balance: float = 10000.0,
) -> SemanticRunResult:
    """Run a script against deterministic bars and return emitted intents.

    This is for semantic/spec tests. It does not calculate PnL, fees, slippage,
    equity curves, or next-bar execution. Those belong to integration tests.
    """
    df = _bars_df(bars)
    on_init, on_bar = compile_strategy_script_handlers(code)
    ctx = StrategyScriptContext(df, initial_balance)
    ctx.set_runtime_config(runtime_config or {}, initial_balance=initial_balance)
    if params:
        ctx._params.update(dict(params))
    if callable(on_init):
        on_init(ctx)

    captured: List[SemanticOrder] = []
    for i, row in df.iterrows():
        ctx.current_index = int(i)
        ctx._orders.clear()
        bar = ScriptBar(
            open=_float(row.get("open")),
            high=_float(row.get("high")),
            low=_float(row.get("low")),
            close=_float(row.get("close")),
            volume=_float(row.get("volume")),
            timestamp=row.get("time"),
        )
        on_bar(ctx, bar)
        for raw in list(ctx._orders):
            price = _float(raw.get("price"), bar["close"])
            order = SemanticOrder(
                bar_index=int(i),
                timestamp=row.get("time"),
                intent=str(raw.get("intent") or ""),
                action=str(raw.get("action") or ""),
                price=price,
                amount=_float(raw.get("amount")),
                reason=str(raw.get("reason") or ""),
            )
            captured.append(order)
            _apply_order_to_position(ctx, raw, bar["close"])

    return SemanticRunResult(orders=captured, ctx=ctx)
