"""
Market API routes (local-only).
Provides watchlist, market metadata, symbol search, and pricing helpers for the frontend.
"""
from flask import Blueprint, request, jsonify, g
import os
import traceback
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.kline import KlineService
from app.utils.logger import get_logger
from app.utils.cache import CacheManager
from app.utils.db import get_db_connection
from app.utils.config_loader import load_addon_config
from app.utils.auth import login_required
from app.data.market_symbols_seed import (
    get_hot_symbols as seed_get_hot_symbols,
    search_symbols as seed_search_symbols,
    get_symbol_name as seed_get_symbol_name
)
from app.services.symbol_name import resolve_symbol_name

logger = get_logger(__name__)

market_bp = Blueprint('market', __name__)
kline_service = KlineService()
cache = CacheManager()

# Thread pool for parallel price fetching.
# Each task may grab a DB connection, so keep this well below DB_POOL_MAX.
# Tunable via MARKET_EXECUTOR_WORKERS env.
def _market_executor_workers() -> int:
    try:
        v = int(os.getenv("MARKET_EXECUTOR_WORKERS", "6"))
        return v if v > 0 else 6
    except Exception:
        return 6

executor = ThreadPoolExecutor(max_workers=_market_executor_workers())

def _now_ts() -> int:
    return int(time.time())

def _normalize_symbol(symbol: str) -> str:
    return (symbol or '').strip().upper()

def _ensure_watchlist_table():
    # Table is created by db schema init; this is only a sanity hook.
    return True

@market_bp.route('/config', methods=['GET'])
def get_public_config():
    """
    Public config for frontend (local mode).
    Mirrors the old PHP `/addons/quantdinger/index/getConfig` shape.
    """
    try:
        cfg = load_addon_config()
        models = (cfg.get('ai', {}) or {}).get('models')
        if not isinstance(models, dict) or not models:
            # Fallback defaults (offline friendly)
            models = {
                # Keep some legacy defaults
                'openai/gpt-4o': 'GPT-4o',

                # Unified frontend model list (OpenRouter-style ids)
                'x-ai/grok-code-fast-1': 'xAI: Grok Code Fast 1',
                'x-ai/grok-4-fast': 'xAI: Grok 4 Fast',
                'x-ai/grok-4.1-fast': 'xAI: Grok 4.1 Fast',
                'google/gemini-2.5-flash': 'Google: Gemini 2.5 Flash',
                'google/gemini-2.0-flash-001': 'Google: Gemini 2.0 Flash',
                'google/gemini-3-pro-preview': 'Google: Gemini 3 Pro Preview',
                'google/gemini-2.5-flash-lite': 'Google: Gemini 2.5 Flash Lite',
                'google/gemini-2.5-pro': 'Google: Gemini 2.5 Pro',
                'openai/gpt-4o-mini': 'OpenAI: GPT-4o-mini',
                'openai/gpt-5-mini': 'OpenAI: GPT-5 Mini',
                'openai/gpt-4.1-mini': 'OpenAI: GPT-4.1 Mini',
                'deepseek/deepseek-v3.2': 'DeepSeek: DeepSeek V3.2',
                'minimax/minimax-m2': 'MiniMax: MiniMax M2',
                'anthropic/claude-sonnet-4': 'Anthropic: Claude Sonnet 4',
                'anthropic/claude-sonnet-4.5': 'Anthropic: Claude Sonnet 4.5',
                'anthropic/claude-opus-4.5': 'Anthropic: Claude Opus 4.5',
                'anthropic/claude-haiku-4.5': 'Anthropic: Claude Haiku 4.5',
                'z-ai/glm-4.6': 'Z.AI: GLM 4.6',
            }
        return jsonify({'code': 1, 'msg': 'success', 'data': {'models': models, 'qdt_cost': {}}})
    except Exception as e:
        logger.error(f"get_public_config failed: {str(e)}")
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500

@market_bp.route('/types', methods=['GET'])
def get_market_types():
    """Return supported market types for the add-watchlist modal."""
    # Keep a stable UX order; add CN/HK stocks near US stocks.
    desired_order = ['USStock', 'CNStock', 'HKStock', 'MOEX', 'Crypto', 'Forex', 'Futures']
    order_rank = {v: i for i, v in enumerate(desired_order)}

    def _normalize_item(x):
        # Expected: {value: 'USStock', i18nKey: '...'}
        if isinstance(x, dict):
            v = (x.get('value') or '').strip()
            if not v:
                return None
            return {
                'value': v,
                'i18nKey': x.get('i18nKey') or f'dashboard.analysis.market.{v}'
            }
        if isinstance(x, str):
            v = x.strip()
            if not v:
                return None
            return {'value': v, 'i18nKey': f'dashboard.analysis.market.{v}'}
        return None

    def _sort_items(items):
        # Keep unknown market types after known ones, stable by original order.
        out = []
        for it in items or []:
            norm = _normalize_item(it)
            if norm:
                out.append(norm)
        out.sort(key=lambda it: (order_rank.get(it['value'], 10_000)))
        return out

    cfg = load_addon_config()
    data = (cfg.get('market', {}) or {}).get('types')

    # Normalize & force desired order (even if config overrides the list order).
    if isinstance(data, list) and data:
        data = _sort_items(data)
    else:
        data = _sort_items(desired_order)
    return jsonify({'code': 1, 'msg': 'success', 'data': data})


@market_bp.route('/menuFooterConfig', methods=['GET'])
def get_menu_footer_config():
    """
    Compatibility stub for old PHP `getMenuFooterConfig`.
    Frontend can also hardcode this locally; this endpoint remains for completeness.
    """
    data = {
        'contact': {
            'support_url': 'https://github.com/',
            'feature_request_url': 'https://github.com/',
            'email': 'support@example.com',
            'live_chat_url': 'https://github.com/'
        },
        'social_accounts': [
            {'name': 'GitHub', 'icon': 'github', 'url': 'https://github.com/'},
            {'name': 'X', 'icon': 'x', 'url': 'https://x.com/'}
        ],
        'legal': {
            'user_agreement': '',
            'privacy_policy': ''
        },
        'copyright': '© 2025-2026 QuantDinger'
    }
    return jsonify({'code': 1, 'msg': 'success', 'data': data})

@market_bp.route('/symbols/search', methods=['GET'])
def search_symbols():
    """
    Lightweight symbol search.
    DB seed first; for Crypto, falls back to exchange market list when DB yields few results.
    """
    try:
        market = (request.args.get('market') or '').strip()
        keyword = (request.args.get('keyword') or '').strip().upper()
        limit = int(request.args.get('limit') or 20)

        if not market or not keyword:
            return jsonify({'code': 1, 'msg': 'success', 'data': []})

        out = seed_search_symbols(market=market, keyword=keyword, limit=limit)

        if market == 'Crypto' and len(out) < 3:
            extra = _search_crypto_exchange(keyword, limit - len(out), {r['symbol'] for r in out})
            out.extend(extra)

        return jsonify({'code': 1, 'msg': 'success', 'data': out})
    except Exception as e:
        logger.error(f"search_symbols failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': []}), 500


_crypto_markets_cache: dict = {"data": None, "ts": 0}


def _search_crypto_exchange(keyword: str, limit: int, existing: set) -> list:
    """
    Dynamically search exchange (via CCXT) for crypto pairs matching keyword.
    Caches the full market list for 4 hours to avoid repeated API calls.
    """
    if limit <= 0:
        return []
    try:
        import ccxt  # type: ignore
        from app.config.data_sources import CCXTConfig

        now = time.time()
        if _crypto_markets_cache["data"] and now - _crypto_markets_cache["ts"] < 14400:
            markets = _crypto_markets_cache["data"]
        else:
            exchange_cls = getattr(ccxt, CCXTConfig.DEFAULT_EXCHANGE, None) or ccxt.gate
            ex = exchange_cls()
            ex.load_markets()
            markets = []
            for sym, info in ex.markets.items():
                if not info.get("active"):
                    continue
                quote = info.get("quote", "")
                if quote != "USDT":
                    continue
                markets.append({
                    "symbol": sym,
                    "base": info.get("base", ""),
                    "name": info.get("base", sym),
                })
            _crypto_markets_cache["data"] = markets
            _crypto_markets_cache["ts"] = now
            logger.info("Cached %d USDT crypto pairs from %s", len(markets), CCXTConfig.DEFAULT_EXCHANGE)

        kw = keyword.upper().replace("/USDT", "").replace("/", "")
        results = []
        for m in markets:
            sym = m["symbol"]
            if sym in existing:
                continue
            base_up = m["base"].upper()
            if kw in base_up or kw in sym.upper():
                results.append({"market": "Crypto", "symbol": sym, "name": m["name"]})
                if len(results) >= limit:
                    break
        return results
    except Exception as e:
        logger.debug("_search_crypto_exchange failed: %s", e)
        return []

@market_bp.route('/symbols/hot', methods=['GET'])
def get_hot_symbols():
    """Return a small curated hot list per market (local-only)."""
    try:
        market = (request.args.get('market') or '').strip()
        limit = int(request.args.get('limit') or 10)
        hot = seed_get_hot_symbols(market=market, limit=limit)
        return jsonify({'code': 1, 'msg': 'success', 'data': hot})
    except Exception as e:
        logger.error(f"get_hot_symbols failed: {str(e)}")
        return jsonify({'code': 0, 'msg': str(e), 'data': []}), 500

@market_bp.route('/watchlist/get', methods=['GET'])
@login_required
def get_watchlist():
    """Get watchlist for the current user."""
    try:
        user_id = g.user_id
        _ensure_watchlist_table()
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT id, market, symbol, name FROM qd_watchlist WHERE user_id = ? ORDER BY id DESC",
                (user_id,)
            )
            rows = cur.fetchall() or []

            # Backfill display names for legacy rows (name empty or equals symbol).
            # This keeps UI consistent without requiring users to re-add items.
            for row in rows:
                try:
                    market = row.get('market')
                    symbol = row.get('symbol')
                    current_name = (row.get('name') or '').strip()
                    if not market or not symbol:
                        continue
                    if current_name and current_name != symbol:
                        continue
                    resolved = resolve_symbol_name(market, symbol) or seed_get_symbol_name(market, symbol)
                    if resolved and resolved != current_name:
                        row['name'] = resolved
                        cur.execute(
                            "UPDATE qd_watchlist SET name = ?, updated_at = NOW() WHERE user_id = ? AND market = ? AND symbol = ?",
                            (resolved, user_id, market, symbol)
                        )
                except Exception:
                    continue
            db.commit()
            cur.close()
        return jsonify({'code': 1, 'msg': 'success', 'data': rows})
    except Exception as e:
        logger.error(f"get_watchlist failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': []}), 500

@market_bp.route('/watchlist/add', methods=['POST'])
@login_required
def add_watchlist():
    """Add a symbol to watchlist for the current user."""
    try:
        user_id = g.user_id
        data = request.get_json() or {}
        market = (data.get('market') or '').strip()
        symbol = _normalize_symbol(data.get('symbol'))
        name_in = (data.get('name') or '').strip()
        if not market or not symbol:
            return jsonify({'code': 0, 'msg': 'Missing market or symbol', 'data': None}), 400

        # Prefer frontend-provided name (search results), otherwise resolve via seed/public sources.
        resolved = resolve_symbol_name(market, symbol) or seed_get_symbol_name(market, symbol)
        name = name_in or resolved or symbol

        with get_db_connection() as db:
            cur = db.cursor()
            # Insert or update (PostgreSQL UPSERT)
            cur.execute(
                """
                INSERT INTO qd_watchlist (user_id, market, symbol, name, created_at, updated_at) 
                VALUES (?, ?, ?, ?, NOW(), NOW())
                ON CONFLICT(user_id, market, symbol) DO UPDATE SET
                    name = excluded.name,
                    updated_at = NOW()
                """,
                (user_id, market, symbol, name)
            )
            db.commit()
            cur.close()

        return jsonify({'code': 1, 'msg': 'success', 'data': None})
    except Exception as e:
        logger.error(f"add_watchlist failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500

@market_bp.route('/watchlist/remove', methods=['POST'])
@login_required
def remove_watchlist():
    """Remove a symbol from watchlist for the current user."""
    try:
        user_id = g.user_id
        data = request.get_json() or {}
        symbol = _normalize_symbol(data.get('symbol'))
        if not symbol:
            return jsonify({'code': 0, 'msg': 'Missing symbol', 'data': None}), 400

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "DELETE FROM qd_watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, symbol)
            )
            db.commit()
            cur.close()
        return jsonify({'code': 1, 'msg': 'success', 'data': None})
    except Exception as e:
        logger.error(f"remove_watchlist failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


def get_single_price(market: str, symbol: str) -> dict:
    """获取单个标的的价格数据"""
    try:
        # 使用 get_realtime_price 获取实时价格（内部已有30秒缓存）
        # 相比原先的 '1D' K线逻辑，这能更及时地反映 Crypto 等 24h 市场的变化
        price_data = kline_service.get_realtime_price(market, symbol)
        
        return {
            'market': market,
            'symbol': symbol,
            'price': price_data.get('price', 0),
            'change': price_data.get('change', 0),
            'changePercent': price_data.get('changePercent', 0)
        }
    except Exception as e:
        logger.error(f"Failed to fetch price {market}:{symbol} - {str(e)}")
        return {
            'market': market,
            'symbol': symbol,
            'price': 0,
            'change': 0,
            'changePercent': 0
        }


@market_bp.route('/watchlist/prices', methods=['GET'])
def get_watchlist_prices():
    """
    批量获取自选股价格
    
    Params (Query String):
        watchlist: JSON string of list of {market, symbol} objects
        e.g. ?watchlist=[{"market":"USStock","symbol":"AAPL"}]
    """
    try:
        watchlist_str = request.args.get('watchlist', '[]')
        try:
            watchlist = json.loads(watchlist_str)
        except Exception:
            watchlist = []
        
        if not watchlist or not isinstance(watchlist, list):
            return jsonify({
                'code': 0,
                'msg': 'Invalid watchlist format (expected JSON list in query param)',
                'data': []
            }), 400
        
        # logger.info(f"开始获取 {len(watchlist)} 个自选股价格数据")
        
        results = []
        
        # 使用线程池并行获取价格
        futures = {}
        for item in watchlist:
            market = item.get('market', '')
            symbol = item.get('symbol', '')
            
            if market and symbol:
                future = executor.submit(get_single_price, market, symbol)
                futures[future] = (market, symbol)
        
        # 收集结果（带超时保护）
        completed_futures = set()
        try:
            for future in as_completed(futures, timeout=30):
                completed_futures.add(future)
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    market, symbol = futures[future]
                    logger.warning(f"Price fetch failed: {market}:{symbol} - {str(e)}")
                    results.append({
                        'market': market,
                        'symbol': symbol,
                        'price': 0,
                        'change': 0,
                        'changePercent': 0
                    })
        except TimeoutError:
            # 超时时，为未完成的任务添加默认结果
            for future, (market, symbol) in futures.items():
                if future not in completed_futures:
                    logger.warning(f"Price fetch timed out: {market}:{symbol}")
                    results.append({
                        'market': market,
                        'symbol': symbol,
                        'price': 0,
                        'change': 0,
                        'changePercent': 0,
                        'error': 'timeout'
                    })
        
        success_count = sum(1 for r in results if r.get('price', 0) > 0)
        logger.info(f"Watchlist prices: {success_count}/{len(results)} successful")
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': results
        })
        
    except Exception as e:
        logger.error(f"Batch watchlist price fetch failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Failed: {str(e)}',
            'data': []
        }), 500


@market_bp.route('/price', methods=['GET'])
def get_price():
    """
    获取单个标的价格
    
    参数:
        market: 市场类型
        symbol: 交易标的
    """
    try:
        market = request.args.get('market', '')
        symbol = request.args.get('symbol', '')
        
        if not market or not symbol:
            return jsonify({
                'code': 0,
                'msg': 'Missing market or symbol parameter(s)',
                'data': None
            }), 400
        
        result = get_single_price(market, symbol)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': result
        })
        
    except Exception as e:
        logger.error(f"Failed to fetch price: {str(e)}")
        return jsonify({
            'code': 0,
            'msg': f'Failed: {str(e)}',
            'data': None
        }), 500


@market_bp.route('/stock/name', methods=['POST'])
def get_stock_name():
    """
    获取股票名称
    
    请求体:
    {
        "market": "USStock",
        "symbol": "AAPL"
    }
    
    响应:
    {
        "code": 1,
        "msg": "success",
        "data": {
            "name": "Apple Inc."
        }
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'code': 0,
                'msg': 'Request body is required',
                'data': None
            }), 400
        
        market = data.get('market', '')
        symbol = data.get('symbol', '')
        
        if not market or not symbol:
            return jsonify({
                'code': 0,
                'msg': 'Missing market or symbol parameter(s)',
                'data': None
            }), 400
        
        # 尝试从缓存获取（1天缓存）
        cache_key = f"stock_name:{market}:{symbol}"
        cached_name = cache.get(cache_key)
        
        if cached_name:
            logger.debug(f"Stock name cache hit: {market}:{symbol}")
            return jsonify({
                'code': 1,
                'msg': 'success',
                'data': {'name': cached_name}
            })
        
        # 根据不同市场获取股票名称
        stock_name = symbol  # 默认使用代码
        
        try:
            if market == 'USStock':
                # 对于股票，尝试获取基本信息
                import yfinance as yf
                
                yf_symbol = symbol
                ticker = yf.Ticker(yf_symbol)
                info = ticker.info
                
                # 尝试获取名称
                stock_name = info.get('longName') or info.get('shortName') or symbol
                
            elif market == 'Crypto':
                # 加密货币，使用交易对格式
                if '/' in symbol:
                    stock_name = symbol
                else:
                    stock_name = f"{symbol}/USDT"
            
            elif market == 'Forex':
                # 外汇
                forex_names = {
                    'XAUUSD': '黄金',
                    'XAGUSD': '白银',
                    'EURUSD': '欧元/美元',
                    'GBPUSD': '英镑/美元',
                    'USDJPY': '美元/日元',
                    'AUDUSD': '澳元/美元',
                    'USDCAD': '美元/加元',
                    'USDCHF': '美元/瑞郎',
                }
                stock_name = forex_names.get(symbol, symbol)
            
            elif market == 'Futures':
                # 期货
                futures_names = {
                    'GC': '黄金期货',
                    'SI': '白银期货',
                    'CL': '原油期货',
                    'NG': '天然气期货',
                    'ZC': '玉米期货',
                    'ZW': '小麦期货',
                    'BTCUSDT': 'BTC永续合约',
                    'ETHUSDT': 'ETH永续合约',
                }
                stock_name = futures_names.get(symbol, symbol)
            
        except Exception as e:
            logger.warning(f"Failed to fetch stock name; falling back to symbol: {market}:{symbol} - {str(e)}")
            stock_name = symbol
        
        # 缓存1天
        cache.set(cache_key, stock_name, 86400)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': {'name': stock_name}
        })
        
    except Exception as e:
        logger.error(f"Failed to fetch stock name: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Failed: {str(e)}',
            'data': None
        }), 500
