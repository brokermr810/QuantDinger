from __future__ import annotations

import pandas as pd


STRATEGY_SAMPLES = {
    "ema_trend_pullback": """
\"\"\"
EMA Trend Pullback Probe
Trend-following pullback entry using fast and slow EMA filters.
\"\"\"
# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.04

def on_init(ctx):
    ctx.fast = ctx.param("fast", 3)
    ctx.slow = ctx.param("slow", 6)
    ctx.pullback_pct = ctx.param("pullback_pct", 0.01)
    ctx.target_pct = ctx.param("target_pct", 0.25)

def _ema(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = values[0]
    for value in values[1:]:
        out = value * k + out * (1.0 - k)
    return out

def on_bar(ctx, bar):
    bars = ctx.bars(int(ctx.slow) + 1)
    if len(bars) < int(ctx.slow) + 1:
        return
    closes = [float(b["close"]) for b in bars]
    fast = _ema(closes[-int(ctx.fast):], int(ctx.fast))
    slow = _ema(closes[-int(ctx.slow):], int(ctx.slow))
    price = float(bar["close"])
    if ctx.positions["long"]["size"] > 0:
        if fast < slow:
            ctx.order_target(0, side="long", reason="ema_exit")
        return
    if fast > slow and price <= fast * (1.0 - float(ctx.pullback_pct)):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side="long", reason="ema_pullback")
""",
    "donchian_breakout": """
\"\"\"
Donchian Breakout Probe
Channel breakout entry with opposite-channel exit.
\"\"\"
# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.05

def on_init(ctx):
    ctx.entry_lookback = ctx.param("entry_lookback", 5)
    ctx.exit_lookback = ctx.param("exit_lookback", 3)
    ctx.target_pct = ctx.param("target_pct", 0.3)

def on_bar(ctx, bar):
    need = max(int(ctx.entry_lookback), int(ctx.exit_lookback)) + 1
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    entry_window = bars[-int(ctx.entry_lookback)-1:-1]
    exit_window = bars[-int(ctx.exit_lookback)-1:-1]
    high = max([float(b["high"]) for b in entry_window])
    exit_low = min([float(b["low"]) for b in exit_window])
    if ctx.positions["long"]["size"] > 0:
        if price < exit_low:
            ctx.order_target(0, side="long", reason="donchian_exit")
        return
    if price > high:
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side="long", reason="donchian_breakout")
""",
    "rsi_mean_reversion": """
\"\"\"
RSI Mean Reversion Probe
RSI exhaustion entry with midline recovery exit.
\"\"\"
# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.04

def on_init(ctx):
    ctx.period = ctx.param("period", 5)
    ctx.oversold = ctx.param("oversold", 35)
    ctx.exit_level = ctx.param("exit_level", 50)
    ctx.target_pct = ctx.param("target_pct", 0.2)

def _rsi(values, period):
    gains = []
    losses = []
    for i in range(len(values) - int(period), len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)

def on_bar(ctx, bar):
    bars = ctx.bars(int(ctx.period) + 1)
    if len(bars) < int(ctx.period) + 1:
        return
    closes = [float(b["close"]) for b in bars]
    rsi = _rsi(closes, int(ctx.period))
    if ctx.positions["long"]["size"] > 0:
        if rsi >= float(ctx.exit_level):
            ctx.order_target(0, side="long", reason="rsi_exit")
        return
    if rsi <= float(ctx.oversold):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side="long", reason="rsi_oversold")
""",
    "macd_momentum": """
\"\"\"
MACD Momentum Probe
MACD line above signal line momentum entry.
\"\"\"
# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.04

def on_init(ctx):
    ctx.fast = ctx.param("fast", 3)
    ctx.slow = ctx.param("slow", 5)
    ctx.signal = ctx.param("signal", 3)
    ctx.target_pct = ctx.param("target_pct", 0.25)

def _ema_series(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = []
    ema = values[0]
    for value in values:
        ema = value * k + ema * (1.0 - k)
        out.append(ema)
    return out

def on_bar(ctx, bar):
    need = int(ctx.slow) + int(ctx.signal) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    closes = [float(b["close"]) for b in bars]
    fast = _ema_series(closes, int(ctx.fast))
    slow = _ema_series(closes, int(ctx.slow))
    macd = [fast[i] - slow[i] for i in range(len(closes))]
    signal = _ema_series(macd, int(ctx.signal))
    bullish = macd[-1] > signal[-1]
    if ctx.positions["long"]["size"] > 0:
        if not bullish:
            ctx.order_target(0, side="long", reason="macd_exit")
        return
    if bullish:
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side="long", reason="macd_entry")
""",
    "bollinger_reversion": """
\"\"\"
Bollinger Reversion Probe
Band-touch mean reversion entry with middle-band exit.
\"\"\"
# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.05

def on_init(ctx):
    ctx.period = ctx.param("period", 5)
    ctx.std_mult = ctx.param("std_mult", 1.2)
    ctx.target_pct = ctx.param("target_pct", 0.2)

def _mean(values):
    return sum(values) / len(values) if values else 0.0

def _std(values):
    mid = _mean(values)
    return (sum([(v - mid) * (v - mid) for v in values]) / len(values)) ** 0.5 if values else 0.0

def on_bar(ctx, bar):
    bars = ctx.bars(int(ctx.period) + 1)
    if len(bars) < int(ctx.period) + 1:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars[-int(ctx.period)-1:-1]]
    mid = _mean(closes)
    dev = _std(closes)
    lower = mid - dev * float(ctx.std_mult)
    if ctx.positions["long"]["size"] > 0:
        if price >= mid:
            ctx.order_target(0, side="long", reason="bollinger_exit")
        return
    if price <= lower:
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side="long", reason="bollinger_touch")
""",
}


def make_probe_frame(name: str) -> pd.DataFrame:
    closes_by_name = {
        "ema_trend_pullback": [100, 104, 108, 112, 116, 120, 112, 117, 121, 125],
        "donchian_breakout": [100, 101, 102, 103, 104, 105, 111, 113, 110, 108],
        "rsi_mean_reversion": [110, 108, 106, 103, 100, 97, 98, 101, 104, 107],
        "macd_momentum": [100, 100, 101, 102, 104, 107, 111, 116, 122, 129, 135, 140],
        "bollinger_reversion": [100, 101, 100, 102, 101, 92, 96, 100, 103, 105],
    }
    closes = closes_by_name[name]
    rows = []
    for i, close in enumerate(closes):
        open_ = closes[i - 1] if i else close
        high = max(open_, close) + 1.0
        low = min(open_, close) - 1.0
        rows.append(
            {
                "time": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": 1000.0 + i,
            }
        )
    frame = pd.DataFrame(rows).set_index("time")
    return frame
