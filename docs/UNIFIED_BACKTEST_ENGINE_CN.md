# QuantDinger 统一回测引擎与策略契约

本文定义当前统一回测链路的系统契约。它面向后端、前端、AI 生成和 Agent 调用，目标是避免指标、策略、模板各走一套规则。

## 唯一链路

```text
策略资产
  -> 策略适配器
  -> 明确订单意图
  -> BacktestEngine V2
  -> BrokerSimulator
  -> PerformanceAnalyzer
  -> 统一结果 / 统一入库
```

所有可回测资产最终都必须进入 BacktestEngine V2。新策略类型只能新增适配器，不能绕过 V2，也不能新增第二套撮合、资金账户或结果结构。

## 指标与策略边界

### 指标不是策略

当前指标契约是 chart-only：

- 输入：`df`、`params`
- 输出：`output`
- 用途：图表线、标记、灯带、图层、注释和可调参数
- 禁止：订单、仓位、止盈止损、杠杆、回测区间、`# @strategy`、四路执行列

指标可以显示 `buy` / `sell` 标记，但这些标记只用于图表展示，不能直接下单。

### 策略必须显式表达订单意图

当前标准策略是 Script Strategy：

```python
def on_init(ctx):
    ...

def on_bar(ctx, bar):
    ...
```

允许的基础意图：

| 意图 | 含义 |
|------|------|
| `ctx.open_long(...)` | 开多或建立首笔多单 |
| `ctx.add_long(...)` | 多头加仓 |
| `ctx.close_long(...)` | 平多 |
| `ctx.open_short(...)` | 开空或建立首笔空单 |
| `ctx.add_short(...)` | 空头加仓 |
| `ctx.close_short(...)` | 平空 |

`long` 和 `short` 信号不是自动反转。一个只包含 buy/sell 的普通指标默认转成长-only 策略：buy 开多，sell 平多。只有明确要求反转或双向交易时，才把 sell 转为空头开仓。

## Basket 策略规则

篮子/分层策略仍然必须使用明确的订单意图。`ctx.side` 只能是：

- `"long"`
- `"short"`

不能使用 `"open"`、`"close"`、`"buy"`、`"sell"`、`"both"` 等非方向语义。

打开子订单时必须传入两个 keyword-only 参数：

```python
ctx.open_child_order(layer=layer, order=order)
```

缺少 `layer` 或 `order` 会导致运行时报错，不能由回测引擎猜测。

## 回测参数归属

回测中心负责本次运行参数：

- 标的
- 市场类型
- K 线周期
- 起止时间
- 初始资金
- 手续费
- 滑点
- 杠杆
- 资金费率
- 交易方向

策略代码可以声明策略逻辑参数，例如均线周期、冷却 K 数、止损比例、止盈比例等。但不要在代码里硬编码回测面板已经负责的运行环境，除非用户明确要求。

## 风控优先级

风控来源包括：

1. 本次回测中心输入
2. 已保存策略资产配置或代码参数默认值
3. 模板默认值

回测中心输入只影响本次运行。用户点击保存版本后，才写回策略资产。

## 结果结构

V2 回测结果必须包含可以用于前端展示和历史复盘的统一结构：

- `equityCurve`
- `benchmarkCurve`
- `trades`
- `closedTrades`
- `tradeRecords`
- `orders`
- `tradeDirections`
- `engine`
- `executionAssumptions`

前端展示交易记录时应优先使用 `closedTrades` 或 `tradeRecords`，不要把原始流水直接当成完整交易。

## 不可回测时的处理

如果资产类型、代码内容或运行环境不可回测，系统必须明确失败并返回原因，不能返回全 0 假结果。

常见失败包括：

- 指标没有先转换成脚本策略
- 策略代码没有 `on_init` / `on_bar`
- Basket 子订单缺少 `layer` 或 `order`
- 策略试图使用未支持的交易方向
- 现货策略试图做空或使用杠杆

## 策略发布

策略上架市场前必须有至少一条成功回测记录。发布接口和前端弹窗都应阻止没有成功回测的策略上架。

指标发布不要求回测记录，因为指标不是可执行策略。

## AI 生成必须遵守的契约

AI 生成指标时，只输出 chart-only 指标代码。

AI 生成策略时，只输出 Script Strategy 代码。

AI 指标转策略时，必须先理解指标的视觉含义，再按策略系统规则生成显式订单意图。不能把指标里的 `sell` 自动当成开空，不能把图表标记当成可执行订单。

更多细则见：

- [指标开发指南](INDICATOR_DEV_GUIDE_CN.md)
- [策略开发指南](STRATEGY_DEV_GUIDE_CN.md)
