from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _namespace(name, path):
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


_namespace("app", ROOT / "app")
_namespace("app.services", ROOT / "app" / "services")
_namespace("app.services.live_trading", ROOT / "app" / "services" / "live_trading")
_namespace("app.utils", ROOT / "app" / "utils")

resource_guard = types.ModuleType("app.utils.resource_guard")
resource_guard.ResourceExhaustedError = RuntimeError
resource_guard.assert_fd_available = lambda _label: None
resource_guard.is_fd_exhaustion = lambda _exc: False
resource_guard.mark_fd_exhausted = lambda _exc: None
sys.modules.setdefault("app.utils.resource_guard", resource_guard)

from app.services.live_trading.base import LiveOrderResult
from app.services.live_trading.contracts import FillSnapshot, OrderIntent, PositionSnapshot
from app.services.live_trading.executors import LimitThenMarketExecutor, MarketOrderExecutor


@dataclass
class DurableLedger:
    position_qty: float = 0.0
    orders: dict = field(default_factory=dict)


class SimulatedExchangeAdapter:
    exchange_id = "simulated"

    def __init__(self, ledger: DurableLedger, *, limit_fill_qty: float = 0.0):
        self.ledger = ledger
        self.limit_fill_qty = float(limit_fill_qty)
        self.calls = []

    def _existing(self, intent: OrderIntent):
        return self.ledger.orders.get(str(intent.client_order_id or ""))

    def _remember(self, intent: OrderIntent, result: LiveOrderResult):
        key = str(intent.client_order_id or "")
        if key:
            self.ledger.orders[key] = result
        return result

    def place_limit_order(self, intent: OrderIntent):
        self.calls.append(("limit", intent.client_order_id, intent.quantity))
        existing = self._existing(intent)
        if existing:
            return existing
        return self._remember(
            intent,
            LiveOrderResult(self.exchange_id, "limit-1", 0.0, 0.0, {}),
        )

    def place_market_order(self, intent: OrderIntent):
        self.calls.append(("market", intent.client_order_id, intent.quantity, intent.reduce_only))
        existing = self._existing(intent)
        if existing:
            return existing
        qty = float(intent.quantity or 0.0)
        if intent.reduce_only:
            qty = min(qty, self.ledger.position_qty)
            self.ledger.position_qty -= qty
        else:
            self.ledger.position_qty += qty
        return self._remember(
            intent,
            LiveOrderResult(self.exchange_id, f"market-{len(self.ledger.orders) + 1}", qty, 101.0, {}),
        )

    def wait_for_fill(self, intent: OrderIntent, *, order_id: str = "", max_wait_sec: float = 15.0):
        self.calls.append(("wait", order_id, max_wait_sec))
        if order_id == "limit-1":
            qty = min(float(intent.quantity or 0.0), self.limit_fill_qty)
            if qty > 0 and not self.ledger.orders.get("limit-fill-applied"):
                self.ledger.position_qty += qty
                self.ledger.orders["limit-fill-applied"] = True
            return FillSnapshot(qty, 100.0 if qty > 0 else 0.0, "partial" if qty > 0 else "open", {})
        placed = self._existing(intent)
        return FillSnapshot(
            float(placed.filled if placed else 0.0),
            float(placed.avg_price if placed else 0.0),
            "filled",
            {},
        )

    def cancel_order(self, intent: OrderIntent, *, order_id: str = ""):
        self.calls.append(("cancel", order_id))
        return {"ok": True}

    def query_position(self, intent: OrderIntent):
        return PositionSnapshot(intent.symbol, intent.pos_side or "long", self.ledger.position_qty, 100.5, {})


def test_partial_fill_cancel_market_fallback_close_and_restart_idempotency():
    ledger = DurableLedger()
    first_process = SimulatedExchangeAdapter(ledger, limit_fill_qty=1.0)
    open_intent = OrderIntent(
        symbol="BTC/USDT",
        side="buy",
        quantity=3.0,
        price=100.0,
        pos_side="long",
        client_order_id="open-limit",
        fallback_client_order_id="open-market",
    )

    opened = LimitThenMarketExecutor(
        first_process,
        max_wait_sec=0.1,
        fallback_to_market=True,
    ).execute(open_intent)

    assert opened.success is True
    assert opened.filled_qty == pytest.approx(3.0)
    assert opened.avg_price == pytest.approx((1 * 100 + 2 * 101) / 3)
    assert ledger.position_qty == pytest.approx(3.0)
    assert ("cancel", "limit-1") in first_process.calls

    restarted_process = SimulatedExchangeAdapter(ledger)
    close_intent = OrderIntent(
        symbol="BTC/USDT",
        side="sell",
        quantity=3.0,
        pos_side="long",
        reduce_only=True,
        client_order_id="close-market",
    )
    closed = MarketOrderExecutor(restarted_process).execute(close_intent)
    replayed = MarketOrderExecutor(restarted_process).execute(close_intent)

    assert closed.success is True
    assert closed.filled_qty == pytest.approx(3.0)
    assert replayed.exchange_order_id == closed.exchange_order_id
    assert ledger.position_qty == pytest.approx(0.0)
    assert restarted_process.query_position(close_intent).base_qty == pytest.approx(0.0)
