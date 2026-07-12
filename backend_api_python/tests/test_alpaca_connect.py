from uuid import UUID
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.alpaca_trading.client import AlpacaClient, AlpacaConfig, _as_str_id, _id_log_prefix


def test_as_str_id_from_uuid():
    uid = UUID("12345678-1234-5678-1234-567812345678")
    assert _as_str_id(uid) == "12345678-1234-5678-1234-567812345678"
    assert _id_log_prefix(uid) == "12345678-123"


@patch("app.services.alpaca_trading.client._ensure_alpaca")
def test_alpaca_connect_stores_string_account_id(mock_ensure):
    mock_modules = {
        "TradingClient": MagicMock(),
        "StockHistoricalDataClient": MagicMock(),
        "CryptoHistoricalDataClient": MagicMock(),
    }
    mock_ensure.return_value = mock_modules

    account = MagicMock()
    account.id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    account.status = "ACTIVE"

    trading = MagicMock()
    trading.get_account.return_value = account
    mock_modules["TradingClient"].return_value = trading

    client = AlpacaClient(
        AlpacaConfig(api_key="PKtest", secret_key="secret", paper=True)
    )
    assert client.connect() is True
    assert client._account_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert isinstance(client._account_id, str)
    mock_modules["StockHistoricalDataClient"].assert_called_once_with(
        api_key="PKtest", secret_key="secret", sandbox=False
    )
    mock_modules["CryptoHistoricalDataClient"].assert_called_once_with(
        api_key="PKtest", secret_key="secret", sandbox=False
    )


@patch("app.services.alpaca_trading.client.time.sleep", return_value=None)
@patch("app.services.alpaca_trading.client._ensure_alpaca")
def test_crypto_market_sell_caps_quantity_to_available_position(mock_ensure, _mock_sleep):
    market_request = MagicMock()
    modules = {
        "MarketOrderRequest": market_request,
        "OrderSide": SimpleNamespace(BUY="buy", SELL="sell"),
        "TimeInForce": SimpleNamespace(GTC="gtc", DAY="day"),
    }
    mock_ensure.return_value = modules
    trading = MagicMock()
    trading.get_all_positions.return_value = [SimpleNamespace(symbol="BTCUSD", qty="0.000349125")]
    order = SimpleNamespace(
        id="order-1",
        filled_qty="0.000349125",
        filled_avg_price="100000",
        status=SimpleNamespace(value="filled"),
        submitted_at="now",
    )
    trading.submit_order.return_value = order
    trading.get_order_by_id.return_value = order

    client = AlpacaClient(AlpacaConfig(api_key="PKtest", secret_key="secret", paper=True))
    client._trading_client = trading
    client._account_id = "account-1"

    result = client.place_market_order("BTC/USD", "sell", 0.00035, "crypto")

    assert result.success is True
    market_request.assert_called_once_with(
        symbol="BTC/USD", qty=0.000349125, side="sell", time_in_force="gtc"
    )
    assert result.raw["requested_qty"] == 0.00035
    assert result.raw["submitted_qty"] == 0.000349125
