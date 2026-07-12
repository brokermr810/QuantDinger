from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Dict, Tuple

import pandas as pd
import pytest

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner
from tests.fixtures.script_strategy_samples import STRATEGY_SAMPLES


TEST_DEPS = Path(__file__).resolve().parents[1] / ".test_deps"
if TEST_DEPS.exists():
    sys.path.insert(0, str(TEST_DEPS))

pytest.importorskip("backtesting")
from backtesting import Strategy  # noqa: E402
from backtesting.lib import FractionalBacktest  # noqa: E402
from backtesting.test import BTCUSD, EURUSD, GOOG  # noqa: E402


StrategyParams = Dict[str, float | int]
SignalFn = Callable[[pd.DataFrame, StrategyParams], Tuple[pd.Series, pd.Series]]


CROSS_PARAMS: Dict[str, StrategyParams] = {
    "ema_trend_pullback": {"fast": 3, "slow": 8, "pullback_pct": 0.0, "target_pct": 0.25},
    "donchian_breakout": {"entry_lookback": 10, "exit_lookback": 5, "target_pct": 0.3},
    "rsi_mean_reversion": {"period": 7, "oversold": 45, "exit_level": 55, "target_pct": 0.2},
    "macd_momentum": {"fast": 4, "slow": 9, "signal": 4, "target_pct": 0.25},
    "bollinger_reversion": {"period": 10, "std_mult": 1.0, "target_pct": 0.2},
}


def _to_qd_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns={c: c.lower() for c in df.columns}).copy()
    return out[["open", "high", "low", "close", "volume"]].dropna()


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if rule == "raw":
        return df.copy()
    out = df.resample(rule).agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    return out.dropna()


def _with_terminal_sentinel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    last = out.iloc[-1].copy()
    close = float(last["Close"])
    last["Open"] = close
    last["High"] = close
    last["Low"] = close
    last["Close"] = close
    try:
        step = out.index[-1] - out.index[-2]
        next_index = out.index[-1] + step
    except Exception:
        next_index = out.index[-1] + pd.Timedelta(days=1)
    out.loc[next_index] = last
    return out


def _ema(values, period: int) -> float:
    k = 2.0 / (float(period) + 1.0)
    out = float(values[0])
    for value in values[1:]:
        out = float(value) * k + out * (1.0 - k)
    return out


def _ema_series(values, period: int) -> list[float]:
    k = 2.0 / (float(period) + 1.0)
    out = []
    ema = float(values[0])
    for value in values:
        ema = float(value) * k + ema * (1.0 - k)
        out.append(ema)
    return out


def _rsi(values, period: int) -> float:
    gains = []
    losses = []
    for i in range(len(values) - period, len(values)):
        change = float(values[i]) - float(values[i - 1])
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _mean(values) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values) -> float:
    mid = _mean(values)
    return (sum([(float(v) - mid) * (float(v) - mid) for v in values]) / len(values)) ** 0.5 if values else 0.0


def _ema_trend_pullback(df: pd.DataFrame, params: StrategyParams) -> Tuple[pd.Series, pd.Series]:
    close = df["Close"].astype(float).tolist()
    fast_n = int(params["fast"])
    slow_n = int(params["slow"])
    pullback = float(params["pullback_pct"])
    entries, exits = [], []
    for i, price in enumerate(close):
        if i < slow_n:
            entries.append(False)
            exits.append(False)
            continue
        window = close[: i + 1]
        fast = _ema(window[-fast_n:], fast_n)
        slow = _ema(window[-slow_n:], slow_n)
        entries.append(fast > slow and float(price) <= fast * (1.0 - pullback))
        exits.append(fast < slow)
    return pd.Series(entries, index=df.index), pd.Series(exits, index=df.index)


def _donchian_breakout(df: pd.DataFrame, params: StrategyParams) -> Tuple[pd.Series, pd.Series]:
    entry_n = int(params["entry_lookback"])
    exit_n = int(params["exit_lookback"])
    entries, exits = [], []
    for i, row in enumerate(df.itertuples()):
        if i < max(entry_n, exit_n):
            entries.append(False)
            exits.append(False)
            continue
        prev = df.iloc[:i]
        high = float(prev["High"].iloc[-entry_n:].max())
        exit_low = float(prev["Low"].iloc[-exit_n:].min())
        price = float(row.Close)
        entries.append(price > high)
        exits.append(price < exit_low)
    return pd.Series(entries, index=df.index), pd.Series(exits, index=df.index)


def _rsi_mean_reversion(df: pd.DataFrame, params: StrategyParams) -> Tuple[pd.Series, pd.Series]:
    close = df["Close"].astype(float).tolist()
    period = int(params["period"])
    oversold = float(params["oversold"])
    exit_level = float(params["exit_level"])
    entries, exits = [], []
    for i in range(len(close)):
        if i < period:
            entries.append(False)
            exits.append(False)
            continue
        value = _rsi(close[: i + 1], period)
        entries.append(value <= oversold)
        exits.append(value >= exit_level)
    return pd.Series(entries, index=df.index), pd.Series(exits, index=df.index)


def _macd_momentum(df: pd.DataFrame, params: StrategyParams) -> Tuple[pd.Series, pd.Series]:
    close = df["Close"].astype(float).tolist()
    fast_n = int(params["fast"])
    slow_n = int(params["slow"])
    sig_n = int(params["signal"])
    need = slow_n + sig_n + 2
    entries, exits = [], []
    for i in range(len(close)):
        if i + 1 < need:
            entries.append(False)
            exits.append(False)
            continue
        window = close[i - need + 1 : i + 1]
        fast = _ema_series(window, fast_n)
        slow = _ema_series(window, slow_n)
        macd = [fast[j] - slow[j] for j in range(len(window))]
        signal = _ema_series(macd, sig_n)
        bullish = macd[-1] > signal[-1]
        entries.append(bullish)
        exits.append(not bullish)
    return pd.Series(entries, index=df.index), pd.Series(exits, index=df.index)


def _bollinger_reversion(df: pd.DataFrame, params: StrategyParams) -> Tuple[pd.Series, pd.Series]:
    close = df["Close"].astype(float).tolist()
    period = int(params["period"])
    mult = float(params["std_mult"])
    entries, exits = [], []
    for i, price in enumerate(close):
        if i < period:
            entries.append(False)
            exits.append(False)
            continue
        previous = close[i - period : i]
        mid = _mean(previous)
        dev = _std(previous)
        lower = mid - dev * mult
        entries.append(float(price) <= lower)
        exits.append(float(price) >= mid)
    return pd.Series(entries, index=df.index), pd.Series(exits, index=df.index)


SIGNAL_FNS: Dict[str, SignalFn] = {
    "ema_trend_pullback": _ema_trend_pullback,
    "donchian_breakout": _donchian_breakout,
    "rsi_mean_reversion": _rsi_mean_reversion,
    "macd_momentum": _macd_momentum,
    "bollinger_reversion": _bollinger_reversion,
}


def _run_quantdinger(strategy_key: str, df: pd.DataFrame, params: StrategyParams):
    qd_df = _to_qd_frame(df)
    result = ScriptBacktestRunner(
        config=BacktestConfig(
            initial_capital=10_000,
            commission=0.0,
            slippage=0.0,
            leverage=1,
            trade_direction="long",
            timeframe="cross",
            market_type="spot",
            signal_timing="next_bar_open",
        ),
        code=STRATEGY_SAMPLES[strategy_key],
        params=dict(params),
        runtime={"symbol": "CROSS/TEST"},
    ).run(
        df=qd_df,
        start_date=qd_df.index[0].to_pydatetime(),
        end_date=qd_df.index[-1].to_pydatetime(),
    )
    return result


def _run_backtesting_py(df: pd.DataFrame, entries: pd.Series, exits: pd.Series, target_pct: float):
    entries = entries.reindex(df.index).fillna(False).astype(bool).tolist()
    exits = exits.reindex(df.index).fillna(False).astype(bool).tolist()

    class ReferenceStrategy(Strategy):
        def init(self):
            self.entries = entries
            self.exits = exits
            self.target_pct = target_pct

        def next(self):
            i = len(self.data.Close) - 1
            if self.position:
                if self.exits[i]:
                    self.position.close()
            elif self.entries[i]:
                self.buy(size=self.target_pct)

    stats = FractionalBacktest(
        df,
        ReferenceStrategy,
        cash=10_000,
        commission=0.0,
        spread=0.0,
        trade_on_close=False,
        finalize_trades=True,
    ).run()
    return stats


DATASETS = [
    ("GOOG", "1D", lambda: GOOG.iloc[:900].copy()),
    ("GOOG", "1W", lambda: _resample(GOOG.iloc[:1500], "W-FRI")),
    ("EURUSD", "4H", lambda: _resample(EURUSD, "4h").iloc[:700]),
    ("BTCUSD", "1M", lambda: BTCUSD.copy()),
]


@pytest.mark.parametrize("strategy_key", sorted(STRATEGY_SAMPLES))
@pytest.mark.parametrize("asset,timeframe,loader", DATASETS)
def test_quantdinger_matches_backtesting_py_cross_engine(strategy_key, asset, timeframe, loader):
    df = _with_terminal_sentinel(loader())
    params = CROSS_PARAMS[strategy_key]
    entries, exits = SIGNAL_FNS[strategy_key](df, params)

    qd = _run_quantdinger(strategy_key, df, params)
    bt = _run_backtesting_py(df, entries, exits, float(params["target_pct"]))

    qd_trades = int(qd["totalTrades"])
    bt_trades = int(len(bt["_trades"]))
    qd_equity = float(qd["finalEquity"])
    bt_equity = float(bt["Equity Final [$]"])
    tolerance = max(25.0, abs(bt_equity) * 0.015)

    assert qd_trades == bt_trades, (strategy_key, asset, timeframe, qd_trades, bt_trades)
    assert qd_equity == pytest.approx(bt_equity, abs=tolerance), (
        strategy_key,
        asset,
        timeframe,
        qd_equity,
        bt_equity,
    )
    if qd_trades:
        assert {t["side"] for t in qd["closedTrades"]} == {"long"}
