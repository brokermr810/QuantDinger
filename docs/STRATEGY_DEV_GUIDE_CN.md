# QuantDinger 策略开发指南

本文定义当前版本 QuantDinger 的可执行策略开发契约。这里的“策略”指 **ScriptStrategy**：能进入回测中心、创建实盘、产生订单意图并参与市场发布审核的 Python 脚本。

如果你只想画均线、灯带、信号标记或区间，请看 [指标开发指南](./INDICATOR_DEV_GUIDE_CN.md)。指标不能下单，也不能直接回测。指标想交易时，必须先通过“AI 指标转策略”生成 ScriptStrategy，再回测验证。

---

## 1. 三条 AI 生成链路

当前系统有三类核心提示词/契约：

| 入口 | 生成什么 | 关键边界 |
| --- | --- | --- |
| 指标 AI 生成 | Chart Indicator | 只输出 `output` 图表结构，不下单 |
| 首页 AI 策略快捷工具 | ScriptStrategy | 只讲策略运行时规则，直接生成可执行脚本 |
| AI 指标转策略 | ScriptStrategy | 既理解指标视觉信号，又遵守策略运行时规则 |

指标转策略不是简单复制指标代码。它要把视觉信号翻译成明确订单意图。例如 long-only 双均线指标中：

- `Golden` / `buy` -> `open_long`
- `Death` / `sell` -> `close_long`
- 不是自动 `open_short`

只有用户明确要求做空、双向或反转时，才生成 short 路径。

---

## 2. ScriptStrategy 基本结构

每个策略必须包含：

```python
"""
Strategy Name
One or two neutral sentences describing logic, markets, entries, exits, and risk controls.
"""

def on_init(ctx):
    ...

def on_bar(ctx, bar):
    ...
```

规则：

- 文件开头的三引号 docstring 第一行是策略名称。
- 后续非空行是策略描述。
- 不要把策略名称或描述做成 `ctx.param(...)`。
- `on_init(ctx)` 初始化参数和状态。
- `on_bar(ctx, bar)` 每根 bar 执行策略判断。

`bar` 支持：

```python
bar["open"]
bar["high"]
bar["low"]
bar["close"]
bar["volume"]
bar["timestamp"]
```

### 可选代码表头

ScriptStrategy 的元数据分两层：

- 文件开头的三引号 docstring 负责策略名称和策略简介。
- 可选的 `# key: value` 表头只负责少量运行默认值。

推荐结构：

```python
"""
EMA Pullback Long
Trades long pullbacks in an EMA uptrend with optional stop and take-profit controls.
"""
# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: engine

def on_init(ctx):
    ...
```

当前支持的表头：

| 表头 | 可选值 | 含义 |
| --- | --- | --- |
| `# timeframe: 1D` | `1m`, `3m`, `5m`, `15m`, `30m`, `1H`, `4H`, `1D`, `1W` | 代码拥有的默认 K 线周期。回测/实盘快照中会覆盖已保存的面板配置。 |
| `# kline_timeframe: 1D` | 同 `timeframe` | `timeframe` 的别名。 |
| `# signal_timing: next_bar_open` | `next_bar_open`, `same_bar_close` | 信号执行时机。默认并推荐使用 `next_bar_open`。 |
| `# exit_owner: engine` | `engine`, `strategy`, `indicator` | 是否允许服务端风控退出平仓。使用引擎托管的 `# @strategy` 风控注解时用 `engine` 或省略；`strategy` 兼容旧模板，当前运行时仍允许引擎风控；只有 `indicator` 会关闭服务端价格退出。 |

规则：

- symbol、market、交易方向、投入金额、杠杆不要写进表头，它们属于运行面板。
- 不要随手写这些表头。缺省时由运行面板和保存配置决定。
- 优先使用 `next_bar_open`，不要为了模拟下一根开盘成交而手写 `pending_signal` 延迟。
- `same_bar_close` 更乐观，只在用户明确要求同 K 线成交时使用。
- `signal_form` 和 `flip_mode` 是旧指标转换协议字段，新 ScriptStrategy 不建议继续依赖。

### 代码拥有的风控注解

`# @strategy ...` 注解在 ScriptStrategy 里仍然支持。它不是图表指标语法，也不是 `ctx.param(...)` 参数面板旋钮，而是“代码拥有的回测/实盘风控默认值”。回测快照会解析这些注解，并交给执行引擎消费。

示例：

```python
# @strategy entryPct 1
# @strategy stopLossPct 0.04
# @strategy takeProfitPct 0.08
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.015
# @strategy trailingActivationPct 0.03
# @strategy maxHoldingBars 12
# exit_owner: engine
```

当前支持的注解：

| 注解 | 可选值 | 含义 |
| --- | --- | --- |
| `# @strategy entryPct 1` | `0.01` 到 `1` | 每次入场使用运行面板投入金额的比例。`1` 表示 100%。 |
| `# @strategy stopLossPct 0.04` | `0` 到 `1` | 服务端止损比例。`0.04` 表示 4%。 |
| `# @strategy takeProfitPct 0.08` | `0` 到 `5` | 服务端止盈比例。`0.08` 表示 8%。 |
| `# @strategy trailingEnabled true` | `true` / `false` | 配合移动止损参数启用移动止损。 |
| `# @strategy trailingStopPct 0.015` | `0` 到 `1` | 移动止损回撤距离。`0.015` 表示 1.5%。 |
| `# @strategy trailingActivationPct 0.03` | `0` 到 `1` | 浮盈达到该比例后才启动移动止损。 |
| `# @strategy maxHoldingBars 12` | 大于等于 `0` 的整数 | 最多持有多少根 K 线后由引擎退出。`0` 表示关闭。 |

规则：

- 只有当风控应该由代码自身拥有时，才写这些注解。
- 所有百分比类值都用小数比例，不用整数百分比：4% 写 `0.04`，不要写 `4`。
- 回测和实盘快照都会读取这些值。缺省时，除入场比例外，引擎托管风控默认关闭。
- `exit_owner: engine` 允许引擎托管止损、止盈、移动止损、最大持仓 K 线退出。
- `exit_owner: strategy` 是历史模板写法；当前运行时不会把它当成“关闭引擎风控”。新模板优先使用 `engine` 或省略。
- `exit_owner: indicator` 是兼容旧指标转策略链路的高级开关，表示退出完全由代码产生的 `close_*` 意图负责，服务端价格退出不平仓。
- 如果脚本自己实现硬止损、止盈、移动止损或分层退出，不要再写同类 `@strategy` 风控，避免引擎风控和脚本风控重复平仓。
- 网格、DCA、马丁以“交易机器人”形式交付，但仍生成可编辑的标准策略代码。DCA 与马丁在 `on_bar` 中表达状态机；网格在 `on_init` 中通过 `ctx.configure_robot(...)` 声明配置，由宿主提供可靠的挂单、成交轮询和对账能力。
- 不要把这些注解写进图表指标里。

---

## 3. 产品面板和策略代码的分工

运行面板负责：

- symbol / market
- 现货或合约
- 交易方向：long / short / both
- 投入金额
- 杠杆
- 账户、通知和实盘风控开关

策略代码负责：

- 入场、离场、加仓、减仓条件
- 周期、阈值、倍数、层数、冷却期
- 状态管理和防重复下单
- 日志、篮子状态、风险逻辑

不要把运行面板字段写成参数：

```python
# 错误
ctx.direction = ctx.param("direction", "long")
ctx.market_type = ctx.param("market_type", "swap")
ctx.investment_amount = ctx.param("investment_amount", 1000)
ctx.leverage = ctx.param("leverage", 3)
ctx.base_notional = ctx.param("base_notional", 50)
```

需要时读取运行上下文：

```python
direction = ctx.direction
market_type = ctx.market_type
budget = float(ctx.investment_amount or 0)
leverage = float(ctx.leverage or 1)
```

### 回测与实盘运行心智

专业策略链路是：

```text
ScriptStrategy Code
    -> ScriptBacktestRunner
    -> BacktestContext
    -> BrokerSimulator
    -> Trades / Equity Curve / Audit / Replay
```

回测中，策略代码每根 K 线运行一次。默认 `signal_timing: next_bar_open` 时，第 N 根已确认 K 线产生的订单，会在第 N+1 根 K 线开盘交给 broker 成交；成交后 broker 立即更新现金、保证金、持仓、手续费、滑点和权益，下一根 K 线策略读到的是最新账户状态。

实盘中有两个节奏：

- 价格 tick：普通脚本策略默认约每 10 秒同步一次最新价，用于服务端止损、止盈、移动止损、订单状态和通知链路。可通过 `STRATEGY_TICK_INTERVAL_SEC` 调整。
- K 线信号：严格模式默认开启，只在策略周期的 K 线收盘后加载新 K 线并计算一次信号，默认在周期边界后约 2 秒轮询，偏移由 `KLINE_BOUNDARY_POLL_OFFSET_SEC` 控制。

例如用户在 10:20 启动 1H 策略，系统会先加载历史 K 线初始化；之后下一次新的已收盘 1H 信号检查发生在约 11:00:02，而不是 11:20。

严格模式的含义：

- 信号按已收盘 K 线确认，尽量和回测一致。
- 止损、止盈、移动止损按最新价 tick 检查，不等 K 线收盘。
- 同一根 K 线内，普通脚本策略有信号去重和状态机保护，避免“开仓后止损/止盈又在同一根 K 线反复开仓”。
- 非严格模式会用当前价格更新正在形成的 K 线并更频繁评估，响应更快，但结果可能和回测不同。只有用户明确需要盘中实时触发时才建议使用。

### 核心上下文 API

策略代码应只依赖这些核心上下文能力：

| 类别 | API |
| --- | --- |
| 时间和市场 | `ctx.current_dt`, `ctx.symbol`, `ctx.market_type`, `ctx.direction`, `ctx.leverage` |
| 账户 | `ctx.initial_capital`, `ctx.equity`, `ctx.available_cash`, `ctx.available_margin` |
| 持仓 | `ctx.position`, `ctx.positions` |
| 数据 | `ctx.bars(count)` |
| 参数和状态 | `ctx.param(name, default)`, `ctx.state.get(name)`, `ctx.state.set(name, value)` |
| 下单 | `ctx.open_long(...)`, `ctx.close_long(...)`, `ctx.open_short(...)`, `ctx.close_short(...)`, `ctx.order_value(...)`, `ctx.order_target(...)` |
| 诊断 | `ctx.log(...)` |

---

## 4. 参数契约

在 `on_init(ctx)` 中声明策略参数：

```python
def on_init(ctx):
    ctx.fast_period = ctx.param("fast_period", 12)
    ctx.slow_period = ctx.param("slow_period", 36)
    ctx.cooldown_bars = ctx.param("cooldown_bars", 0)
    ctx.stop_loss_pct = ctx.param("stop_loss_pct", 0.0)
    ctx.take_profit_pct = ctx.param("take_profit_pct", 0.0)
```

规则：

- 每个 `ctx.param` 必须有默认值。
- 不要在 `on_bar` 里反复读取 `ctx.param`。
- 只把策略旋钮放进参数，不放 symbol、方向、投入金额、杠杆。
- `*_pct` 使用 0-1 小数：`0.02 = 2%`，`0.8 = 80%`。
- 默认风险项如果用户没有要求，应为 `0` 或关闭。

---

## 5. 显式订单意图

QuantDinger 策略使用显式意图：

| 意图 | 含义 |
| --- | --- |
| `open_long` | 开多或创建多头腿 |
| `close_long` | 平多，只平多，不开空 |
| `open_short` | 开空或创建空头腿 |
| `close_short` | 平空，只平空，不开多 |
| `add_long` | 增加已有多头腿 |
| `add_short` | 增加已有空头腿 |
| `reduce_long` | 部分减少多头腿 |
| `reduce_short` | 部分减少空头腿 |

反转必须拆成两个动作：

```text
close_long -> open_short
close_short -> open_long
```

只有用户明确要求反转/flip 时才写反转逻辑。不要把 `sell`、`close_long` 或 `Death` 自动解释成 `open_short`。

---

## 6. Basket API

推荐新策略优先使用 basket，因为 `notional` 表示计价货币金额，例如 USDT 金额，回测和实盘更容易保持一致。

关键规则：

- `ctx.basket(side)` 只能传 `"long"` 或 `"short"`。
- 如果运行时对象暴露 `ctx.side`，它也只能保存 `"long"` 或 `"short"`，不要用 `"open"`、`"close"`、`"buy"`、`"sell"` 或 `"both"` 表示方向。
- 不能传 `"buy"` 或 `"sell"`。
- `open_child_order(...)` 必须每次显式传 `layer=` 和 `order=`。
- `action` 只能是 `"open"`、`"add"`、`"reduce"`、`"close"`。

映射关系：

| side | action | 策略意图 |
| --- | --- | --- |
| long | open | `open_long` |
| long | add | `add_long` |
| long | reduce | `reduce_long` |
| long | close | `close_long` |
| short | open | `open_short` |
| short | add | `add_short` |
| short | reduce | `reduce_short` |
| short | close | `close_short` |

示例：

```python
ctx.basket("long").open_child_order(
    layer=1,
    order=1,
    notional=quote_amount,
    price=price,
    action="open",
    payload={"reason": "golden_cross"},
)

ctx.basket("long").open_child_order(
    layer=1,
    order=2,
    notional=quote_amount,
    price=price,
    action="close",
    payload={"reason": "death_cross"},
)
```

---

## 7. 直接订单 API

直接 API 适合简单策略：

```python
ctx.open_long(price=price, amount=base_qty, reason="entry")
ctx.add_long(price=price, amount=base_qty, reason="scale_in")
ctx.reduce_long(price=price, amount=base_qty, reason="partial_exit")
ctx.close_long(price=price, reason="exit")

ctx.open_short(price=price, amount=base_qty, reason="entry")
ctx.add_short(price=price, amount=base_qty, reason="scale_in")
ctx.reduce_short(price=price, amount=base_qty, reason="partial_exit")
ctx.close_short(price=price, reason="exit")

ctx.order_value(side="long", value=quote_amount, reason="budget_entry")
ctx.order_target(side="long", target_value=target_quote_amount, reason="rebalance")
```

注意：

- 直接 API 的 `amount` 是基础币数量，不是 USDT 金额。
- `ctx.order_value(...)` 使用计价货币金额下单，适合按预算建仓。
- `ctx.order_target(...)` 表示把目标方向调到指定计价货币敞口，适合再平衡。
- 如果要按投入金额拆单，优先使用 basket 的 `notional`。
- `ctx.buy()` / `ctx.sell()` 是简单方向语义，不适合加仓、反转和复杂脚本。
- AI 生成策略应避免依赖 `ctx.buy()` / `ctx.sell()` 的自动语义。

---

## 8. 状态管理

有冷却、加仓、分层、止盈止损、重入限制的策略必须使用 `ctx.state`。

常见状态：

```python
ctx.state.set("bar_index", current_bar)
ctx.state.set("last_order_bar", current_bar)
ctx.state.set("entry_price", price)
ctx.state.set("layer", 1)
ctx.state.set("pending_entry", False)
ctx.state.set("cooldown_until", current_bar + ctx.cooldown_bars)
```

同一根 bar 防重复：

```python
bar_index = int(ctx.state.get("bar_index", -1) or -1) + 1
ctx.state.set("bar_index", bar_index)

last_order_bar = int(ctx.state.get("last_order_bar", -999999) or -999999)
if last_order_bar == bar_index:
    return

# issue order...
ctx.state.set("last_order_bar", bar_index)
```

不要把所有逻辑写成：

```python
if ctx.position.is_flat():
    ...
    return
```

如果策略需要加仓，持仓后仍然要执行 add / reduce / close 判断。

---

## 9. 现货和合约

现货：

- 只支持 long。
- 杠杆固定为 1。
- short 意图会被拒绝。

合约：

- 支持 long / short / both。
- 杠杆、资金费率、滑点和手续费由运行配置和回测中心处理。

策略可以读取 `ctx.market_type` 和 `ctx.direction` 做保护，但不要把市场类型和方向硬编码为参数。

---

## 10. 风控写法

如果用户没有明确要求，止损止盈默认关闭：

```python
ctx.stop_loss_pct = ctx.param("stop_loss_pct", 0.0)
ctx.take_profit_pct = ctx.param("take_profit_pct", 0.0)
```

简单多头止损止盈：

```python
entry_price = float(ctx.state.get("entry_price", 0.0) or 0.0)
if entry_price > 0 and ctx.position.has_long():
    if ctx.stop_loss_pct > 0 and price <= entry_price * (1.0 - ctx.stop_loss_pct):
        ctx.basket("long").open_child_order(
            layer=1,
            order=99,
            notional=0,
            price=price,
            action="close",
            payload={"reason": "stop_loss"},
        )
        ctx.state.set("last_order_bar", bar_index)
        return
```

更复杂的移动止盈、分批止盈、保本止损需要明确状态字段，避免同一根 bar 重复发单。

---

## 11. 指标转策略规则

转换时必须先理解指标含义：

| 指标视觉信号 | 默认策略解释 |
| --- | --- |
| `buy` / `Golden` / `Bullish` | long-only 下 `open_long` |
| `sell` / `Death` / `Bearish exit` | long-only 下 `close_long` |
| bearish short entry 明确存在 | 可生成 `open_short` |
| 用户明确要求 reversal | `close_*` 后再 `open_*` |
| 用户明确要求 add/reduce | 使用 `add_*` / `reduce_*` 或 basket action |

不要做这些事：

- 把指标 `output` 原样放进策略。
- 把 `sell` 直接写成 `ctx.basket("short").open_child_order(...)`。
- 用 `ctx.basket("buy")` 或 `ctx.basket("sell")`。
- 省略 `layer=` / `order=`。
- 默默添加网格、DCA、马丁、加仓层、主动 TP/SL。

---

## 12. 完整示例：EMA 交叉 long-only 策略

```python
"""
Dual EMA Long Strategy
Long-only EMA crossover strategy. Golden crosses open a long position, death crosses close the long position, and optional stop/take-profit defaults are off.
"""

def on_init(ctx):
    ctx.fast_period = ctx.param("fast_period", 12)
    ctx.slow_period = ctx.param("slow_period", 26)
    ctx.order_pct = ctx.param("order_pct", 1.0)
    ctx.cooldown_bars = ctx.param("cooldown_bars", 0)
    ctx.stop_loss_pct = ctx.param("stop_loss_pct", 0.0)
    ctx.take_profit_pct = ctx.param("take_profit_pct", 0.0)
    ctx.state.set("bar_index", -1)
    ctx.state.set("last_order_bar", -999999)
    ctx.state.set("entry_price", 0.0)

def _ema(values, period):
    if not values:
        return []
    alpha = 2.0 / (float(period) + 1.0)
    out = []
    ema = None
    for value in values:
        price = float(value)
        ema = price if ema is None else alpha * price + (1.0 - alpha) * ema
        out.append(ema)
    return out

def _quote_amount(ctx):
    try:
        budget = float(ctx.investment_amount or 0.0)
    except Exception:
        budget = 0.0
    pct = max(0.0, min(1.0, float(ctx.order_pct or 0.0)))
    return budget * pct

def on_bar(ctx, bar):
    bar_index = int(ctx.state.get("bar_index", -1) or -1) + 1
    ctx.state.set("bar_index", bar_index)

    price = float(bar["close"])
    history = ctx.bars(max(int(ctx.slow_period) + 3, 5))
    closes = [float(item["close"]) for item in history]
    if len(closes) < max(int(ctx.fast_period), int(ctx.slow_period)) + 2:
        return

    fast = _ema(closes, int(ctx.fast_period))
    slow = _ema(closes, int(ctx.slow_period))
    golden = fast[-1] > slow[-1] and fast[-2] <= slow[-2]
    death = fast[-1] < slow[-1] and fast[-2] >= slow[-2]

    last_order_bar = int(ctx.state.get("last_order_bar", -999999) or -999999)
    if last_order_bar == bar_index:
        return
    cooldown_until = int(ctx.state.get("cooldown_until", -1) or -1)
    if cooldown_until >= bar_index:
        return

    entry_price = float(ctx.state.get("entry_price", 0.0) or 0.0)

    if ctx.position.has_long() and entry_price > 0:
        if ctx.stop_loss_pct > 0 and price <= entry_price * (1.0 - float(ctx.stop_loss_pct)):
            ctx.basket("long").open_child_order(layer=1, order=90, notional=0, price=price, action="close", payload={"reason": "stop_loss"})
            ctx.state.set("last_order_bar", bar_index)
            return
        if ctx.take_profit_pct > 0 and price >= entry_price * (1.0 + float(ctx.take_profit_pct)):
            ctx.basket("long").open_child_order(layer=1, order=91, notional=0, price=price, action="close", payload={"reason": "take_profit"})
            ctx.state.set("last_order_bar", bar_index)
            return

    if golden and not ctx.position.has_long():
        quote = _quote_amount(ctx)
        if quote > 0:
            ctx.basket("long").open_child_order(layer=1, order=1, notional=quote, price=price, action="open", payload={"reason": "golden_cross"})
            ctx.state.set("entry_price", price)
            ctx.state.set("last_order_bar", bar_index)
            if int(ctx.cooldown_bars or 0) > 0:
                ctx.state.set("cooldown_until", bar_index + int(ctx.cooldown_bars))
        return

    if death and ctx.position.has_long():
        ctx.basket("long").open_child_order(layer=1, order=2, notional=0, price=price, action="close", payload={"reason": "death_cross"})
        ctx.state.set("entry_price", 0.0)
        ctx.state.set("last_order_bar", bar_index)
```

---

## 13. 发布和回测要求

策略可以保存多个版本。为了避免市场里出现未经验证的代码，发布规则是：

- 代码必须保存为 Script Source。
- 策略必须至少有一条成功回测记录。
- 未回测成功时，发布会被前端和后端拒绝。
- 回测参数、市场、周期、标的和结果应能解释策略用途。

发布前检查：

- 代码能通过校验。
- 没有使用旧指标输出结构。
- 没有把运行面板字段写成 `ctx.param`。
- 没有把 `ctx.basket("buy")` / `ctx.basket("sell")` 写进代码。
- 所有 `open_child_order` 都有 `layer=` 和 `order=`。
- 现货策略没有 short 意图。
- sell/death 语义没有被误写成开空。

---

## 14. 常见校验提示

| 提示 | 含义 | 修复 |
| --- | --- | --- |
| `MISSING_ON_INIT` | 缺少 `on_init(ctx)` | 添加初始化函数 |
| `MISSING_ON_BAR` | 缺少 `on_bar(ctx, bar)` | 添加逐 bar 函数 |
| `CTX_PARAM_MISSING_DEFAULT` | `ctx.param` 没有默认值 | 写成 `ctx.param("name", default)` |
| `CTX_PARAM_RUN_PANEL_FIELD` | 把运行面板字段声明成参数 | 改为读取 `ctx.direction` 等 |
| `INDICATOR_OUTPUT_CONTRACT` | 策略里残留 `output/plots/signals` | 删除指标输出结构 |
| `BASKET_CHILD_ORDER_MISSING_LAYER_ORDER` | 子订单缺少 `layer/order` | 显式传 `layer=` 和 `order=` |
| `BASKET_SIDE_MUST_BE_LONG_OR_SHORT` | basket side 写错 | 只用 `"long"` 或 `"short"` |

---

## 15. 最佳实践

- 先用指标把想法看清楚，再转策略；复杂执行直接写 ScriptStrategy。
- 默认模板应优先覆盖趋势、突破、均线、动量、均值回归、波动率止损等常见策略，不把网格、DCA、马丁作为普通策略模板。
- 策略默认应保守，风险参数默认关闭或低风险。
- 明确区分 open、add、reduce、close。
- 反转必须拆成“先平再开”。
- 加仓必须有层数上限、距离触发、冷却和止损。
- 所有循环都应有明确 lookback，不写无限循环或无界列表。
- 用日志说明重要状态变化，但不要刷屏。
- 每次大改后保存新版本并重新回测。
