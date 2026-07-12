# QuantDinger Indicator Development Guide

This guide defines the current QuantDinger indicator contract. It is the shared reference for human authors, AI generators, validators, and reviewers.

The core boundary is simple: **an indicator is for chart display only, not trading execution.**

Indicator code draws plots, lamps, markers, zones, channels, labels, and other chart annotations. It must not place orders, backtest, run live trading, size positions, set leverage, or define stop-loss/take-profit execution. To trade an idea, convert the indicator through the Indicator-to-Strategy workflow and validate the generated ScriptStrategy in the strategy page and backtest center.

Legacy `IndicatorStrategy`, `# @strategy`, `signal_form`, `exit_owner`, `open_long`, `close_long`, `df["buy"]`, and `df["sell"]` patterns are no longer part of the indicator contract.

---

## 1. Product Boundary

| Asset | Owns | Does Not Own |
| --- | --- | --- |
| Chart Indicator | chart visuals, parameters, visual markers, analysis overlays | backtest, live trading, orders, positions, leverage, risk execution |
| ScriptStrategy | backtest, live trading, order intents, position state, risk, logs | indicator `output` rendering |
| Indicator-to-Strategy | translation from visual signal meaning to executable strategy | mixing execution behavior into indicator code |

`output["signals"]` are visual markers only. A `sell` or `Death` marker means a bearish or exit visual context; it does not automatically open a short or reverse a position.

For a long-only indicator conversion:

- `buy` / `Golden` / `Bullish` usually maps to `open_long`
- `sell` / `Death` / `Bearish exit` usually maps to `close_long`
- `open_short` is generated only when the user explicitly asks for shorting, both-side trading, or reversal behavior

---

## 2. Runtime Environment

The runtime provides:

- `df`: the current chart's K-line DataFrame, ordered oldest to newest.
- `params`: a dict populated from `# @param` declarations and the parameter panel.
- `pd` / `np`: preloaded pandas and numpy handles.

Common columns:

```python
open_ = df["open"]
high = df["high"]
low = df["low"]
close = df["close"]
volume = df["volume"]
```

Start mutable work with:

```python
df = df.copy()
```

Do not assume a `time` column always exists or always has the same dtype.

---

## 3. Sandbox Rules

Indicator code runs inside a sandbox. Do not use:

- network calls, file I/O, database access, subprocesses
- `eval`, `exec`, `compile`, `open`, `__import__`
- `globals`, `vars`, `dir`, dunder escapes, sandbox-breaking metaprogramming
- `getattr`, `setattr`, or `delattr` against untrusted names
- imports such as `os`, `sys`, `requests`, `socket`, `subprocess`, `threading`, `sqlite3`, `multiprocessing`, `pathlib`, `tempfile`, `glob`, `io`, `pickle`, `ctypes`, or `operator`

Usually you do not need `import pandas` or `import numpy`; `pd` and `np` already exist.

---

## 4. Required Metadata

Every indicator should define:

```python
my_indicator_name = "Dual EMA Viewer"
my_indicator_description = "Chart-only EMA crossover indicator with visual event markers."
```

These fields are used in lists, saved records, marketplace displays, and AI conversion context. Describe what the indicator draws and what its parameters mean; do not make trading-performance claims.

---

## 5. Parameters

Declare tunable parameters with `# @param`:

```python
# @param fast_len int 12 Fast EMA period
# @param slow_len int 26 Slow EMA period
# @param show_marks bool true Show crossover markers
# @param band_pct float 1.5 Channel width percent
```

Read them explicitly:

```python
fast_len = int(params.get("fast_len", 12))
slow_len = int(params.get("slow_len", 26))
show_marks = bool(params.get("show_marks", True))
band_pct = float(params.get("band_pct", 1.5))
```

Rules:

- The declared default must match the `params.get(..., default)` fallback.
- Parameters control calculation and display only.
- Do not declare trading configuration such as `direction`, `market_type`, `investment_amount`, `leverage`, `stop_loss`, `take_profit`, or `position_size`.
- Boolean defaults may be written as `true` / `false` in comments and `True` / `False` in Python.

---

## 6. Output Shape

Set an `output` dict:

```python
output = {
    "name": my_indicator_name,
    "plots": plots,
    "signals": signals,
    "layers": layers,
}
```

Optional:

```python
output["calculatedVars"] = {}
```

Length rules:

- Every `plot["data"]` must have length `len(df)`.
- Every `signal["data"]` must have length `len(df)`.
- `layers` do not need per-bar arrays, but their indices/times/prices must be meaningful for the current data.

---

## 7. plots

Use `plots` for lines, histograms, lamps, oscillators, and other per-bar visual series.

```python
plots = [
    {
        "name": "EMA Fast",
        "data": ema_fast_values,
        "color": "#22c55e",
        "type": "line",
        "overlay": True,
    },
    {
        "name": "RSI",
        "data": rsi_values,
        "color": "#3b82f6",
        "type": "line",
        "overlay": False,
    },
]
```

Price moving averages, bands, and channels usually use `overlay=True`. RSI, MACD histograms, and lamp rows usually use `overlay=False`.

For missing values:

```python
def to_plot_list(series):
    return [None if pd.isna(v) else float(v) for v in series]
```

Avoid filling price overlays with zero during warm-up periods; that creates misleading chart lines.

---

## 8. signals

Use `signals` for visual event markers:

```python
signals = [
    {"type": "buy", "text": "Golden", "color": "#22c55e", "data": buy_marks},
    {"type": "sell", "text": "Death", "color": "#ef4444", "data": sell_marks},
]
```

Rules:

- `type` is a visual direction, commonly `buy` or `sell`.
- `data` is a list of `None` or float prices with length `len(df)`.
- Mark one-bar events by default, not continuous states.
- Continuous regimes belong in `plots`, lamp rows, or `layers`.

Recommended edge helper:

```python
def edge(condition):
    s = condition.fillna(False).astype(bool)
    return s & ~s.shift(1).fillna(False)
```

Marker generation:

```python
buy_signal = edge(ema_fast > ema_slow)
sell_signal = edge(ema_fast < ema_slow)

buy_marks = [
    float(df["low"].iloc[i] * 0.995) if bool(buy_signal.iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(df["high"].iloc[i] * 1.005) if bool(sell_signal.iloc[i]) else None
    for i in range(len(df))
]
```

For "show after confirmation", shift the event:

```python
confirmed_buy = edge(raw_buy).shift(1).fillna(False).astype(bool)
```

---

## 9. layers

Use `layers` for sparse chart annotations such as supply/demand zones, support/resistance, channels, invalidation ranges, and labels. Do not add many layers by default.

Zone:

```python
{
    "type": "zone",
    "startIndex": 120,
    "endIndex": 180,
    "top": 105.2,
    "bottom": 101.8,
    "text": "Demand",
    "fillColor": "#22c55e",
    "borderColor": "#22c55e",
    "opacity": 0.12,
}
```

Line:

```python
{
    "type": "line",
    "startIndex": 100,
    "endIndex": len(df) - 1,
    "price": 98.5,
    "text": "Support",
    "color": "#f59e0b",
    "dashed": True,
}
```

Labels:

```python
{
    "type": "label",
    "index": len(df) - 1,
    "price": float(df["close"].iloc[-1]),
    "text": "Trend weakens",
    "color": "#ef4444",
    "textColor": "#ffffff",
}
```

Layers are still visual only. Do not use them as orders or risk rules.

---

## 10. pandas / numpy Type Pitfalls

The most common AI-generated bug is treating ndarray values as pandas Series.

Bad:

```python
x = np.where(close > close.shift(1), close, 0)
ma = x.rolling(10).mean()
```

`np.where` may return ndarray, and ndarray has no `.rolling()`.

Good:

```python
x = close.where(close > close.shift(1), 0)
ma = x.rolling(10).mean()
```

If wrapping ndarray is necessary:

```python
arr = np.where(close > close.shift(1), close, 0)
x = pd.Series(arr, index=df.index)
```

Always pass `index=df.index`; otherwise DatetimeIndex alignment can silently break calculations.

---

## 11. Legacy Execution Fields Are Forbidden

Do not write these in indicator code:

```python
# @strategy stopLossPct 0.02
# signal_form: four_way
# exit_owner: engine
# flip_mode: R2

df["buy"] = ...
df["sell"] = ...
df["open_long"] = ...
df["close_long"] = ...
df["open_short"] = ...
df["close_short"] = ...
df["add_long"] = ...
df["reduce_long"] = ...
```

These fields do not make an indicator trade. They only confuse users and AI generators. Use ScriptStrategy for execution.

---

## 12. Full Example: Dual EMA Viewer

```python
# @param fast_len int 12 Fast EMA period
# @param slow_len int 26 Slow EMA period
# @param confirm_next_bar bool false Show markers one bar after confirmation

my_indicator_name = "Dual EMA Viewer"
my_indicator_description = "Chart-only EMA crossover indicator with visual event markers."

df = df.copy()

fast_len = int(params.get("fast_len", 12))
slow_len = int(params.get("slow_len", 26))
confirm_next_bar = bool(params.get("confirm_next_bar", False))

close = df["close"]
high = df["high"]
low = df["low"]

def edge(condition):
    s = condition.fillna(False).astype(bool)
    return s & ~s.shift(1).fillna(False)

def to_plot_list(series):
    return [None if pd.isna(v) else float(v) for v in series]

ema_fast = close.ewm(span=fast_len, adjust=False).mean()
ema_slow = close.ewm(span=slow_len, adjust=False).mean()

golden = edge(ema_fast > ema_slow)
death = edge(ema_fast < ema_slow)

if confirm_next_bar:
    golden = golden.shift(1).fillna(False).astype(bool)
    death = death.shift(1).fillna(False).astype(bool)

buy_marks = [
    float(low.iloc[i] * 0.995) if bool(golden.iloc[i]) else None
    for i in range(len(df))
]
sell_marks = [
    float(high.iloc[i] * 1.005) if bool(death.iloc[i]) else None
    for i in range(len(df))
]

output = {
    "name": my_indicator_name,
    "plots": [
        {
            "name": "EMA Fast",
            "data": to_plot_list(ema_fast),
            "color": "#22c55e",
            "type": "line",
            "overlay": True,
        },
        {
            "name": "EMA Slow",
            "data": to_plot_list(ema_slow),
            "color": "#3b82f6",
            "type": "line",
            "overlay": True,
        },
    ],
    "signals": [
        {"type": "buy", "text": "Golden", "color": "#22c55e", "data": buy_marks},
        {"type": "sell", "text": "Death", "color": "#ef4444", "data": sell_marks},
    ],
    "layers": [],
}
```

---

## 13. Before Converting an Indicator to a Strategy

Check:

- The indicator runs successfully and sets `output`.
- Plot and signal arrays all have length `len(df)`.
- Markers are events, not repeated state spam.
- The meaning of `sell` / `Death` is clear: long exit or short entry.
- Requirements for both-side trading, reversal, scale-in, scale-out, and risk controls are explicit.
- The indicator contains no legacy execution columns or `# @strategy` annotations.

Generated strategies must be backtested. A strategy cannot be published to the marketplace until it has at least one successful backtest record.

---

## 14. Common Quality Hints

| Hint | Meaning | Fix |
| --- | --- | --- |
| `MISSING_OUTPUT` | `output` is missing | Add a complete output dict |
| `MISSING_DF_COPY` | `df = df.copy()` is missing | Add it before calculations |
| `MISSING_INDICATOR_NAME` | name metadata is missing | Add `my_indicator_name` |
| `MISSING_INDICATOR_DESCRIPTION` | description metadata is missing | Add `my_indicator_description` |
| `PARAM_DEFAULT_MISMATCH` | parameter defaults disagree | Align `# @param` and `params.get` |
| `EXECUTION_COLUMNS_IGNORED_FOR_INDICATOR` | execution columns were detected | Remove them; convert to strategy for execution |
| `STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR` | strategy annotations were detected | Remove old `# @strategy` style annotations |
| `NDARRAY_PANDAS_METHOD_MISUSE` | ndarray is used as Series | Use pandas-native ops or wrap with index |

---

## 15. Best Practices

- Make the chart readable before converting to a strategy.
- Indicators should not secretly trade; strategies should not pretend to be indicators.
- Keep markers sparse and meaningful.
- Use plots/lamp rows for persistent regimes.
- Keep defaults conservative and reproducible.
- Avoid future leaks: no `shift(-1)`, no `iloc[i + 1]`, no centered rolling.
- Save versions before large rewrites.
