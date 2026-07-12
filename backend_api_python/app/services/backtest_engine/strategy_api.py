"""SignalFrame strategy API for the V2 backtest engine."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import pandas as pd

from app.services.strategy_runtime.signals import canonical_signal_columns

from .engine import BacktestEngine
from .models import BacktestConfig
from .signals import SignalStrategyAdapter


class SignalFrameStrategy:
    """Base class for vectorized single-symbol strategies."""

    def populate_indicators(self, df: pd.DataFrame, metadata: Mapping[str, Any]) -> pd.DataFrame:
        return df

    def populate_signals(self, df: pd.DataFrame, metadata: Mapping[str, Any]) -> pd.DataFrame:
        return df

    def build_signal_frame(self, df: pd.DataFrame, metadata: Optional[Mapping[str, Any]] = None) -> pd.DataFrame:
        work = df.copy()
        meta = dict(metadata or {})
        work = self.populate_indicators(work, meta)
        work = self.populate_signals(work, meta)
        return ensure_canonical_signal_frame(work)


class SignalFrameBacktestRunner:
    """Run a SignalFrameStrategy through the canonical broker simulator."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def run(
        self,
        *,
        strategy: SignalFrameStrategy,
        df: pd.DataFrame,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        frame = strategy.build_signal_frame(df, metadata or {})
        signals = {key: frame[key] for key in canonical_signal_columns() if key in frame}
        return BacktestEngine(self.config).run(
            df=df,
            strategy=SignalStrategyAdapter(df, signals, self.config),
            start_date=df.index[0].to_pydatetime(),
            end_date=df.index[-1].to_pydatetime(),
        )


def ensure_canonical_signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame):
        raise ValueError("strategy must return a pandas DataFrame")
    out = frame.copy()
    canonical = set(canonical_signal_columns())
    alias_columns = {"enter_long", "exit_long", "enter_short", "exit_short"}
    present_aliases = sorted(alias_columns.intersection(out.columns))
    if present_aliases:
        raise ValueError(f"SignalFrame contains unsupported alias columns: {', '.join(present_aliases)}")
    for key in canonical_signal_columns():
        if key not in out.columns:
            out[key] = False
    return out
