import os
import time
import json
import threading
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.utils.logger import get_logger
from app.utils.db import get_db_connection

logger = get_logger(__name__)

class StrategyService:
    """Strategy service."""
    
    # Class variable: limit connection test concurrency
    _connection_test_semaphore = threading.Semaphore(5)
    
    def __init__(self):
        # Local deployment: do not use encryption/decryption.
        pass
        
    def get_running_strategies(self) -> List[Dict[str, Any]]:
        """Get all running strategies (ID only)"""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                query = "SELECT id FROM qd_strategies_trading WHERE status = 'running'"
                cursor.execute(query)
                results = cursor.fetchall()
                cursor.close()
                return [row['id'] for row in results]
        except Exception as e:
            logger.error(f"Failed to fetch running strategies: {str(e)}")
            return []

    def get_running_strategies_with_type(self) -> List[Dict[str, Any]]:
        """Get all running strategies (with type info)"""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                # Assume qd_strategies_trading table has strategy_type field
                # If not, may need join query or determine from other fields
                # Here we assume table structure is updated
                query = "SELECT id, strategy_type FROM qd_strategies_trading WHERE status = 'running'"
                cursor.execute(query)
                results = cursor.fetchall()
                cursor.close()
                
                strategies = [{'id': row['id'], 'strategy_type': row.get('strategy_type', '')} for row in results]
                logger.info(f"Found {len(strategies)} running strategies: {strategies}")
                return strategies
                
        except Exception as e:
            logger.error(f"Failed to fetch running strategies: {str(e)}")
            return []
    
    def get_exchange_symbols(self, exchange_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get exchange trading pairs (no API Key required)
        """
        try:
            exchange_id = exchange_config.get('exchange_id', '')
            proxies = exchange_config.get('proxies')
            
            if not exchange_id:
                return {'success': False, 'message': 'Please select an exchange', 'symbols': []}

            # For these exchanges, prefer direct REST (no ccxt), aligned with local live-trading design.
            ex = str(exchange_id or "").strip().lower()
            if ex in ("bybit", "coinbaseexchange", "coinbase_exchange", "kraken", "kucoin", "gate", "bitfinex"):
                import requests

                def _req_json(url: str) -> Any:
                    r = requests.get(url, timeout=15, proxies=proxies)
                    r.raise_for_status()
                    return r.json()

                symbols: List[str] = []
                market_type = str(exchange_config.get("market_type") or exchange_config.get("defaultType") or "spot").strip().lower()
                if market_type in ("futures", "future", "perp", "perpetual"):
                    market_type = "swap"
                if ex == "bybit":
                    base = str(exchange_config.get("base_url") or exchange_config.get("baseUrl") or "https://api.bybit.com").rstrip("/")
                    cat = "spot" if market_type == "spot" else "linear"
                    j = _req_json(f"{base}/v5/market/instruments-info?category={cat}")
                    lst = (((j.get("result") or {}).get("list")) if isinstance(j, dict) else None) or []
                    if isinstance(lst, list):
                        for it in lst:
                            if not isinstance(it, dict):
                                continue
                            sym = str(it.get("symbol") or "")
                            status = str(it.get("status") or "").lower()
                            if not sym or (status and status not in ("trading", "tradable", "online")):
                                continue
                            if sym.endswith("USDT") and len(sym) > 4:
                                symbols.append(f"{sym[:-4]}/USDT")
                    symbols = sorted(list(set(symbols)))
                    return {'success': True, 'message': f'Success, {len(symbols)} trading pairs', 'symbols': symbols}

                if ex in ("coinbaseexchange", "coinbase_exchange"):
                    base = str(exchange_config.get("base_url") or exchange_config.get("baseUrl") or "https://api.exchange.coinbase.com").rstrip("/")
                    j = _req_json(f"{base}/products")
                    if isinstance(j, list):
                        for it in j:
                            if not isinstance(it, dict):
                                continue
                            if str(it.get("status") or "").lower() not in ("online", ""):
                                continue
                            base_ccy = str(it.get("base_currency") or "").upper()
                            quote_ccy = str(it.get("quote_currency") or "").upper()
                            if quote_ccy == "USDT" and base_ccy:
                                symbols.append(f"{base_ccy}/USDT")
                    symbols = sorted(list(set(symbols)))
                    return {'success': True, 'message': f'Success, {len(symbols)} trading pairs', 'symbols': symbols}

                if ex == "kraken":
                    if market_type == "spot":
                        j = _req_json("https://api.kraken.com/0/public/AssetPairs")
                        res = (j.get("result") if isinstance(j, dict) else None) or {}
                        if isinstance(res, dict):
                            for _k, v in res.items():
                                if not isinstance(v, dict):
                                    continue
                                wsname = str(v.get("wsname") or "")
                                if not wsname or "/" not in wsname:
                                    continue
                                base_ccy, quote_ccy = wsname.split("/", 1)
                                if str(quote_ccy).upper() == "USDT":
                                    symbols.append(f"{str(base_ccy).upper()}/USDT")
                    else:
                        base = str(exchange_config.get("futures_base_url") or exchange_config.get("futuresBaseUrl") or "https://futures.kraken.com").rstrip("/")
                        j = _req_json(f"{base}/derivatives/api/v3/instruments")
                        instruments = j.get("instruments") if isinstance(j, dict) else None
                        if isinstance(instruments, list):
                            for it in instruments:
                                if not isinstance(it, dict):
                                    continue
                                sym = str(it.get("symbol") or "")
                                typ = str(it.get("type") or "").lower()
                                if sym and ("perpetual" in typ or typ.startswith("pf") or sym.startswith("PF_")):
                                    symbols.append(sym)
                    symbols = sorted(list(set(symbols)))
                    return {'success': True, 'message': f'Success, {len(symbols)} trading pairs', 'symbols': symbols}

                if ex == "kucoin":
                    if market_type == "spot":
                        base = str(exchange_config.get("base_url") or exchange_config.get("baseUrl") or "https://api.kucoin.com").rstrip("/")
                        j = _req_json(f"{base}/api/v1/symbols")
                        data = (j.get("data") if isinstance(j, dict) else None) or []
                        if isinstance(data, list):
                            for it in data:
                                if not isinstance(it, dict):
                                    continue
                                if not bool(it.get("enableTrading", True)):
                                    continue
                                if str(it.get("quoteCurrency") or "").upper() != "USDT":
                                    continue
                                b = str(it.get("baseCurrency") or "").upper()
                                if b:
                                    symbols.append(f"{b}/USDT")
                    else:
                        base = str(exchange_config.get("futures_base_url") or exchange_config.get("futuresBaseUrl") or "https://api-futures.kucoin.com").rstrip("/")
                        j = _req_json(f"{base}/api/v1/contracts/active")
                        data = (j.get("data") if isinstance(j, dict) else None) or []
                        if isinstance(data, list):
                            for it in data:
                                if not isinstance(it, dict):
                                    continue
                                sym = str(it.get("symbol") or "")
                                if not sym or not sym.upper().endswith("USDTM"):
                                    continue
                                base_ccy = sym[:-5].upper()
                                if base_ccy == "XBT":
                                    base_ccy = "BTC"
                                if base_ccy:
                                    symbols.append(f"{base_ccy}/USDT")
                    symbols = sorted(list(set(symbols)))
                    return {'success': True, 'message': f'Success, {len(symbols)} trading pairs', 'symbols': symbols}

                if ex == "gate":
                    base = str(exchange_config.get("base_url") or exchange_config.get("baseUrl") or "https://api.gateio.ws").rstrip("/")
                    if market_type == "spot":
                        j = _req_json(f"{base}/api/v4/spot/currency_pairs")
                        if isinstance(j, list):
                            for it in j:
                                if not isinstance(it, dict):
                                    continue
                                if str(it.get("trade_status") or "").lower() not in ("tradable", "trading", ""):
                                    continue
                                base_ccy = str(it.get("base") or "").upper()
                                quote_ccy = str(it.get("quote") or "").upper()
                                if quote_ccy == "USDT" and base_ccy:
                                    symbols.append(f"{base_ccy}/USDT")
                    else:
                        j = _req_json(f"{base}/api/v4/futures/usdt/contracts")
                        if isinstance(j, list):
                            for it in j:
                                if not isinstance(it, dict):
                                    continue
                                name = str(it.get("name") or it.get("contract") or "")
                                if name and name.upper().endswith("_USDT"):
                                    symbols.append(name.replace("_", "/"))
                    symbols = sorted(list(set(symbols)))
                    return {'success': True, 'message': f'Success, {len(symbols)} trading pairs', 'symbols': symbols}

                if ex == "bitfinex":
                    j = _req_json("https://api-pub.bitfinex.com/v2/conf/pub:list:pair:exchange") if market_type == "spot" else _req_json(
                        "https://api-pub.bitfinex.com/v2/conf/pub:list:pair:futures"
                    )
                    pairs = []
                    if isinstance(j, list) and j and isinstance(j[0], list):
                        pairs = j[0]
                    for p in pairs:
                        s = str(p or "").upper()
                        if not s:
                            continue
                        if market_type != "spot":
                            symbols.append(s)
                            continue
                        # Focus USDT (Bitfinex uses UST)
                        if s.endswith("UST") and len(s) > 3:
                            symbols.append(f"{s[:-3]}/USDT")
                        elif s.endswith("USDT") and len(s) > 4:
                            symbols.append(f"{s[:-4]}/USDT")
                    symbols = sorted(list(set(symbols)))
                    return {'success': True, 'message': f'Success, {len(symbols)} trading pairs', 'symbols': symbols}
                return {'success': True, 'message': 'Success', 'symbols': symbols}
            
            import ccxt
            
            # Create exchange instance (public only)
            exchange_class = getattr(ccxt, exchange_id, None)
            if not exchange_class:
                return {'success': False, 'message': f'Unsupported exchange: {exchange_id}', 'symbols': []}
            
            exchange_config_dict = {
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'}  # Default to swap
            }
            if proxies:
                exchange_config_dict['proxies'] = proxies
            
            exchange = exchange_class(exchange_config_dict)
            markets = exchange.load_markets()
            
            symbols = []
            for symbol, market in markets.items():
                if market.get('active', False) and market.get('quote') == 'USDT':
                    symbols.append(symbol)
            
            symbols.sort()
            return {'success': True, 'message': f'Success, {len(symbols)} trading pairs', 'symbols': symbols}
            
        except Exception as e:
            logger.error(f"Failed to fetch symbols: {str(e)}")
            return {'success': False, 'message': f'Failed to get trading pairs: {str(e)}', 'symbols': []}
    
    def test_exchange_connection(self, exchange_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test exchange connection via direct REST clients (no ccxt).

        Notes:
        - This is local-only; failures are returned as user-friendly messages.
        - We do not log secrets.
        """
        # Limit concurrency to protect CPU / rate limits
        with StrategyService._connection_test_semaphore:
            try:
                from app.services.exchange_execution import resolve_exchange_config, safe_exchange_config_for_log
                from app.services.live_trading.factory import create_client
                from app.services.live_trading.binance import BinanceFuturesClient
                from app.services.live_trading.binance_spot import BinanceSpotClient
                from app.services.live_trading.okx import OkxClient
                from app.services.live_trading.bitget import BitgetMixClient
                from app.services.live_trading.bybit import BybitClient
                from app.services.live_trading.coinbase_exchange import CoinbaseExchangeClient
                from app.services.live_trading.kraken import KrakenClient
                from app.services.live_trading.kraken_futures import KrakenFuturesClient
                from app.services.live_trading.kucoin import KucoinSpotClient
                from app.services.live_trading.kucoin import KucoinFuturesClient
                from app.services.live_trading.gate import GateSpotClient, GateUsdtFuturesClient
                from app.services.live_trading.bitfinex import BitfinexClient, BitfinexDerivativesClient
                from app.services.live_trading.deepcoin import DeepcoinClient

                resolved = resolve_exchange_config(exchange_config or {})
                safe_cfg = safe_exchange_config_for_log(resolved)

                exchange_id = (resolved.get("exchange_id") or "").strip().lower()
                if not exchange_id:
                    return {'success': False, 'message': 'Missing exchange_id', 'data': None}

                # Handle MT5 (Forex) connection test
                if exchange_id == 'mt5':
                    # Validate that MT5 is only used for Forex market
                    market_category = str(resolved.get("market_category") or exchange_config.get("market_category") or "").strip()
                    if market_category and market_category != "Forex":
                        return {
                            'success': False,
                            'message': f'MT5 can only be used for Forex trading, but market_category is {market_category}. Please use MT5 only with Forex market.',
                            'data': {'exchange': safe_cfg}
                        }
                    
                    try:
                        from app.services.live_trading.factory import create_mt5_client
                        mt5_client = create_mt5_client(resolved)
                        if mt5_client and mt5_client.connected:
                            # Get account info if available
                            account_info = None
                            try:
                                account_info = mt5_client.get_account_info()
                            except Exception:
                                pass
                            return {
                                'success': True,
                                'message': 'MT5 connection successful',
                                'data': {
                                    'exchange': safe_cfg,
                                    'account': account_info
                                }
                            }
                        else:
                            return {
                                'success': False,
                                'message': 'Failed to connect to MT5. Please check credentials and ensure terminal is running.',
                                'data': {'exchange': safe_cfg}
                            }
                    except Exception as e:
                        error_msg = str(e)
                        return {
                            'success': False,
                            'message': f'MT5 connection failed: {error_msg}',
                            'data': {'exchange': safe_cfg}
                        }

                # Handle IBKR (US Stocks) connection test
                if exchange_id == 'ibkr':
                    try:
                        from app.services.live_trading.factory import create_ibkr_client
                        ibkr_client = create_ibkr_client(resolved)
                        # create_ibkr_client already connects, so if it returns, connection is successful
                        if ibkr_client and ibkr_client.connected():
                            # Get account summary if available
                            account_summary = None
                            try:
                                account_summary = ibkr_client.get_account_summary()
                            except Exception:
                                pass
                            return {
                                'success': True,
                                'message': 'IBKR connection successful',
                                'data': {
                                    'exchange': safe_cfg,
                                    'account': account_summary
                                }
                            }
                        else:
                            return {
                                'success': False,
                                'message': 'Failed to connect to IBKR. Please check TWS/Gateway is running and credentials are correct.',
                                'data': {'exchange': safe_cfg}
                            }
                    except Exception as e:
                        error_msg = str(e)
                        return {
                            'success': False,
                            'message': f'IBKR connection failed: {error_msg}',
                            'data': {'exchange': safe_cfg}
                        }

                # IMPORTANT:
                # Test connection should respect configured market_type (spot vs swap).
                # Otherwise Binance will default to futures endpoints (fapi) and spot-only keys will fail with -2015.
                market_type = str(resolved.get("market_type") or resolved.get("defaultType") or "swap").strip().lower()
                client = create_client(resolved, market_type=market_type)
                client_kind = type(client).__name__

                # Best-effort detect current egress IP (for Binance IP whitelist debugging).
                egress_ip = ""
                try:
                    import requests as _rq
                    egress_ip = str(_rq.get("https://ifconfig.me/ip", timeout=5).text or "").strip()
                except Exception:
                    egress_ip = ""

                # 1) Public connectivity
                ok_public = False
                try:
                    ok_public = bool(getattr(client, "ping")())
                except Exception:
                    ok_public = False
                if not ok_public:
                    return {
                        'success': False,
                        'message': f'Public ping failed: {exchange_id}',
                        'data': {'exchange': safe_cfg, 'client': client_kind, 'market_type': market_type, 'egress_ip': egress_ip},
                    }

                # 2) Private credential validation (best-effort)
                priv_data = None
                try:
                    if isinstance(client, BinanceFuturesClient):
                        priv_data = client.get_account()
                    elif isinstance(client, BinanceSpotClient):
                        priv_data = client.get_account()
                    elif isinstance(client, OkxClient):
                        priv_data = client.get_balance()
                    elif isinstance(client, BitgetMixClient):
                        product_type = str(resolved.get("product_type") or resolved.get("productType") or "USDT-FUTURES")
                        priv_data = client.get_accounts(product_type=product_type)
                    elif isinstance(client, BybitClient):
                        priv_data = client.get_wallet_balance()
                    elif isinstance(client, CoinbaseExchangeClient):
                        priv_data = client.get_accounts()
                    elif isinstance(client, KrakenClient):
                        priv_data = client.get_balance()
                    elif isinstance(client, KrakenFuturesClient):
                        priv_data = client.get_accounts()
                    elif isinstance(client, KucoinSpotClient):
                        priv_data = client.get_accounts()
                    elif isinstance(client, KucoinFuturesClient):
                        priv_data = client.get_accounts()
                    elif isinstance(client, GateSpotClient):
                        priv_data = client.get_accounts()
                    elif isinstance(client, GateUsdtFuturesClient):
                        priv_data = client.get_accounts()
                    elif isinstance(client, BitfinexClient):
                        priv_data = client.get_wallets()
                    elif isinstance(client, BitfinexDerivativesClient):
                        priv_data = client.get_wallets()
                    elif isinstance(client, DeepcoinClient):
                        priv_data = client.get_balance()
                except Exception as e:
                    msg = str(e)
                    # Add actionable hints for the most common Binance auth error.
                    if exchange_id == "binance" and ("-2015" in msg or "Invalid API-key, IP, or permissions" in msg):
                        # Auto A/B test: try the other market_type once to pinpoint permission mismatch.
                        alt_market_type = "spot" if market_type != "spot" else "swap"
                        alt_client_kind = ""
                        alt_base_url = ""
                        alt_ok = False
                        try:
                            alt_client = create_client(resolved, market_type=alt_market_type)
                            alt_client_kind = type(alt_client).__name__
                            alt_base_url = getattr(alt_client, "base_url", "") or ""
                            if isinstance(alt_client, BinanceFuturesClient) or isinstance(alt_client, BinanceSpotClient):
                                _ = alt_client.get_account()
                                alt_ok = True
                        except Exception:
                            alt_ok = False

                        base_url = getattr(client, "base_url", "") or ""
                        hint = (
                            f"Binance auth failed (-2015). Verify: "
                            f"(1) IP whitelist includes this server egress IP={egress_ip or 'unknown'}, "
                            f"(2) API key permissions match market_type={market_type} "
                            f"(spot requires Spot permissions; swap requires Futures permissions), "
                            f"(3) you're using binance.com keys for base_url={base_url or 'unknown'}."
                        )
                        if alt_ok:
                            hint += (
                                f" Auto-check: your key works for market_type={alt_market_type} "
                                f"(client={alt_client_kind}, base_url={alt_base_url or 'unknown'}) "
                                f"but fails for market_type={market_type}. This is almost always a permissions/product mismatch."
                            )
                        msg = f"{msg} | {hint}"
                    return {
                        'success': False,
                        'message': f'Auth failed: {msg}',
                        'data': {
                            'exchange': safe_cfg,
                            'client': client_kind,
                            'market_type': market_type,
                            'egress_ip': egress_ip,
                            'base_url': getattr(client, "base_url", "") or "",
                        },
                    }

                return {
                    'success': True,
                    'message': 'Connection OK',
                    'data': {
                        'exchange': safe_cfg,
                        'client': client_kind,
                        'market_type': market_type,
                        'egress_ip': egress_ip,
                        'base_url': getattr(client, "base_url", "") or "",
                        'private': priv_data,
                    },
                }
            except Exception as e:
                logger.error(f"test_exchange_connection failed: {str(e)}")
                return {'success': False, 'message': f'Connection failed: {str(e)}', 'data': None}

    def get_strategy_type(self, strategy_id: int) -> str:
        """Get strategy type from DB."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    "SELECT strategy_type FROM qd_strategies_trading WHERE id = ?",
                    (strategy_id,)
                )
                row = cur.fetchone()
                cur.close()
            return (row or {}).get('strategy_type') or 'IndicatorStrategy'
        except Exception:
            return 'IndicatorStrategy'

    def update_strategy_status(self, strategy_id: int, status: str, user_id: int = None) -> bool:
        """Update strategy status. If user_id is provided, verify ownership."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                if user_id is not None:
                    cur.execute(
                        "UPDATE qd_strategies_trading SET status = ?, updated_at = NOW() WHERE id = ? AND user_id = ?",
                        (status, strategy_id, user_id)
                    )
                else:
                    cur.execute(
                        "UPDATE qd_strategies_trading SET status = ?, updated_at = NOW() WHERE id = ?",
                        (status, strategy_id)
                    )
                db.commit()
                cur.close()
            return True
        except Exception as e:
            logger.error(f"update_strategy_status failed: {e}")
            return False

    def _safe_json_loads(self, value: Any, default: Any):
        """Load JSON string into Python object (local deployment: plaintext only)."""
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return default
        s = value.strip()
        if not s:
            return default
        try:
            return json.loads(s)
        except Exception:
            return default

    def _dump_json_or_encrypt(self, obj: Any, encrypt: bool = False) -> str:
        if obj is None:
            return ''
        # Local deployment: always store plaintext JSON.
        return json.dumps(obj, ensure_ascii=False)

    def list_strategies(self, user_id: int = 1) -> List[Dict[str, Any]]:
        """List strategies for the specified user."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM qd_strategies_trading
                    WHERE user_id = ?
                    ORDER BY id DESC
                    """,
                    (user_id,)
                )
                rows = cur.fetchall() or []
                cur.close()

            out = []
            for r in rows:
                ex = self._safe_json_loads(r.get('exchange_config'), {})
                ind = self._safe_json_loads(r.get('indicator_config'), {})
                tr = self._safe_json_loads(r.get('trading_config'), {})
                ai = self._safe_json_loads(r.get('ai_model_config'), {})
                notify = self._safe_json_loads(r.get('notification_config'), {})
                out.append({
                    **r,
                    'exchange_config': ex,
                    'indicator_config': ind,
                    'trading_config': tr,
                    'ai_model_config': ai,
                    'notification_config': notify
                })
            return out
        except Exception as e:
            logger.error(f"list_strategies failed: {e}")
            return []

    def get_strategy(self, strategy_id: int, user_id: int = None) -> Optional[Dict[str, Any]]:
        """Get strategy by ID. If user_id is provided, verify ownership."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                if user_id is not None:
                    cur.execute("SELECT * FROM qd_strategies_trading WHERE id = ? AND user_id = ?", (strategy_id, user_id))
                else:
                    cur.execute("SELECT * FROM qd_strategies_trading WHERE id = ?", (strategy_id,))
                r = cur.fetchone()
                cur.close()
            if not r:
                return None
            r['exchange_config'] = self._safe_json_loads(r.get('exchange_config'), {})
            r['indicator_config'] = self._safe_json_loads(r.get('indicator_config'), {})
            r['trading_config'] = self._safe_json_loads(r.get('trading_config'), {})
            r['ai_model_config'] = self._safe_json_loads(r.get('ai_model_config'), {})
            r['notification_config'] = self._safe_json_loads(r.get('notification_config'), {})
            return r
        except Exception as e:
            logger.error(f"get_strategy failed: {e}")
            return None

    def create_strategy(self, payload: Dict[str, Any]) -> int:
        name = (payload.get('strategy_name') or '').strip()
        if not name:
            raise ValueError("strategy_name is required")

        user_id = payload.get('user_id') or 1
        strategy_type = payload.get('strategy_type') or 'IndicatorStrategy'
        market_category = payload.get('market_category') or 'Crypto'
        execution_mode = payload.get('execution_mode') or 'signal'
        notification_config = payload.get('notification_config') or {}

        indicator_config = payload.get('indicator_config') or {}
        trading_config = payload.get('trading_config') or {}
        exchange_config = payload.get('exchange_config') or {}

        # Validate MT5 can only be used for Forex trading
        exchange_id = (exchange_config.get('exchange_id') or '').strip().lower() if isinstance(exchange_config, dict) else ''
        if exchange_id == 'mt5' and market_category != 'Forex':
            raise ValueError(
                f"MT5 can only be used for Forex trading, but market_category is '{market_category}'. "
                f"MT5 does not support Crypto or Stock trading. Please use MT5 only with Forex market."
            )

        # When credential_id is present, strip raw API keys to avoid
        # storing secrets in the strategy record — they live in qd_exchange_credentials.
        if isinstance(exchange_config, dict) and exchange_config.get('credential_id'):
            for _secret_key in ('api_key', 'secret_key', 'passphrase', 'apiKey', 'secret', 'password'):
                exchange_config.pop(_secret_key, None)

        # Strategy group fields
        strategy_group_id = payload.get('strategy_group_id') or ''
        group_base_name = payload.get('group_base_name') or ''

        # Denormalized fields for quick list rendering
        symbol = (trading_config or {}).get('symbol')
        timeframe = (trading_config or {}).get('timeframe')
        initial_capital = (trading_config or {}).get('initial_capital') or payload.get('initial_capital') or 1000
        leverage = (trading_config or {}).get('leverage') or 1
        market_type = (trading_config or {}).get('market_type') or 'swap'
        
        # Cross-sectional strategy fields (store in trading_config to avoid DB schema changes)
        cs_strategy_type = payload.get('cs_strategy_type') or trading_config.get('cs_strategy_type') or 'single'
        symbol_list = payload.get('symbol_list') or trading_config.get('symbol_list') or []
        portfolio_size = payload.get('portfolio_size') or trading_config.get('portfolio_size') or 10
        long_ratio = float(payload.get('long_ratio') or trading_config.get('long_ratio') or 0.5)
        rebalance_frequency = payload.get('rebalance_frequency') or trading_config.get('rebalance_frequency') or 'daily'
        
        # Store cross-sectional config in trading_config
        if cs_strategy_type == 'cross_sectional':
            trading_config['cs_strategy_type'] = cs_strategy_type
            trading_config['symbol_list'] = symbol_list
            trading_config['portfolio_size'] = portfolio_size
            trading_config['long_ratio'] = long_ratio
            trading_config['rebalance_frequency'] = rebalance_frequency

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_strategies_trading
                (user_id, strategy_name, strategy_type, market_category, execution_mode, notification_config,
                 status, symbol, timeframe, initial_capital, leverage, market_type,
                 exchange_config, indicator_config, trading_config, ai_model_config, decide_interval,
                 strategy_group_id, group_base_name,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())
                """,
                (
                    user_id,
                    name,
                    strategy_type,
                    market_category,
                    execution_mode,
                    self._dump_json_or_encrypt(notification_config, encrypt=False),
                    payload.get('status') or 'stopped',
                    symbol,
                    timeframe,
                    float(initial_capital or 1000),
                    int(leverage or 1),
                    market_type,
                    self._dump_json_or_encrypt(exchange_config, encrypt=False) if exchange_config else '',
                    self._dump_json_or_encrypt(indicator_config, encrypt=False),
                    self._dump_json_or_encrypt(trading_config, encrypt=False),
                    self._dump_json_or_encrypt(payload.get('ai_model_config') or {}, encrypt=False),
                    int(payload.get('decide_interval') or 300),
                    strategy_group_id,
                    group_base_name
                )
            )
            new_id = cur.lastrowid
            db.commit()
            cur.close()
        return int(new_id)

    def batch_create_strategies(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Batch create strategies (multi-symbol)
        
        Args:
            payload: Contains symbols (array) and other strategy config
            
        Returns:
            {
                'success': True/False,
                'strategy_group_id': '...',
                'created_ids': [1, 2, 3],
                'failed_symbols': []
            }
        """
        symbols = payload.get('symbols') or []
        if not symbols or not isinstance(symbols, list):
            raise ValueError("symbols array is required")
        
        base_name = (payload.get('strategy_name') or '').strip()
        if not base_name:
            raise ValueError("strategy_name is required")
        
        # Validate MT5 can only be used for Forex trading
        market_category = payload.get('market_category') or 'Crypto'
        exchange_config = payload.get('exchange_config') or {}
        exchange_id = (exchange_config.get('exchange_id') or '').strip().lower() if isinstance(exchange_config, dict) else ''
        if exchange_id == 'mt5' and market_category != 'Forex':
            raise ValueError(
                f"MT5 can only be used for Forex trading, but market_category is '{market_category}'. "
                f"MT5 does not support Crypto or Stock trading. Please use MT5 only with Forex market."
            )
        
        # Generate strategy group ID
        strategy_group_id = str(uuid.uuid4())[:8]
        
        created_ids = []
        failed_symbols = []
        
        for symbol in symbols:
            try:
                # Create individual strategy for each symbol
                single_payload = dict(payload)
                
                # Parse symbol (may be "Market:SYMBOL" format)
                if isinstance(symbol, str) and ':' in symbol:
                    parts = symbol.split(':', 1)
                    market_category = parts[0]
                    symbol_name = parts[1]
                else:
                    market_category = payload.get('market_category') or 'Crypto'
                    symbol_name = symbol
                
                # Strategy name with symbol suffix
                single_payload['strategy_name'] = f"{base_name}-{symbol_name}"
                single_payload['strategy_group_id'] = strategy_group_id
                single_payload['group_base_name'] = base_name
                single_payload['market_category'] = market_category
                
                # Update symbol in trading_config
                trading_config = dict(single_payload.get('trading_config') or {})
                trading_config['symbol'] = symbol_name
                single_payload['trading_config'] = trading_config
                
                new_id = self.create_strategy(single_payload)
                created_ids.append(new_id)
                
            except Exception as e:
                logger.error(f"Failed to create strategy for symbol {symbol}: {e}")
                failed_symbols.append({'symbol': symbol, 'error': str(e)})
        
        return {
            'success': len(created_ids) > 0,
            'strategy_group_id': strategy_group_id,
            'group_base_name': base_name,
            'created_ids': created_ids,
            'failed_symbols': failed_symbols,
            'total_created': len(created_ids),
            'total_failed': len(failed_symbols)
        }

    def batch_start_strategies(self, strategy_ids: List[int], user_id: int = None) -> Dict[str, Any]:
        """Batch start strategies. If user_id is provided, verify ownership."""
        success_ids = []
        failed_ids = []
        
        for sid in strategy_ids:
            try:
                self.update_strategy_status(sid, 'running', user_id=user_id)
                success_ids.append(sid)
            except Exception as e:
                logger.error(f"Failed to start strategy {sid}: {e}")
                failed_ids.append({'id': sid, 'error': str(e)})
        
        return {
            'success': len(success_ids) > 0,
            'success_ids': success_ids,
            'failed_ids': failed_ids
        }

    def batch_stop_strategies(self, strategy_ids: List[int], user_id: int = None) -> Dict[str, Any]:
        """Batch stop strategies. If user_id is provided, verify ownership."""
        success_ids = []
        failed_ids = []
        
        for sid in strategy_ids:
            try:
                self.update_strategy_status(sid, 'stopped', user_id=user_id)
                success_ids.append(sid)
            except Exception as e:
                logger.error(f"Failed to stop strategy {sid}: {e}")
                failed_ids.append({'id': sid, 'error': str(e)})
        
        return {
            'success': len(success_ids) > 0,
            'success_ids': success_ids,
            'failed_ids': failed_ids
        }

    def batch_delete_strategies(self, strategy_ids: List[int], user_id: int = None) -> Dict[str, Any]:
        """Batch delete strategies. If user_id is provided, verify ownership."""
        success_ids = []
        failed_ids = []
        
        for sid in strategy_ids:
            try:
                self.delete_strategy(sid, user_id=user_id)
                success_ids.append(sid)
            except Exception as e:
                logger.error(f"Failed to delete strategy {sid}: {e}")
                failed_ids.append({'id': sid, 'error': str(e)})
        
        return {
            'success': len(success_ids) > 0,
            'success_ids': success_ids,
            'failed_ids': failed_ids
        }

    def get_strategies_by_group(self, strategy_group_id: str, user_id: int = None) -> List[Dict[str, Any]]:
        """Get all strategies in a group. If user_id is provided, filter by user."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                if user_id is not None:
                    cur.execute(
                        "SELECT id FROM qd_strategies_trading WHERE strategy_group_id = ? AND user_id = ?",
                        (strategy_group_id, user_id)
                    )
                else:
                    cur.execute(
                        "SELECT id FROM qd_strategies_trading WHERE strategy_group_id = ?",
                        (strategy_group_id,)
                    )
                rows = cur.fetchall() or []
                cur.close()
            return [row['id'] for row in rows]
        except Exception as e:
            logger.error(f"get_strategies_by_group failed: {e}")
            return []

    def update_strategy(self, strategy_id: int, payload: Dict[str, Any], user_id: int = None) -> bool:
        existing = self.get_strategy(strategy_id, user_id=user_id)
        if not existing:
            return False

        # Merge: allow partial updates
        name = (payload.get('strategy_name') or existing.get('strategy_name') or '').strip()
        market_category = payload.get('market_category') or existing.get('market_category') or 'Crypto'
        execution_mode = payload.get('execution_mode') or existing.get('execution_mode') or 'signal'
        notification_config = payload.get('notification_config') if payload.get('notification_config') is not None else (existing.get('notification_config') or {})

        indicator_config = payload.get('indicator_config') if payload.get('indicator_config') is not None else (existing.get('indicator_config') or {})
        trading_config = payload.get('trading_config') if payload.get('trading_config') is not None else (existing.get('trading_config') or {})
        exchange_config = payload.get('exchange_config') if payload.get('exchange_config') is not None else (existing.get('exchange_config') or {})
        ai_model_config = payload.get('ai_model_config') if payload.get('ai_model_config') is not None else (existing.get('ai_model_config') or {})

        # When credential_id is present, strip raw API keys to avoid
        # storing secrets in the strategy record — they live in qd_exchange_credentials.
        if isinstance(exchange_config, dict) and exchange_config.get('credential_id'):
            for _secret_key in ('api_key', 'secret_key', 'passphrase', 'apiKey', 'secret', 'password'):
                exchange_config.pop(_secret_key, None)

        # Handle cross-sectional strategy config updates
        if payload.get('cs_strategy_type') is not None:
            trading_config['cs_strategy_type'] = payload.get('cs_strategy_type')
        if payload.get('symbol_list') is not None:
            trading_config['symbol_list'] = payload.get('symbol_list')
        if payload.get('portfolio_size') is not None:
            trading_config['portfolio_size'] = payload.get('portfolio_size')
        if payload.get('long_ratio') is not None:
            trading_config['long_ratio'] = payload.get('long_ratio')
        if payload.get('rebalance_frequency') is not None:
            trading_config['rebalance_frequency'] = payload.get('rebalance_frequency')

        symbol = (trading_config or {}).get('symbol')
        timeframe = (trading_config or {}).get('timeframe')
        initial_capital = (trading_config or {}).get('initial_capital') or existing.get('initial_capital') or 1000
        leverage = (trading_config or {}).get('leverage') or existing.get('leverage') or 1
        market_type = (trading_config or {}).get('market_type') or existing.get('market_type') or 'swap'

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE qd_strategies_trading
                SET strategy_name = ?,
                    market_category = ?,
                    execution_mode = ?,
                    notification_config = ?,
                    symbol = ?,
                    timeframe = ?,
                    initial_capital = ?,
                    leverage = ?,
                    market_type = ?,
                    exchange_config = ?,
                    indicator_config = ?,
                    trading_config = ?,
                    ai_model_config = ?,
                    updated_at = NOW()
                WHERE id = ?
                """,
                (
                    name,
                    market_category,
                    execution_mode,
                    self._dump_json_or_encrypt(notification_config, encrypt=False),
                    symbol,
                    timeframe,
                    float(initial_capital or 1000),
                    int(leverage or 1),
                    market_type,
                    self._dump_json_or_encrypt(exchange_config, encrypt=False) if exchange_config else '',
                    self._dump_json_or_encrypt(indicator_config, encrypt=False),
                    self._dump_json_or_encrypt(trading_config, encrypt=False),
                    self._dump_json_or_encrypt(ai_model_config, encrypt=False),
                    strategy_id
                )
            )
            db.commit()
            cur.close()
        return True

    def delete_strategy(self, strategy_id: int, user_id: int = None) -> bool:
        """Delete strategy. If user_id is provided, verify ownership."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                if user_id is not None:
                    cur.execute("DELETE FROM qd_strategies_trading WHERE id = ? AND user_id = ?", (strategy_id, user_id))
                else:
                    cur.execute("DELETE FROM qd_strategies_trading WHERE id = ?", (strategy_id,))
                db.commit()
                cur.close()
            return True
        except Exception as e:
            logger.error(f"delete_strategy failed: {e}")
            return False
