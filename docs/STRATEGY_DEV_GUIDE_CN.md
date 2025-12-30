# QuantDinger Python 策略开发指南

本指南将详细介绍如何在 QuantDinger 平台中使用 Python 开发交易策略。QuantDinger 提供了灵活的执行环境，支持数据访问、指标计算和信号生成。

## 1. 概览

QuantDinger 中的策略基于 **信号提供者 (Signal Provider)** 模式运行。系统执行你的 Python 脚本，该脚本负责处理市场数据（DataFrame）并输出交易信号。

执行流程如下：
1.  **输入**：系统将包含 OHLCV 数据的 `df` (Pandas DataFrame) 注入到你的脚本环境中。
2.  **处理**：你使用 Python (`pandas`, `numpy`) 计算指标并定义 `buy`/`sell` 逻辑。
3.  **输出**：你构造一个特定的 `output` 字典，包含绘图数据和信号。

---

## 2. 环境与数据

你的脚本运行在一个沙盒化的 Python 环境中。

### 2.1 预导入库
以下库默认可用（**无需** `import`）：
*   `pd` (pandas)
*   `np` (numpy)

### 2.2 输入数据 (`df`)
一个名为 `df` 的 Pandas DataFrame 变量会自动存在于全局作用域中。它包含所选代码和时间周期的历史市场数据。

**列 (Columns):**
*   `time`: 时间戳 (datetime 或 int，视上下文而定)
*   `open`: 开盘价 (float)
*   `high`: 最高价 (float)
*   `low`: 最低价 (float)
*   `close`: 收盘价 (float)
*   `volume`: 成交量 (float)

**示例:**
```python
# 获取收盘价序列
closes = df['close']

# 计算简单移动平均线 (SMA)
sma_20 = df['close'].rolling(20).mean()
```

---

## 3. 开发策略

一个标准的策略脚本包含三个部分：
1.  **指标计算**：计算技术指标。
2.  **信号生成**：定义买入和卖出信号逻辑。
3.  **输出构建**：格式化结果以供图表展示和执行引擎使用。

### 3.1 指标计算
你可以使用标准的 Pandas 操作来计算指标。

```python
# 示例：MACD 计算
short_window = 12
long_window = 26
signal_window = 9

ema12 = df['close'].ewm(span=short_window, adjust=False).mean()
ema26 = df['close'].ewm(span=long_window, adjust=False).mean()
macd = ema12 - ema26
signal_line = macd.ewm(span=signal_window, adjust=False).mean()
```

### 3.2 信号生成 (关键)

你 **必须** 在 `df` 中创建（或作为独立变量）两个布尔类型的 Series，分别命名为 `buy` 和 `sell`。

*   `True` 表示触发信号。
*   `False` 表示无信号。

**重要：边缘触发 (Edge Triggering)**
为了避免在连续的 K 线上重复发出信号（这可能导致重复下单，取决于后端配置），最佳实践是使用 **边缘触发** 信号（即只在条件变真的那一刻发出信号）。

```python
# 条件：收盘价上穿 SMA 20
condition_buy = (df['close'] > sma_20) & (df['close'].shift(1) <= sma_20.shift(1))

# 条件：收盘价下穿 SMA 20
condition_sell = (df['close'] < sma_20) & (df['close'].shift(1) >= sma_20.shift(1))

# 赋值给 df (回测必需)
df['buy'] = condition_buy.fillna(False)
df['sell'] = condition_sell.fillna(False)
```

**关于信号类型的说明:**
*   QuantDinger 会根据你的策略配置（仅做多、仅做空或双向）来标准化信号。
*   你的脚本只需输出 "buy"（看涨意图）或 "sell"（看跌意图）。后端会处理开仓/平仓逻辑。

### 3.3 可视化标记
为了在图表上展示，你通常希望将信号图标放在 K 线的上方或下方。

```python
# 将买入标记放在最低价下方 0.5% 处
buy_marks = [
    df['low'].iloc[i] * 0.995 if df['buy'].iloc[i] else None 
    for i in range(len(df))
]

# 将卖出标记放在最高价上方 0.5% 处
sell_marks = [
    df['high'].iloc[i] * 1.005 if df['sell'].iloc[i] else None 
    for i in range(len(df))
]
```

### 3.4 `output` 变量 (必须)
最后一步是将一个字典赋值给变量 `output`。这告诉前端如何绘图，以及告诉后端信号在哪里。

**结构:**
```python
output = {
    "name": "我的策略名称",
    "plots": [ ... ],   # 要绘制的线条/指标列表
    "signals": [ ... ]  # 信号标记列表
}
```

**Plots Schema (绘图配置):**
*   `name`: 图例名称 (例如 "SMA 20")
*   `data`: 数值列表 (必须与 `df` 长度一致)。使用 `.tolist()` 转换。
*   `color`: 十六进制颜色字符串 (例如 "#ff0000")。
*   `overlay`: `True` 表示绘制在主图（价格图）上，`False` 表示绘制在副图（如 RSI/MACD）。

**Signals Schema (信号配置):**
*   `type`: 必须是 "buy" 或 "sell"。
*   `text`: 图标上显示的文本 (例如 "B", "S")。
*   `data`: 数值列表 (价格位置)。无信号处为 `None`。
*   `color`: 图标颜色。

---

## 4. 完整示例：双均线交叉 (Dual SMA)

以下是一个完整的、可复制的双均线策略示例：当 SMA(10) 上穿 SMA(30) 时买入，下穿时卖出。

```python
# 1. 指标计算
# -----------------------
# 计算短期和长期 SMA
sma_short = df['close'].rolling(10).mean()
sma_long = df['close'].rolling(30).mean()

# 2. 信号逻辑
# -----------------------
# 买入：短期 SMA 上穿 长期 SMA
raw_buy = (sma_short > sma_long) & (sma_short.shift(1) <= sma_long.shift(1))

# 卖出：短期 SMA 下穿 长期 SMA
raw_sell = (sma_short < sma_long) & (sma_short.shift(1) >= sma_long.shift(1))

# 清理 NaN 并确保布尔类型
buy = raw_buy.fillna(False)
sell = raw_sell.fillna(False)

# 赋值给 df 列 (后端执行的关键)
df['buy'] = buy
df['sell'] = sell

# 3. 可视化格式化
# -----------------------
# 计算标记位置
buy_marks = [
    df['low'].iloc[i] * 0.995 if buy.iloc[i] else None 
    for i in range(len(df))
]

sell_marks = [
    df['high'].iloc[i] * 1.005 if sell.iloc[i] else None 
    for i in range(len(df))
]

# 4. 最终输出
# -----------------------
output = {
  'name': '双均线策略',
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
        'text': '买',
        'data': buy_marks,
        'color': '#00E676'
    },
    {
        'type': 'sell',
        'text': '卖',
        'data': sell_marks,
        'color': '#FF5252'
    }
  ]
}
```

## 5. 最佳实践与故障排除

### 5.1 处理 NaN
滚动计算（如 `rolling(14)`）会在数据开头产生 `NaN` 值。
*   **规则**：生成信号前必须处理 `NaN`。
*   **修复**：使用 `.fillna(0)` 或 `.fillna(False)`。

### 5.2 未来函数 (Look-ahead Bias)
系统基于 K 线 **收盘** 时产生的信号执行交易。
*   回测引擎通常在 **下一根 K 线的开盘价** 执行订单。
*   你的信号逻辑应依赖 `close` (当前已完成的 K 线) 或 `shift(1)` (前一根 K 线)。切勿使用 `shift(-1)`。

### 5.3 性能
避免在计算逻辑中遍历 DataFrame 行 (`for i in range(len(df)): ...`)。这非常慢。
*   **错误**：使用循环计算 SMA。
*   **正确**：使用 `df['close'].rolling(...)`。
*   **例外**：构建 `buy_marks`/`sell_marks` 列表通常需要列表推导式，这是可接受的（仅用于可视化输出）。

### 5.4 调试
由于在某些执行模式下无法轻易看到 `print()` 输出，如果策略加载失败，请检查后端日志 (`backend_api_python/logs/app.log`)。
*   常见错误：`KeyError` (列名错误)。
*   常见错误：`ValueError` (数组长度不一致)。确保 `plots` 中的数据长度与 `df` 一致。

