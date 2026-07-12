# 因子库与 Qlib 插件化接入方案备忘录

> 当前目标：建设 CTA 与组合策略共享的因子服务，同时支持技术面与基本面因子；Qlib 保持可选插件，不成为实盘核心路径的强依赖。

> 实现状态：已完成版本化注册表、技术/基本面首批因子、因子目录 API、去极值 Z-score、IC、RankIC 与分组收益研究接口，并接入组合策略 `ctx.factor()`。基本面点时数据供应、行业/市值中性化、ICIR/衰减/相关性页面和 Qlib 插件仍待实现；在这些数据契约完成前，基本面因子不能宣称无未来数据偏差。

## 1. 产品边界

因子库既是研究与发现界面，也是回测和实盘可调用的版本化计算服务。

- 策略页面增加“因子库”入口，打开弹窗查看内置因子和可选 Qlib 因子。
- 因子弹窗支持搜索、分类、市场适配、字段依赖、参数说明、计算公式、代码片段复制。
- 可做少量样本预览，例如选择 BTC/USDT、4H、最近 200 根 K 线，展示因子曲线或最近值。
- CTA 策略继续使用 `on_init(ctx)`、`on_bar(ctx, bar)` 和显式订单意图。
- 组合策略通过 `on_rebalance(ctx, panel)` 读取同一因子服务，输出目标权重。
- 因子结果必须记录因子版本、参数、数据版本、计算时点和标的池快照，保证回测可复现。
- 基本面因子必须使用当时已公开的数据及发布日期，禁止按财报期直接读取后来修订的数据。
- 截面因子必须支持去极值、标准化、可选行业/市值中性化、覆盖率检查和缺失值策略。

### 已确认的因子范围

- 技术面：趋势、动量、反转、波动率、成交量和流动性。
- 基本面：估值、盈利能力、质量、成长、杠杆和现金流。
- 研究评价：IC、RankIC、ICIR、分组收益、换手率、衰减、覆盖率、缺失率、因子相关性和样本外稳定性。
- 使用场景：单标的 CTA、Top N 选股、指数成分选股、ETF 轮动和加密资产轮动。

## 2. AI 决策器设计

AI 决策器是策略运行时能力，不是让 AI 编写因子。策略把某个标的截至当前时点的基本面、量价、K 线、技术指标或文本材料交给用户选择的模型，模型返回受控的交易评价，策略再自行决定是否买卖或如何打分。

建议的策略契约：

```python
opinion = ctx.ai.evaluate(
    profile="stock-review",
    symbol=ctx.symbol,
    prompt="评估未来 5 个交易日的风险收益，仅根据给定数据判断",
    inputs={
        "fundamentals": ctx.fundamentals.as_of(ctx.as_of),
        "technicals": features,
        "bars": ctx.bars.tail(60),
    },
    output="trade_opinion_v1",
)

if opinion.available and opinion.score >= 70 and opinion.confidence >= 0.75:
    ctx.open_long()
```

`profile` 是部署配置中的 AI 模型档案，包含供应商、模型、温度、超时、成本上限、缓存周期和降级规则。API Key 只保存在服务器配置或用户密钥库中，不能写入策略源码。

标准输出 `trade_opinion_v1`：

```json
{
  "action": "buy",
  "score": 78,
  "confidence": 0.82,
  "horizon": "5d",
  "risk_level": "medium",
  "reason_codes": ["trend_confirmed", "valuation_neutral"],
  "summary": "..."
}
```

`action` 只能是 `buy`、`sell` 或 `hold`，`score` 范围固定，`confidence` 必须单独返回。AI 结果只是信号数据，不能包含可执行订单，也不能绕过仓位和风险控制。

### 2.1 调用时机

默认只允许在明确的决策点调用：

- 单标的 CTA 出现候选入场或退出信号时。
- 日线或更低频策略在新完成 K 线后。
- 组合策略调仓日对候选集批量评分。
- 用户手动请求策略复核时。

不允许每个 tick 无限制调用。策略应先用确定性条件缩小候选范围，再让 AI 做确认或排序，避免成本、延迟和噪声失控。

### 2.2 回测与实盘边界

AI 决策器只参与实盘、模拟盘或仅通知运行，不参与回测。回测引擎遇到 `ctx.ai.evaluate()` 或兼容别名 `ctx.ask_ai()` 时：

- 不调用任何外部模型。
- 不扣除 AI 额度。
- 返回明确的 `skipped_in_backtest` 结果。
- 不产生买入、卖出或拦截效果。
- 在结果诊断中记录 AI 决策器调用次数，并提示该部分没有经过回测验证。

策略应为回测提供明确的非 AI 基础逻辑。AI 作为候选信号确认器时，回测采用 `bypass` 语义，让原始技术面或基本面候选信号继续通过；如果买卖或评分完全依赖 AI、没有基础逻辑，回测必须标记为“不支持评估”，不能生成一条看似有效但实际没有覆盖核心逻辑的资金曲线。不允许用当前模型补算历史判断并把结果混入普通回测指标。

实盘可以在决策点创建 AI 请求，策略运行等待有上限的结果；超时、限流、解析失败或低置信度默认返回 `hold`。同一 `strategy + symbol + as_of + prompt_version + input_hash + model_profile_version` 使用相同幂等键，禁止重复计费和重复决策。

每个 AI 决策结果必须记录：

- 决策器 ID、输出 schema 和版本。
- 模型供应商、模型标识和模型快照。
- system prompt、用户模板和完整 prompt 的哈希。
- 输入数据哈希、数据时点、发布时间和系统可用时间。
- 结构化输出、置信度、拒答或错误状态。
- 生成时间、耗时、成本和缓存命中状态。

AI 历史模拟以后可以作为独立研究工具实现，但不得混入普通策略回测，也不能作为上线前已通过回测的证明。

### 2.3 自由提示词与模型选择

用户可以编写提示词，也可以选择模型，但上线策略必须把自由提示词保存成带版本的模板。`ctx.ask_ai()` 可以作为易用别名，发布时编译为 `ctx.ai.evaluate()` 并绑定模型档案、输出 schema 和提示词版本。

必须满足：

- 只接受结构化特征，不允许策略任意读取系统秘密或账户凭证。
- 使用固定 JSON schema，只返回 `score`、`confidence`、`reason_code` 等受控字段。
- 必须有模型白名单、超时、成本上限、幂等键、缓存和确定性降级值。
- 不允许返回订单对象，也不能直接调用下单 API。
- 只有保存完整审计快照后，策略才能消费其判断结果。

产品界面显示为“AI 决策器”，允许选择数据包、提示词模板、模型档案、调用频率、最低置信度、失败策略和预算。普通数值因子继续使用 `ctx.factor()`，两者不混用。

## 3. 内置轻量高质量因子

内置因子应优先选择数据依赖少、解释性强、计算稳定、适合单标的策略引用的因子。

### 趋势类

- `ema_slope`: EMA 斜率，衡量趋势方向和强度。
- `ma_distance`: 收盘价相对均线偏离度。
- `donchian_position`: 当前价格在 Donchian 通道中的位置。
- `adx_trend_strength`: ADX 趋势强度。

### 动量类

- `roc`: N 周期收益率。
- `momentum_zscore`: 动量标准分。
- `macd_histogram`: MACD 柱状图。
- `rsi_momentum`: RSI 动量状态。

### 反转类

- `bollinger_zscore`: 布林带标准化偏离。
- `rsi_reversal`: RSI 超买超卖反转。
- `mean_reversion_distance`: 价格相对滚动均值偏离。

### 波动与风险类

- `atr_pct`: ATR 占价格比例。
- `realized_volatility`: 已实现波动率。
- `range_volatility`: 高低价区间波动。
- `max_drawdown_window`: 滚动最大回撤。

### 成交与流动性类

- `volume_zscore`: 成交量标准分。
- `turnover_proxy`: 成交额代理，`close * volume`。
- `obv_slope`: OBV 斜率。
- `volume_price_confirm`: 量价确认状态。

### 加密市场扩展类

如果后续数据源稳定，可以增加：

- `funding_rate_zscore`: 资金费率标准分。
- `open_interest_change`: 持仓量变化。
- `long_short_ratio`: 多空账户或持仓比。
- `basis_rate`: 现货与合约基差。

## 4. 因子注册表契约

每个因子用统一 metadata 描述，前端弹窗和后端计算都读取同一份注册表。

```json
{
  "factor_id": "ema_slope",
  "name_i18n_key": "factor.ema_slope.name",
  "description_i18n_key": "factor.ema_slope.description",
  "category": "trend",
  "source": "builtin",
  "market_support": ["crypto_spot", "crypto_swap"],
  "required_fields": ["open", "high", "low", "close", "volume"],
  "frequency_support": ["1m", "5m", "15m", "1H", "4H", "1D"],
  "lookback": 60,
  "params_schema": [
    { "name": "period", "type": "int", "default": 20, "min": 2, "max": 500 }
  ],
  "output_type": "series",
  "direction_hint": "higher_is_bullish",
  "stability": "stable"
}
```

## 5. 后端模块建议

建议单独放在 `services/factors/`，不要塞进策略服务。

- `registry.py`: 因子注册表，合并内置和插件因子 metadata。
- `builtin.py`: 内置因子计算函数，输入标准 K 线 DataFrame，输出 Series/DataFrame。
- `preview.py`: 单标的因子预览，负责拉 K 线、校验参数、返回最近值和曲线。
- `qlib_adapter.py`: Qlib 可选接入层，仅在开关启用时加载。
- `schemas.py`: 因子 metadata、参数 schema、预览响应结构。

API 建议：

- `GET /api/factors`: 因子列表，支持分类、来源、关键字过滤。
- `GET /api/factors/{factor_id}`: 因子详情。
- `POST /api/factors/preview`: 单标的样本预览。
- `POST /api/factors/qlib/sync`: 管理员同步 Qlib 因子 metadata。

## 6. Qlib 插件化接入

Qlib 不建议作为核心运行依赖直接绑死。它更适合作为可选插件或独立 worker。

环境变量建议：

```env
FACTOR_QLIB_ENABLED=false
FACTOR_QLIB_PROVIDER=local
FACTOR_QLIB_DATA_DIR=
FACTOR_QLIB_PYTHON=
FACTOR_QLIB_TIMEOUT_SECONDS=30
```

接入原则：

- 默认关闭，避免部署环境没有 Qlib 时影响主系统。
- Qlib 因子只通过 adapter 暴露 metadata 和预览计算。
- 主策略运行时不直接依赖 Qlib，避免实盘路径变慢或不稳定。
- Qlib 数据目录、日历、标的命名必须和系统 symbol master 做映射。

## 7. 前端因子库弹窗

建议在策略页面工具栏增加一个“因子库”按钮，打开 `FactorLibraryModal`。

弹窗结构：

- 左侧：分类筛选，趋势、动量、反转、波动、成交、加密扩展、Qlib。
- 顶部：搜索框、来源筛选、市场筛选、收藏筛选。
- 中间：因子列表，展示名称、说明、字段依赖、适用周期。
- 右侧：因子详情，展示公式、参数、解释、方向含义、代码片段。
- 底部：复制代码、复制参数声明、预览样本。

策略 CTA 代码片段示例：

```python
def _ema_slope(values, period=20):
    if len(values) < period + 2:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    prev = values[-2]
    return (ema - prev) / prev if prev else 0.0
```

## 8. 数据表可选设计

如果第一阶段因子很少，可以先用代码注册表，不急着建表。需要运营后台管理时再落表。

可选表：

- `qd_factor_definitions`: 因子定义、metadata、启用状态。
- `qd_factor_favorites`: 用户收藏。
- `qd_factor_preview_cache`: 预览缓存，减少重复计算。
- `qd_factor_plugin_sources`: 插件来源，例如 Qlib、本地包、远程 worker。

## 9. 分阶段落地

### 阶段一：内置因子弹窗

- 内置 20 个左右高质量因子。
- 策略页面可打开弹窗。
- 可复制 CTA 代码片段。
- 支持单标的预览。

### 阶段二：Qlib 插件 metadata 接入

- 增加 Qlib 开关和 adapter。
- 同步 Qlib 因子列表。
- 支持管理员配置 Qlib 数据目录。

### 阶段三：因子实验台

- 单因子预览。
- 分组统计、IC/RankIC、稳定性、缺失率。
- 仍不直接改变策略执行模型。

### 阶段四：组合 / 截面策略

只有当组合回测引擎、调仓契约、订单撮合、市场发布规则都成熟后，再把因子库接入截面策略。

## 10. 暂不做事项

- 不在现有策略创建流程里暴露截面策略。
- 不让 `on_bar(ctx, bar)` 伪装成多标的选股。
- 不在实盘路径里直接调用 Qlib。
- 不把半成品 `symbol_list`、`portfolio_size`、`rebalance_frequency` 字段继续留在当前 CTA 策略链路。
