# 截面策略与组合回测改造备忘录

> 状态：核心主链已实现，产品化与生产验收进行中。  
> 目标：支持截面策略、选股策略、定期调仓、组合回测和组合实盘执行。

当前已落地：点时股票池与快照、`portfolio_strategy` 代码资产、`on_rebalance` 运行时、只做多 Top-N 组合回测、下一交易日开盘撮合、目标权重调仓计划、通知/实盘分流、组合机器人部署与调度、Alpaca Paper 订单队列。当前仍需补齐系统股票池的数据供应、交易所日历、基准与归因结果页、人工持仓对账、对冲撮合和生产容量测试。

## 0. 已确认的产品范围

首期组合策略统一使用代码契约和目标权重模型，支持以下标的池：

- 手动股票池。
- 用户自选列表。
- 沪深 300。
- 中证 500。
- 标普 500。
- 纳斯达克 100。
- ETF 池。
- 加密货币市值前 100。
- 港股股票池。

首期策略能力为只做多、Top N、定期轮动，调仓频率支持日频、周频和月频。指数与市值排名必须按历史时点解析成分，禁止用当前成分替代历史成分。

首期只做多闭环稳定后，组合策略扩展对冲能力。对冲不是一个布尔开关，而是三类明确契约：

- 截面多空：买入高分组、卖空低分组，控制总敞口和净敞口。
- 配对 / 价差：多个标的组成同一交易组，按对冲比率建立和退出仓位。
- 组合 Beta 对冲：保留多头组合，同时用可交易 ETF、期货或其他对冲工具把目标 Beta 调整到指定范围。

期权保护属于更后阶段能力，不与第一版股票多空撮合混在一起。

交易机器人不是独立策略引擎，而是“标准策略代码 + 参数 + 标的池或交易对 + 账户 + 运行模式 + 持久状态”的部署实例。网格、DCA 和马丁向导必须生成标准策略代码，用户可以在创建后进入编辑器继续修改。

组合策略与交易机器人统一支持两种执行出口：

- `live`：把通过风控检查的交易指令提交到已连接的券商或交易所。
- `notify_only`：生成完整调仓清单并发送通知，不向券商提交订单，由用户人工执行。

策略代码不得感知或绑定执行出口。策略只生成目标权重，组合运行时计算调仓差额并形成标准交易指令；部署实例再根据执行模式决定实盘提交或仅通知。当前没有实盘通道的 A 股和港股必须支持 `notify_only`，未来接入券商后可以直接切换到 `live`，无需修改策略。

## 1. 背景

当前 QuantDinger 的可执行策略主要是单标的 CTA / Script Strategy：

```text
单个 symbol
  -> on_init(ctx)
  -> on_bar(ctx, bar)
  -> ctx.open_long / close_long / open_short / close_short / add_long / add_short
  -> 单标的仓位与订单
  -> BacktestEngine V2
  -> 单标的回测结果
```

这套链路适合趋势、均线、突破、网格、马丁、篮子分层等围绕一个交易标的运行的策略，但不适合直接承载截面选股策略。

截面策略的核心不是“某个标的什么时候开仓”，而是：

```text
股票池 / 标的池
  -> 多标的数据对齐
  -> 因子计算
  -> 截面打分与排序
  -> 目标持仓 / 目标权重
  -> 调仓订单
  -> 组合净值与组合风险
```

因此，截面策略应该作为新的策略类型与现有 CTA 策略并列，而不是把现有 `on_bar(ctx, bar)` 强行扩展成多标的循环。

## 2. 结论

回测中心必须支持截面策略。

如果只在策略 IDE 增加截面策略代码生成，而回测中心仍然只理解单标的，就会出现以下问题：

- 无法选择股票池或多标的池。
- 无法设置调仓频率、Top N、目标权重、最大单票权重、换手率限制。
- 无法展示组合净值、基准对比、持仓变化、调仓记录、个股贡献。
- 无法保存组合回测结果，市场发布审核也无法判断策略是否有有效回测。
- 无法做后续模拟盘和实盘组合调仓。

所以需要新增一条组合策略链路：

```text
Portfolio Strategy
  -> Portfolio Strategy Runtime
  -> Portfolio Backtest Engine
  -> Portfolio Broker Simulator
  -> Portfolio Analytics
  -> Backtest Center Portfolio Result Views
```

现有 CTA 链路继续保留，不要破坏。

## 3. 术语

| 术语 | 含义 |
| --- | --- |
| CTA 策略 | 当前单标的 Script Strategy，以 K 线事件驱动，用显式订单意图开平仓。 |
| 截面策略 | 在同一时间点比较多个标的，根据因子或规则选出目标组合。 |
| 股票池 / 标的池 | 策略可选择的候选标的集合，例如沪深 300、纳斯达克 100、自定义 watchlist。 |
| 调仓 | 按周期或事件重新计算目标持仓，并把当前持仓调整到目标持仓。 |
| 目标权重 | 每个标的在组合中的目标资金占比，例如 AAPL 10%、MSFT 8%。 |
| 组合净值 | 整个组合随时间变化的权益曲线，而不是单笔交易盈亏。 |
| 换手率 | 本次调仓买卖金额相对组合资产的比例。 |
| 个股贡献 | 某个标的对组合收益、回撤或风险的贡献。 |

## 4. 策略契约建议

### 4.1 新增资产类型

建议新增资产类型：

```text
portfolio_strategy
```

或者更明确地命名：

```text
cross_section_strategy
```

建议产品上显示为“截面策略”或“组合策略”，技术内部可以用 `portfolio_strategy`，因为未来不仅有选股，还可能有资产配置、行业轮动、ETF 轮动、long-short、市场中性等组合策略。

### 4.2 不复用 CTA 的 on_bar 契约

不要让截面策略继续写：

```python
def on_bar(ctx, bar):
    ...
```

因为 `bar` 是单标的 K 线，会误导 AI 和用户把多标的逻辑写成循环下单。

建议新增组合策略契约：

```python
def on_init(ctx):
    ctx.universe = ctx.param("universe", "watchlist")
    ctx.rebalance = ctx.param("rebalance", "weekly")
    ctx.top_n = int(ctx.param("top_n", 20))
    ctx.max_weight = float(ctx.param("max_weight", 0.10))

def on_rebalance(ctx, panel):
    scores = {}

    for symbol, data in panel.items():
        if len(data.close) < 60:
            continue
        momentum = data.close[-1] / data.close[-60] - 1
        volatility = data.close[-20:].std() / data.close[-1]
        scores[symbol] = momentum - volatility

    selected = ctx.rank(scores, descending=True)[:ctx.top_n]
    weight = min(1.0 / max(len(selected), 1), ctx.max_weight)

    targets = {}
    for symbol in selected:
        targets[symbol] = weight

    ctx.set_target_weights(targets)
```

### 4.3 最小 API

第一版建议只开放目标权重，不开放逐笔订单：

```python
ctx.set_target_weights({
    "AAPL": 0.08,
    "MSFT": 0.07,
    "NVDA": 0.05,
})
```

也可以提供辅助方法：

```python
ctx.equal_weight(symbols)
ctx.top_n(scores, n=20)
ctx.long_only_top_n(scores, n=20, max_weight=0.10)
ctx.long_short(scores, long_n=20, short_n=20, gross=1.0)
```

第一版不要让策略直接调用 `ctx.open_long()`、`ctx.close_long()`。截面策略应该输出“目标组合”，由引擎生成调仓订单。

对冲阶段允许带符号目标权重，并显式声明风险预算：

```python
ctx.set_target_weights(
    {"AAPL": 0.25, "MSFT": 0.25, "QQQ": -0.40},
    gross_limit=1.0,
    net_limit=0.20,
    rebalance_group="beta-hedge",
)
```

组合运行时必须校验券商和市场能力，包括是否允许卖空、可借数量、保证金、最小订单、杠杆、交易时段和对冲工具可用性。仅通知模式也必须标明无法自动执行的腿，不能把不可执行组合显示为已对冲。

### 4.4 运行时上下文

`panel` 建议是按 symbol 索引的数据容器：

```python
panel["AAPL"].close
panel["AAPL"].volume
panel["AAPL"].high
panel["AAPL"].low
panel["AAPL"].open
```

或者先用更简单的 DataFrame 字典：

```python
panel = {
    "AAPL": df_aapl,
    "MSFT": df_msft,
}
```

MVP 阶段可以用 DataFrame 字典，后续再封装成更安全的只读对象。

## 5. 回测中心改造

### 5.1 新增回测类型

回测中心现有入口偏向：

- 指标回测
- 策略回测

后续建议调整为：

- 单标的策略回测
- 组合 / 截面策略回测
- 历史记录

如果暂时不改导航，也至少要在策略回测里根据资产类型切换表单。

### 5.2 截面策略配置项

组合回测表单需要新增：

| 配置 | 说明 |
| --- | --- |
| 标的池 | watchlist、手动输入、自定义 universe、指数成分。 |
| 市场 | A 股、美股、Crypto、ETF 等。 |
| 调仓频率 | daily、weekly、monthly、custom。 |
| 调仓日规则 | 每周一、每月第一个交易日、每月最后一个交易日。 |
| 初始资金 | 组合级资金。 |
| 基准 | SPY、沪深 300、BTC、等权基准等。 |
| Top N | 选出排名前 N 个标的。 |
| 权重方式 | 等权、因子权重、市值权重、风险平价。 |
| 最大单票权重 | 防止过度集中。 |
| 最小交易金额 | 太小的调仓不交易。 |
| 最大换手率 | 单次调仓最多换多少仓。 |
| 手续费 | 按市场统一设置。 |
| 滑点 | 按市场统一设置。 |
| 做空开关 | MVP 建议关闭，只做 long-only。 |
| 停牌 / 不可交易处理 | 跳过、保留旧仓、延迟成交。 |

### 5.3 结果页必须新增的视图

单标的结果页的“交易记录”不够用。组合回测需要这些区域：

- 组合净值曲线
- 基准净值曲线
- 超额收益曲线
- 回撤曲线
- 收益指标：总收益、年化收益、波动率、夏普、最大回撤、Calmar
- 交易指标：调仓次数、平均换手率、总手续费、总滑点
- 组合指标：平均持仓数、最大单票权重、现金占比
- 调仓记录表
- 每日 / 每期持仓表
- 个股收益贡献
- 个股风险贡献
- 行业 / 板块暴露，后续阶段实现
- 多空暴露，long-short 阶段实现

### 5.4 历史记录字段

回测历史列表需要能区分：

```text
run_type = strategy_script
run_type = portfolio_strategy
```

历史记录列表中建议新增：

- 策略类型
- 标的池名称
- 标的数量
- 调仓频率
- 基准
- 持仓数量
- 年化收益
- 最大回撤
- 夏普
- 调仓次数

### 5.5 市场发布规则

现有规则是“策略发布到市场前必须有成功回测记录”。截面策略也应该遵守，但成功回测的定义要升级：

- 必须有 `run_type = portfolio_strategy` 的成功回测。
- 必须有非空组合净值曲线。
- 必须有至少 2 个调仓点，避免只跑一天的假回测。
- 必须有实际候选标的数量和最终持仓数量。
- 如果是付费策略，审核页应该展示组合回测摘要。

## 6. 后端改造计划

### 6.1 数据模型

建议新增或扩展这些表。

#### qd_strategy_assets

长期建议把指标、单标的策略、组合策略资产抽象统一；短期可以继续用现有脚本源表，增加类型字段。

最小字段：

```sql
asset_type: strategy_script | portfolio_strategy
strategy_id / source_id
name
description
code
param_schema
metadata
```

#### qd_universes

```sql
id
user_id
name
market
universe_type        -- watchlist / manual / index / dynamic
description
metadata
created_at
updated_at
```

#### qd_universe_members

```sql
id
universe_id
symbol
market
start_date
end_date
weight_hint
metadata
```

`start_date` / `end_date` 很重要。真实指数成分会变化，不能用今天的成分回测过去，否则会有生存者偏差。

#### qd_portfolio_backtest_runs

可以新建，也可以扩展 `qd_backtest_runs`。建议先扩展 `qd_backtest_runs`，保持统一历史入口：

```sql
run_type = portfolio_strategy
asset_type = portfolio_strategy
config_snapshot
result_json
```

如果结果体过大，再拆分子表：

```sql
qd_portfolio_equity_points
qd_portfolio_rebalances
qd_portfolio_holdings
qd_portfolio_orders
qd_portfolio_contributions
```

### 6.2 数据读取

当前单标的回测主要拉一个 symbol 的 K 线。截面策略需要批量拉取并对齐：

```text
symbols + timeframe + date range
  -> fetch candles for every symbol
  -> align trading calendar
  -> fill / skip missing bars according to policy
  -> build panel
```

需要重点处理：

- 某些标的历史数据不足。
- 某些标的中途上市。
- 停牌或缺失 K 线。
- 不同市场交易日不一致。
- 大股票池拉数据性能问题。
- 缓存和任务队列。

MVP 阶段建议限制：

- 只支持日线。
- 股票池最多 100 个标的。
- 回测区间最多 3 年。
- 不做分钟级截面。
- 不做动态指数成分，只做固定 watchlist / 手动列表。

### 6.3 Portfolio Strategy Runtime

新增服务：

```text
app/services/portfolio_strategy_runtime.py
```

职责：

- 加载策略代码。
- 提供 `PortfolioContext`。
- 在调仓日调用 `on_rebalance(ctx, panel)`。
- 收集 `target_weights`。
- 校验目标权重合法性。
- 禁止直接下单。
- 生成与执行出口无关的标准调仓计划。

校验规则：

- 权重必须是数字。
- symbol 必须属于 universe。
- long-only 模式权重不能小于 0。
- 单票权重不能超过 `max_weight`。
- 总权重不能超过 `gross_exposure_limit`。
- 未被选中的旧持仓默认目标权重为 0。

### 6.4 Portfolio Backtest Engine

新增服务：

```text
app/services/portfolio_backtest.py
```

核心流程：

```text
initialize cash
for each trading date:
  mark positions to market
  if rebalance date:
    call on_rebalance
    normalize / validate target weights
    calculate target shares
    generate orders
    apply commission / slippage
    update cash and positions
  record equity / holdings / exposures
calculate analytics
persist result
```

第一版撮合假设：

- 调仓信号在调仓日收盘后生成。
- 订单在下一交易日开盘价成交。
- 如果下一交易日无价格，跳过该标的订单。
- 手续费和滑点由回测中心配置。
- 不支持部分成交。
- 不支持涨跌停，后续 A 股阶段再加。

### 6.5 Portfolio Broker Simulator

组合撮合需要维护：

```python
cash
positions = {
    symbol: {
        "quantity": ...,
        "avg_price": ...,
        "market_value": ...,
        "weight": ...,
        "unrealized_pnl": ...,
    }
}
orders
fills
```

不要复用单标的 broker 的 position 结构硬凑，否则后面展示持仓、贡献、调仓会非常难维护。

### 6.6 Portfolio Analytics

新增：

```text
app/services/portfolio_analytics.py
```

第一版指标：

- total_return
- annual_return
- volatility
- sharpe
- max_drawdown
- calmar
- win_months
- rebalance_count
- turnover
- total_commission
- total_slippage
- average_position_count
- max_position_weight

对冲阶段增加：

- gross_exposure
- net_exposure
- long_exposure
- short_exposure
- portfolio_beta
- hedge_ratio
- borrow_cost
- funding_cost
- margin_usage
- legging_risk

第二版再加：

- benchmark_return
- excess_return
- information_ratio
- beta
- alpha
- sector_exposure
- factor_exposure
- contribution_by_symbol

## 7. 前端改造计划

### 7.1 策略 IDE

新增策略类型选择：

- 单标的 CTA 策略
- 截面 / 组合策略

截面策略模板不展示单标的 `ctx.open_long()` 示例，而展示 `on_rebalance` 和 `ctx.set_target_weights`。

参数区域支持：

- universe
- rebalance_frequency
- top_n
- max_weight
- min_trade_value
- turnover_limit
- benchmark

### 7.2 回测中心

当前回测中心左侧是单标的配置思路。截面策略选择后应该切换为组合配置：

```text
当前策略
策略类型：组合策略

标的池
  - 选择 watchlist
  - 手动输入 symbol
  - 后续：指数成分

调仓
  - daily / weekly / monthly
  - 调仓日规则

组合约束
  - Top N
  - 最大单票权重
  - 最大换手率
  - 最小交易金额

回测环境
  - 初始资金
  - 手续费
  - 滑点
  - 基准
  - 日期范围
```

### 7.3 结果页组件

建议新增组件：

```text
PortfolioEquityChart.vue
PortfolioDrawdownChart.vue
PortfolioMetricsGrid.vue
PortfolioRebalanceTable.vue
PortfolioHoldingsTable.vue
PortfolioContributionTable.vue
PortfolioExposurePanel.vue
```

不要把单标的交易记录表改到过度复杂。组合调仓记录和单笔开平仓记录的语义不同。

### 7.4 历史记录

历史记录筛选支持：

- 全部
- 单标的策略
- 组合策略

组合策略历史详情要能恢复当时的：

- universe
- symbol list
- rebalance frequency
- parameters
- benchmark
- result snapshot

## 8. AI 与提示词改造

需要新增独立契约：

```text
PORTFOLIO_STRATEGY_CONTRACT
```

不要把它混进现有策略契约里。

原因：

- 单标的策略输出订单意图。
- 组合策略输出目标权重。
- AI 如果同时看到两套规则，容易把 `ctx.open_long()` 和 `ctx.set_target_weights()` 混用。

组合策略提示词必须强调：

- 只能生成 `on_init` 和 `on_rebalance`。
- 不要调用 `ctx.open_long`、`ctx.close_long`、`ctx.open_short`、`ctx.add_long`。
- 不要自己模拟现金账户。
- 不要自己计算手续费和滑点。
- 不要使用未来数据。
- 所有标的必须来自 `panel` 或 `ctx.universe`。
- 输出必须是目标权重。
- long-only 默认不允许负权重。
- 没有足够历史数据的标的必须跳过。

## 9. MCP / Agent 改造

Agent Gateway 需要新增能力：

```text
portfolio_strategy.create
portfolio_strategy.validate
portfolio_backtest.run
portfolio_backtest.get
universe.list
universe.create
universe.update_members
```

MCP 返回结果不能只返回单标的交易记录，要支持：

- portfolio metrics
- equity curve
- rebalance records
- holdings snapshot
- warnings
- data coverage diagnostics

Agent 安全规则：

- 默认只能回测，不能实盘调仓。
- 实盘组合调仓必须有单独权限。
- Agent 生成组合策略后必须先通过回测中心验证。

## 10. 市场发布与购买链路

组合策略进入市场时，需要补齐：

- asset_type 支持 `portfolio_strategy`。
- 发布前必须有组合回测成功记录。
- 购买后生成买家的组合策略副本。
- 如果作者下架或删除原始策略，买家仍然能从购买快照恢复。
- 隐藏源码策略仍然只允许调参和回测，不允许查看源码。
- 市场详情页展示组合回测摘要，而不是单标的交易摘要。

购买快照至少保存：

```text
code snapshot
param schema snapshot
universe config snapshot
default benchmark
asset_type = portfolio_strategy
is_hidden_source
```

## 11. 实盘与模拟盘改造

截面策略实盘已进入首版闭环，但当前自动提交只开放给美股股票池与 Alpaca Paper；A 股、港股及未接实盘通道的股票池使用 `notify_only`。

后续实盘组合调仓需要：

- 组合账户状态。
- 当前持仓读取。
- 目标权重转订单。
- 下单前预检查。
- 最大单次交易金额。
- 最大换手率。
- 黑名单 / 白名单。
- 交易时段检查。
- 不可交易标的跳过。
- 调仓审批，至少第一版需要人工确认。

组合部署实例必须保存执行模式：

```text
execution_mode = live | notify_only
```

`notify_only` 不是简化后的提示消息，而应包含可人工执行和审计的完整交易清单：

- 策略、组合、股票池快照和调仓批次 ID。
- 标的、买卖方向、目标权重、当前权重和权重差。
- 建议数量、参考价格、预计金额、手续费估算和币种。
- 生成时间、计划交易日、数据时点和过期时间。
- 被风控拦截、不可交易、数据不足或价格失效的原因。

通知必须具备幂等键，避免同一调仓批次重复推送。通知记录和实盘订单共享同一调仓批次与审计链路。

不要让组合策略一上线就自动实盘调仓。建议先做到：

```text
组合策略 -> 生成调仓建议 -> 用户确认 -> 模拟盘执行
```

再进入：

```text
组合策略 -> 自动模拟盘调仓
```

最后才是：

```text
组合策略 -> 自动实盘调仓
```

## 12. 开源项目参考

### 12.1 Microsoft Qlib

适合参考：

- 因子研究
- 数据集管理
- 模型训练
- 截面预测
- 组合构建

不建议直接把 Qlib 整个嵌入主交易系统。可以作为离线研究 worker 或因子计算参考。

### 12.2 QuantConnect LEAN

适合参考架构：

- Universe Selection
- Alpha Model
- Portfolio Construction
- Risk Management
- Execution

LEAN 的架构很完整，但直接集成成本高。建议学习模块边界，而不是直接替换当前引擎。

### 12.3 RQAlpha

适合参考：

- A 股回测语义
- 多证券组合回测
- 交易日历
- 停牌、涨跌停、手续费处理

如果未来重点做 A 股，RQAlpha 的经验很有价值。

### 12.4 vectorbt

适合参考：

- 快速向量化研究
- 多资产参数扫描
- 因子组合原型

不适合作为主产品的完整实盘执行内核。

## 13. 分阶段实施建议

### Phase 0：文档与边界确认

- 明确当前系统仍是单标的 CTA。
- 标记旧的截面策略指南为历史草稿或重写。
- 新增组合策略契约文档。
- 新增组合回测结果 JSON schema 草案。

### Phase 1：最小可用组合回测

目标：让用户能跑 long-only 选股组合回测。

范围：

- 日线。
- 固定标的池。
- Top N。
- 等权。
- 每周 / 每月调仓。
- 仅做多。
- 下一交易日开盘成交。
- 组合净值、持仓、调仓记录。

不做：

- 分钟级。
- 做空。
- 杠杆。
- 行业中性。
- 动态指数成分。
- 实盘自动调仓。

### Phase 2：产品化回测中心

- 回测中心组合策略表单。
- 组合结果页。
- 组合历史记录。
- 发布审核读取组合回测。
- AI 解释组合回测结果。

### Phase 3：因子与股票池

- 自定义 universe。
- watchlist 转 universe。
- 指数成分导入。
- 因子缓存。
- 数据覆盖率诊断。
- 生存者偏差提示。

### Phase 4：高级组合构建

- 因子权重。
- 波动率倒数权重。
- 风险平价。
- 最大权重约束。
- 行业约束。
- 最大换手约束。
- long-short。

### Phase 5：模拟盘与实盘调仓

- 生成调仓建议。
- 用户确认执行。
- 模拟盘组合调仓。
- 实盘组合调仓权限。
- 调仓审计日志。

## 14. 主要风险

### 14.1 数据风险

截面策略最容易被数据问题污染：

- 生存者偏差。
- 未来函数。
- 停牌数据缺失。
- 指数成分使用了当前成分。
- 财务数据发布时间未对齐。

第一版必须把数据覆盖率和限制写清楚，不要伪装成机构级选股回测。

### 14.2 性能风险

100 个标的 x 3 年日线问题不大，但分钟级或几千只股票会很重。

需要：

- K 线缓存。
- 批量读取。
- 异步任务。
- 结果分表或压缩。
- 回测范围限制。

### 14.3 产品复杂度风险

组合策略表单如果一次性放太多约束，用户会不知道怎么用。

MVP 应该极简：

```text
选股票池 -> 选调仓频率 -> Top N -> 等权 -> 跑回测
```

高级参数折叠起来。

### 14.4 与现有 CTA 混淆

必须在 UI、AI 提示词、文档中反复强调：

- CTA 策略是订单意图。
- 截面策略是目标权重。
- 两者不可混写。

## 15. 建议的结果 JSON 草案

```json
{
  "runType": "portfolio_strategy",
  "engineVersion": "quantdinger-portfolio-backtest-v1",
  "config": {
    "universeId": 1,
    "symbols": ["AAPL", "MSFT"],
    "timeframe": "1D",
    "rebalanceFrequency": "monthly",
    "initialCapital": 100000,
    "commission": 0.0005,
    "slippage": 0.0005,
    "benchmark": "SPY"
  },
  "metrics": {
    "totalReturn": 0.18,
    "annualReturn": 0.12,
    "volatility": 0.16,
    "sharpe": 0.75,
    "maxDrawdown": -0.11,
    "turnover": 1.8,
    "rebalanceCount": 12
  },
  "equityCurve": [
    { "time": "2026-01-02", "equity": 100000, "cash": 100000 }
  ],
  "benchmarkCurve": [
    { "time": "2026-01-02", "equity": 100000 }
  ],
  "rebalances": [
    {
      "time": "2026-02-01",
      "targetWeights": { "AAPL": 0.1, "MSFT": 0.1 },
      "turnover": 0.2,
      "orders": []
    }
  ],
  "holdings": [
    {
      "time": "2026-02-01",
      "positions": [
        { "symbol": "AAPL", "quantity": 10, "marketValue": 2000, "weight": 0.1 }
      ]
    }
  ],
  "diagnostics": {
    "symbolsRequested": 100,
    "symbolsUsed": 87,
    "symbolsSkipped": [
      { "symbol": "XYZ", "reason": "insufficient_history" }
    ]
  }
}
```

## 16. 后续落地前检查清单

- [ ] 是否明确第一版只做 long-only 日线组合回测？
- [ ] 是否确定资产类型命名？
- [ ] 是否确定组合策略 Python 契约？
- [ ] 是否确定 universe 数据来源？
- [ ] 是否确定回测结果 JSON schema？
- [ ] 是否确定回测中心 UI 信息架构？
- [ ] 是否确定市场发布审核规则？
- [ ] 是否确定购买快照字段？
- [ ] 是否确定 Agent / MCP 是否第一版支持？
- [x] 旧 `CROSS_SECTIONAL_STRATEGY_GUIDE_*` 文档已删除，避免误导为当前已支持功能。

## 17. 推荐优先级

推荐先做：

1. 组合策略契约。
2. 日线固定标的池回测。
3. 回测中心组合结果页。
4. 历史记录和发布审核接入。
5. 市场购买快照接入。

暂缓：

- 实盘自动调仓。
- long-short。
- 行业中性。
- 财务因子。
- 动态指数成分。
- 分钟级截面。
