# QuantDinger 指标开发指南

本文是当前版本 QuantDinger 的指标开发契约。请把它当作指标作者、AI 生成器和代码审查的共同标准。

核心边界只有一句话：**指标只负责看图，不负责交易。**

指标代码用于在 K 线图上绘制曲线、灯带、标记、区域、通道和说明。它不能下单，不能回测，不能实盘，不能声明仓位、杠杆、止盈止损或交易方向。需要交易执行时，请把指标通过“AI 指标转策略”转换为 ScriptStrategy，再在策略页和回测中心验证。

旧文档里出现过的 `IndicatorStrategy`、`# @strategy`、`signal_form`、`exit_owner`、`open_long`、`close_long`、`df["buy"]`、`df["sell"]` 等“指标即策略”写法已经不再是当前指标契约。

---

## 1. 指标和策略的边界

| 类型 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| Chart Indicator | 图表展示、参数调节、视觉信号、辅助分析 | 回测、实盘、下单、仓位、杠杆、风控 |
| ScriptStrategy | 回测、实盘、订单意图、仓位状态、风控、日志 | 指标页的 `output` 图表渲染 |
| Indicator-to-Strategy | 把指标视觉信号翻译成可执行策略 | 在指标代码里直接混入交易执行 |

指标中的 `output["signals"]` 只是图上的标记。比如一个 `sell` 或 `Death` 标记，默认意思是“视觉上的空头/离场提示”，不是自动开空，也不是反手。

如果把一个 long-only 指标转换为策略：

- `buy` / `Golden` / `Bullish` 通常映射为 `open_long`
- `sell` / `Death` / `Bearish exit` 通常映射为 `close_long`
- 只有用户明确要求双向、做空或反转时，才生成 `open_short`

---

## 2. 运行环境

指标运行时提供：

- `df`：当前图表 K 线数据，按时间从旧到新排列。
- `params`：由 `# @param` 声明并由参数面板传入的字典。
- `pd` / `np`：已预置的 pandas / numpy。

常见字段：

```python
open_ = df["open"]
high = df["high"]
low = df["low"]
close = df["close"]
volume = df["volume"]
```

第一条可变操作必须是：

```python
df = df.copy()
```

不要假设一定有 `time` 字段，也不要假设字段类型永远一致。需要使用可选字段时，先判断是否存在。

---

## 3. 安全限制

指标代码运行在沙盒里。禁止：

- 网络请求、文件读写、数据库访问、子进程。
- `eval`、`exec`、`compile`、`open`、`__import__`。
- `globals`、`vars`、`dir`、dunder 绕过、元编程逃逸。
- `getattr` / `setattr` / `delattr` 访问不可信名称。
- 导入 `os`、`sys`、`requests`、`socket`、`subprocess`、`threading`、`sqlite3`、`multiprocessing`、`pathlib`、`tempfile`、`glob`、`io`、`pickle`、`ctypes`、`operator` 等模块。

通常不需要写 `import pandas` 或 `import numpy`，因为 `pd` 和 `np` 已经存在。

---

## 4. 必需元数据

每个指标都应声明：

```python
my_indicator_name = "Dual EMA Viewer"
my_indicator_description = "Chart-only EMA crossover indicator with visual event markers."
```

这些字段会用于指标列表、保存记录、市场展示和 AI 转策略上下文。描述应说明它画什么、标记什么、有哪些关键参数；不要写交易承诺或收益描述。

---

## 5. 参数声明

使用 `# @param` 声明参数：

```python
# @param fast_len int 12 Fast EMA period
# @param slow_len int 26 Slow EMA period
# @param show_marks bool true Show crossover markers
# @param band_pct float 1.5 Channel width percent
```

然后在代码里显式读取：

```python
fast_len = int(params.get("fast_len", 12))
slow_len = int(params.get("slow_len", 26))
show_marks = bool(params.get("show_marks", True))
band_pct = float(params.get("band_pct", 1.5))
```

规则：

- `# @param` 的默认值必须和 `params.get(..., default)` 的默认值一致。
- 参数只控制指标计算和图表展示。
- 不要声明 `direction`、`market_type`、`investment_amount`、`leverage`、`stop_loss`、`take_profit`、`position_size` 等交易配置。
- 布尔默认值在注释里可写 `true` / `false`，Python 里使用 `True` / `False`。

---

## 6. 输出结构

指标必须设置 `output` 字典：

```python
output = {
    "name": my_indicator_name,
    "plots": plots,
    "signals": signals,
    "layers": layers,
}
```

可选字段：

```python
output["calculatedVars"] = {}
```

长度规则非常重要：

- 每个 `plot["data"]` 的长度必须等于 `len(df)`。
- 每个 `signal["data"]` 的长度必须等于 `len(df)`。
- `layers` 不需要逐 bar 数组，但索引、时间和价格必须在当前数据范围内有意义。

---

## 7. plots：连续视觉序列

`plots` 用于曲线、柱状图、灯带、振荡器等连续或半连续序列。

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

字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 图例和左侧标签名称 |
| `data` | 与 `df` 等长的数组 |
| `color` | 推荐 `#RRGGBB` |
| `type` | 可选，常见为 `line`、`bar`、`lamp` |
| `overlay` | `True` 画在主图，`False` 画在副图 |

价格均线、布林带、通道线通常 `overlay=True`。RSI、MACD 柱、灯带通常 `overlay=False`。

处理空值建议：

```python
def to_plot_list(series):
    return [None if pd.isna(v) else float(v) for v in series]
```

不要把价格叠加线的 warm-up 空值硬填成 `0`，否则图表会出现误导性的零线。

---

## 8. signals：视觉事件标记

`signals` 只用于图表标记：

```python
signals = [
    {"type": "buy", "text": "Golden", "color": "#22c55e", "data": buy_marks},
    {"type": "sell", "text": "Death", "color": "#ef4444", "data": sell_marks},
]
```

规则：

- `type` 只能表达视觉方向，常用 `buy` / `sell`。
- `data` 是与 `df` 等长的数组，空位置为 `None`，有标记的位置为价格。
- 默认标记一次性事件，不标记持续状态。
- 持续状态应使用 `plots`、灯带或 `layers` 表达。

推荐事件函数：

```python
def edge(condition):
    s = condition.fillna(False).astype(bool)
    return s & ~s.shift(1).fillna(False)
```

生成 marker：

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

如果用户要求“确认后下一根显示”，可以整体右移：

```python
confirmed_buy = edge(raw_buy).shift(1).fillna(False).astype(bool)
```

---

## 9. layers：稀疏图层

`layers` 用于区域、线段、标签等辅助分析图层。不要默认添加大量图层，只有用户明确要求供需区、支撑阻力、通道、失效区域、溢价/折价区时才使用。

区域：

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

水平线：

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

标签：

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

图层不要模拟订单，不要表达真实止盈止损或仓位。

---

## 10. pandas / numpy 类型陷阱

AI 和手写代码最常见的错误是把 numpy 数组当 pandas Series 用。

危险写法：

```python
x = np.where(close > close.shift(1), close, 0)
ma = x.rolling(10).mean()
```

`np.where` 可能返回 ndarray，ndarray 没有 `.rolling()`。

正确写法：

```python
x = close.where(close > close.shift(1), 0)
ma = x.rolling(10).mean()
```

如果必须包装 ndarray：

```python
arr = np.where(close > close.shift(1), close, 0)
x = pd.Series(arr, index=df.index)
```

必须传 `index=df.index`，否则在 DatetimeIndex 下会静默错位。

---

## 11. 禁止的旧策略字段

指标代码中不要出现：

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

这些字段不会让指标下单。它们只会误导用户和 AI。需要执行时请生成 ScriptStrategy。

---

## 12. 完整示例：双 EMA 图表指标

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

## 13. 指标转策略前的检查清单

在点击“AI 指标转策略”前，请检查：

- 指标能正常运行，`output` 存在。
- `plots` / `signals` 长度等于 `len(df)`。
- 视觉标记是事件而不是持续刷屏。
- `sell` / `Death` 的真实含义已经明确：是 long exit，还是 short entry。
- 是否需要双向交易、反转、加仓、减仓、止损止盈。
- 指标代码里没有旧的执行列和 `# @strategy`。

转换后的策略必须再跑回测。策略发布到市场前，必须至少有一条成功回测记录。

---

## 14. 质量检查常见提示

| 提示 | 含义 | 修复 |
| --- | --- | --- |
| `MISSING_OUTPUT` | 没有设置 `output` | 补完整 output dict |
| `MISSING_DF_COPY` | 没有 `df = df.copy()` | 在计算前添加 |
| `MISSING_INDICATOR_NAME` | 缺少名称 | 添加 `my_indicator_name` |
| `MISSING_INDICATOR_DESCRIPTION` | 缺少描述 | 添加 `my_indicator_description` |
| `PARAM_DEFAULT_MISMATCH` | 参数默认值不一致 | 对齐 `# @param` 和 `params.get` |
| `EXECUTION_COLUMNS_IGNORED_FOR_INDICATOR` | 指标里写了执行列 | 删除执行列，转策略再执行 |
| `STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR` | 指标里写了策略注解 | 删除 `# @strategy` 等旧注解 |
| `NDARRAY_PANDAS_METHOD_MISUSE` | ndarray 被当成 Series | 使用 pandas 原生方法或包装为 Series |

---

## 15. 最佳实践

- 先让图表清楚，再考虑转策略。
- 指标不要“偷偷交易”，策略不要“假装指标”。
- 标记要少而准，持续状态用曲线/灯带。
- 参数默认值要保守、可解释、可复现。
- 不要使用未来函数：`shift(-1)`、`iloc[i + 1]`、居中 rolling 都应避免。
- 发布前先保存版本，避免覆盖好用的旧实现。
