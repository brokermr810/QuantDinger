from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Dict

import numpy as np
import pandas as pd

from app.services.backtest_engine.engine import BacktestEngine
from app.services.backtest_engine.models import BacktestConfig
from app.services.backtest_engine.signals import SignalStrategyAdapter


SignalDict = Dict[str, pd.Series]
SignalFactory = Callable[[pd.DataFrame], SignalDict]


@dataclass(frozen=True)
class StressScenario:
    name: str
    days: int
    freq: str
    timeframe: str
    seed: int
    signal_factory: SignalFactory
    config: BacktestConfig
    min_fills: int = 2
    max_seconds: float = 30.0


def make_synthetic_ohlcv(*, days: int, freq: str, seed: int, base_price: float = 100.0) -> pd.DataFrame:
    periods_per_day = {
        "1min": 24 * 60,
        "5min": 24 * 12,
        "15min": 24 * 4,
        "1h": 24,
        "4h": 6,
        "1d": 1,
    }
    freq_alias = {
        "1min": "1min",
        "5min": "5min",
        "15min": "15min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1D",
    }
    if freq not in periods_per_day:
        raise ValueError(f"unsupported freq: {freq}")

    periods = int(days * periods_per_day[freq])
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=periods, freq=freq_alias[freq])
    x = np.arange(periods, dtype=float)
    scale = {
        "1min": 0.00055,
        "5min": 0.0009,
        "15min": 0.0014,
        "1h": 0.0022,
        "4h": 0.004,
        "1d": 0.012,
    }[freq]

    thirds = max(1, periods // 3)
    drift = np.piecewise(
        x,
        [x < thirds, (x >= thirds) & (x < 2 * thirds), x >= 2 * thirds],
        [scale * 0.045, -scale * 0.025, scale * 0.015],
    )
    seasonality = np.sin(x / max(12.0, periods / 36.0)) * scale * 0.6
    micro_cycle = np.sin(x / 17.0) * scale * 0.25
    noise = rng.normal(0.0, scale, periods)
    shocks = np.zeros(periods)
    shock_step = max(97, periods // 41)
    for i in range(shock_step, periods, shock_step):
        shocks[i] = rng.choice([-1.0, 1.0]) * scale * rng.uniform(4.0, 9.0)

    close = base_price * np.exp(np.cumsum(drift + seasonality + micro_cycle + noise + shocks))
    close = np.maximum(close, 0.5)
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0.0, scale * 0.18, periods))
    body_high = np.maximum(open_, close)
    body_low = np.minimum(open_, close)
    wick = np.abs(rng.normal(scale * 1.8, scale * 0.6, periods))
    high = body_high * (1 + wick)
    low = np.maximum(0.01, body_low * (1 - wick))
    volume = rng.lognormal(mean=9.0, sigma=0.45, size=periods)

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )
    return df


def blank_signals(df: pd.DataFrame) -> SignalDict:
    false = pd.Series(False, index=df.index)
    return {
        "open_long": false.copy(),
        "close_long": false.copy(),
        "open_short": false.copy(),
        "close_short": false.copy(),
        "add_long": false.copy(),
        "add_short": false.copy(),
    }


def adaptive_momentum_reversal(df: pd.DataFrame) -> SignalDict:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    fast = close.ewm(span=18, adjust=False).mean()
    slow = close.ewm(span=64, adjust=False).mean()
    trend = close.ewm(span=180, adjust=False).mean()
    atr = _atr(df, 21)
    rsi = _rsi(close, 14)
    range_breakout = close > high.rolling(55, min_periods=20).max().shift(1)
    range_breakdown = close < low.rolling(55, min_periods=20).min().shift(1)
    vol_ok = (atr / close).between(0.001, 0.12)

    signals = blank_signals(df)
    signals["open_long"] = _cooldown((fast > slow) & (close > trend) & range_breakout & (rsi < 78) & vol_ok, 19)
    signals["open_short"] = _cooldown((fast < slow) & (close < trend) & range_breakdown & (rsi > 22) & vol_ok, 19)
    signals["close_long"] = _cooldown(((fast < slow) & (rsi < 48)) | (rsi > 86), 7)
    signals["close_short"] = _cooldown(((fast > slow) & (rsi > 52)) | (rsi < 14), 7)

    pullback_long = (close < fast - atr * 0.55) & (close > trend) & (rsi < 56)
    pullback_short = (close > fast + atr * 0.55) & (close < trend) & (rsi > 44)
    signals["add_long"] = _cooldown(pullback_long, 31)
    signals["add_short"] = _cooldown(pullback_short, 31)
    signals["open_long_quote_amount"] = pd.Series(np.where(signals["open_long"], 1400.0, 0.0), index=df.index)
    signals["open_short_quote_amount"] = pd.Series(np.where(signals["open_short"], 1400.0, 0.0), index=df.index)
    signals["add_long_quote_amount"] = pd.Series(np.where(signals["add_long"], 700.0, 0.0), index=df.index)
    signals["add_short_quote_amount"] = pd.Series(np.where(signals["add_short"], 700.0, 0.0), index=df.index)
    return signals


def layered_basket_martingale(df: pd.DataFrame) -> SignalDict:
    close = df["close"].to_numpy(dtype=float)
    index = df.index
    signals = blank_signals(df)
    open_quote = np.zeros(len(df))
    add_quote = np.zeros(len(df))
    active = False
    entries: list[tuple[float, float]] = []
    next_trigger = 0.0
    max_orders = 15
    base_quote = 180.0
    layer_spacings = [0.006, 0.009, 0.012, 0.016, 0.021]
    martingale = 1.72

    lower = pd.Series(close, index=index).rolling(72, min_periods=24).quantile(0.22).to_numpy()
    mid = pd.Series(close, index=index).rolling(72, min_periods=24).mean().to_numpy()

    for i, price in enumerate(close):
        if i < 80:
            continue
        if not active and price < lower[i] and price < mid[i] * 0.985:
            signals["open_long"].iat[i] = True
            open_quote[i] = base_quote
            entries = [(price, base_quote)]
            active = True
            next_trigger = price * (1 - layer_spacings[0])
            continue

        if not active:
            continue

        total_quote = sum(q for _, q in entries)
        avg = sum(p * q for p, q in entries) / total_quote
        if price >= avg * 1.006 or price <= entries[0][0] * 0.86:
            signals["close_long"].iat[i] = True
            active = False
            entries = []
            next_trigger = 0.0
            continue

        order_no = len(entries)
        if order_no < max_orders and price <= next_trigger:
            layer_no = order_no // 3
            child_no = order_no % 3
            quote = base_quote * (1 + 0.28 * layer_no) * (martingale ** child_no)
            signals["add_long"].iat[i] = True
            add_quote[i] = quote
            entries.append((price, quote))
            spacing = layer_spacings[min(layer_no, len(layer_spacings) - 1)]
            next_trigger = price * (1 - spacing)

    signals["open_long_quote_amount"] = pd.Series(open_quote, index=index)
    signals["add_long_quote_amount"] = pd.Series(add_quote, index=index)
    return signals


def stop_limit_breakout_grid(df: pd.DataFrame) -> SignalDict:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    fast = close.ewm(span=10, adjust=False).mean()
    slow = close.ewm(span=48, adjust=False).mean()
    upper = high.rolling(42, min_periods=20).max().shift(1)
    lower = low.rolling(42, min_periods=20).min().shift(1)
    mid = close.rolling(34, min_periods=15).mean()

    signals = blank_signals(df)
    long_raw = (close > upper) & (fast > slow)
    short_raw = (close < lower) & (fast < slow)
    signals["open_long"] = _cooldown(long_raw.fillna(False), 41)
    signals["open_short"] = _cooldown(short_raw.fillna(False), 41)
    signals["close_long"] = _cooldown((close < mid) | (fast < slow), 23)
    signals["close_short"] = _cooldown((close > mid) | (fast > slow), 23)

    signals["open_long_stop_price"] = pd.Series(np.where(signals["open_long"], high * 1.0004, 0.0), index=df.index)
    signals["open_long_price"] = pd.Series(np.where(signals["open_long"], high * 1.002, 0.0), index=df.index)
    signals["open_short_stop_price"] = pd.Series(np.where(signals["open_short"], low * 0.9996, 0.0), index=df.index)
    signals["open_short_price"] = pd.Series(np.where(signals["open_short"], low * 0.998, 0.0), index=df.index)
    signals["open_long_quote_amount"] = pd.Series(np.where(signals["open_long"], 900.0, 0.0), index=df.index)
    signals["open_short_quote_amount"] = pd.Series(np.where(signals["open_short"], 900.0, 0.0), index=df.index)
    return signals


def run_engine_case(df: pd.DataFrame, signals: SignalDict, config: BacktestConfig) -> dict:
    engine = BacktestEngine(config)
    return engine.run(
        df=df,
        strategy=SignalStrategyAdapter(df, signals, config),
        start_date=df.index[0].to_pydatetime(),
        end_date=df.index[-1].to_pydatetime(),
    )


def run_scenario(scenario: StressScenario) -> dict:
    df = make_synthetic_ohlcv(days=scenario.days, freq=scenario.freq, seed=scenario.seed)
    signals = scenario.signal_factory(df)
    start = perf_counter()
    result = run_engine_case(df, signals, scenario.config)
    elapsed = perf_counter() - start
    validate_result(scenario.name, df, result, min_fills=scenario.min_fills)
    return {
        "name": scenario.name,
        "bars": len(df),
        "seconds": round(elapsed, 4),
        "orders": result["engine"]["orderCount"],
        "fills": result["engine"]["fillCount"],
        "trades": result["totalTrades"],
        "returnPct": result["totalReturn"],
        "maxDrawdownPct": result["maxDrawdown"],
        "intrabarMode": result["engine"]["intrabarMode"],
    }


def validate_result(name: str, df: pd.DataFrame, result: dict, *, min_fills: int = 1) -> None:
    equity = result.get("equityCurve") or []
    assert len(equity) == len(df), f"{name}: equity length mismatch"
    values = np.array([float(item["value"]) for item in equity], dtype=float)
    assert np.isfinite(values).all(), f"{name}: non-finite equity"
    assert (values >= 0).all(), f"{name}: negative equity"
    assert result["engine"]["fillCount"] >= min_fills, f"{name}: too few fills"
    assert result["engine"]["orderCount"] >= result["engine"]["fillCount"], f"{name}: order/fill mismatch"
    assert result["totalCommission"] >= 0, f"{name}: negative commission"


def default_stress_scenarios() -> list[StressScenario]:
    return [
        StressScenario(
            name="one_year_1h_adaptive_momentum_reversal",
            days=365,
            freq="1h",
            timeframe="1H",
            seed=7101,
            signal_factory=adaptive_momentum_reversal,
            config=BacktestConfig(
                initial_capital=100000,
                commission=0.0004,
                slippage=0.0002,
                leverage=3,
                trade_direction="both",
                timeframe="1H",
                entry_pct=0.18,
                stop_loss_pct=0.028,
                take_profit_pct=0.055,
                trailing_enabled=True,
                trailing_pct=0.018,
                trailing_activation_pct=0.035,
                intrabar_mode="balanced",
            ),
            min_fills=10,
        ),
        StressScenario(
            name="six_month_15m_layered_basket_martingale",
            days=180,
            freq="15min",
            timeframe="15m",
            seed=7202,
            signal_factory=layered_basket_martingale,
            config=BacktestConfig(
                initial_capital=60000,
                commission=0.0005,
                slippage=0.00015,
                leverage=2,
                trade_direction="long",
                timeframe="15m",
                entry_pct=0.12,
                stop_loss_pct=0.0,
                take_profit_pct=0.0,
                intrabar_mode="conservative",
            ),
            min_fills=8,
        ),
        StressScenario(
            name="one_year_5m_stop_limit_breakout_grid",
            days=365,
            freq="5min",
            timeframe="5m",
            seed=7303,
            signal_factory=stop_limit_breakout_grid,
            config=BacktestConfig(
                initial_capital=80000,
                commission=0.00045,
                slippage=0.00025,
                leverage=4,
                trade_direction="both",
                timeframe="5m",
                entry_pct=0.1,
                stop_loss_pct=0.018,
                take_profit_pct=0.036,
                intrabar_mode="conservative",
            ),
            min_fills=6,
            max_seconds=45.0,
        ),
    ]


def heavy_stress_scenarios() -> list[StressScenario]:
    return [
        StressScenario(
            name="six_month_1m_adaptive_momentum_reversal",
            days=180,
            freq="1min",
            timeframe="1m",
            seed=7404,
            signal_factory=adaptive_momentum_reversal,
            config=BacktestConfig(
                initial_capital=120000,
                commission=0.0004,
                slippage=0.00018,
                leverage=3,
                trade_direction="both",
                timeframe="1m",
                entry_pct=0.08,
                stop_loss_pct=0.012,
                take_profit_pct=0.024,
                trailing_enabled=True,
                trailing_pct=0.009,
                trailing_activation_pct=0.018,
                intrabar_mode="balanced",
            ),
            min_fills=30,
            max_seconds=90.0,
        ),
        *default_stress_scenarios(),
    ]


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def _cooldown(signal: pd.Series, bars: int) -> pd.Series:
    raw = signal.fillna(False).astype(bool).to_numpy()
    out = np.zeros(len(raw), dtype=bool)
    last = -10**9
    for i, flag in enumerate(raw):
        if flag and i - last >= bars:
            out[i] = True
            last = i
    return pd.Series(out, index=signal.index)
