from contextlib import AbstractContextManager

from app.services import pending_order_worker as worker_module


class FakeCursor:
    def __init__(self, calls):
        self.calls = calls

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def close(self):
        return None


class FakeConnection(AbstractContextManager):
    def __init__(self, calls):
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self.calls)

    def commit(self):
        return None


def test_alpaca_fill_snapshot_updates_intent_without_an_undefined_order_id(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_module, "get_db_connection", lambda: FakeConnection(calls))
    worker = object.__new__(worker_module.PendingOrderWorker)

    worker._update_alpaca_sent_order_snapshot(
        order_id=42,
        status="sent",
        exchange_status="partially_filled",
        filled=0.25,
        avg_price=100.0,
        exchange_response_json="{}",
        final=False,
    )

    assert len(calls) == 2
    intent_sql, intent_params = calls[1]
    assert "po.exchange_order_id" in intent_sql
    assert intent_params == ("sent", "sent", "sent", 0.25, 42)
