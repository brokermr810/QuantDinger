# QuantDinger v3 Python Strategy Development Guide

This guide documents the **current** Python strategy architecture in QuantDinger. It covers both development paths now supported by the product:

- **IndicatorStrategy**: dataframe-based scripts used in the Indicator IDE, chart rendering, and signal-style backtests.
- **ScriptStrategy**: event-driven scripts used by the strategy runtime, strategy backtesting, and live execution.

If you are upgrading from older docs: QuantDinger is no longer just a single "signal provider" workflow. The current stack includes persisted strategy records, strategy snapshot resolution, dedicated strategy backtest routes, and a separate runtime contract for script-based execution.

---

## 1. Architecture Overview

At a high level, QuantDinger supports two Python authoring models.

### 1.1 IndicatorStrategy

This is the chart-first workflow:

- You write Python against a pandas `df`
- You calculate indicators and boolean `buy` / `sell` signals
- You return an `output` dict for chart rendering
- The same signal logic can be used by the indicator backtest engine
- Saved indicator-based strategies can later be wrapped into persisted trading strategies

This model is the best fit for:

- indicator research
- visual strategy prototyping
- parameter tuning in the Indicator IDE
- signal-based backtests

### 1.2 ScriptStrategy

This is the runtime-first workflow:

- You write `on_init(ctx)` and `on_bar(ctx, bar)` handlers
- QuantDinger executes your script bar by bar
- You place actions through `ctx.buy()`, `ctx.sell()`, and `ctx.close_position()`
- The same stored strategy can be used in strategy backtesting and live execution

This model is the best fit for:

- explicit runtime control
- stateful strategy logic
- bot-like workflows
- execution-oriented strategies

### 1.3 Persisted Strategy Flow

Saved strategies are stored in `qd_strategies_trading` and resolved by the backend into a normalized snapshot for backtesting and execution. Current important fields include:

- `strategy_type`
- `strategy_mode`
- `strategy_code`
- `indicator_config`
- `trading_config`

In current versions:

- `IndicatorStrategy` typically uses indicator code stored in `indicator_config`
- `ScriptStrategy` typically uses `strategy_code`
- strategy backtests are persisted with `run_type` such as `strategy_indicator` or `strategy_script`

---

## 2. Which Development Mode Should You Use?

| Use Case | Recommended Mode |
|----------|------------------|
| Visual indicator development with plots and markers | `IndicatorStrategy` |
| Signal research with K-line overlays | `IndicatorStrategy` |
| Strategy logic managed bar by bar | `ScriptStrategy` |
| Execution-oriented bot logic | `ScriptStrategy` |
| Existing indicator converted into a saved strategy | `IndicatorStrategy` |
| Stateful script with explicit order methods | `ScriptStrategy` |

---

## 3. IndicatorStrategy Contract

IndicatorStrategy code runs in the Indicator IDE and must satisfy the current sandbox and output contract.

### 3.1 Runtime Rules

- `pd` and `np` are already available
- start with `df = df.copy()`
- expected dataframe columns: `open`, `high`, `low`, `close`, `volume`
- a `time` column may exist
- do not rely on network, file I/O, subprocesses, or unsafe metaprogramming
- avoid `eval`, `exec`, `open`, `__import__`, `globals`, and similar sandbox-breaking patterns

### 3.2 Required Globals

Your script should define:

```python
my_indicator_name = "..."
my_indicator_description = "..."
```

### 3.3 Required Signal Columns

The backtest engine reads **boolean** columns from `df`:

- `df['buy']`
- `df['sell']`

These should:

- have exactly the same length as `df`
- be boolean after `fillna(False)`
- be edge-triggered unless repeated signals are explicitly intended

Recommended pattern:

```python
raw_buy = (df['close'] > ma_fast) & (df['close'].shift(1) <= ma_fast.shift(1))
raw_sell = (df['close'] < ma_fast) & (df['close'].shift(1) >= ma_fast.shift(1))

df['buy'] = (raw_buy.fillna(False) & (~raw_buy.shift(1).fillna(False))).astype(bool)
df['sell'] = (raw_sell.fillna(False) & (~raw_sell.shift(1).fillna(False))).astype(bool)
```

### 3.4 Required `output` Structure

Your script must assign a final `output` dictionary:

```python
output = {
    "name": "My Strategy",
    "plots": [],
    "signals": []
}
```

Supported keys:

- `name`: display name
- `plots`: chart series
- `signals`: marker series
- `calculatedVars`: optional future-facing metadata container

Each plot item should contain:

- `name`
- `data` as a list with length exactly `len(df)`
- `color`
- `overlay` as `True` or `False`
- optional `type`

Each signal item should contain:

- `type`: `buy` or `sell`
- `text`
- `color`
- `data`: list with length exactly `len(df)` using `None` for bars without a marker

### 3.5 Optional Metadata Comments

QuantDinger supports inline metadata for indicator-style strategies.

#### `# @param`

Use this for tunable parameters:

```python
# @param rsi_len int 14 RSI period
# @param overbought float 70 Overbought threshold
```

#### `# @strategy`

Use this for strategy defaults:

```python
# @strategy stopLossPct 0.03
# @strategy takeProfitPct 0.06
# @strategy entryPct 0.25
# @strategy tradeDirection both
```

Supported keys include:

- `stopLossPct`
- `takeProfitPct`
- `entryPct`
- `trailingEnabled`
- `trailingStopPct`
- `trailingActivationPct`
- `tradeDirection`

Do not set `leverage` here. The product manages leverage in the backtest or strategy configuration UI.

### 3.6 Indicator Example

```python
my_indicator_name = "Dual SMA Strategy"
my_indicator_description = "Buy when SMA10 crosses above SMA30 and sell on the reverse cross."

df = df.copy()

sma_short = df['close'].rolling(10).mean()
sma_long = df['close'].rolling(30).mean()

raw_buy = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))
raw_sell = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))

buy = (raw_buy.fillna(False) & (~raw_buy.shift(1).fillna(False))).astype(bool)
sell = (raw_sell.fillna(False) & (~raw_sell.shift(1).fillna(False))).astype(bool)

df['buy'] = buy
df['sell'] = sell

buy_marks = [df['low'].iloc[i] * 0.995 if buy.iloc[i] else None for i in range(len(df))]
sell_marks = [df['high'].iloc[i] * 1.005 if sell.iloc[i] else None for i in range(len(df))]

output = {
    "name": my_indicator_name,
    "plots": [
        {
            "name": "SMA 10",
            "data": sma_short.fillna(0).tolist(),
            "color": "#1890ff",
            "overlay": True
        },
        {
            "name": "SMA 30",
            "data": sma_long.fillna(0).tolist(),
            "color": "#faad14",
            "overlay": True
        }
    ],
    "signals": [
        {
            "type": "buy",
            "text": "B",
            "data": buy_marks,
            "color": "#00E676"
        },
        {
            "type": "sell",
            "text": "S",
            "data": sell_marks,
            "color": "#FF5252"
        }
    ]
}
```

---

## 4. ScriptStrategy Contract

ScriptStrategy is used by the strategy runtime and the newer strategy-backtest flow.

### 4.1 Required Functions

Current UI verification expects:

- `def on_init(ctx): ...`
- `def on_bar(ctx, bar): ...`

The runtime can tolerate `on_init` being absent in some internal paths, but for product-facing strategy creation you should define **both**.

### 4.2 Available Objects

#### `bar`

`bar` is a lightweight object with fields such as:

- `bar.open`
- `bar.high`
- `bar.low`
- `bar.close`
- `bar.volume`
- `bar.timestamp`

#### `ctx`

The runtime context currently exposes:

- `ctx.param(name, default=None)` for parameter defaults
- `ctx.bars(n=1)` to get recent bars
- `ctx.position`
- `ctx.balance`
- `ctx.equity`
- `ctx.log(message)`
- `ctx.buy(price=None, amount=None)`
- `ctx.sell(price=None, amount=None)`
- `ctx.close_position()`

### 4.3 Position Semantics

`ctx.position` is a stateful object representing the current runtime position. It includes fields such as:

- `side`
- `size`
- `entry_price`
- `direction`
- `amount`

You can use it for state checks such as:

```python
if not ctx.position:
    ...

if ctx.position.side == "long":
    ...
```

### 4.4 Script Example

```python
def on_init(ctx):
    ctx.log("strategy initialized")


def on_bar(ctx, bar):
    bars = ctx.bars(30)
    if len(bars) < 20:
        return

    closes = [b.close for b in bars]
    ma_fast = sum(closes[-10:]) / 10
    ma_slow = sum(closes[-20:]) / 20

    if not ctx.position and ma_fast > ma_slow:
        ctx.buy(price=bar.close, amount=1)
        return

    if ctx.position and ctx.position.side == "long" and ma_fast < ma_slow:
        ctx.close_position()
```

### 4.5 Script Verification Notes

The current verification endpoint checks:

- code is not empty
- Python syntax compiles
- both `on_init` and `on_bar` exist in the source text

This means a script may be logically valid for the runtime but still fail the UI verifier if one of those functions is missing.

---

## 5. Backtesting in the Current Architecture

QuantDinger now supports both indicator backtests and strategy backtests.

### 5.1 Indicator Backtest

Indicator backtest is driven by dataframe signal columns:

- `df['buy']`
- `df['sell']`

The engine treats signals as bar-close confirmation and typically fills on the **next bar open**.

### 5.2 Strategy Backtest

Strategy backtests now resolve a saved strategy row into a normalized snapshot before execution. Important fields include:

- `strategy_type`
- `strategy_mode`
- `strategy_code`
- `indicator_config`
- `trading_config`
- backtest overrides such as symbol, timeframe, capital, commission, and slippage

Current run types include:

- `indicator`
- `strategy_indicator`
- `strategy_script`

### 5.3 Current Limitations

- Cross-sectional strategies are not yet supported in the current strategy backtest snapshot flow.
- `ScriptStrategy` does not support `cross_sectional` live execution mode.
- Strategy backtests expect a valid symbol and non-empty code source.

---

## 6. Best Practices

### 6.1 Always Avoid Look-Ahead Bias

- Use completed-bar information only
- prefer `shift(1)` over any future-looking pattern
- do not use `shift(-1)` in signal logic

### 6.2 Handle NaNs Explicitly

Rolling and EWM calculations produce leading NaNs. Clean them before signal generation.

### 6.3 Keep Series Lengths Aligned

Every `plot['data']` and `signal['data']` list must match `len(df)` exactly.

### 6.4 Prefer Vectorized Logic for Indicator Scripts

IndicatorStrategy code should use pandas-native operations instead of row-by-row loops for core calculations.

### 6.5 Keep Script Strategies Deterministic

For `ScriptStrategy`, avoid hidden state outside `ctx`, avoid random logic, and make order intent explicit through `ctx.buy`, `ctx.sell`, and `ctx.close_position`.

### 6.6 Keep Config in the Right Layer

- Use `# @param` and `# @strategy` for indicator-style defaults
- use `ctx.param()` for script defaults
- keep leverage, execution venue, and account credentials in product configuration, not hardcoded in strategy code

---

## 7. Troubleshooting

### 7.1 `column "strategy_mode" does not exist`

Your database schema is older than the running code. Run the required migration on `qd_strategies_trading`.

### 7.2 `Strategy script must define on_bar(ctx, bar)`

Your `ScriptStrategy` code is missing the required handler.

### 7.3 `Missing required functions: on_init, on_bar`

The UI verification endpoint currently requires both functions to be present in the source.

### 7.4 `Strategy code is empty and cannot be backtested`

Your saved strategy does not contain valid `strategy_code` or `indicator_code` for the selected mode.

### 7.5 Marker or plot length mismatch

All chart output arrays must align exactly with the dataframe length.

### 7.6 Backend logs

If strategy creation, verification, backtest, or execution fails, inspect backend logs first. Common classes of issues:

- schema mismatch
- invalid JSON/config payloads
- code verification failure
- market or symbol mismatch
- credential / exchange configuration issues

---

## 8. Recommended Development Workflow

1. Prototype the logic as an `IndicatorStrategy` in the Indicator IDE.
2. Validate chart output, signal density, and next-bar-open backtest behavior.
3. Save the strategy with clean metadata and tuned parameters.
4. If you need bar-by-bar control, port it to `ScriptStrategy` using `on_init` / `on_bar`.
5. Verify code before saving.
6. Run strategy backtests on the persisted strategy record.
7. Move to paper or live execution only after configuration, credentials, and market semantics are verified.

