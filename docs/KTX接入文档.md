# KTX 交易所接入文档

> 整理时间：2026-05-27
> 代码位置：`backend_api_python/app/services/live_trading/ktx.py`

---

## 1. 概述

KTX 是统一账户模式的加密货币交易所（现货 + U本位合约），**不支持 CCXT**，需使用原生 REST API 接入。

**API 域名：**
- 市场数据：`https://api.ktx.com/api`
- 用户私有数据：`https://api.ktx.com/papi`

**认证方式：**
- 签名：`HMAC-SHA256(apiSecret, expireTime + queryString | body)`
- Headers: `api-key`, `api-sign`, `api-expire-time`

---

## 2. 账户体系

KTX 采用统一账户模式，资产分为两层：

### 2.1 交易账户（现货 + 合约都在这里）

**端点：** `GET /papi/v1/trade/accounts`

现货资产（买入的币）和合约保证金共用此账户。

**API 方法：**
```python
get_trade_balance(asset?)      # 获取交易账户资产
get_spot_balance(asset?)      # get_trade_balance() 的别名
```

**返回字段语义（交易账户）：**

| 字段 | 语义 |
|------|------|
| `balance` | 总资产 |
| `free` | 账户总可用（等于 balance） |
| `withdrawable` | **实际可提取/可用的部分**（扣除挂单冻结后的余额） |
| `locked` | **挂单等冻结不可用部分** |
| `collateral` | 是否作为保证金币种（USDT=true，BTC/ETH=false） |

> 示例：USDT `balance=30.435, withdrawable=4.675, locked=0`，说明 25.76 USDT 被其它持仓的保证金占用，只有 4.67 可自由支配。

### 2.2 钱包账户（独立于交易账户）

**端点：** `POST /papi/v1/main/accounts`

存放未划入交易账户的资产（充币到账后默认在这里）。

**API 方法：**
```python
get_wallet_balance(asset?)    # 获取钱包账户资产
get_account()                  # get_wallet_balance() 别名
get_balance()                 # get_account() 别名
```

### 2.3 资产划转

**端点：** `POST /papi/v1/transfer`

```python
spot_transfer(symbol, amount, direction)
# direction: "WALLET_TRADE"  = 钱包 → 交易账户
#            "TRADE_WALLET"   = 交易账户 → 钱包
```

---

## 3. market 参数规范

KTX 所有订单类 API **必须显式传递 market 参数**，否则返回 404：

| market 值 | 说明 |
|-----------|------|
| `spot` | 现货 |
| `lpc` | U本位永续合约 |

```python
_ktx_market_param(market="")  # 内部方法
# 若传入空字符串，则自动使用 self.market_type（"spot" 或 "lpc"）
```

---

## 4. 账户相关 API

| 方法 | 端点 | 账户类型 | 说明 |
|------|------|----------|------|
| `get_wallet_balance(asset?)` | POST `/v1/main/accounts` | 钱包 | 未划转资产 |
| `get_account()` | POST `/v1/main/accounts` | 钱包 | get_wallet_balance 别名 |
| `get_trade_balance(asset?)` | GET `/v1/trade/accounts` | 交易 | 现货+合约总资产 |
| `get_spot_balance(asset?)` | GET `/v1/trade/accounts` | 交易 | get_trade_balance 别名 |
| `spot_transfer(symbol, amount, direction)` | POST `/v1/transfer` | 划转 | 钱包↔交易账户 |
| `get_ledger(...)` | GET `/v1/ledgers` | 账单 | 划转/交易/手续费/资金费 |
| `get_positions(position_id?, market?, symbol?)` | GET `/v1/positions` | 合约 | 过滤 quantity=0 空仓位 |

### 4.1 获取账单

```python
get_ledger(asset?, start_time?, end_time?, ledger_type?, limit?)
# ledger_type: "transfer" | "trade" | "fee" | "rebate" | "funding"
```

---

## 5. 订单相关 API

**重要：** 所有订单接口 `market` 参数必传。

| 方法 | 端点 | 说明 |
|------|------|------|
| `place_market_order(symbol, side, qty, reduce_only?, pos_side?, client_order_id?)` | POST `/v1/order` | 市价下单 |
| `place_limit_order(symbol, side, qty, price, reduce_only?, pos_side?, time_in_force?, client_order_id?)` | POST `/v1/order` | 限价下单 |
| `get_order(symbol, order_id?, client_order_id?, market?)` | GET `/v1/order?id={id}` | 订单详情 |
| `get_open_orders(symbol?, market?)` | GET `/v1/pending/orders` | 未完成订单 |
| `get_history_orders(symbol?, market?, start_time?, end_time?, limit?)` | GET `/v1/history/orders` | 历史订单（3个月内） |
| `cancel_order(symbol, order_id?, client_order_id?, market?)` | POST `/v1/order/delete` | 取消订单 |
| `wait_for_fill(symbol, order_id?, client_order_id?, max_wait_sec?, poll_interval_sec?)` | 轮询 get_order | 等待成交 |

### 5.1 设置杠杆

```python
set_leverage(symbol, leverage, position_id?)
# 端点：POST /v1/change/leverage
# position_id: 仓位ID，若为空则按 symbol 设置（best-effort）
```

---

## 6. 行情 API（公开，无需签名）

| 方法 | 端点 | 说明 |
|------|------|------|
| `get_ticker(symbol, market?)` | GET `/api/v1/ticker` | 最新价、成交量等 |
| `ping()` | GET `/api/v1/products` | 连通性检查 |

---

## 7. 已知问题与修复记录

### 7.1 仓位接口返回假仓位

**问题：** `/v1/positions` 不指定 market 时返回所有市场（含从未交易的空记录）。

**修复：** 始终强制设置 `market=lpc`，并过滤 `quantity=0` 的仓位记录。

### 7.2 POST 空 body 导致 Invalid JSON

**问题：** `get_spot_balance()` 等 POST 接口传 `None` body 时，签名用空字符串，导致 KTX 返回 `-12102 Invalid JSON`。

**修复：** POST 空 body 时发送 `{}` 而非空字符串。

### 7.3 订单端点路径错误

| 方法 | 错误路径 | 正确路径 |
|------|----------|----------|
| `get_order` | `/v1/orders/{id}` | `/v1/order?id={id}` |
| `cancel_order` | `DELETE /v1/orders/{id}` | `POST /v1/order/delete` |
| `get_open_orders` | `/v1/orders` | `/v1/pending/orders` |

### 7.4 set_leverage 端点错误

**错误：** `/v1/trade/leverage`
**正确：** `/v1/change/leverage`（需要 `positionId`）

---

## 8. 测试

运行完整测试套件：
```bash
cd backend_api_python
python3 tests/run_ktx_tests.py
# 43 个测试全部通过
```

测试文件：`tests/run_ktx_tests.py`

---

## 9. Client 初始化

```python
from app.services.live_trading.ktx import KtxClient

client = KtxClient(
    api_key="your_api_key",
    secret_key="your_secret_key",
    market_type="swap",  # "spot" 或 "swap"（默认），不影响交易下单
)
```

`market_type` 仅影响默认 market 参数值，下单时需显式指定或通过参数覆盖。