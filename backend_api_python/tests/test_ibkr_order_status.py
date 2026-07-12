from types import SimpleNamespace

from app.services.ibkr_trading.client import IBKRClient


def test_ibkr_get_order_status_queries_completed_orders_after_restart():
    order = SimpleNamespace(orderId=123, permId=987)
    status = SimpleNamespace(status="Filled", filled=4, remaining=0, avgFillPrice=205.25)
    trade = SimpleNamespace(order=order, orderStatus=status)
    ib = SimpleNamespace(
        openTrades=lambda: [],
        trades=lambda: [],
        reqCompletedOrders=lambda api_only: [trade],
    )
    client = object.__new__(IBKRClient)
    client._ib = ib
    client._ensure_connected = lambda: None

    result = client.get_order_status(123)

    assert result.success is True
    assert result.status == "Filled"
    assert result.filled == 4
    assert result.avg_price == 205.25
    assert result.raw["permId"] == 987
