"""
Factory for direct exchange clients.

Supports:
- Crypto exchanges: Binance, OKX, Bitget, Bybit, Coinbase, Kraken, KuCoin, Gate, Bitfinex
- Traditional brokers: Interactive Brokers (IBKR) for US stocks
- Forex brokers: MetaTrader 5 (MT5)
"""

from __future__ import annotations

from typing import Any, Dict, Union

from app.services.live_trading.base import BaseRestClient, LiveTradingError
from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.okx import OkxClient
from app.services.live_trading.bitget import BitgetMixClient
from app.services.live_trading.bitget_spot import BitgetSpotClient
from app.services.live_trading.bybit import BybitClient
from app.services.live_trading.coinbase_exchange import CoinbaseExchangeClient
from app.services.live_trading.kraken import KrakenClient
from app.services.live_trading.kraken_futures import KrakenFuturesClient
from app.services.live_trading.kucoin import KucoinSpotClient, KucoinFuturesClient
from app.services.live_trading.gate import GateSpotClient, GateUsdtFuturesClient
from app.services.live_trading.bitfinex import BitfinexClient, BitfinexDerivativesClient
from app.services.live_trading.deepcoin import DeepcoinClient

# Lazy import IBKR to avoid ImportError if ib_insync not installed
IBKRClient = None
IBKRConfig = None

# Lazy import MT5 to avoid ImportError if MetaTrader5 not installed
MT5Client = None
MT5Config = None


def _get(cfg: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = cfg.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def create_client(exchange_config: Dict[str, Any], *, market_type: str = "swap") -> BaseRestClient:
    if not isinstance(exchange_config, dict):
        raise LiveTradingError("Invalid exchange_config")
    exchange_id = _get(exchange_config, "exchange_id", "exchangeId").lower()
    api_key = _get(exchange_config, "api_key", "apiKey")
    secret_key = _get(exchange_config, "secret_key", "secret")
    passphrase = _get(exchange_config, "passphrase", "password")

    mt = (market_type or exchange_config.get("market_type") or exchange_config.get("defaultType") or "swap").strip().lower()
    if mt in ("futures", "future", "perp", "perpetual"):
        mt = "swap"

    if exchange_id == "binance":
        # 检查是否启用模拟交易，支持布尔值和字符串
        enable_demo = exchange_config.get("enable_demo_trading") or exchange_config.get("enableDemoTrading")
        is_demo = bool(enable_demo) if isinstance(enable_demo, bool) else str(enable_demo).lower() in ("true", "1", "yes")
        
        if mt == "spot":
            default_url = "https://demo-api.binance.com" if is_demo else "https://api.binance.com"
            base_url = _get(exchange_config, "base_url", "baseUrl") or default_url
            return BinanceSpotClient(api_key=api_key, secret_key=secret_key, base_url=base_url, enable_demo_trading=is_demo)
        # Default to USDT-M futures  
        default_url = "https://demo-fapi.binance.com" if is_demo else "https://fapi.binance.com"
        base_url = _get(exchange_config, "base_url", "baseUrl") or default_url
        return BinanceFuturesClient(api_key=api_key, secret_key=secret_key, base_url=base_url, enable_demo_trading=is_demo)
    if exchange_id == "okx":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://www.okx.com"
        broker_code = "56fa80b0ce8cBCDE"
        return OkxClient(
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
            base_url=base_url,
            broker_code=broker_code
        )
    if exchange_id == "bitget":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.bitget.com"
        if mt == "spot":
            channel_api_code = _get(exchange_config, "channel_api_code", "channelApiCode") or "bntva"
            return BitgetSpotClient(api_key=api_key, secret_key=secret_key, passphrase=passphrase, base_url=base_url, channel_api_code=channel_api_code)
        return BitgetMixClient(api_key=api_key, secret_key=secret_key, passphrase=passphrase, base_url=base_url)

    if exchange_id == "bybit":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.bybit.com"
        category = "spot" if mt == "spot" else "linear"
        recv_window_ms = int(exchange_config.get("recv_window_ms") or exchange_config.get("recvWindow") or 5000)
        return BybitClient(api_key=api_key, secret_key=secret_key, base_url=base_url, category=category, recv_window_ms=recv_window_ms)

    if exchange_id in ("coinbaseexchange", "coinbase_exchange"):
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.exchange.coinbase.com"
        if mt != "spot":
            raise LiveTradingError("CoinbaseExchange only supports spot market_type in this project")
        return CoinbaseExchangeClient(api_key=api_key, secret_key=secret_key, passphrase=passphrase, base_url=base_url)

    if exchange_id == "kraken":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.kraken.com"
        if mt == "spot":
            return KrakenClient(api_key=api_key, secret_key=secret_key, base_url=base_url)
        # Futures/perp
        fut_url = _get(exchange_config, "futures_base_url", "futuresBaseUrl") or "https://futures.kraken.com"
        return KrakenFuturesClient(api_key=api_key, secret_key=secret_key, base_url=fut_url)

    if exchange_id == "kucoin":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.kucoin.com"
        if mt == "spot":
            return KucoinSpotClient(api_key=api_key, secret_key=secret_key, passphrase=passphrase, base_url=base_url)
        fut_url = _get(exchange_config, "futures_base_url", "futuresBaseUrl") or "https://api-futures.kucoin.com"
        return KucoinFuturesClient(api_key=api_key, secret_key=secret_key, passphrase=passphrase, base_url=fut_url)

    if exchange_id == "gate":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.gateio.ws"
        if mt == "spot":
            return GateSpotClient(api_key=api_key, secret_key=secret_key, base_url=base_url)
        # Default to USDT futures for swap
        return GateUsdtFuturesClient(api_key=api_key, secret_key=secret_key, base_url=base_url)

    if exchange_id == "bitfinex":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.bitfinex.com"
        if mt == "spot":
            return BitfinexClient(api_key=api_key, secret_key=secret_key, base_url=base_url)
        return BitfinexDerivativesClient(api_key=api_key, secret_key=secret_key, base_url=base_url)

    if exchange_id == "deepcoin":
        base_url = _get(exchange_config, "base_url", "baseUrl") or "https://api.deepcoin.com"
        return DeepcoinClient(
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
            base_url=base_url,
            market_type=mt,
        )

    # Traditional brokers (IBKR for US stocks only)
    if exchange_id == "ibkr":
        # Note: Market category validation should be done at the caller level
        # This factory only creates clients based on exchange_id
        return create_ibkr_client(exchange_config)

    # Forex brokers (MT5 for Forex only)
    if exchange_id == "mt5":
        # Note: Market category validation should be done at the caller level
        # This factory only creates clients based on exchange_id
        return create_mt5_client(exchange_config)

    raise LiveTradingError(f"Unsupported exchange_id: {exchange_id}")


def create_ibkr_client(exchange_config: Dict[str, Any]):
    """
    Create IBKR client for US stock trading.

    exchange_config should contain:
    - ibkr_host: TWS/Gateway host (default: 127.0.0.1)
    - ibkr_port: TWS/Gateway port (default: 7497)
    - ibkr_client_id: Client ID (default: 1)
    - ibkr_account: Account ID (optional, auto-select if empty)
    """
    global IBKRClient, IBKRConfig

    # Lazy import to avoid ImportError if ib_insync not installed
    if IBKRClient is None or IBKRConfig is None:
        try:
            from app.services.ibkr_trading import IBKRClient as _IBKRClient, IBKRConfig as _IBKRConfig
            IBKRClient = _IBKRClient
            IBKRConfig = _IBKRConfig
        except ImportError:
            raise LiveTradingError("IBKR trading requires ib_insync. Run: pip install ib_insync")

    host = str(exchange_config.get("ibkr_host") or "127.0.0.1").strip()
    port = int(exchange_config.get("ibkr_port") or 7497)
    client_id = int(exchange_config.get("ibkr_client_id") or 1)
    account = str(exchange_config.get("ibkr_account") or "").strip()

    config = IBKRConfig(
        host=host,
        port=port,
        client_id=client_id,
        account=account,
        readonly=False,
    )

    client = IBKRClient(config)

    # Connect immediately (IBKR requires active connection)
    if not client.connect():
        raise LiveTradingError("Failed to connect to IBKR TWS/Gateway. Please check if it's running.")

    return client


def create_mt5_client(exchange_config: Dict[str, Any]):
    """
    Create MT5 client for forex trading.

    exchange_config should contain:
    - mt5_login: MT5 account number
    - mt5_password: MT5 password
    - mt5_server: Broker server name (e.g., "ICMarkets-Demo")
    - mt5_terminal_path: Optional path to terminal64.exe
    - market_category: Must be "Forex" (validated)
    
    Note: MT5 is ONLY for Forex trading, not for Crypto or Stocks.
    """
    global MT5Client, MT5Config

    # Validate market category - MT5 is ONLY for Forex
    market_category = str(exchange_config.get("market_category") or "").strip()
    if market_category and market_category != "Forex":
        raise LiveTradingError(
            f"MT5 can only be used for Forex trading, but market_category is '{market_category}'. "
            f"MT5 does not support Crypto or Stock trading. Please use MT5 only with Forex market."
        )

    # Lazy import to avoid ImportError if MetaTrader5 not installed
    if MT5Client is None or MT5Config is None:
        try:
            from app.services.mt5_trading import MT5Client as _MT5Client, MT5Config as _MT5Config
            MT5Client = _MT5Client
            MT5Config = _MT5Config
        except ImportError:
            raise LiveTradingError(
                "MT5 trading requires MetaTrader5 library. Run: pip install MetaTrader5\n"
                "Note: This library only works on Windows."
            )

    # Handle login as int (may come as string from JSON)
    login_raw = exchange_config.get("mt5_login") or 0
    try:
        login = int(login_raw) if login_raw else 0
    except (ValueError, TypeError):
        # Try converting string to int
        try:
            login = int(str(login_raw).strip())
        except (ValueError, TypeError):
            login = 0
    
    password = str(exchange_config.get("mt5_password") or "").strip()
    server = str(exchange_config.get("mt5_server") or "").strip()
    terminal_path = str(exchange_config.get("mt5_terminal_path") or "").strip()

    if not login or not password or not server:
        raise LiveTradingError("MT5 requires login, password, and server")

    config = MT5Config(
        login=login,
        password=password,
        server=server,
        terminal_path=terminal_path,
    )

    client = MT5Client(config)

    # Connect immediately
    if not client.connect():
        raise LiveTradingError(
            "Failed to connect to MT5 terminal. Please check:\n"
            "1. MT5 terminal is running\n"
            "2. Credentials are correct\n"
            "3. You are on Windows"
        )

    return client


