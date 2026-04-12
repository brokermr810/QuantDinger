# QuantDinger Python v3策略开发指南

本指南对应 **当前版本** 的 QuantDinger Python 策略架构，覆盖平台已经支持的两条主要开发路径：

- **IndicatorStrategy**：基于 `df` 的指标/信号脚本，用于 Indicator IDE、图表渲染和信号型回测。
- **ScriptStrategy**：基于 `on_init / on_bar` 的事件驱动脚本，用于策略运行时、策略回测与实盘执行。

如果你之前看过旧版文档，需要特别注意：QuantDinger 现在已经不只是单一的 “Signal Provider” 模式，而是包含了持久化策略记录、策略快照解析层、策略回测路由，以及单独的脚本运行时契约。

---

## 1. 架构概览

当前 QuantDinger 支持两种 Python 开发模型。

### 1.1 IndicatorStrategy

这是偏图表与研究的开发路径：

- 你围绕 pandas `df` 编写 Python 逻辑
- 你计算指标，并生成布尔型 `buy` / `sell` 信号
- 你返回 `output` 字典用于前端图表渲染
- 同一份信号逻辑可以直接用于指标回测
- 保存后的指标型策略，也可以进一步进入持久化策略管理流程

适合场景：

- 指标研究
- 图表信号验证
- 参数调优
- 信号型回测

### 1.2 ScriptStrategy

这是偏运行时与执行的开发路径：

- 你实现 `on_init(ctx)` 和 `on_bar(ctx, bar)`
- 系统按 K 线逐根推进执行你的脚本
- 你通过 `ctx.buy()`、`ctx.sell()`、`ctx.close_position()` 下达动作意图
- 同一份策略可以进入策略回测和实盘执行链路

适合场景：

- 需要逐根控制逻辑的策略
- 有状态的策略执行
- bot 型工作流
- 更偏执行和运行时管理的策略

### 1.3 持久化策略流

保存后的策略记录存储在 `qd_strategies_trading` 表中，后端会在回测或执行前解析为统一快照。当前关键字段包括：

- `strategy_type`
- `strategy_mode`
- `strategy_code`
- `indicator_config`
- `trading_config`

当前架构下：

- `IndicatorStrategy` 通常使用 `indicator_config` 中的指标代码
- `ScriptStrategy` 通常使用 `strategy_code`
- 策略回测会使用 `strategy_indicator` 或 `strategy_script` 等 `run_type` 持久化运行结果

---

## 2. 应该选哪种开发模式？

| 使用场景 | 推荐模式 |
|----------|----------|
| 可视化指标开发、叠加到图表上 | `IndicatorStrategy` |
| K 线信号研究与图表验证 | `IndicatorStrategy` |
| 逐根执行的策略逻辑 | `ScriptStrategy` |
| 更偏执行层的 bot 策略 | `ScriptStrategy` |
| 由指标逻辑保存成平台策略 | `IndicatorStrategy` |
| 带显式买卖动作的状态型脚本 | `ScriptStrategy` |

---

## 3. IndicatorStrategy 契约

IndicatorStrategy 代码运行在 Indicator IDE 中，必须满足当前版本的沙盒与输出契约。

### 3.1 运行规则

- `pd` 和 `np` 已经预置可用
- 开头建议先写 `df = df.copy()`
- 预期 dataframe 列包括：`open`、`high`、`low`、`close`、`volume`
- `time` 列可能存在，但不要假设类型固定
- 不要依赖网络、文件 I/O、子进程或危险元编程
- 避免使用 `eval`、`exec`、`open`、`__import__`、`globals` 等破坏沙盒边界的写法

### 3.2 必需全局变量

脚本应定义：

```python
my_indicator_name = "..."
my_indicator_description = "..."
```

### 3.3 必需信号列

回测引擎读取 **布尔型** 信号列：

- `df['buy']`
- `df['sell']`

这些列需要满足：

- 与 `df` 长度完全一致
- 在 `fillna(False)` 后为布尔类型
- 除非你明确需要连续信号，否则建议使用边缘触发

推荐写法：

```python
raw_buy = (df['close'] > ma_fast) & (df['close'].shift(1) <= ma_fast.shift(1))
raw_sell = (df['close'] < ma_fast) & (df['close'].shift(1) >= ma_fast.shift(1))

df['buy'] = (raw_buy.fillna(False) & (~raw_buy.shift(1).fillna(False))).astype(bool)
df['sell'] = (raw_sell.fillna(False) & (~raw_sell.shift(1).fillna(False))).astype(bool)
```

### 3.4 必需 `output` 结构

脚本最后必须赋值一个 `output` 字典：

```python
output = {
    "name": "My Strategy",
    "plots": [],
    "signals": []
}
```

支持的主要键：

- `name`：展示名称
- `plots`：图表线条或指标序列
- `signals`：买卖标记
- `calculatedVars`：可选，供未来 UI 或扩展使用

每个 plot 项通常应包含：

- `name`
- `data`：长度必须与 `len(df)` 完全一致
- `color`
- `overlay`：`True` 或 `False`
- 可选 `type`

每个 signal 项通常应包含：

- `type`：`buy` 或 `sell`
- `text`
- `color`
- `data`：长度与 `df` 一致，无信号的 bar 用 `None`

### 3.5 可选元数据注释

QuantDinger 目前支持通过注释声明参数和默认策略配置。

#### `# @param`

用于声明可调参数：

```python
# @param rsi_len int 14 RSI period
# @param overbought float 70 Overbought threshold
```

#### `# @strategy`

用于声明默认策略配置：

```python
# @strategy stopLossPct 0.03
# @strategy takeProfitPct 0.06
# @strategy entryPct 0.25
# @strategy tradeDirection both
```

当前常用支持项包括：

- `stopLossPct`
- `takeProfitPct`
- `entryPct`
- `trailingEnabled`
- `trailingStopPct`
- `trailingActivationPct`
- `tradeDirection`

不要在这里写 `leverage`，杠杆由产品配置面板控制。

### 3.6 IndicatorStrategy 示例

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

## 4. ScriptStrategy 契约

ScriptStrategy 用于策略运行时和新版策略回测流程。

### 4.1 必需函数

当前产品侧代码校验默认要求你定义：

- `def on_init(ctx): ...`
- `def on_bar(ctx, bar): ...`

运行时在部分内部路径上可以容忍 `on_init` 缺省，但在面向用户的策略创建和验证流程中，建议 **两个都写**。

### 4.2 可用对象

#### `bar`

`bar` 是一根 K 线的轻量对象，通常包含：

- `bar.open`
- `bar.high`
- `bar.low`
- `bar.close`
- `bar.volume`
- `bar.timestamp`

#### `ctx`

当前运行时上下文主要暴露：

- `ctx.param(name, default=None)`
- `ctx.bars(n=1)`
- `ctx.position`
- `ctx.balance`
- `ctx.equity`
- `ctx.log(message)`
- `ctx.buy(price=None, amount=None)`
- `ctx.sell(price=None, amount=None)`
- `ctx.close_position()`

### 4.3 仓位语义

`ctx.position` 是一个有状态对象，当前常见字段包括：

- `side`
- `size`
- `entry_price`
- `direction`
- `amount`

可以这样使用：

```python
if not ctx.position:
    ...

if ctx.position.side == "long":
    ...
```

### 4.4 ScriptStrategy 示例

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

### 4.5 脚本校验说明

当前代码校验接口会检查：

- 代码不为空
- Python 语法可以编译
- 源码文本中同时存在 `on_init` 和 `on_bar`

所以即使脚本对运行时来说逻辑上可用，如果缺少其中一个函数，仍然可能无法通过 UI 校验。

---

## 5. 当前架构下的回测方式

QuantDinger 现在同时支持指标回测和策略回测。

### 5.1 指标回测

指标回测依赖 dataframe 信号列：

- `df['buy']`
- `df['sell']`

系统将信号视为 bar close 确认，并通常在 **下一根 bar 开盘价** 执行。

### 5.2 策略回测

策略回测会先把保存后的策略记录解析成统一快照，再执行。核心字段包括：

- `strategy_type`
- `strategy_mode`
- `strategy_code`
- `indicator_config`
- `trading_config`
- 回测覆盖参数，例如 symbol、timeframe、capital、commission、slippage

当前常见 `run_type` 包括：

- `indicator`
- `strategy_indicator`
- `strategy_script`

### 5.3 当前限制

- `cross_sectional` 策略在当前策略回测快照链路中尚未完整支持。
- `ScriptStrategy` 当前不支持 `cross_sectional` 的实盘运行模式。
- 策略回测要求保存策略具备合法 symbol 且代码不为空。

---

## 6. 最佳实践

### 6.1 始终避免未来函数

- 只使用已完成 bar 的信息
- 优先使用 `shift(1)`
- 不要在信号逻辑中使用 `shift(-1)`

### 6.2 显式处理 NaN

滚动窗口和 EWM 计算都会在前部产生 NaN，生成信号前必须处理。

### 6.3 保持长度完全对齐

所有 `plot['data']` 和 `signal['data']` 的长度都必须与 `len(df)` 完全一致。

### 6.4 IndicatorStrategy 尽量向量化

指标型脚本优先使用 pandas 向量化计算，而不是逐行循环处理核心逻辑。

### 6.5 ScriptStrategy 保持确定性

对于 `ScriptStrategy`：

- 不要在 `ctx` 之外维护隐式状态
- 尽量避免随机逻辑
- 显式通过 `ctx.buy`、`ctx.sell`、`ctx.close_position` 表达动作意图

### 6.6 把配置放在正确层级

- 指标型默认参数用 `# @param` 和 `# @strategy`
- 脚本型默认参数优先用 `ctx.param()`
- 杠杆、交易所、账户凭证等应由产品配置层管理，不应硬编码在脚本中

---

## 7. 故障排除

### 7.1 `column "strategy_mode" does not exist`

说明数据库结构版本落后于当前代码版本，需要对 `qd_strategies_trading` 执行迁移补列。

### 7.2 `Strategy script must define on_bar(ctx, bar)`

说明你的 `ScriptStrategy` 缺少必需的 `on_bar` 处理函数。

### 7.3 `Missing required functions: on_init, on_bar`

说明当前 UI 校验器要求源码中同时存在 `on_init` 和 `on_bar`。

### 7.4 `Strategy code is empty and cannot be backtested`

说明保存后的策略在当前模式下没有有效的 `strategy_code` 或 `indicator_code`。

### 7.5 图表数组长度不一致

所有图表输出数组必须与 `df` 长度严格一致。

### 7.6 后端日志排查

如果策略创建、校验、回测或执行失败，请优先检查后端日志。当前最常见问题包括：

- 数据库结构版本不匹配
- JSON / 配置载荷格式不正确
- 代码校验失败
- 市场 / symbol 不匹配
- 交易所凭证或交易配置异常

---

## 8. 推荐开发流程

1. 先在 Indicator IDE 中以 `IndicatorStrategy` 原型化你的逻辑。
2. 验证图表显示、信号密度，以及 next-bar-open 回测语义是否符合预期。
3. 保存策略并清理元数据与参数。
4. 如果需要逐根控制和运行时状态管理，再迁移到 `ScriptStrategy`，使用 `on_init` / `on_bar`。
5. 保存前先做代码校验。
6. 通过保存后的策略记录执行策略回测。
7. 在确认配置、凭证和市场语义都正确后，再进入模拟盘或实盘执行。

