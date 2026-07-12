from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pandas as pd

from .analyzers import PerformanceAnalyzer
from .broker import BrokerSimulator
from .models import BacktestConfig
from .serialization import serialize_orders


class BacktestEngine:
    VERSION = "quantdinger-backtest-engine-v2"

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.broker = BrokerSimulator(config)

    def run(
        self,
        *,
        df: pd.DataFrame,
        strategy: Any,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        if df is None or df.empty:
            raise ValueError("No candle data available in the backtest date range")
        if not all(col in df.columns for col in ("open", "high", "low", "close")):
            raise ValueError("Backtest data must include open/high/low/close columns")

        for idx, (timestamp, row) in enumerate(df.iterrows()):
            strategy.before_orders(self.broker, idx, timestamp, row)
            strategy.submit_bar_orders(self.broker, idx, timestamp, row)
            self.broker.process_bar(idx, timestamp, row)
            self.broker.check_liquidation(
                timestamp=timestamp,
                bar_index=idx,
                high=float(row.get("high") or row.get("close") or 0.0),
                low=float(row.get("low") or row.get("close") or 0.0),
            )

        last_ts = df.index[-1]
        last_close = float(df.iloc[-1].get("close") or 0.0)
        self.broker.close_all(
            price=last_close,
            timestamp=last_ts,
            bar_index=len(df) - 1,
            reason="end_of_backtest",
        )
        if self.broker.equity_curve:
            self.broker.equity_curve[-1]["value"] = round(
                max(0.0, self.broker.cash),
                2,
            )
        else:
            self.broker.record_equity(last_ts, last_close)

        equity_curve = [
            {k: v for k, v in item.items() if not str(k).startswith("_")}
            for item in self.broker.equity_curve
        ]
        trades = list(self.broker.trades)
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
            "trades": trades,
            "closedTrades": closed_trades,
            "tradeRecords": closed_trades,
            "orders": serialize_orders(self.broker.orders),
            "totalFundingPaid": round(float(self.broker.total_funding or 0.0), 6),
            "engine": {
                "version": self.VERSION,
                "intrabarMode": self.config.intrabar_mode,
                "signalTiming": self.config.signal_timing,
                "totalFundingPaid": round(float(self.broker.total_funding or 0.0), 6),
                "orderCount": len(self.broker.orders),
                "fillCount": len([
                    o for o in self.broker.orders
                    if o.status.value == "filled"
                ]),
                "rejectedOrderCount": len([
                    o for o in self.broker.orders
                    if o.status.value == "rejected"
                ]),
                "pendingOrderCount": len([
                    o for o in self.broker.orders
                    if o.status.value in ("accepted", "partial_filled")
                ]),
            },
        }
