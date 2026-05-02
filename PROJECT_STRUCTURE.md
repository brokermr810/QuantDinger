# QuantDinger 项目目录结构

```
QuantDinger/
│
├── backend_api_python/          # Python 后端 API (FastAPI)
│   ├── app/
│   │   ├── config/              # 配置模块
│   │   │   ├── api_keys.py      # API密钥管理
│   │   │   ├── data_sources.py  # 数据源配置
│   │   │   ├── database.py      # 数据库配置
│   │   │   └── settings.py      # 应用设置
│   │   │
│   │   ├── data/                # 静态数据
│   │   │   ├── market_symbols_seed.py   # 市场代码种子数据
│   │   │   └── strategy_templates.json  # 策略模板
│   │   │
│   │   ├── data_providers/       # 数据提供器（聚合接口）
│   │   │   ├── adanos_sentiment.py  # Adanos情绪数据
│   │   │   ├── commodities.py     # 大宗商品
│   │   │   ├── crypto.py          # 加密货币
│   │   │   ├── forex.py           # 外汇
│   │   │   ├── heatmap.py         # 市场热度图
│   │   │   ├── indices.py         # 指数
│   │   │   ├── news.py            # 新闻
│   │   │   ├── opportunities.py   # 交易机会
│   │   │   └── sentiment.py       # 情绪数据
│   │   │
│   │   ├── data_sources/         # 数据源（底层接口）
│   │   │   ├── base.py            # 基类
│   │   │   ├── cn_stock.py        # A股
│   │   │   ├── hk_stock.py        # 港股
│   │   │   ├── us_stock.py        # 美股
│   │   │   ├── crypto.py          # 加密货币
│   │   │   ├── forex.py           # 外汇
│   │   │   ├── futures.py         # 期货
│   │   │   ├── moex.py            # 莫斯科交易所
│   │   │   ├── polymarket.py      # Polymarket预测市场
│   │   │   ├── cache_manager.py   # 缓存管理
│   │   │   ├── circuit_breaker.py # 熔断器
│   │   │   └── rate_limiter.py    # 限流器
│   │   │
│   │   ├── routes/               # API路由
│   │   │   ├── auth.py           # 认证
│   │   │   ├── ai_chat.py        # AI对话
│   │   │   ├── strategy.py       # 策略管理
│   │   │   ├── backtest.py       # 回测
│   │   │   ├── market.py         # 市场数据
│   │   │   ├── kline.py          # K线数据
│   │   │   ├── portfolio.py      # 组合管理
│   │   │   ├── billing.py        # 计费
│   │   │   ├── experiment.py     # 实验/策略演进
│   │   │   ├── mt5.py            # MT5交易
│   │   │   ├── ibkr.py           # IBKR交易
│   │   │   ├── polymarket.py     # Polymarket
│   │   │   └── health.py         # 健康检查
│   │   │
│   │   ├── services/             # 业务服务层
│   │   │   ├── experiment/        # 策略实验系统
│   │   │   │   ├── evolution.py   # 策略进化
│   │   │   │   ├── regime.py      # 市场状态识别
│   │   │   │   ├── runner.py      # 实验运行器
│   │   │   │   └── scoring.py     # 评分系统
│   │   │   │
│   │   │   ├── live_trading/      # 实盘交易（多交易所）
│   │   │   │   ├── binance.py     # 币安
│   │   │   │   ├── okx.py         # OKX
│   │   │   │   ├── bybit.py       # Bybit
│   │   │   │   ├── gate.py        # Gate.io
│   │   │   │   ├── kucoin.py      # Kucoin
│   │   │   │   ├── bitget.py      # Bitget
│   │   │   │   ├── coinbase.py    # Coinbase
│   │   │   │   ├── kraken.py      # Kraken
│   │   │   │   ├── htx.py         # HTX(虎符)
│   │   │   │   ├── deepcoin.py    # DeepCoin
│   │   │   │   └── factory.py     # 工厂模式
│   │   │   │
│   │   │   ├── ibkr_trading/     # IBKR智能路由
│   │   │   │   ├── client.py      # IBKR客户端
│   │   │   │   └── symbols.py     # 交易品种
│   │   │   │
│   │   │   ├── mt5_trading/      # MT5智能路由
│   │   │   │   ├── client.py      # MT5客户端
│   │   │   │   └── symbols.py     # 交易品种
│   │   │   │
│   │   │   ├── strategy.py           # 策略管理
│   │   │   ├── backtest.py           # 回测引擎
│   │   │   ├── llm.py                # LLM服务(AI)
│   │   │   ├── fast_analysis.py       # 快速分析
│   │   │   ├── trading_executor.py    # 交易执行
│   │   │   ├── portfolio_monitor.py   # 组合监控
│   │   │   ├── market_data_collector.py # 数据采集
│   │   │   ├── signal_notifier.py     # 信号通知
│   │   │   ├── billing_service.py      # 计费服务
│   │   │   └── email_service.py        # 邮件服务
│   │   │
│   │   └── utils/                # 工具函数
│   │       ├── auth.py           # 认证工具
│   │       ├── cache.py          # 缓存
│   │       ├── logger.py         # 日志
│   │       ├── db.py            # 数据库
│   │       └── safe_exec.py     # 安全执行
│   │
│   ├── migrations/               # 数据库迁移
│   │   └── init.sql
│   ├── scripts/                  # 后端脚本
│   │   ├── backfill_zero_trades.py
│   │   └── run_calibration.py
│   ├── tests/                    # 测试
│   ├── Dockerfile
│   ├── env.example              # 环境变量模板
│   └── requirements.txt         # 依赖
│
├── frontend/                     # Vue.js 前端
│   ├── dist/                    # 构建输出
│   ├── Dockerfile
│   └── nginx.conf
│
├── docs/                        # 文档
│   ├── examples/                # 示例代码
│   ├── screenshots/             # 截图
│   ├── STRATEGY_DEV_GUIDE_CN.md # 策略开发指南
│   └── CLOUD_DEPLOYMENT_CN.md   # 云部署指南
│
├── scripts/                     # 项目脚本
│   ├── generate-secret-key.sh   # 生成密钥
│   ├── build-frontend.sh        # 构建前端
│   ├── i18n-diff.js            # 国际化差异
│   └── i18n-fill-ai.js         # AI填充翻译
│
├── .github/
│   └── workflows/               # CI/CD流水线
│
├── docker-compose.yml          # Docker编排
├── .env.example                # 环境变量模板
└── README.md                   # 项目说明
```

---

## 核心模块说明

| 模块 | 功能 |
|------|------|
| **data_sources/** | 底层数据接口（交易所、行情） |
| **data_providers/** | 聚合数据接口，封装业务逻辑 |
| **routes/** | RESTful API 接口 |
| **services/** | 核心业务逻辑（策略、回测、交易执行） |
| **live_trading/** | 多交易所实盘交易适配器 |
| **experiment/** | 策略自动演化/优化系统 |

这是一个**量化交易平台**，支持A股、港股、美股、期货、外汇、加密货币等多市场，支持策略编写、回测和实盘交易。
