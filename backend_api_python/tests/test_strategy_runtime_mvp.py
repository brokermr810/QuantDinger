from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.services.unified_backtest import UnifiedBacktestService
from app.services.strategy_runtime.order_intents import OrderIntent, OrderIntentService
from app.services.strategy_runtime.state import RuntimeStateProxy
from app.services.strategy_script_runtime import StrategyScriptContext
from app.services.trading_executor import TradingExecutor


def _make_executor() -> TradingExecutor:
    return TradingExecutor.__new__(TradingExecutor)


def _run_script_with_df(
    monkeypatch,
    df: pd.DataFrame,
    code: str,
    *,
    trade_direction: str = "long",
    leverage: int = 1,
    strategy_config: dict | None = None,
    start_date=None,
    end_date=None,
):
    config = strategy_config or {"market_type": "swap"}

    def fake_fetch(self, *args, **kwargs):
        return df

    monkeypatch.setattr(UnifiedBacktestService, "_fetch_kline_data", fake_fetch)
    return UnifiedBacktestService()._run_script_strategy(
        code=code,
        market="Crypto",
        symbol="BTC/USDT",
        timeframe=str(df.attrs.get("timeframe") or "15m"),
        start_date=pd.Timestamp(start_date if start_date is not None else df.index[0]).to_pydatetime(),
        end_date=pd.Timestamp(end_date if end_date is not None else df.index[-1]).to_pydatetime(),
        initial_capital=1000,
        commission=0,
        slippage=0,
        leverage=leverage,
        trade_direction=trade_direction,
        strategy_config=config,
        market_type=str(config.get("market_type") or "swap"),
    )


@dataclass
class _MemoryStore:
    saved: dict | None = None

    def load(self):
        return {"cooldown": 1}

    def save(self, values):
        self.saved = dict(values)


def test_runtime_state_proxy_loads_sets_and_flushes():
    store = _MemoryStore()
    state = RuntimeStateProxy(store=store)

    assert state.get("cooldown") == 1
    state.set("cooldown", 3)
    state["last_price"] = 101.5
    state.flush()

    assert store.saved == {"cooldown": 3, "last_price": 101.5}


def test_order_intent_key_is_stable_for_basket_child_order():
    key1 = OrderIntentService.build_signal_idempotency_key(
        strategy_run_id=8,
        strategy_id=2,
        symbol="BTC/USDT",
        signal_type="add_long",
        signal_ts=0,
        basket_id="BTC/USDT:long",
        layer_index=2,
        order_index=3,
        action="add",
    )
    key2 = OrderIntentService.build_signal_idempotency_key(
        strategy_run_id=8,
        strategy_id=2,
        symbol="BTC/USDT",
        signal_type="add_long",
        signal_ts=123,
        basket_id="BTC/USDT:long",
        layer_index=2,
        order_index=3,
        action="add",
    )

    assert key1 == key2
    assert "L2:O3:add" in key1


def test_ctx_basket_open_child_order_emits_script_order(monkeypatch):
    def fake_create_intent(self, **kwargs):
        return OrderIntent(id=123, idempotency_key=kwargs["idempotency_key"], status="intent_created")

    monkeypatch.setattr(OrderIntentService, "create_intent", fake_create_intent)

    ctx = StrategyScriptContext(
        pd.DataFrame({"close": [100.0]}),
        1000.0,
        strategy_id=1,
        strategy_run_id=77,
        symbol="BTC/USDT",
    )
    result = ctx.basket("long").open_child_order(
        layer=2,
        order=3,
        notional=50,
        price=99.5,
        action="add",
    )

    assert result["order_intent_id"] == 123
    assert len(ctx._orders) == 1
    emitted = ctx._orders[0]
    assert emitted["intent"] == "add_long"
    assert emitted["action"] == "buy"
    assert emitted["strategy_run_id"] == 77
    assert emitted["basket_id"] == "BTC/USDT:long"
    assert emitted["layer_index"] == 2
    assert emitted["order_index"] == 3
    assert emitted["order_intent_id"] == 123
    assert emitted["idempotency_key"]
    assert emitted["script_quote_amount"] == 50


def test_script_context_exposes_simple_runtime_contract():
    ctx = StrategyScriptContext(
        pd.DataFrame({"close": [100.0]}),
        2500.0,
        symbol="BTC/USDT",
    )
    ctx.set_runtime_config({
        "runtime_contract_version": "simple_script_v1",
        "symbol": "BTC/USDT",
        "trade_direction": "short",
        "market_type": "swap",
        "leverage": 5,
        "investment_amount": 800,
        "timeframe": "1m",
        "tick_interval_sec": 10,
    })

    assert ctx.direction == "short"
    assert ctx.trade_direction == "short"
    assert ctx.market_type == "swap"
    assert ctx.leverage == 5
    assert ctx.investment_amount == 800
    assert ctx.runtime["timeframe"] == "1m"
    assert ctx.runtime["tick_interval_sec"] == 10


def test_script_context_limits_bars_per_call(monkeypatch):
    monkeypatch.setenv("STRATEGY_SCRIPT_MAX_BARS_PER_CALL", "3")
    df = pd.DataFrame(
        {
            "open": list(range(10)),
            "high": list(range(10)),
            "low": list(range(10)),
            "close": list(range(10)),
            "volume": [1.0] * 10,
        },
        index=pd.date_range("2026-06-01", periods=10, freq="min"),
    )
    ctx = StrategyScriptContext(df, 1000.0)
    ctx.current_index = 9

    bars = ctx.bars(999999)

    assert len(bars) == 3
    assert bars[0]["close"] == 7.0
    assert bars[-1]["close"] == 9.0


def test_script_context_limits_user_logs(monkeypatch):
    monkeypatch.setenv("STRATEGY_SCRIPT_MAX_LOGS_PER_FLUSH", "3")
    monkeypatch.setenv("STRATEGY_SCRIPT_MAX_LOG_CHARS", "8")
    ctx = StrategyScriptContext()

    ctx.log("123456789abcdef")
    ctx.log("second")
    ctx.log("third")
    ctx.log("fourth")
    logs = ctx.flush_logs()

    assert len(logs) == 3
    assert logs[0] == "12345678... [truncated]"
    assert logs[-1] == "ctx.log limit reached; further logs dropped (max=3 per flush)"
    assert ctx.flush_logs() == []


def test_script_order_runtime_metadata_survives_signal_conversion():
    ex = _make_executor()
    ctx = StrategyScriptContext(pd.DataFrame({"close": [100.0]}), 1000.0)
    ctx._orders.append(
        {
            "action": "buy",
            "intent": "open_long",
            "price": 100.0,
            "amount": 25.0,
            "strategy_run_id": 77,
            "basket_id": "BTC/USDT:long",
            "basket_order_db_id": 9,
            "order_intent_id": 123,
            "idempotency_key": "run:77:basket:BTC/USDT:long:L1:O1:open",
            "layer_index": 1,
            "order_index": 1,
        }
    )

    sigs = ex._script_orders_to_execution_signals(
        ctx,
        trade_direction="long",
        bar_close=100.0,
        closed_ts=pd.Timestamp("2026-06-30T00:00:00Z"),
        trading_config={"market_type": "swap", "leverage": 2, "bot_type": "martingale"},
    )

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig["type"] == "open_long"
    assert sig["strategy_run_id"] == 77
    assert sig["basket_id"] == "BTC/USDT:long"
    assert sig["basket_order_db_id"] == 9
    assert sig["order_intent_id"] == 123
    assert sig["idempotency_key"] == "run:77:basket:BTC/USDT:long:L1:O1:open"
    assert sig["layer_index"] == 1
    assert sig["order_index"] == 1


def test_script_backtest_user_direction_is_outer_gate(monkeypatch):
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.0, 100.0],
            "volume": [1.0, 1.0],
        },
        index=pd.date_range("2026-06-01", periods=2, freq="15min"),
    )
    df.attrs["timeframe"] = "15m"
    code = """
def on_bar(ctx, bar):
    if int(ctx.current_index) == 0:
        ctx.basket('long').open_child_order(
            layer=1,
            order=1,
            notional=50,
            price=bar['close'],
            action='open',
        )
"""
    result = _run_script_with_df(
        monkeypatch,
        df,
        code,
        trade_direction="short",
        leverage=2,
        strategy_config={
            "market_type": "swap",
            "script_template_params": {"direction": "long"},
        },
    )

    assert result["totalTrades"] == 0
    assert result["signalDiagnostics"]["entrySignals"] == 0
    engine = result["engine"]
    assert engine["orderCount"] == 0


def test_script_backtest_basket_quote_amount_sizes_trade(monkeypatch):
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0],
            "high": [101.0, 101.0, 111.0],
            "low": [99.0, 99.0, 109.0],
            "close": [100.0, 100.0, 110.0],
            "volume": [1.0, 1.0, 1.0],
        },
        index=pd.date_range("2026-06-01", periods=3, freq="15min"),
    )
    df.attrs["timeframe"] = "15m"
    code = """
def on_bar(ctx, bar):
    if int(ctx.current_index) == 0:
        ctx.basket('long').open_child_order(
            layer=1,
            order=1,
            notional=50,
            price=bar['close'],
            action='open',
        )
"""
    result = _run_script_with_df(
        monkeypatch,
        df,
        code,
        trade_direction="long",
        leverage=2,
        strategy_config={"market_type": "swap"},
    )

    trades = result["trades"]
    assert trades[0]["type"] == "open_long"
    assert trades[0]["amount"] == 1.0


def test_script_backtest_warmup_does_not_carry_trade_position(monkeypatch):
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0, 100.0],
            "high": [102.0, 102.0, 102.0, 102.0, 102.0],
            "low": [98.0, 98.0, 98.0, 98.0, 98.0],
            "close": [101.0, 101.0, 99.0, 101.0, 101.0],
            "volume": [1.0, 1.0, 1.0, 1.0, 1.0],
        },
        index=pd.date_range("2026-06-01", periods=5, freq="1D"),
    )
    df.attrs["timeframe"] = "1D"
    code = """
def on_bar(ctx, bar):
    if bar['close'] > 100 and not ctx.position.has_long():
        ctx.basket('long').open_child_order(
            layer=1,
            order=1,
            notional=50,
            price=bar['close'],
            action='open',
        )
    elif bar['close'] < 100 and ctx.position.has_long():
        ctx.basket('long').open_child_order(
            layer=1,
            order=2,
            price=bar['close'],
            action='close',
        )
"""
    result = _run_script_with_df(
        monkeypatch,
        df,
        code,
        trade_direction="long",
        leverage=1,
        strategy_config={"market_type": "swap"},
        start_date=df.index[2],
    )

    assert result["signalDiagnostics"]["entrySignals"] == 1
    assert result["orders"][0]["submittedBar"] == 4
    assert result["trades"][0]["type"] == "open_long"
