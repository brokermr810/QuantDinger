from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import numpy as np


class PerformanceAnalyzer:
    def __init__(
        self,
        *,
        initial_capital: float,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        total_commission: float = 0.0,
    ):
        self.initial_capital = float(initial_capital or 0.0)
        self.timeframe = str(timeframe or "1D")
        self.start_date = start_date
        self.end_date = end_date
        self.total_commission = float(total_commission or 0.0)

    def analyze(self, equity_curve: List[Dict[str, Any]], trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not equity_curve or self.initial_capital <= 0:
            return {}
        final_value = _safe_float(equity_curve[-1].get("value"))
        total_return = (final_value - self.initial_capital) / self.initial_capital * 100.0
        values = [_safe_float(item.get("value")) for item in equity_curve]
        closing = [
            t for t in trades
            if str(t.get("type") or "").lower().startswith("close")
        ]
        if not closing:
            closing = [
                t for t in trades
                if any(k in t for k in ("profit", "pnl", "realized_pnl", "realizedPnl"))
            ]
        wins = [t for t in closing if _safe_float(t.get("profit")) > 0]
        losses = [t for t in closing if _safe_float(t.get("profit")) < 0]
        gross_profit = sum(_safe_float(t.get("profit")) for t in wins)
        gross_loss = abs(sum(_safe_float(t.get("profit")) for t in losses))
        win_rate = len(wins) / len(closing) * 100.0 if closing else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        max_dd = _max_drawdown(values)
        sharpe = _sharpe(values, self.timeframe)
        annual_return = _annualized_return(total_return, equity_curve, self.start_date, self.end_date)
        loss_streak = _max_loss_streak(closing)
        avg_holding = _mean([_safe_float(t.get("holding_bars")) for t in closing])
        expectancy = (
            (gross_profit - gross_loss) / len(closing)
            if closing
            else 0.0
        )
        largest_win = round(max([_safe_float(t.get("profit")) for t in wins], default=0.0), 2)
        largest_loss = round(min([_safe_float(t.get("profit")) for t in losses], default=0.0), 2)
        avg_trade = round(_mean([_safe_float(t.get("profit")) for t in closing]), 2)

        return {
            "totalReturn": round(total_return, 2),
            "annualReturn": round(annual_return, 2),
            "maxDrawdown": round(max_dd, 2),
            "sharpeRatio": round(sharpe, 2),
            "winRate": round(win_rate, 2),
            "profitFactor": round(profit_factor, 2),
            "totalTrades": len(closing),
            "totalProfit": round(final_value - self.initial_capital, 2),
            "finalEquity": round(final_value, 2),
            "totalCommission": round(self.total_commission, 2),
            "grossProfit": round(gross_profit, 2),
            "grossLoss": round(gross_loss, 2),
            "avgWin": round(_mean([_safe_float(t.get("profit")) for t in wins]), 2),
            "avgLoss": round(_mean([_safe_float(t.get("profit")) for t in losses]), 2),
            "expectancy": round(expectancy, 2),
            "largestWin": largest_win,
            "largestLoss": largest_loss,
            "bestTrade": largest_win,
            "worstTrade": largest_loss,
            "avgTrade": avg_trade,
            "maxConsecutiveLosses": loss_streak,
            "avgHoldingBars": round(avg_holding, 2),
        }


def _safe_float(value: Any) -> float:
    try:
        out = float(value or 0.0)
        return out if np.isfinite(out) else 0.0
    except Exception:
        return 0.0


def _mean(values: List[float]) -> float:
    values = [v for v in values if np.isfinite(v)]
    return float(np.mean(values)) if values else 0.0


def _max_drawdown(values: List[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak <= 0:
            continue
        dd = (peak - value) / peak * 100.0
        max_dd = max(max_dd, dd)
    return -max_dd


def _sharpe(values: List[float], timeframe: str, risk_free_rate: float = 0.02) -> float:
    clean = np.array([v for v in values if v > 0 and np.isfinite(v)], dtype=float)
    if len(clean) < 3:
        return 0.0
    returns = np.diff(clean) / clean[:-1]
    returns = returns[np.isfinite(returns)]
    if len(returns) < 2:
        return 0.0
    tf = _timeframe_key(timeframe)
    annualization = {
        "1m": 365 * 24 * 60,
        "5m": 365 * 24 * 12,
        "15m": 365 * 24 * 4,
        "30m": 365 * 24 * 2,
        "1H": 365 * 24,
        "4H": 365 * 6,
        "1D": 365,
        "1W": 52,
    }.get(tf, 252)
    std = float(np.std(returns)) * np.sqrt(annualization)
    if std <= 0 or not np.isfinite(std):
        return 0.0
    avg = float(np.mean(returns)) * annualization
    out = (avg - risk_free_rate) / std
    return float(out) if np.isfinite(out) else 0.0


def _timeframe_key(timeframe: Any) -> str:
    raw = str(timeframe or "1D").strip()
    lower = raw.lower()
    if lower.endswith("h"):
        return lower[:-1] + "H"
    if lower.endswith("d"):
        return lower[:-1] + "D"
    if lower.endswith("w"):
        return lower[:-1] + "W"
    return lower


def _annualized_return(total_return_pct: float, equity_curve: List[Dict[str, Any]], start_date: datetime, end_date: datetime) -> float:
    try:
        actual_start = datetime.strptime(str(equity_curve[0].get("time")), "%Y-%m-%d %H:%M")
        actual_end = datetime.strptime(str(equity_curve[-1].get("time")), "%Y-%m-%d %H:%M")
        days = (actual_end - actual_start).total_seconds() / 86400.0
    except Exception:
        days = (end_date - start_date).total_seconds() / 86400.0
    years = days / 365.0
    return total_return_pct / years if years > 0 else 0.0


def _max_loss_streak(trades: List[Dict[str, Any]]) -> int:
    best = 0
    cur = 0
    for trade in trades:
        if _safe_float(trade.get("profit")) < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best
