"""Long-only event-driven portfolio backtest engine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from app.services.portfolio_strategy_runtime import (
    PortfolioConstraints,
    PortfolioContext,
    TargetWeightPlan,
    compile_portfolio_strategy_handlers,
    rebalance_dates,
)


@dataclass(frozen=True)
class PortfolioBacktestConfig:
    initial_capital: float = 100000.0
    commission_rate: float = 0.0005
    slippage_rate: float = 0.0005
    rebalance_frequency: str = "weekly"
    max_weight: float = 0.1
    min_trade_value: float = 0.0
    allow_fractional: bool = True
    trading_start: Any = None

    def normalized(self) -> "PortfolioBacktestConfig":
        initial_capital = _finite_positive(self.initial_capital, "portfolio.invalidInitialCapital")
        commission = _finite_non_negative(self.commission_rate, "portfolio.invalidCommission")
        slippage = _finite_non_negative(self.slippage_rate, "portfolio.invalidSlippage")
        max_weight = _finite_positive(self.max_weight, "portfolio.invalidMaxWeight")
        min_trade = _finite_non_negative(self.min_trade_value, "portfolio.invalidMinTradeValue")
        rebalance_dates([], self.rebalance_frequency)
        return PortfolioBacktestConfig(
            initial_capital=initial_capital,
            commission_rate=commission,
            slippage_rate=slippage,
            rebalance_frequency=str(self.rebalance_frequency).strip().lower(),
            max_weight=max_weight,
            min_trade_value=min_trade,
            allow_fractional=bool(self.allow_fractional),
            trading_start=self.trading_start,
        )


class PortfolioBacktestEngine:
    """Execute target-weight strategies with next-session-open semantics."""

    VERSION = "quantdinger-portfolio-backtest-v1"

    def __init__(
        self,
        *,
        config: PortfolioBacktestConfig,
        code: str,
        params: Optional[Mapping[str, Any]] = None,
    ):
        self.config = config.normalized()
        self.code = str(code or "")
        self.params = dict(params or {})
        self.cash = float(self.config.initial_capital)
        self.positions: dict[str, float] = {}
        self.last_prices: dict[str, float] = {}
        self.orders: list[dict] = []
        self.rebalances: list[dict] = []
        self.equity_curve: list[dict] = []
        self.holdings: list[dict] = []
        self.logs: list[str] = []
        self.diagnostics: list[dict] = []
        self.total_commission = 0.0
        self.total_slippage = 0.0
        self.total_turnover_notional = 0.0

    def run(
        self,
        panel: Mapping[str, pd.DataFrame],
        *,
        universe_by_date: Optional[Mapping[Any, Any]] = None,
    ) -> dict:
        frames = _normalize_panel(panel)
        if not frames:
            raise ValueError("portfolio.noData")
        calendar = _calendar(frames)
        if len(calendar) < 2:
            raise ValueError("portfolio.insufficientSessions")
        trading_start = pd.Timestamp(self.config.trading_start) if self.config.trading_start else calendar[0]
        signal_calendar = pd.DatetimeIndex([item for item in calendar if item >= trading_start])
        signal_dates = frozenset(rebalance_dates(signal_calendar, self.config.rebalance_frequency))
        dated_universes = _normalize_dated_universes(universe_by_date)
        on_init, on_rebalance = compile_portfolio_strategy_handlers(self.code)
        context = PortfolioContext(
            universe=frames.keys(),
            params=self.params,
            constraints=PortfolioConstraints(
                long_only=True,
                max_weight=self.config.max_weight,
                gross_limit=1.0,
                net_limit=1.0,
            ),
            runtime={"mode": "backtest", "ai_decisions": "skipped"},
        )
        from app.services.ai_decision import BacktestAIDecisionClient

        context.bind_ai(BacktestAIDecisionClient(context.runtime))
        if callable(on_init):
            on_init(context)

        pending: Optional[tuple[pd.Timestamp, TargetWeightPlan]] = None
        for session in calendar:
            bars = _bars_at(frames, session)
            self._seed_open_prices(bars)
            if pending is not None:
                signal_date, plan = pending
                self._execute_plan(plan, signal_date=signal_date, execution_date=session, bars=bars)
                pending = None
            self._mark_close_prices(bars)
            self._record_close_state(session)

            if session in signal_dates:
                eligible = dated_universes.get(session, frozenset(frames.keys()))
                context.update_universe(eligible)
                clipped_panel = {
                    symbol: frame.loc[frame.index <= session].copy()
                    for symbol, frame in frames.items()
                    if symbol in eligible and not frame.loc[frame.index <= session].empty
                }
                context.reset_rebalance(session)
                context.runtime.update({
                    "current_time": session,
                    "cash": self.cash,
                    "equity": self._equity(),
                    "positions": dict(self.positions),
                    "current_weights": self._current_weights(),
                })
                on_rebalance(context, clipped_panel)
                plan = context.consume_plan()
                self.logs.extend(context.flush_logs())
                pending = (session, plan)
                self.rebalances.append({
                    "signal_date": session.isoformat(),
                    "execution_date": "",
                    "target_weights": dict(plan.weights),
                    "gross_exposure": plan.gross_exposure,
                    "net_exposure": plan.net_exposure,
                    "cash_weight": plan.cash_weight,
                    "status": "pending",
                })

        if pending is not None:
            self.diagnostics.append({
                "code": "portfolio.noNextSessionForRebalance",
                "signal_date": pending[0].isoformat(),
            })
        result = self._result(frames, trading_start, calendar[-1])
        result["diagnostics"]["aiDecisionCalls"] = int(context.runtime.get("ai_decision_calls") or 0)
        return result

    def _execute_plan(
        self,
        plan: TargetWeightPlan,
        *,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
        bars: dict[str, pd.Series],
    ) -> None:
        equity_before = self._equity_at_open(bars)
        target_values = {symbol: equity_before * weight for symbol, weight in plan.weights.items()}
        all_symbols = sorted(set(self.positions) | set(plan.weights))
        sell_symbols = []
        buy_symbols = []
        for symbol in all_symbols:
            price = _open_price(bars.get(symbol))
            if price <= 0:
                if abs(self.positions.get(symbol, 0.0)) > 1e-12 or symbol in plan.weights:
                    self._rejected_order(
                        symbol, signal_date, execution_date, "portfolio.missingExecutionPrice",
                    )
                continue
            current_value = self.positions.get(symbol, 0.0) * price
            delta = target_values.get(symbol, 0.0) - current_value
            if delta < -self.config.min_trade_value:
                sell_symbols.append((symbol, delta, price))
            elif delta > self.config.min_trade_value:
                buy_symbols.append((symbol, delta, price))

        for symbol, delta, raw_price in sell_symbols:
            quantity = min(self.positions.get(symbol, 0.0), abs(delta) / raw_price)
            quantity = self._round_quantity(quantity)
            if quantity > 0:
                self._fill_sell(symbol, quantity, raw_price, signal_date, execution_date)

        buy_candidates = []
        for symbol, _, raw_price in buy_symbols:
            current_value = self.positions.get(symbol, 0.0) * raw_price
            desired_delta = max(0.0, target_values.get(symbol, 0.0) - current_value)
            execution_price = raw_price * (1.0 + self.config.slippage_rate)
            unit_cash_cost = execution_price * (1.0 + self.config.commission_rate)
            quantity = desired_delta / execution_price if unit_cash_cost > 0 else 0.0
            buy_candidates.append((symbol, raw_price, quantity, quantity * unit_cash_cost, desired_delta))

        required_cash = sum(item[3] for item in buy_candidates)
        scale = min(1.0, self.cash / required_cash) if required_cash > 0 else 0.0
        for symbol, raw_price, raw_quantity, _, desired_delta in buy_candidates:
            quantity = self._round_quantity(raw_quantity * scale)
            execution_price = raw_price * (1.0 + self.config.slippage_rate)
            if quantity > 0 and quantity * execution_price >= self.config.min_trade_value:
                self._fill_buy(symbol, quantity, raw_price, signal_date, execution_date)
            elif desired_delta >= self.config.min_trade_value:
                self._rejected_order(
                    symbol, signal_date, execution_date, "portfolio.insufficientCash",
                )

        for record in reversed(self.rebalances):
            if record.get("signal_date") == signal_date.isoformat() and record.get("status") == "pending":
                record["execution_date"] = execution_date.isoformat()
                record["status"] = "executed"
                record["equity_before"] = round(equity_before, 8)
                record["equity_after"] = round(self._equity_at_open(bars), 8)
                break

    def _fill_buy(
        self,
        symbol: str,
        quantity: float,
        raw_price: float,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> None:
        price = raw_price * (1.0 + self.config.slippage_rate)
        notional = quantity * price
        commission = notional * self.config.commission_rate
        total = notional + commission
        if total > self.cash + 1e-8:
            self._rejected_order(symbol, signal_date, execution_date, "portfolio.insufficientCash")
            return
        self.cash -= total
        self.positions[symbol] = self.positions.get(symbol, 0.0) + quantity
        self._record_fill("buy", symbol, quantity, raw_price, price, commission, signal_date, execution_date)

    def _fill_sell(
        self,
        symbol: str,
        quantity: float,
        raw_price: float,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> None:
        price = raw_price * (1.0 - self.config.slippage_rate)
        notional = quantity * price
        commission = notional * self.config.commission_rate
        self.cash += notional - commission
        remaining = max(0.0, self.positions.get(symbol, 0.0) - quantity)
        if remaining <= 1e-12:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = remaining
        self._record_fill("sell", symbol, quantity, raw_price, price, commission, signal_date, execution_date)

    def _record_fill(
        self,
        side: str,
        symbol: str,
        quantity: float,
        raw_price: float,
        execution_price: float,
        commission: float,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> None:
        notional = quantity * execution_price
        slippage_cost = quantity * abs(execution_price - raw_price)
        self.total_commission += commission
        self.total_slippage += slippage_cost
        self.total_turnover_notional += notional
        self.orders.append({
            "signal_date": signal_date.isoformat(),
            "execution_date": execution_date.isoformat(),
            "symbol": symbol,
            "side": side,
            "quantity": round(quantity, 12),
            "reference_price": round(raw_price, 8),
            "price": round(execution_price, 8),
            "notional": round(notional, 8),
            "commission": round(commission, 8),
            "slippage_cost": round(slippage_cost, 8),
            "status": "filled",
            "reason": "rebalance",
        })

    def _rejected_order(
        self,
        symbol: str,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
        reason: str,
    ) -> None:
        self.orders.append({
            "signal_date": signal_date.isoformat(),
            "execution_date": execution_date.isoformat(),
            "symbol": symbol,
            "side": "",
            "quantity": 0.0,
            "reference_price": 0.0,
            "price": 0.0,
            "notional": 0.0,
            "commission": 0.0,
            "slippage_cost": 0.0,
            "status": "rejected",
            "reason": reason,
        })

    def _round_quantity(self, quantity: float) -> float:
        if self.config.allow_fractional:
            return math.floor(max(0.0, quantity) * 1e8) / 1e8
        return float(math.floor(max(0.0, quantity)))

    def _seed_open_prices(self, bars: dict[str, pd.Series]) -> None:
        for symbol, row in bars.items():
            price = _open_price(row)
            if price > 0 and symbol not in self.last_prices:
                self.last_prices[symbol] = price

    def _mark_close_prices(self, bars: dict[str, pd.Series]) -> None:
        for symbol, row in bars.items():
            price = _price(row.get("close"))
            if price > 0:
                self.last_prices[symbol] = price

    def _equity(self) -> float:
        return self.cash + sum(
            quantity * self.last_prices.get(symbol, 0.0)
            for symbol, quantity in self.positions.items()
        )

    def _equity_at_open(self, bars: dict[str, pd.Series]) -> float:
        value = self.cash
        for symbol, quantity in self.positions.items():
            price = _open_price(bars.get(symbol)) or self.last_prices.get(symbol, 0.0)
            value += quantity * price
        return value

    def _current_weights(self) -> dict[str, float]:
        equity = self._equity()
        if equity <= 0:
            return {}
        return {
            symbol: (quantity * self.last_prices.get(symbol, 0.0)) / equity
            for symbol, quantity in sorted(self.positions.items())
        }

    def _record_close_state(self, session: pd.Timestamp) -> None:
        equity = self._equity()
        self.equity_curve.append({
            "time": session.isoformat(),
            "equity": round(equity, 8),
            "value": round(equity, 8),
            "cash": round(self.cash, 8),
        })
        self.holdings.append({
            "time": session.isoformat(),
            "positions": [
                {
                    "symbol": symbol,
                    "quantity": round(quantity, 12),
                    "price": round(self.last_prices.get(symbol, 0.0), 8),
                    "market_value": round(quantity * self.last_prices.get(symbol, 0.0), 8),
                    "weight": round(weight, 12),
                }
                for symbol, quantity in sorted(self.positions.items())
                for weight in [
                    (quantity * self.last_prices.get(symbol, 0.0) / equity) if equity > 0 else 0.0
                ]
            ],
        })

    def _result(self, frames: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> dict:
        metrics = _performance_metrics(
            self.equity_curve,
            initial_capital=self.config.initial_capital,
            start=start,
            end=end,
        )
        average_equity = float(np.mean([item["equity"] for item in self.equity_curve])) if self.equity_curve else 0.0
        metrics.update({
            "turnover": (self.total_turnover_notional / average_equity) if average_equity > 0 else 0.0,
            "rebalance_count": len([item for item in self.rebalances if item["status"] == "executed"]),
            "total_commission": self.total_commission,
            "total_slippage": self.total_slippage,
            "average_position_count": float(np.mean([
                len(item["positions"]) for item in self.holdings
            ])) if self.holdings else 0.0,
        })
        filled_orders = [item for item in self.orders if item.get("status") == "filled"]
        return {
            "runType": "portfolio_strategy",
            "engineVersion": self.VERSION,
            "totalReturn": metrics["total_return"] * 100.0,
            "maxDrawdown": abs(metrics["max_drawdown"]) * 100.0,
            "sharpeRatio": metrics["sharpe"],
            "totalTrades": len(filled_orders),
            "config": {
                "initialCapital": self.config.initial_capital,
                "commission": self.config.commission_rate,
                "slippage": self.config.slippage_rate,
                "rebalanceFrequency": self.config.rebalance_frequency,
                "maxWeight": self.config.max_weight,
                "minTradeValue": self.config.min_trade_value,
                "allowFractional": self.config.allow_fractional,
            },
            "metrics": metrics,
            "equityCurve": self.equity_curve,
            "rebalances": self.rebalances,
            "holdings": self.holdings,
            "orders": self.orders,
            "logs": self.logs,
            "diagnostics": {
                "symbolsRequested": len(frames),
                "symbolsUsed": len(frames),
                "warnings": self.diagnostics,
                "aiDecisions": "skipped_in_backtest",
            },
        }


def _normalize_panel(panel: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    if not isinstance(panel, Mapping):
        raise ValueError("portfolio.panelMustBeMapping")
    frames: dict[str, pd.DataFrame] = {}
    for raw_symbol, raw_frame in panel.items():
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol or not isinstance(raw_frame, pd.DataFrame) or raw_frame.empty:
            continue
        missing = {"open", "high", "low", "close"} - set(raw_frame.columns)
        if missing:
            raise ValueError("portfolio.missingOhlc")
        frame = raw_frame.copy()
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index))
        if frame.index.tz is not None:
            frame.index = frame.index.tz_convert("UTC").tz_localize(None)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frames[symbol] = frame
    return frames


def _calendar(frames: Mapping[str, pd.DataFrame]) -> pd.DatetimeIndex:
    combined = pd.DatetimeIndex([])
    for frame in frames.values():
        combined = combined.union(frame.index)
    return combined.sort_values().unique()


def _normalize_dated_universes(value: Optional[Mapping[Any, Any]]) -> dict[pd.Timestamp, frozenset[str]]:
    if not value:
        return {}
    normalized = {}
    for raw_date, raw_symbols in value.items():
        timestamp = pd.Timestamp(raw_date)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        normalized[timestamp] = frozenset(
            str(symbol or "").strip().upper() for symbol in (raw_symbols or []) if symbol
        )
    return normalized


def _bars_at(frames: Mapping[str, pd.DataFrame], session: pd.Timestamp) -> dict[str, pd.Series]:
    bars = {}
    for symbol, frame in frames.items():
        if session in frame.index:
            bars[symbol] = frame.loc[session]
    return bars


def _open_price(row: Optional[pd.Series]) -> float:
    if row is None:
        return 0.0
    return _price(row.get("open"))


def _price(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed > 0 else 0.0


def _finite_positive(value: Any, code: str) -> float:
    parsed = _finite_non_negative(value, code)
    if parsed <= 0:
        raise ValueError(code)
    return parsed


def _finite_non_negative(value: Any, code: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(code)
    return parsed


def _performance_metrics(
    curve: list[dict],
    *,
    initial_capital: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict:
    if not curve:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "volatility": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
        }
    equity = pd.Series([float(item["equity"]) for item in curve], dtype=float)
    total_return = equity.iloc[-1] / initial_capital - 1.0
    elapsed_days = max(1, (pd.Timestamp(end) - pd.Timestamp(start)).days)
    annual_return = (1.0 + total_return) ** (365.25 / elapsed_days) - 1.0 if total_return > -1 else -1.0
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    volatility = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 else 0.0
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    return {
        "total_return": float(total_return),
        "annual_return": float(annual_return),
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": float(calmar),
    }
