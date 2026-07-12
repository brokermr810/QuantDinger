# Backend Refactor Plan

This plan keeps public API routes stable while moving domain logic out of route
modules and oversized services. Refactors should stay incremental, syntax-checked,
and easy to review.

## Route Layer

- `routes/settings.py`: environment file, runtime settings, branding.
- `routes/user.py`: user profile, notification preferences, chart templates, password changes.
- `routes/auth.py`: session/token helpers and login metadata.
- `routes/market.py`: symbol search, watchlist, quote aggregation.
- `routes/ai_chat.py`: chat persistence, report export, task orchestration.
- `routes/fast_analysis.py`: async analysis tasks and credit refund helpers.
- `routes/indicator.py`: indicator CRUD, version history, validation, AI code generation.
- `routes/strategy.py`: lifecycle HTTP endpoints, code validation, bot recommendation, AI code generation.
- Existing split strategy route modules stay as route modules because they already map cleanly to API areas.

## Strategy And Indicator Domain

- `services/indicator_versions.py`: indicator code history.
- `services/indicator_validation.py`: mock K-lines, parameter merge, safe execution, output validation.
- `services/strategy_code_quality.py`: script strategy quality hints and validation.
- `services/strategy_live_guard.py`: duplicate live-strategy guard by account, market and symbol.
- `services/strategy_bot_recommend.py`: AI bot recommendation, market data context, parameter normalization.
- Future safe step: move indicator AI prompt/template handling into `services/indicator_ai_generation.py`.
- Future safe step: move strategy AI code generation and parameter adjustment into `services/strategy_ai_generation.py`.

## Core Backtest Domain

- `services/backtest_cache.py`: K-line cache.
- Future safe step: move run persistence and hydration into `services/backtest_storage.py`.
- Future safe step: move timeframe/warmup/window helpers into `services/backtest_windows.py`.
- Future safe step: move metrics and result formatting into `services/backtest_metrics.py`.
- Future safe step: keep simulation engines together until regression coverage is stronger.

## Trading Execution Domain

- Future safe step: move pure signal gating and dedup helpers into `services/trading_signal_policy.py`.
- Future safe step: move exchange/kline fetch helpers into `services/trading_market_data.py`.
- Future safe step: move notification persistence into `services/trading_notifications.py`.
- Future safe step: design portfolio-strategy execution as a separate module only after the backtest engine contract is ready.
- Keep order execution and position mutation close to `TradingExecutor` until live-trading tests cover broker edge cases.

## Data And Market Domain

- `services/market/*`: symbol search, quotes, watchlist.
- Future safe step: move symbol master-data maintenance into `services/symbol_master/*`.
- Future safe step: consolidate K-line source fallback and naming normalization into one market-data facade.

## Rules

- Do not change API paths or response keys unless a migration is explicitly requested.
- Prefer small service modules by domain, not one file per helper.
- Keep comments and logs in English.
- Run Python syntax checks after each backend step.
- Do not commit automatically.
