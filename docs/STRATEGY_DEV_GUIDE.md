# QuantDinger Python Strategy Development Guide

This guide describes how to develop trading strategies using Python in the QuantDinger platform. QuantDinger provides a flexible execution environment that supports data access, indicator calculation, and signal generation.

## 1. Overview

Strategies in QuantDinger operate based on the **Signal Provider** mode. The system executes your Python script, which is expected to process market data (a DataFrame) and output trading signals.

The execution flow is as follows:
1.  **Input**: The system injects a `df` (Pandas DataFrame) containing OHLCV data into your script environment.
2.  **Processing**: You use Python (`pandas`, `numpy`) to calculate indicators and define `buy`/`sell` logic.
3.  **Output**: You construct a specific `output` dictionary containing plot data and signals.

---

## 2. Environment & Data

Your script runs in a sandboxed Python environment.

### 2.1 Pre-imported Libraries
The following libraries are available by default (do not `import` them):
*   `pd` (pandas)
*   `np` (numpy)

### 2.2 Input Data (`df`)
A Pandas DataFrame variable named `df` is automatically available in the global scope. It contains the historical market data for the selected symbol and timeframe.

**Columns:**
*   `time`: Timestamp (datetime or int, depending on context, usually localized)
*   `open`: Open price (float)
*   `high`: High price (float)
*   `low`: Low price (float)
*   `close`: Close price (float)
*   `volume`: Trading volume (float)

**Example:**
```python
# Access closing prices
closes = df['close']

# Calculate a Simple Moving Average (SMA)
sma_20 = df['close'].rolling(20).mean()
```

---

## 3. Developing a Strategy

A standard strategy script consists of three parts:
1.  **Indicator Calculation**: Compute technical indicators.
2.  **Signal Generation**: Define logic for Buy and Sell signals.
3.  **Output Construction**: Format the results for the chart and execution engine.

### 3.1 Indicator Calculation
You can use standard Pandas operations to calculate indicators.

```python
# Example: MACD Calculation
short_window = 12
long_window = 26
signal_window = 9

ema12 = df['close'].ewm(span=short_window, adjust=False).mean()
ema26 = df['close'].ewm(span=long_window, adjust=False).mean()
macd = ema12 - ema26
signal_line = macd.ewm(span=signal_window, adjust=False).mean()
```

### 3.2 Signal Generation (Crucial)

You **MUST** create two boolean Series in the `df` or as standalone variables, named `buy` and `sell`.

*   `True` indicates a signal trigger.
*   `False` indicates no signal.

**Important: Edge Triggering**
To avoid repeated signals on consecutive candles (which might lead to multiple orders depending on backend config), it is best practice to use **edge-triggered** signals (signal only on the moment the condition becomes true).

```python
# Condition: Close price crosses above SMA 20
condition_buy = (df['close'] > sma_20) & (df['close'].shift(1) <= sma_20.shift(1))

# Condition: Close price crosses below SMA 20
condition_sell = (df['close'] < sma_20) & (df['close'].shift(1) >= sma_20.shift(1))

# Assign to df (Required for backtesting)
df['buy'] = condition_buy.fillna(False)
df['sell'] = condition_sell.fillna(False)
```

**Note on Signal Types:**
*   QuantDinger normalizes signals based on your strategy configuration (Long-only, Short-only, or Bi-directional).
*   Your script simply outputs "buy" (bullish intent) or "sell" (bearish intent). The backend handles opening/closing positions.

### 3.3 Visual Markers
For charting, you often want to place the signal icon slightly above or below the candle.

```python
# Place Buy marker 0.5% below the Low
buy_marks = [
    df['low'].iloc[i] * 0.995 if df['buy'].iloc[i] else None 
    for i in range(len(df))
]

# Place Sell marker 0.5% above the High
sell_marks = [
    df['high'].iloc[i] * 1.005 if df['sell'].iloc[i] else None 
    for i in range(len(df))
]
```

### 3.4 The `output` Variable (Mandatory)
The final step is to assign a dictionary to the variable `output`. This tells the frontend what to draw and the backend where the signals are.

**Structure:**
```python
output = {
    "name": "My Strategy Name",
    "plots": [ ... ],   # List of lines/indicators to draw
    "signals": [ ... ]  # List of signal markers
}
```

**Plots Schema:**
*   `name`: Legend name (e.g., "SMA 20")
*   `data`: List of values (must match `df` length). Use `.tolist()`.
*   `color`: Hex color string (e.g., "#ff0000").
*   `overlay`: `True` to draw on main chart (price), `False` to draw on separate pane (like RSI/MACD).

**Signals Schema:**
*   `type`: Must be "buy" or "sell".
*   `text`: Text to display on icon (e.g., "B", "S").
*   `data`: List of values (prices) where the icon appears. `None` where no signal.
*   `color`: Icon color.

---

## 4. Complete Example: Dual SMA Crossover

Here is a full, copy-pasteable example of a strategy that buys when SMA(10) crosses above SMA(30) and sells when it crosses below.

```python
# 1. Indicator Calculation
# -----------------------
# Calculate Short and Long SMAs
sma_short = df['close'].rolling(10).mean()
sma_long = df['close'].rolling(30).mean()

# 2. Signal Logic
# -----------------------
# Buy: Short SMA crosses above Long SMA
raw_buy = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))

# Sell: Short SMA crosses below Long SMA
raw_sell = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))

# Clean up NaNs and ensure boolean type
buy = raw_buy.fillna(False)
sell = raw_sell.fillna(False)

# Assign to df columns (CRITICAL for backend execution)
df['buy'] = buy
df['sell'] = sell

# 3. Visual Formatting
# -----------------------
# Calculate marker positions
buy_marks = [
    df['low'].iloc[i] * 0.995 if buy.iloc[i] else None 
    for i in range(len(df))
]

sell_marks = [
    df['high'].iloc[i] * 1.005 if sell.iloc[i] else None 
    for i in range(len(df))
]

# 4. Final Output
# -----------------------
output = {
  'name': 'Dual SMA Strategy',
  'plots': [
    {
        'name': 'SMA 10',
        'data': sma_short.fillna(0).tolist(),
        'color': '#1890ff',
        'overlay': True
    },
    {
        'name': 'SMA 30',
        'data': sma_long.fillna(0).tolist(),
        'color': '#faad14',
        'overlay': True
    }
  ],
  'signals': [
    {
        'type': 'buy',
        'text': 'B',
        'data': buy_marks,
        'color': '#00E676'
    },
    {
        'type': 'sell',
        'text': 'S',
        'data': sell_marks,
        'color': '#FF5252'
    }
  ]
}
```

## 5. Best Practices & Troubleshooting

### 5.1 Handling NaNs
Rolling calculations (like `rolling(14)`) produce `NaN` values at the beginning of the data.
*   **Rule**: Always handle `NaN`s before generating signals.
*   **Fix**: Use `.fillna(0)` or `.fillna(False)` depending on context.

### 5.2 Look-ahead Bias
The system executes trades based on the signal generated at the *close* of a bar.
*   The backtester typically executes the order at the **Open** of the **Next Bar**.
*   Your signal logic should rely on `close` (current completed bar) or `shift(1)` (previous bar). Do not use `shift(-1)`.

### 5.3 Performance
Avoid iterating over the DataFrame rows (`for i in range(len(df)): ...`) for calculation logic. It is slow.
*   **Bad**: Loop to calculate SMA.
*   **Good**: `df['close'].rolling(...)`.
*   **Exception**: Constructing the `buy_marks`/`sell_marks` list usually requires a list comprehension, which is acceptable for visual output.

### 5.4 Debugging
Since you cannot see `print()` output easily in some execution modes, check the backend logs (`backend_api_python/logs/app.log`) if your strategy fails to load.
*   Common error: `KeyError` (wrong column name).
*   Common error: `ValueError` (arrays must be same length). Ensure `plots` data matches `df` length.

