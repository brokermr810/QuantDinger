"""QuantDinger backtest engine v2.

The implementation is original code. It follows the same broad architecture
used by mature event-driven backtesting systems: data bars feed a broker
simulator, strategies submit orders, the broker owns fills/positions, and
analyzers derive reports from the execution ledger.
"""

from .models import BacktestConfig, Order, OrderSide, OrderStatus, OrderType
from .script_strategy import BacktestContext, ScriptBacktestRunner, ScriptStrategyBacktestRunner

__all__ = [
    "BacktestContext",
    "BacktestConfig",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "ScriptBacktestRunner",
    "ScriptStrategyBacktestRunner",
]
