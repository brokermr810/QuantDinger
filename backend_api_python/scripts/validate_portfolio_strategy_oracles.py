"""Validate built-in portfolio strategies against independent real-data rankings."""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime, timedelta

import pandas as pd

from app.services.portfolio_backtest import PortfolioBacktestConfig, PortfolioBacktestEngine
from app.services.portfolio_backtest_service import PortfolioBacktestService
from app.services.portfolio_strategy_examples import list_portfolio_strategy_examples


def _score(frame: pd.DataFrame, key: str, lookback: int) -> float | None:
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if key in {"portfolio_momentum_top_n", "portfolio_mean_reversion_top_n"}:
        if len(closes) <= lookback or float(closes.iloc[-lookback - 1]) <= 0:
            return None
        value = float(closes.iloc[-1] / closes.iloc[-lookback - 1] - 1.0)
        return -value if key == "portfolio_mean_reversion_top_n" else value
    returns = closes.pct_change().dropna()
    if len(returns) < lookback:
        return None
    return -float(returns.iloc[-lookback:].std(ddof=1) * math.sqrt(252))


def _expected_weights(panel: dict[str, pd.DataFrame], signal: pd.Timestamp, key: str, lookback: int, top_n: int):
    scores = {}
    for symbol, frame in panel.items():
        clipped = frame.loc[frame.index <= signal]
        value = _score(clipped, key, lookback)
        if value is not None and math.isfinite(value):
            scores[symbol] = value
    selected = [item[0] for item in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_n]]
    return {symbol: 1.0 / top_n for symbol in sorted(selected)}, scores


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="AAPL,MSFT,NVDA,TSLA")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--top-n", type=int, default=2)
    args = parser.parse_args()

    end = datetime.now(UTC).replace(tzinfo=None)
    start = end - timedelta(days=max(120, args.days))
    candidates = [
        {"symbol": symbol.strip().upper(), "market": "USStock", "market_type": "spot", "exchange_id": ""}
        for symbol in args.symbols.split(",")
        if symbol.strip()
    ]
    service = PortfolioBacktestService()
    panel, skipped = service._fetch_panel(candidates, start - timedelta(days=args.lookback * 3), end)
    if len(panel) < args.top_n:
        raise RuntimeError(f"portfolio validation has insufficient real data: {skipped}")

    summaries = []
    for example in list_portfolio_strategy_examples():
        result = PortfolioBacktestEngine(
            config=PortfolioBacktestConfig(
                initial_capital=100_000,
                commission_rate=0.0005,
                slippage_rate=0.0005,
                rebalance_frequency="weekly",
                max_weight=1.0 / args.top_n,
                trading_start=start,
            ),
            code=example["code"],
            params={"top_n": args.top_n, "lookback": args.lookback},
        ).run(panel)
        checked = 0
        for rebalance in result["rebalances"]:
            signal = pd.Timestamp(rebalance["signal_date"])
            expected, scores = _expected_weights(panel, signal, example["template_key"], args.lookback, args.top_n)
            actual = rebalance["target_weights"]
            if actual != expected:
                raise AssertionError(
                    f"{example['template_key']} {signal.date()} expected {expected}, got {actual}; scores={scores}"
                )
            checked += 1
        for order in result["orders"]:
            if order["status"] == "filled" and pd.Timestamp(order["execution_date"]) <= pd.Timestamp(order["signal_date"]):
                raise AssertionError(f"same-session fill detected: {order}")
        summaries.append({
            "strategy": example["template_key"],
            "signals_checked": checked,
            "orders": len([item for item in result["orders"] if item["status"] == "filled"]),
            "total_return_pct": round(result["totalReturn"], 6),
            "final_equity": result["equityCurve"][-1]["equity"],
        })

    print(json.dumps({"symbols": sorted(panel), "skipped": skipped, "strategies": summaries}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
