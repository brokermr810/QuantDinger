# Backtest Validation Fixtures

This folder keeps local validation assets for the ScriptStrategy backtest chain.

There is no universal open-source "truth dataset" that proves every backtest
engine correct. The validation approach here is layered:

1. Hand-calculated golden oracles verify broker mechanics exactly:
   next-bar-open timing, quote sizing, leverage, slippage, commission, realized
   PnL, final equity, and order lifecycle.
2. Strategy-chain probes verify realistic ScriptStrategy samples compile, run
   through `ScriptBacktestRunner`, emit trades/equity curves, and reach the live
   notify-only pending-order boundary.
3. Open-source engines such as Backtesting.py or Backtrader can be used as
   additional cross-checks for compatible single-asset, market-order scenarios,
   but they do not share QuantDinger's full broker contract, hedge-mode model,
   ScriptStrategy API, or notification/live-order pipeline.

Current local assets:

- `script_strategy_samples.py`: five runnable ScriptStrategy samples.
- `test_script_backtest_accuracy_oracles.py`: exact hand-calculated broker
  correctness cases.
- `test_script_strategy_chain_probe.py`: compile, backtest, live-signal, and
  notify-mode enqueue chain probes for the five samples.
- `test_script_backtest_cross_engine.py`: cross-engine validation against
  Backtesting.py 0.6.5 installed under `.test_deps`.

Cross-engine matrix:

- Strategies: EMA Trend Pullback, Donchian Breakout, RSI Mean Reversion,
  MACD Momentum, Bollinger Reversion.
- Open-source data: Backtesting.py bundled `GOOG`, `EURUSD`, and `BTCUSD`.
- Timeframes: GOOG 1D, GOOG 1W, EURUSD 4H, BTCUSD 1M.
- Shared model: long-only spot, no fee, no slippage, no leverage,
  next-bar-open market execution, fractional position sizing.

The cross-engine test deliberately restricts itself to the overlap between
QuantDinger and Backtesting.py. Leverage, hedge mode, notification-only live
orders, and QuantDinger-specific broker rules are covered by local golden
oracles and chain probes instead.
