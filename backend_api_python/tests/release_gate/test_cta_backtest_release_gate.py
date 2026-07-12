from datetime import datetime
from pathlib import Path
import sys
import types

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]


def _namespace(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


_namespace("app", ROOT / "app")
_namespace("app.services", ROOT / "app" / "services")
_namespace("app.services.backtest_engine", ROOT / "app" / "services" / "backtest_engine")
_namespace("app.services.strategy_runtime", ROOT / "app" / "services" / "strategy_runtime")
_namespace("app.utils", ROOT / "app" / "utils")

from app.services.backtest_engine.broker import BrokerSimulator
from app.services.backtest_engine.models import BacktestConfig, OrderStatus
from app.services.backtest_engine.script_strategy import ScriptStrategyBacktestRunner
from app.services.strategy_runtime.executors import build_executor_strategy_payload, preview_executor
from app.services.strategy_runtime.signals import StrategySignal
from app.services.strategy_script_runtime import ScriptBar, StrategyScriptContext, compile_strategy_script_handlers


def _frame(rows):
    index = pd.date_range("2026-01-01", periods=len(rows), freq="1h")
    return pd.DataFrame(rows, index=index)


def _run_script(code, rows, **config_overrides):
    config = BacktestConfig(
        initial_capital=10_000,
        market_type="swap",
        timeframe="1H",
        signal_timing="next_bar_open",
        **config_overrides,
    )
    frame = _frame(rows)
    runner = ScriptStrategyBacktestRunner(config=config, code=code)
    return runner.run(
        df=frame,
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 1, 2),
    )


def test_script_signals_fill_on_the_next_bar_open():
    code = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.open_long(amount=1, reason="entry")
    elif ctx.current_index == 1 and ctx.position:
        ctx.close_long(reason="exit")
"""
    result = _run_script(
        code,
        [
            {"open": 90, "high": 95, "low": 85, "close": 92, "volume": 1000},
            {"open": 100, "high": 106, "low": 98, "close": 104, "volume": 1000},
            {"open": 110, "high": 112, "low": 108, "close": 111, "volume": 1000},
        ],
    )

    assert [trade["bar_time"] for trade in result["trades"]] == [
        "2026-01-01 01:00",
        "2026-01-01 02:00",
    ]
    assert [trade["price"] for trade in result["trades"]] == [100.0, 110.0]
    assert result["closedTrades"][0]["profit"] == 10.0


def test_script_context_never_exposes_future_bars():
    code = """
def on_bar(ctx, bar):
    ctx.log("visible=%d,index=%d" % (len(ctx._bars_df), ctx.current_index))
"""
    result = _run_script(
        code,
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"open": 101, "high": 102, "low": 100, "close": 101, "volume": 1},
            {"open": 102, "high": 103, "low": 101, "close": 102, "volume": 1},
        ],
    )

    assert result["logs"] == ["visible=1,index=0", "visible=2,index=1", "visible=3,index=2"]


def test_conservative_intrabar_policy_chooses_the_stop_when_both_barriers_hit():
    code = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.open_long(amount=1)
"""
    result = _run_script(
        code,
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"open": 100, "high": 110, "low": 90, "close": 100, "volume": 100},
        ],
        stop_loss_pct=0.05,
        take_profit_pct=0.05,
        intrabar_mode="conservative",
    )

    assert result["closedTrades"][0]["close_reason"] == "stop_loss"
    assert result["closedTrades"][0]["exit_price"] == 95.0


def test_commission_and_slippage_are_applied_on_both_sides():
    code = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.open_long(amount=1)
    elif ctx.current_index == 1 and ctx.position:
        ctx.close_long()
"""
    result = _run_script(
        code,
        [
            {"open": 90, "high": 95, "low": 85, "close": 92, "volume": 100},
            {"open": 100, "high": 105, "low": 95, "close": 102, "volume": 100},
            {"open": 110, "high": 112, "low": 108, "close": 111, "volume": 100},
        ],
        commission=0.01,
        slippage=0.01,
    )

    assert [trade["price"] for trade in result["trades"]] == [101.0, 108.9]
    assert result["totalCommission"] == pytest.approx(2.099)
    assert result["equityCurve"][-1]["value"] == pytest.approx(10005.8, abs=0.01)


def test_volume_participation_produces_real_partial_fills():
    broker = BrokerSimulator(BacktestConfig(initial_capital=10_000, market_type="spot"))
    order = broker.submit(
        side="buy",
        position_side="long",
        quantity=10,
        metadata={"volume_participation": 0.2},
    )
    frame = _frame([
        {"open": 10, "high": 10, "low": 10, "close": 10, "volume": 10}
        for _ in range(5)
    ])

    for index, (timestamp, row) in enumerate(frame.iterrows()):
        broker.process_bar(index, timestamp, row)
        if index < 4:
            assert order.status == OrderStatus.PARTIAL

    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == pytest.approx(10)
    assert len(broker.executions) == 5
    assert broker.long.size == pytest.approx(10)


def test_reduce_only_order_without_a_position_is_rejected():
    broker = BrokerSimulator(BacktestConfig(initial_capital=10_000))
    order = broker.submit(
        side="sell",
        position_side="long",
        reduce_only=True,
        quantity=1,
    )
    timestamp, row = next(iter(_frame([
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}
    ]).iterrows()))
    broker.process_bar(0, timestamp, row)

    assert order.status == OrderStatus.REJECTED
    assert order.metadata["reject_reason"] == "no_position"


def test_leveraged_swap_position_is_liquidated_at_maintenance_margin():
    code = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.open_long(amount=1000)
"""
    result = _run_script(
        code,
        [
            {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"open": 100, "high": 101, "low": 89, "close": 90, "volume": 1000},
        ],
        leverage=10,
        maintenance_margin_rate=0.005,
    )

    trade = result["closedTrades"][0]
    expected_liquidation = (100_000 - 10_000) / (1000 * (1 - 0.005))
    assert trade["close_reason"] == "liquidation"
    assert trade["exit_price"] == pytest.approx(expected_liquidation)


def test_script_order_preserves_base_quote_and_limit_contract():
    quote_signal = StrategySignal.from_script_order(
        {
            "intent": "open_long",
            "script_quote_amount": 250,
            "price": 100,
            "reason": "quote-entry",
        },
        timestamp=1,
        strategy_id=2,
        strategy_run_id=3,
        symbol="BTC/USDT",
    )
    base_signal = StrategySignal.from_script_order(
        {"intent": "reduce_long", "script_base_qty": 0.25},
        timestamp=2,
        symbol="BTC/USDT",
    )

    assert quote_signal.quote_amount == 250
    assert quote_signal.amount == 0
    assert quote_signal.order_type == "limit"
    assert base_signal.amount == 0.25
    assert base_signal.reduce_only is True


def test_reference_price_does_not_turn_an_explicit_market_signal_into_a_limit_order():
    market_signal = StrategySignal(
        timestamp=1,
        symbol="BTC/USDT",
        action="open_long",
        amount=0.1,
        price_hint=100_000,
        metadata={"order_type": "market", "execution_algo": "market"},
    )
    fallback_signal = StrategySignal(
        timestamp=2,
        symbol="BTC/USDT",
        action="open_long",
        amount=0.1,
        price_hint=99_900,
        metadata={"execution_algo": "limit_then_market"},
    )

    assert market_signal.order_type == "market"
    assert market_signal.execution_algo == "market"
    assert market_signal.to_order_intent_kwargs()["limit_price"] == 0
    assert fallback_signal.order_type == "limit"
    assert fallback_signal.execution_algo == "limit_then_market"


@pytest.mark.parametrize("side", ["long", "short"])
def test_dca_preview_take_profit_uses_cumulative_vwap(side):
    result = preview_executor({
        "executor_type": "dca",
        "side": side,
        "entry_price": 100,
        "base_order_size": 100,
        "safety_order_size": 200,
        "price_deviation_pct": 0.1,
        "step_multiplier": 1,
        "volume_multiplier": 1,
        "max_layers": 2,
        "take_profit_pct": 0.01,
    })
    second = result["levels"][1]
    second_price = 90 if side == "long" else 110
    average_price = 300 / ((100 / 100) + (200 / second_price))
    expected = average_price * (1.01 if side == "long" else 0.99)

    assert second["take_profit_price"] == pytest.approx(expected)
    assert second["take_profit_price"] != pytest.approx(second_price * (1.01 if side == "long" else 0.99))


def test_backtest_is_deterministic_for_the_same_inputs():
    code = """
def on_bar(ctx, bar):
    if ctx.current_index == 0:
        ctx.open_short(amount=2)
"""
    rows = [
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
        {"open": 101, "high": 102, "low": 98, "close": 99, "volume": 100},
        {"open": 98, "high": 99, "low": 97, "close": 98, "volume": 100},
    ]

    first = _run_script(code, rows, commission=0.001, slippage=0.001)
    second = _run_script(code, rows, commission=0.001, slippage=0.001)

    for key in ("equityCurve", "trades", "closedTrades", "orders", "totalCommission"):
        assert first[key] == second[key]


def test_dca_algorithm_uses_durable_basket_intents_and_actual_position_average():
    payload = build_executor_strategy_payload({
        "executor_type": "dca",
        "symbol": "BTC/USDT",
        "entry_price": 100,
        "base_order_size": 100,
        "safety_order_size": 100,
        "price_deviation_pct": 0.05,
        "max_layers": 2,
        "take_profit_pct": 0.01,
        "execution_mode": "signal",
    }, user_id=1)
    on_init, on_bar = compile_strategy_script_handlers(payload["strategy_code"])
    context = StrategyScriptContext(
        _frame([{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 1}]).reset_index(),
        1_000,
        symbol="BTC/USDT",
    )
    context.current_index = 0
    on_init(context)
    on_bar(context, ScriptBar(open=100, high=100, low=100, close=100, volume=1, timestamp=1))
    entry_orders = context.flush_orders()

    assert len(entry_orders) == 1
    assert entry_orders[0]["intent"] == "open_long"
    assert entry_orders[0]["script_quote_amount"] == 100
    assert entry_orders[0]["basket_id"]
    assert context.state.get("next_level") == 1

    context.position.open_long(98, 1)
    on_bar(context, ScriptBar(open=99, high=99, low=99, close=99, volume=1, timestamp=2))
    exit_orders = context.flush_orders()

    assert len(exit_orders) == 1
    assert exit_orders[0]["intent"] == "close_long"
    assert exit_orders[0]["reason"] == "dca_take_profit"


def test_dca_algorithm_blocks_a_stale_entry_anchor():
    payload = build_executor_strategy_payload({
        "executor_type": "dca",
        "symbol": "BTC/USDT",
        "entry_price": 100,
        "base_order_size": 100,
        "max_layers": 2,
        "max_entry_drift_pct": 0.03,
        "execution_mode": "signal",
    }, user_id=1)
    on_init, on_bar = compile_strategy_script_handlers(payload["strategy_code"])
    context = StrategyScriptContext(
        _frame([{"open": 50, "high": 50, "low": 50, "close": 50, "volume": 1}]).reset_index(),
        1_000,
        symbol="BTC/USDT",
    )
    context.current_index = 0
    on_init(context)
    on_bar(context, ScriptBar(open=50, high=50, low=50, close=50, volume=1, timestamp=1))

    assert context.flush_orders() == []
    assert context.state.get("next_level") == 0
    assert "entry blocked" in context.flush_logs()[0]
