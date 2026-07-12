import pandas as pd

from app.services.strategy_script_runtime import StrategyScriptContext
from app.services.trading_executor import TradingExecutor


def test_script_execution_signal_preserves_limit_then_market_contract():
    frame = pd.DataFrame([
        {"open": 100, "high": 101, "low": 98, "close": 100, "volume": 1}
    ])
    context = StrategyScriptContext(frame, 1_000, symbol="BTC/USDT")
    context._orders.append({
        "action": "buy",
        "intent": "open_long",
        "price": 99.0,
        "amount": 0.1,
        "script_base_qty": 0.1,
        "execution_algo": "limit_then_market",
    })
    executor = object.__new__(TradingExecutor)

    signals = executor._script_orders_to_execution_signals(
        context,
        "long",
        100.0,
        pd.Timestamp("2026-01-01T00:00:00Z"),
        {"market_type": "swap", "leverage": 1},
    )

    assert len(signals) == 1
    assert signals[0]["execution_algo"] == "limit_then_market"
    assert signals[0]["order_type"] == "limit"
    assert signals[0]["limit_price"] == 99.0
