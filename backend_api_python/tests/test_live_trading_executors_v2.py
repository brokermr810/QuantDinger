from __future__ import annotations

from app.services.live_trading.base import LiveOrderResult
from app.services.live_trading.contracts import FillSnapshot, OrderIntent
from app.services.live_trading.executors import (
    LimitThenMarketExecutor,
    MarketOrderExecutor,
    RestingLimitExecutor,
)


class FakeAdapter:
    exchange_id = "fake"

    def __init__(self, *, fill_status: str = "filled", fill_qty: float = 1.0):
        self.calls = []
        self.fill_status = fill_status
        self.fill_qty = fill_qty

    def place_market_order(self, intent):
        self.calls.append(("market", intent.symbol))
        return LiveOrderResult(exchange_id=self.exchange_id, exchange_order_id="m1", filled=1.0, avg_price=101, raw={})

    def place_limit_order(self, intent):
        self.calls.append(("limit", intent.symbol))
        return LiveOrderResult(exchange_id=self.exchange_id, exchange_order_id="l1", filled=0.0, avg_price=0, raw={})

    def cancel_order(self, intent, *, order_id: str = ""):
        self.calls.append(("cancel", order_id))
        return {"ok": True}

    def wait_for_fill(self, intent, *, order_id: str = "", max_wait_sec: float = 15.0):
        self.calls.append(("wait", order_id, max_wait_sec))
        if order_id == "m1":
            return FillSnapshot(filled_qty=float(intent.quantity or 0.0), avg_price=101, status="filled", raw={})
        return FillSnapshot(filled_qty=self.fill_qty, avg_price=100, status=self.fill_status, raw={})

    def query_position(self, intent):
        raise NotImplementedError


def test_market_order_executor_submits_normalized_intent():
    adapter = FakeAdapter()
    intent = OrderIntent(symbol="BTC/USDT", side="buy", quantity=1)

    result = MarketOrderExecutor(adapter).execute(intent)

    assert result.success is True
    assert result.status == "filled"
    assert result.exchange_order_id == "m1"
    assert adapter.calls == [("market", "BTC/USDT"), ("wait", "m1", 12.0)]


def test_resting_limit_executor_submits_without_waiting_or_cancelling():
    adapter = FakeAdapter(fill_status="open", fill_qty=0)
    intent = OrderIntent(symbol="BTC/USDT", side="buy", quantity=1, price=90000)

    result = RestingLimitExecutor(adapter).execute(intent)

    assert result.success is True
    assert result.status == "submitted"
    assert result.exchange_order_id == "l1"
    assert adapter.calls == [("limit", "BTC/USDT")]


def test_limit_then_market_returns_limit_fill_when_complete():
    adapter = FakeAdapter(fill_status="filled", fill_qty=2)
    intent = OrderIntent(symbol="ETH/USDT", side="buy", quantity=2, price=100)

    result = LimitThenMarketExecutor(adapter, max_wait_sec=3).execute(intent)

    assert result.success is True
    assert result.status == "filled"
    assert result.exchange_order_id == "l1"
    assert adapter.calls == [("limit", "ETH/USDT"), ("wait", "l1", 3.0)]


def test_limit_then_market_cancels_and_falls_back_when_unfilled():
    adapter = FakeAdapter(fill_status="open", fill_qty=0)
    intent = OrderIntent(symbol="SOL/USDT", side="sell", quantity=3, price=100)

    result = LimitThenMarketExecutor(adapter, max_wait_sec=1, fallback_to_market=True).execute(intent)

    assert result.success is True
    assert result.exchange_order_id == "m1"
    assert adapter.calls == [
        ("limit", "SOL/USDT"),
        ("wait", "l1", 1.0),
        ("cancel", "l1"),
        ("market", "SOL/USDT"),
        ("wait", "m1", 12.0),
    ]


def test_limit_then_market_preserves_partial_limit_fill_and_markets_remaining():
    adapter = FakeAdapter(fill_status="open", fill_qty=1)
    intent = OrderIntent(symbol="SOL/USDT", side="sell", quantity=3, price=100)

    result = LimitThenMarketExecutor(adapter, max_wait_sec=1, fallback_to_market=True).execute(intent)

    assert result.success is True
    assert result.filled_qty == 3
    assert result.avg_price == 100.66666666666667
    assert adapter.calls == [
        ("limit", "SOL/USDT"),
        ("wait", "l1", 1.0),
        ("cancel", "l1"),
        ("market", "SOL/USDT"),
        ("wait", "m1", 12.0),
    ]
