from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner
from app.services.strategy_script_runtime import StrategyScriptContext, compile_strategy_script_handlers
from app.services.trading_executor import TradingExecutor
from tests.fixtures.script_strategy_samples import STRATEGY_SAMPLES, make_probe_frame


def _script_bar(row: pd.Series) -> dict:
    return {
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "timestamp": row.get("time"),
    }


def _first_live_signal(name: str, code: str) -> dict:
    frame = make_probe_frame(name).reset_index()
    on_init, on_bar = compile_strategy_script_handlers(code)
    ctx = StrategyScriptContext(frame, initial_balance=10_000, symbol="BTC/USDT")
    ctx.set_runtime_config(
        {
            "symbol": "BTC/USDT",
            "market_type": "swap",
            "trade_direction": "long",
            "leverage": 2,
            "timeframe": "1D",
        },
        initial_balance=10_000,
    )
    if callable(on_init):
        on_init(ctx)

    executor = TradingExecutor.__new__(TradingExecutor)
    for idx, row in frame.iterrows():
        ctx.current_index = int(idx)
        ctx.current_dt = row["time"]
        ctx.equity = 10_000.0
        ctx.available_cash = 10_000.0
        ctx.available_margin = 10_000.0
        ctx.positions = {
            "long": {"side": "long", "size": 0.0, "entry_price": 0.0},
            "short": {"side": "short", "size": 0.0, "entry_price": 0.0},
        }
        ctx._orders.clear()
        on_bar(ctx, _script_bar(row))
        signals = executor._script_orders_to_execution_signals(
            ctx,
            trade_direction="long",
            bar_close=float(row["close"]),
            closed_ts=pd.Timestamp(row["time"]),
            trading_config={"market_type": "swap", "leverage": 2},
        )
        if signals:
            return signals[0]
    raise AssertionError(f"{name} did not emit a live signal")


def _assert_signal_mode_reaches_enqueue(signal: dict, strategy_id: int) -> None:
    executor = TradingExecutor.__new__(TradingExecutor)
    executor._effective_position_state = MagicMock(return_value="flat")
    executor._is_signal_allowed = MagicMock(return_value=True)
    executor._get_available_capital = MagicMock(return_value=10_000.0)
    executor._get_daily_pnl = MagicMock(return_value=0.0)
    executor._ensure_order_intent_for_enqueue = MagicMock(return_value={})
    executor._enqueue_pending_order = MagicMock(return_value=9000 + strategy_id)
    executor._record_trade = MagicMock()
    executor._update_position = MagicMock()
    executor._effective_taker_fee_rate = MagicMock(return_value=0.0)

    with patch("app.services.trading_executor.append_strategy_log"):
        ok = executor._execute_signal(
            strategy_id=strategy_id,
            strategy_name=f"probe-{strategy_id}",
            exchange=MagicMock(),
            symbol="BTC/USDT",
            current_price=float(signal["trigger_price"]),
            signal_type=signal["type"],
            position_size=float(signal.get("position_size") or 0.0),
            current_positions=[],
            trade_direction="long",
            leverage=2,
            initial_capital=10_000.0,
            market_type="swap",
            execution_mode="signal",
            notification_config={"channels": ["browser"], "mode": "notify_only"},
            trading_config={"market_type": "swap", "leverage": 2},
            signal_ts=int(signal.get("timestamp") or 0),
            script_base_qty=signal.get("script_base_qty"),
            script_quote_amount=signal.get("script_quote_amount"),
        )

    assert ok is True
    executor._enqueue_pending_order.assert_called_once()
    kwargs = executor._enqueue_pending_order.call_args.kwargs
    assert kwargs["execution_mode"] == "signal"
    assert kwargs["notification_config"]["channels"] == ["browser"]
    assert kwargs["signal_type"] == signal["type"]


@pytest.mark.parametrize("name,code", sorted(STRATEGY_SAMPLES.items()))
def test_strategy_sample_backtest_and_live_notify_chain(name: str, code: str):
    compile_strategy_script_handlers(code)
    frame = make_probe_frame(name)
    config = BacktestConfig(
        initial_capital=10_000,
        commission=0.001,
        slippage=0.0005,
        leverage=2,
        trade_direction="long",
        timeframe="1D",
        market_type="swap",
        signal_timing="next_bar_open",
    )

    result = ScriptBacktestRunner(
        config=config,
        code=code,
        params={},
        runtime={"symbol": "BTC/USDT"},
    ).run(
        df=frame,
        start_date=frame.index[0].to_pydatetime(),
        end_date=frame.index[-1].to_pydatetime(),
    )

    assert result["engine"]["version"] == "quantdinger-script-backtest-v3"
    assert result["engine"]["orderCount"] >= 1
    assert result["trades"]
    assert result["equityCurve"]

    signal = _first_live_signal(name, code)
    assert signal["type"] == "open_long"
    assert float(signal["script_quote_amount"]) > 0
    _assert_signal_mode_reaches_enqueue(signal, strategy_id=1000 + list(sorted(STRATEGY_SAMPLES)).index(name))
