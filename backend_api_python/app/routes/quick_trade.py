"""
Quick Trade API - manual / discretionary order placement.

Allows users to place market or limit orders directly from AI analysis
or indicator analysis pages, without creating a strategy first.

Endpoints:
  POST /api/quick-trade/place-order      - Place a quick order
  POST /api/quick-trade/close-position   - Close an existing position
  GET  /api/quick-trade/balance          - Get available balance
  GET  /api/quick-trade/position         - Get current position for symbol
  GET  /api/quick-trade/history          - Get quick trade history
"""

from __future__ import annotations

import json
import time
import traceback
import uuid
from typing import Any, Dict, List

from flask import g, jsonify, request
from app.openapi.blueprint import HumanBlueprint as Blueprint

from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.utils.auth import login_required
from app.services.quick_trade.balances import empty_balance_dict, fetch_balance_raw, parse_balance as _parse_balance
from app.services.quick_trade.credentials import build_exchange_config, create_exchange_client
from app.services.quick_trade.errors import (
    exchange_error_user_message,
    merge_balance_leg_errors,
    parse_trade_error_hint,
)
from app.services.quick_trade.orders import enrich_fill, limit_order_kwargs
from app.services.quick_trade.symbols import (
    is_supported_crypto_exchange,
    symbols_match as quick_trade_symbols_match,
)
from app.utils.request_guard import RequestGuardError, cache_key, guarded_cached

logger = get_logger(__name__)

quick_trade_blp = Blueprint('quick_trade', __name__)


# ---------- helpers ----------


def _convert_usdt_to_base_qty(client, symbol: str, usdt_amount: float, market_type: str, limit_price: float = 0.0) -> float:
    """
    Convert USDT amount to base asset quantity for all exchanges.
    
    This is a unified function that works for all exchanges.
    For spot: converts USDT -> base qty (e.g., 100 USDT -> 0.033 ETH)
    For swap: converts USDT -> base qty (e.g., 100 USDT -> 0.033 ETH), which will then be converted to contracts
    
    Args:
        client: Exchange client instance
        symbol: Trading pair (e.g., "ETH/USDT")
        usdt_amount: USDT amount to convert
        market_type: "spot" or "swap"
        limit_price: For limit orders, use this price if provided (optional)
    
    Returns:
        Base asset quantity
    """
    if usdt_amount <= 0:
        return usdt_amount
    
    try:
        # Try to get current price from exchange
        current_price = 0.0
        
        # For limit orders, use the provided price
        if limit_price > 0:
            current_price = limit_price
            logger.info(f"Using limit price {limit_price} for USDT conversion")
        else:
            # Try to get current market price from exchange
            if hasattr(client, "get_ticker"):
                try:
                    ticker = client.get_ticker(symbol=symbol)
                    if isinstance(ticker, dict):
                        for _pk in ("last", "lastPr", "lastPx", "lastPrice", "close", "price"):
                            try:
                                current_price = float(ticker.get(_pk) or 0)
                            except Exception:
                                current_price = 0.0
                            if current_price > 0:
                                break
                except Exception:
                    current_price = 0.0

            # OKX
            from app.services.live_trading.okx import OkxClient
            if current_price <= 0 and isinstance(client, OkxClient):
                try:
                    from app.services.live_trading.symbols import to_okx_spot_inst_id, to_okx_swap_inst_id
                    inst_id = to_okx_spot_inst_id(symbol) if market_type == "spot" else to_okx_swap_inst_id(symbol)
                    logger.debug(f"OKX: Getting ticker for inst_id={inst_id}, symbol={symbol}, market_type={market_type}")
                    ticker = client.get_ticker(inst_id=inst_id)
                    if ticker:
                        current_price = float(ticker.get("last") or ticker.get("lastPx") or 0)
                        logger.debug(f"OKX: Got price {current_price} from ticker")
                    else:
                        logger.warning(f"OKX: get_ticker returned empty result for inst_id={inst_id}")
                except AttributeError as e:
                    logger.error(f"OKX: get_ticker method not found: {e}")
                    raise
                except Exception as e:
                    logger.error(f"OKX: Failed to get ticker: {e}")
                    raise
            
            # Binance - try to get price from public API
            from app.services.live_trading.binance import BinanceFuturesClient
            from app.services.live_trading.binance_spot import BinanceSpotClient
            if current_price <= 0 and isinstance(client, (BinanceFuturesClient, BinanceSpotClient)):
                try:
                    # Binance public ticker endpoint
                    base_url = getattr(client, "base_url", "")
                    if "binance" in base_url.lower():
                        import requests
                        if isinstance(client, BinanceFuturesClient):
                            ticker_url = f"{base_url}/fapi/v1/ticker/price"
                        else:
                            ticker_url = f"{base_url}/api/v3/ticker/price"
                        from app.services.live_trading.symbols import to_binance_futures_symbol
                        # Binance spot and futures use the same symbol format
                        sym = to_binance_futures_symbol(symbol)
                        resp = requests.get(ticker_url, params={"symbol": sym}, timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            if isinstance(data, dict):
                                current_price = float(data.get("price") or 0)
                except Exception:
                    pass

            # Bybit v5 - same host as trading API; tickers/orderbook are public.
            from app.services.live_trading.bybit import BybitClient
            if current_price <= 0 and isinstance(client, BybitClient):
                try:
                    import requests
                    from app.services.live_trading.symbols import to_bybit_symbol

                    bu = (getattr(client, "base_url", "") or "").rstrip("/")
                    bsym = to_bybit_symbol(symbol).upper()
                    cat = "spot" if (market_type or "").strip().lower() == "spot" else "linear"
                    if bu and bsym:
                        tr = requests.get(
                            f"{bu}/v5/market/tickers",
                            params={"category": cat, "symbol": bsym},
                            timeout=8,
                        )
                        if tr.status_code == 200:
                            jd = tr.json() if tr.text else {}
                            lst = (((jd.get("result") or {}).get("list")) or []) if isinstance(jd, dict) else []
                            if lst and isinstance(lst[0], dict):
                                t0 = lst[0]
                                current_price = float(
                                    str(
                                        t0.get("lastPrice")
                                        or t0.get("markPrice")
                                        or t0.get("indexPrice")
                                        or 0
                                    ).replace(",", "")
                                    or 0
                                )
                        if current_price <= 0:
                            obr = requests.get(
                                f"{bu}/v5/market/orderbook",
                                params={"category": cat, "symbol": bsym, "limit": 25},
                                timeout=8,
                            )
                            if obr.status_code == 200:
                                od = obr.json() if obr.text else {}
                                res = (od.get("result") or {}) if isinstance(od, dict) else {}
                                bids = res.get("b") or []
                                asks = res.get("a") or []
                                bp = float(str(bids[0][0]).replace(",", "")) if bids and bids[0] else 0.0
                                ap = float(str(asks[0][0]).replace(",", "")) if asks and asks[0] else 0.0
                                if bp > 0 and ap > 0:
                                    current_price = (bp + ap) / 2.0
                                else:
                                    current_price = bp or ap
                except Exception:
                    pass
            
            # Other exchanges - can be added as needed
            # For exchanges without price API, we'll use a fallback
        
        if current_price > 0:
            base_qty = usdt_amount / current_price
            logger.info(f"Converted USDT amount {usdt_amount} to base qty {base_qty:.8f} using price {current_price} for {symbol}")
            return base_qty
        else:
            # Can't get price - this is critical for quick trade
            # Quick trade always expects USDT input, so we must convert
            logger.error(f"CRITICAL: Could not get price for {symbol} on {type(client).__name__} to convert USDT amount {usdt_amount}")
            logger.error(f"This will cause order to fail. Please check exchange API connectivity or symbol format.")
            # Still return original amount as fallback, but log error
            return usdt_amount
            
    except Exception as e:
        logger.warning(f"Failed to convert USDT amount to base qty: {e}, using original amount")
        return usdt_amount


def _reject_quick_trade_if_desktop_broker(exchange_id: str):
    """Quick Trade is USDT-centric and only wired to crypto exchange clients."""
    if not is_supported_crypto_exchange(exchange_id):
        return jsonify(
            {
                "code": 0,
                "msg": "Quick Trade currently supports crypto exchange API keys only.",
            }
        ), 400
    return None


def _record_quick_trade(
    user_id: int,
    credential_id: int,
    exchange_id: str,
    symbol: str,
    side: str,
    order_type: str,
    amount: float,
    price: float,
    leverage: int,
    market_type: str,
    tp_price: float,
    sl_price: float,
    status: str,
    exchange_order_id: str,
    filled: float,
    avg_price: float,
    error_msg: str,
    source: str,
    raw_result: Dict[str, Any],
    commission: float = 0.0,
    commission_ccy: str = "",
):
    """Insert a quick trade record into the database."""
    try:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_quick_trades
                    (user_id, credential_id, exchange_id, symbol, side, order_type,
                     amount, price, leverage, market_type, tp_price, sl_price,
                     status, exchange_order_id, filled_amount, avg_fill_price,
                     commission, commission_ccy,
                     error_msg, source, raw_result, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    user_id, credential_id, exchange_id, symbol, side, order_type,
                    amount, price, leverage, market_type, tp_price, sl_price,
                    status, exchange_order_id, filled, avg_price,
                    float(commission or 0.0), str(commission_ccy or "").strip().upper(),
                    error_msg, source, json.dumps(raw_result or {}),
                ),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
            return (row or {}).get("id")
    except Exception as e:
        logger.error(f"Failed to record quick trade: {e}")
        return None


# ---------- endpoints ----------

@quick_trade_blp.route('/place-order', methods=['POST'])
@login_required
def place_order():
    """
    Place a quick market or limit order.

    Body JSON:
      credential_id  (int)    - saved exchange credential ID
      symbol         (str)    - e.g. "BTC/USDT"
      side           (str)    - "buy" or "sell"
      order_type     (str)    - "market" or "limit"  (default: market)
      amount         (float)  - USDT amount (always in USDT, will be converted to base qty)
      price          (float)  - limit price (required for limit orders)
      leverage       (int)    - leverage multiplier (default: 1)
                                - leverage = 1: spot market
                                - leverage > 1: swap (perpetual futures) market
      market_type    (str)    - "swap" / "spot" (optional, auto-determined by leverage if not provided)
      tp_price       (float)  - take-profit price (optional, for record only)
      sl_price       (float)  - stop-loss price (optional, for record only)
      source         (str)    - "ai_radar" / "ai_analysis" / "indicator" / "manual"
    """
    try:
        user_id = g.user_id
        body = request.get_json(force=True, silent=True) or {}

        credential_id = int(body.get("credential_id") or 0)
        symbol = str(body.get("symbol") or "").strip()
        side = str(body.get("side") or "").strip().lower()
        order_type = str(body.get("order_type") or "market").strip().lower()
        usdt_amount = float(body.get("amount") or 0)  # Always USDT amount
        price = float(body.get("price") or 0)
        leverage = int(body.get("leverage") or 1)
        market_type = str(body.get("market_type") or "").strip().lower()
        tp_price = float(body.get("tp_price") or 0)
        sl_price = float(body.get("sl_price") or 0)
        source = str(body.get("source") or "manual").strip()
        margin_mode = str(body.get("margin_mode") or body.get("marginMode") or "").strip().lower()
        if margin_mode in ("cross", "crossed"):
            margin_mode = "cross"
        elif margin_mode in ("iso", "isolated"):
            margin_mode = "isolated"
        else:
            margin_mode = ""

        # ---- validation ----
        if not credential_id:
            return jsonify({"code": 0, "msg": "Missing credential_id"}), 400
        if not symbol:
            return jsonify({"code": 0, "msg": "Missing symbol"}), 400
        if side not in ("buy", "sell"):
            return jsonify({"code": 0, "msg": "side must be 'buy' or 'sell'"}), 400
        if usdt_amount <= 0:
            return jsonify({"code": 0, "msg": "amount must be > 0"}), 400
        if order_type == "limit" and price <= 0:
            return jsonify({"code": 0, "msg": "price required for limit orders"}), 400

        # ---- market_type: leverage 1 => spot API, else perpetual (swap) ----
        if market_type in ("futures", "future", "perp", "perpetual"):
            market_type = "swap"
        if leverage > 1:
            market_type = "swap"
        else:
            market_type = "spot"

        # ---- build exchange client ----
        cfg_overrides: Dict[str, Any] = {"market_type": market_type}
        if margin_mode in ("cross", "isolated"):
            cfg_overrides["margin_mode"] = margin_mode
            cfg_overrides["td_mode"] = margin_mode
        exchange_config = build_exchange_config(credential_id, user_id, cfg_overrides)
        exchange_id = (exchange_config.get("exchange_id") or "").strip().lower()
        if not exchange_id:
            return jsonify({"code": 0, "msg": "Invalid credential: missing exchange_id"}), 400

        qt_rej = _reject_quick_trade_if_desktop_broker(exchange_id)
        if qt_rej is not None:
            return qt_rej

        client = create_exchange_client(exchange_config, market_type=market_type)

        # Binance USDT-M: sync isolated/cross margin mode (best-effort; may fail if open orders exist)
        if market_type != "spot" and margin_mode in ("cross", "isolated"):
            try:
                from app.services.live_trading.binance import BinanceFuturesClient
                if isinstance(client, BinanceFuturesClient):
                    client.set_margin_type(symbol=symbol, margin_mode=margin_mode)
            except Exception as me:
                logger.warning(f"Binance set_margin_type failed (non-fatal): {me}")

        # ---- Convert USDT amount to base asset quantity ----
        # Quick trade always accepts USDT amount, convert to base qty for all exchanges
        # For limit orders, use the provided price; for market orders, fetch current price
        limit_price_for_conversion = price if order_type == "limit" and price > 0 else 0.0
        base_qty = _convert_usdt_to_base_qty(client, symbol, usdt_amount, market_type, limit_price_for_conversion)

        quote_for_buy = 0.0
        if market_type == "spot":
            from app.services.live_trading.spot_sizing import (
                fetch_spot_last_price,
                normalize_spot_base_quantity,
                normalize_spot_quote_amount,
                scale_spot_open_notional,
            )
            from app.services.live_trading.bitget_spot import BitgetSpotClient

            if order_type == "market" and side == "buy":
                quote_for_buy = normalize_spot_quote_amount(
                    client,
                    symbol=symbol,
                    quote_amount=scale_spot_open_notional(usdt_amount),
                )
                if quote_for_buy <= 0:
                    return jsonify(
                        {
                            "code": 0,
                            "msg": "Order notional is below the exchange minimum. Increase the USDT amount.",
                        }
                    ), 400
                if not isinstance(client, BitgetSpotClient):
                    base_qty = normalize_spot_base_quantity(
                        client, symbol=symbol, quantity=base_qty, for_market=True
                    )
            else:
                base_qty = normalize_spot_base_quantity(
                    client, symbol=symbol, quantity=base_qty, for_market=(order_type == "market")
                )
            if base_qty <= 0 and quote_for_buy <= 0:
                px = fetch_spot_last_price(client, symbol=symbol)
                hint = f" Unable to fetch a valid {symbol} price; check the API key or symbol." if px <= 0 else ""
                return jsonify(
                    {
                        "code": 0,
                        "msg": f"Order quantity is below the exchange minimum. Increase the amount or check symbol rules.{hint}",
                    }
                ), 400

            if side == "buy":
                need_quote = float(quote_for_buy or 0) if quote_for_buy > 0 else float(usdt_amount or 0)
                if need_quote > 0:
                    try:
                        bal = fetch_balance_raw(
                            client,
                            exchange_id=exchange_id,
                            market_type="spot",
                            exchange_config=exchange_config,
                        )
                        avail = float(bal.get("available") or 0)
                        if need_quote > avail + 1e-6:
                            return jsonify(
                                {
                                    "code": 0,
                                    "msg": (
                                        f"Insufficient spot USDT balance: need about {need_quote:.4f} USDT, "
                                        f"available {avail:.4f} USDT."
                                    ),
                                    "error_hint": "quickTrade.errorHints.insufficientBalance",
                                }
                            ), 400
                    except Exception as be:
                        logger.warning("spot buy balance pre-check skipped: %s", be)
        
        # Validate conversion: if base_qty equals usdt_amount, conversion likely failed
        # For swap markets, base_qty should be much smaller than usdt_amount (e.g., 100 USDT -> 0.033 ETH)
        if market_type != "spot" and base_qty == usdt_amount and usdt_amount >= 1:
            logger.error(f"USDT conversion may have failed: base_qty ({base_qty}) equals usdt_amount ({usdt_amount})")
            logger.error(f"This suggests the price fetch failed. Order may fail due to insufficient margin.")

        # ---- set leverage (futures only) ----
        if market_type != "spot" and leverage > 1:
            try:
                if hasattr(client, "set_leverage"):
                    from app.services.live_trading.okx import OkxClient
                    from app.services.live_trading.gate import GateUsdtFuturesClient
                    
                    # OKX requires inst_id instead of symbol
                    if isinstance(client, OkxClient):
                        from app.services.live_trading.symbols import to_okx_swap_inst_id
                        inst_id = to_okx_swap_inst_id(symbol)
                        client.set_leverage(inst_id=inst_id, lever=leverage)
                    # Gate requires contract (currency_pair) instead of symbol
                    elif isinstance(client, GateUsdtFuturesClient):
                        from app.services.live_trading.symbols import to_gate_currency_pair
                        contract = to_gate_currency_pair(symbol)
                        if not client.set_leverage(contract=contract, leverage=leverage):
                            logger.warning(
                                "Gate set_leverage failed (contract=%s lev=%s); order may use exchange default leverage",
                                contract,
                                leverage,
                            )
                    # Most other exchanges use symbol
                    else:
                        # Try common parameter names
                        try:
                            client.set_leverage(symbol=symbol, leverage=leverage)
                        except TypeError:
                            try:
                                client.set_leverage(symbol=symbol, lever=leverage)
                            except TypeError:
                                pass
            except Exception as le:
                logger.warning(f"set_leverage failed (non-fatal): {le}")

        # ---- swap margin pre-check ----
        # 50 USDT notional at leverage=1 needs ~50 USDT collateral. Many users
        # only see the i18n hint after the exchange rejects the order. Compute
        # the rough margin requirement up-front so we can short-circuit with
        # an actionable message that includes account/balance numbers.
        if market_type != "spot" and order_type == "market":
            try:
                ref_price = price if price > 0 else 0.0
                if ref_price <= 0 and usdt_amount > 0 and base_qty > 0:
                    ref_price = float(usdt_amount) / float(base_qty)
                notional_usdt = float(base_qty or 0) * float(ref_price or 0)
                if notional_usdt <= 0:
                    notional_usdt = float(usdt_amount or 0)
                lev = max(int(leverage or 1), 1)
                # Add a small safety buffer (taker fee + funding accrual + slippage)
                est_margin = (notional_usdt / lev) * 1.05
                bal = fetch_balance_raw(
                    client,
                    exchange_id=exchange_id,
                    market_type="swap",
                    exchange_config=exchange_config,
                )
                avail = float(bal.get("available") or 0)
                if avail > 0 and est_margin > avail:
                    return jsonify({
                        "code": 0,
                        "msg": (
                            f"Insufficient derivatives margin: {notional_usdt:.2f} USDT notional "
                            f"at {lev}x needs about {est_margin:.2f} USDT margin, "
                            f"but only {avail:.2f} USDT is available. "
                            "Reduce order size, adjust leverage, or transfer funds."
                        ),
                        "error_hint": "quickTrade.errorHints.insufficientBalance",
                    }), 400
            except Exception as pe:
                logger.warning("swap margin pre-check skipped: %s", pe)

        # ---- place order ----
        # Generate client_order_id: OKX clOrdId requirements: 1-32 chars, alphanumeric, underscore, hyphen only
        timestamp_suffix = str(int(time.time()))[-6:]  # Last 6 digits of timestamp
        uuid_suffix = uuid.uuid4().hex[:8]  # 8 hex chars
        client_order_id = f"qt{timestamp_suffix}{uuid_suffix}"  # Total: 2 + 6 + 8 = 16 chars

        result = None
        if order_type == "market":
            # Use execution.py's place_order_from_signal for market orders to ensure consistency
            # Convert side to signal_type: buy -> open_long, sell -> open_short (for swap) or close_long (for spot)
            from app.services.live_trading.execution import place_order_from_signal
            
            if market_type == "spot":
                # Spot: buy = open_long, sell = close_long (assuming we're closing a position)
                signal_type = "open_long" if side == "buy" else "close_long"
            else:
                # Swap: buy = open_long, sell = open_short
                signal_type = "open_long" if side == "buy" else "open_short"
            
            result = place_order_from_signal(
                client=client,
                signal_type=signal_type,
                symbol=symbol,
                amount=base_qty,  # Use converted base qty
                market_type=market_type,
                exchange_config=exchange_config,
                client_order_id=client_order_id,
                quote_amount=quote_for_buy,
            )
        else:
            # Limit orders: use direct client call (execution.py doesn't handle limit orders)
            result = client.place_limit_order(
                symbol=symbol,
                side=side.upper() if "binance" in exchange_id else side,
                **limit_order_kwargs(client, symbol, base_qty, price, side, market_type, client_order_id),
            )

        # ---- extract result ----
        exchange_order_id = str(getattr(result, "exchange_order_id", "") or "")
        filled = float(getattr(result, "filled", 0) or 0)
        avg_fill = float(getattr(result, "avg_price", 0) or 0)
        raw = getattr(result, "raw", {}) or {}

        # ---- best-effort post-place enrichment (fee + accurate filled/avg) ----
        # ``place_market_order`` typically only returns the ACK, so the filled
        # qty / avg price / commission have to be polled separately. Without
        # this Quick Trade rows landed with ``commission=0`` and our P&L
        # surfaces were optimistic. Mirrors the strategy worker's behaviour.
        commission = 0.0
        commission_ccy = ""
        if exchange_order_id:
            enrich = enrich_fill(
                client,
                order_id=exchange_order_id,
                symbol=symbol,
                market_type=market_type,
            )
            if enrich.get("filled", 0.0) > 0:
                filled = float(enrich["filled"])
            if enrich.get("avg_price", 0.0) > 0:
                avg_fill = float(enrich["avg_price"])
            commission = float(enrich.get("fee") or 0.0)
            commission_ccy = str(enrich.get("fee_ccy") or "")

        # ---- record trade ----
        # Record original USDT amount, not converted base qty
        trade_id = _record_quick_trade(
            user_id=user_id,
            credential_id=credential_id,
            exchange_id=exchange_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=usdt_amount,  # Record original USDT amount
            price=price if order_type == "limit" else avg_fill,
            leverage=leverage,
            market_type=market_type,
            tp_price=tp_price,
            sl_price=sl_price,
            status="filled" if filled > 0 else "submitted",
            exchange_order_id=exchange_order_id,
            filled=filled,
            avg_price=avg_fill,
            error_msg="",
            source=source,
            raw_result=raw,
            commission=commission,
            commission_ccy=commission_ccy,
        )

        return jsonify({
            "code": 1,
            "msg": "Order placed successfully",
            "data": {
                "trade_id": trade_id,
                "exchange_order_id": exchange_order_id,
                "filled": filled,
                "avg_price": avg_fill,
                "status": "filled" if filled > 0 else "submitted",
            },
        })

    except Exception as e:
        logger.error(f"quick trade failed: {e}")
        logger.error(traceback.format_exc())

        # Try to record the failure
        try:
            _record_quick_trade(
                user_id=g.user_id,
                credential_id=int(body.get("credential_id") or 0),
                exchange_id="",
                symbol=str(body.get("symbol") or ""),
                side=str(body.get("side") or ""),
                order_type=str(body.get("order_type") or "market"),
                amount=float(body.get("amount") or 0),  # Original USDT amount
                price=0,
                leverage=int(body.get("leverage") or 1),
                market_type=str(body.get("market_type") or "swap"),
                tp_price=0,
                sl_price=0,
                status="failed",
                exchange_order_id="",
                filled=0,
                avg_price=0,
                error_msg=str(e)[:500],
                source=str(body.get("source") or "manual"),
                raw_result={},
            )
        except Exception:
            pass

        err_str = str(e)
        err_meta = exchange_error_user_message(exchange_id=exchange_id, err=err_str)
        resp: Dict[str, Any] = {"code": 0, "msg": err_meta.get("message") or err_str}
        if err_meta.get("hint_key"):
            resp["error_hint"] = err_meta["hint_key"]
        return jsonify(resp), 500


@quick_trade_blp.route('/balance', methods=['GET'])
@login_required
def get_balance():
    """
    Get available balance from exchange.

    Query: credential_id (int), market_type (str, default "swap") - active leg for ``available``/``total``.

    Response also includes ``swap`` and ``spot`` so the UI can show both account types.
    """
    try:
        user_id = g.user_id
        credential_id = request.args.get("credential_id", type=int)
        market_type = request.args.get("market_type", "swap").strip().lower()
        if market_type in ("futures", "future", "perp", "perpetual"):
            market_type = "swap"

        if not credential_id:
            return jsonify({"code": 0, "msg": "Missing credential_id"}), 400

        base_cfg = build_exchange_config(credential_id, user_id, {})
        exchange_id = (base_cfg.get("exchange_id") or "").strip().lower()
        qt_rej = _reject_quick_trade_if_desktop_broker(exchange_id)
        if qt_rej is not None:
            return qt_rej

        def _compute_balance() -> Dict[str, Any]:
            swap_bal = empty_balance_dict()
            spot_bal = empty_balance_dict()

            for mt in ("swap", "spot"):
                try:
                    cfg = build_exchange_config(credential_id, user_id, {"market_type": mt})
                    client = create_exchange_client(cfg, market_type=mt)
                    parsed = fetch_balance_raw(
                        client,
                        exchange_id=exchange_id,
                        market_type=mt,
                        exchange_config=cfg,
                    )
                    if mt == "spot":
                        spot_bal = parsed
                    else:
                        swap_bal = parsed
                    logger.info(
                        "Balance for %s/%s: available=%.4f total=%.4f",
                        exchange_id,
                        mt,
                        float(parsed.get("available") or 0),
                        float(parsed.get("total") or 0),
                    )
                except Exception as be:
                    logger.warning("Balance leg failed (%s/%s): %s", exchange_id, mt, be)
                    leg = empty_balance_dict()
                    leg["error"] = str(be)
                    if mt == "spot":
                        spot_bal = leg
                    else:
                        swap_bal = leg

            active = spot_bal if market_type == "spot" else swap_bal
            balance_data = {
                "available": float(active.get("available") or 0),
                "total": float(active.get("total") or 0),
                "currency": str(active.get("currency") or "USDT"),
                "market_type": market_type,
                "swap": swap_bal,
                "spot": spot_bal,
            }
            err_meta = merge_balance_leg_errors(swap_bal, spot_bal, exchange_id=exchange_id)
            if not err_meta and active.get("error"):
                err_meta = exchange_error_user_message(exchange_id=exchange_id, err=str(active.get("error")))
                if err_meta.get("message"):
                    balance_data["error"] = err_meta["message"]
                if err_meta.get("hint_key"):
                    balance_data["error_hint_key"] = err_meta["hint_key"]
                if err_meta.get("request_ip"):
                    balance_data["request_ip"] = err_meta["request_ip"]
            elif err_meta:
                balance_data.update(err_meta)
            return balance_data

        balance_data = guarded_cached(
            cache_key("quick_trade_balance", user_id, credential_id, market_type),
            _compute_balance,
            ttl_sec=8,
            stale_ttl_sec=90,
            timeout_sec=10,
            namespace="quick_trade_balance",
            max_concurrent=4,
        )
        return jsonify({"code": 1, "msg": "success", "data": balance_data})
    except RequestGuardError as e:
        return jsonify({"code": 0, "msg": str(e)}), e.status_code
    except Exception as e:
        logger.error(f"get_balance failed: {e}")
        return jsonify({"code": 0, "msg": str(e)}), 500


def _quick_trade_spot_avg_entry_price(
    user_id: int,
    credential_id: int,
    symbol: str,
    market_type: str,
) -> float:
    """
    Average cost basis from filled Quick Trade rows (chronological avg-cost).
    """
    sym = str(symbol or "").strip()
    mt = (market_type or "spot").strip().lower()
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT side, filled_amount, avg_fill_price, price
            FROM qd_quick_trades
            WHERE user_id = %s AND credential_id = %s AND symbol = %s AND market_type = %s
              AND status = 'filled' AND COALESCE(filled_amount, 0) > 0
            ORDER BY created_at ASC, id ASC
            """,
            (int(user_id), int(credential_id), sym, mt),
        )
        rows = cur.fetchall() or []
        cur.close()

    qty = 0.0
    cost = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        side = str(row.get("side") or "").strip().lower()
        try:
            filled = float(row.get("filled_amount") or 0.0)
        except (TypeError, ValueError):
            filled = 0.0
        try:
            px = float(row.get("avg_fill_price") or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            try:
                px = float(row.get("price") or 0.0)
            except (TypeError, ValueError):
                px = 0.0
        if filled <= 0 or px <= 0:
            continue
        if side == "buy":
            cost += filled * px
            qty += filled
        elif side == "sell" and qty > 0:
            sell_qty = min(filled, qty)
            avg = cost / qty
            cost -= sell_qty * avg
            qty -= sell_qty
    if qty > 1e-12 and cost > 0:
        return cost / qty
    return 0.0


def _enrich_spot_positions(
    positions: list,
    *,
    client: Any,
    symbol: str,
    user_id: int,
    credential_id: int,
    market_type: str,
) -> list:
    """Fill missing spot entry / mark / unrealized PnL for Quick Trade display."""
    from app.services.live_trading.spot_sizing import fetch_spot_last_price

    if not positions:
        return positions

    db_avg = _quick_trade_spot_avg_entry_price(
        user_id, credential_id, symbol, market_type
    )
    last_px = fetch_spot_last_price(client, symbol=symbol)

    enriched: list = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        row = dict(pos)
        entry = float(row.get("entry_price") or 0.0)
        if entry <= 0 and db_avg > 0:
            entry = db_avg
        mark = float(row.get("mark_price") or 0.0)
        if mark <= 0 and last_px > 0:
            mark = last_px
        size = float(row.get("size") or 0.0)
        side = str(row.get("side") or "long").strip().lower()

        row["entry_price"] = entry
        if mark > 0:
            row["mark_price"] = mark

        upl = float(row.get("unrealized_pnl") or 0.0)
        if abs(upl) < 1e-12 and entry > 0 and mark > 0 and size > 0:
            if side == "short":
                upl = (entry - mark) * size
            else:
                upl = (mark - entry) * size
            row["unrealized_pnl"] = upl

        enriched.append(row)
    return enriched


def _fetch_spot_holdings_raw(client: Any, *, symbol: str) -> Dict[str, Any]:
    """
    Spot "position" = base-asset wallet balance for the trading pair.

    Returns the same ``{"data": [row, ...]}`` envelope as derivative position APIs.
    """
    from app.services.live_trading.spot_sizing import get_spot_base_holding
    from app.services.live_trading.symbols import _split_base_quote

    sym = str(symbol or "").strip()
    base, quote = _split_base_quote(sym)
    if not base:
        return {"data": []}
    display = sym if sym else f"{base}/{quote or 'USDT'}"
    holding = get_spot_base_holding(client, symbol=display)
    total = float(holding.get("total") or 0.0)
    avail = float(holding.get("available") or 0.0)
    if total <= 0 and avail <= 0:
        return {"data": []}
    qty = total if total > 0 else avail
    if avail <= 0:
        avail = qty
    row: Dict[str, Any] = {
        "symbol": display,
        "bal": qty,
        "availBal": avail,
        "side": "long",
    }
    avg_cost = float(holding.get("avg_cost") or 0.0)
    if avg_cost > 0:
        row["avgCost"] = avg_cost
        row["openAvgPx"] = avg_cost
    return {"data": [row]}


def _fetch_exchange_positions_raw(
    client: Any,
    exchange_config: Dict[str, Any],
    *,
    symbol: str,
    market_type: str,
) -> Any:
    """
    Fetch raw position payload for quick-trade / close-position.

    Many clients do not accept ``symbol=`` on ``get_positions()`` (Gate),
    or need extra args (Bitget ``product_type``, OKX ``inst_type``). Centralize here.
    """
    from app.services.live_trading.binance import BinanceFuturesClient
    from app.services.live_trading.binance_spot import BinanceSpotClient
    from app.services.live_trading.bitget import BitgetMixClient
    from app.services.live_trading.bitget_spot import BitgetSpotClient
    from app.services.live_trading.bybit import BybitClient
    from app.services.live_trading.gate import GateSpotClient, GateUsdtFuturesClient
    from app.services.live_trading.htx import HtxClient
    from app.services.live_trading.okx import OkxClient
    from app.services.live_trading.symbols import (
        to_bybit_symbol,
        to_gate_currency_pair,
        to_okx_spot_inst_id,
        to_okx_swap_inst_id,
    )

    mt = (market_type or "swap").strip().lower()

    if mt == "spot" and isinstance(
        client, (BinanceSpotClient, BitgetSpotClient, OkxClient)
    ):
        return _fetch_spot_holdings_raw(client, symbol=symbol)

    if isinstance(client, OkxClient):
        inst_id = to_okx_swap_inst_id(symbol)
        raw = client.get_positions(inst_id=inst_id, inst_type="SWAP")
        return _normalize_okx_positions_raw(raw)

    if isinstance(client, BinanceFuturesClient):
        return client.get_positions(symbol=symbol)

    if isinstance(client, BitgetMixClient):
        pt = str(exchange_config.get("product_type") or exchange_config.get("productType") or "USDT-FUTURES")
        return client.get_positions(product_type=pt, symbol=symbol)

    if isinstance(client, GateSpotClient) and mt == "spot":
        raw_accounts = client.get_accounts()
        items = raw_accounts if isinstance(raw_accounts, list) else []
        base_asset = ""
        if symbol:
            base_asset = str(symbol).split("/", 1)[0].split(":", 1)[0].strip().upper()
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ccy = str(item.get("currency") or "").upper()
            if base_asset and ccy != base_asset:
                continue
            try:
                av = float(item.get("available") or item.get("available_balance") or 0)
            except Exception:
                av = 0.0
            try:
                lk = float(item.get("locked") or item.get("freeze") or 0)
            except Exception:
                lk = 0.0
            total = av + lk
            if total <= 0:
                continue
            rows.append(
                {
                    "symbol": f"{ccy}/USDT",
                    "bal": total,
                    "availBal": av,
                }
            )
        return {"data": rows}

    if isinstance(client, BybitClient):
        if mt == "spot" or getattr(client, "category", "") == "spot":
            return client.get_spot_holdings(symbol=symbol)
        # Bybit v5 requires symbol or settleCoin; query the contract directly.
        raw = client.get_positions(symbol=symbol)
        lst = (((raw or {}).get("result") or {}).get("list")) if isinstance(raw, dict) else None
        if not isinstance(lst, list):
            return raw
        sym_norm = to_bybit_symbol(symbol)
        filtered = [p for p in lst if isinstance(p, dict) and str(p.get("symbol") or "").strip() == sym_norm]
        if isinstance(raw, dict):
            out = dict(raw)
            res = dict((raw.get("result") or {}) if isinstance(raw.get("result"), dict) else {})
            res["list"] = filtered
            out["result"] = res
            return out
        return {"result": {"list": filtered}}

    if isinstance(client, GateUsdtFuturesClient):
        raw = client.get_positions()
        items = raw if isinstance(raw, list) else []
        c = to_gate_currency_pair(symbol)
        logger.info("Gate positions: total=%d, target=%s, contracts=%s",
                     len(items), c,
                     [(str(p.get("contract")), p.get("size")) for p in items if isinstance(p, dict) and p.get("size")][:10])
        filtered = [p for p in items if isinstance(p, dict) and str(p.get("contract") or "").strip() == c]
        out = []
        for p in filtered:
            q = dict(p)
            try:
                ct_sz = float(q.get("size") or 0)
            except Exception:
                ct_sz = 0.0
            if abs(ct_sz) > 1e-12:
                base_amt = client.contracts_signed_to_base_qty(contract=c, contracts_signed=ct_sz)
                if base_amt > 0:
                    q["positionAmt"] = base_amt
                    # Preserve direction for _parse_positions. Gate encodes short as
                    # negative contract size but positionAmt is always positive.
                    q["positionSide"] = "LONG" if ct_sz > 0 else "SHORT"
            out.append(q)
        logger.info("Gate filtered positions for %s: %d items, sizes=%s", c, len(out),
                     [(p.get("size"), p.get("positionAmt")) for p in out])
        return out

    if isinstance(client, HtxClient):
        if mt == "spot":
            return client.get_positions(symbol=symbol)
        raw = client.get_positions(symbol=symbol)
        data = (raw.get("data") if isinstance(raw, dict) else None) or []
        if not isinstance(data, list):
            data = []
        out_items = []
        for p in data:
            if not isinstance(p, dict):
                continue
            q = dict(p)
            cc = str(q.get("contract_code") or "").strip()
            if cc:
                parts = cc.split("-", 1)
                if len(parts) == 2:
                    q["symbol"] = f"{parts[0]}/{parts[1]}"
            try:
                vol = float(q.get("volume") or q.get("available") or 0)
            except Exception:
                vol = 0.0
            if abs(vol) > 1e-12 and cc:
                try:
                    info = client.get_contract_info(symbol=symbol or cc) or {}
                    cs = float(info.get("contract_size") or 1)
                    if cs <= 0:
                        cs = 1.0
                    q["positionAmt"] = abs(vol) * cs
                except Exception:
                    pass
            out_items.append(q)
        logger.info("HTX positions for %s: %d items, sizes=%s", symbol, len(out_items),
                     [(p.get("contract_code"), p.get("volume"), p.get("positionAmt")) for p in out_items])
        return {"data": out_items}

    if hasattr(client, "get_positions"):
        try:
            return client.get_positions(symbol=symbol)
        except TypeError:
            return client.get_positions()

    if hasattr(client, "get_position"):
        return client.get_position(symbol=symbol)

    if mt == "spot":
        return _fetch_spot_holdings_raw(client, symbol=symbol)

    return None


@quick_trade_blp.route('/position', methods=['GET'])
@login_required
def get_position():
    """
    Get current position for a symbol from exchange.

    Query: credential_id (int), symbol (str), market_type (str)
    """
    try:
        user_id = g.user_id
        credential_id = request.args.get("credential_id", type=int)
        symbol = request.args.get("symbol", "").strip()
        market_type = request.args.get("market_type", "swap").strip().lower()

        if not credential_id or not symbol:
            return jsonify({"code": 0, "msg": "Missing credential_id or symbol"}), 400

        exchange_config = build_exchange_config(credential_id, user_id, {"market_type": market_type})
        exchange_id_pos = (exchange_config.get("exchange_id") or "").strip().lower()
        qt_rej = _reject_quick_trade_if_desktop_broker(exchange_id_pos)
        if qt_rej is not None:
            return qt_rej

        client = create_exchange_client(exchange_config, market_type=market_type)

        def _compute_position() -> List[Dict[str, Any]]:
            positions: List[Dict[str, Any]] = []
            try:
                raw = _fetch_exchange_positions_raw(
                    client, exchange_config, symbol=symbol, market_type=market_type
                )
                positions = _parse_positions(raw)
                if market_type == "spot" and positions:
                    positions = _enrich_spot_positions(
                        positions,
                        client=client,
                        symbol=symbol,
                        user_id=user_id,
                        credential_id=credential_id,
                        market_type=market_type,
                    )
            except Exception as pe:
                logger.warning(f"Position fetch failed: {pe}")
                logger.warning(traceback.format_exc())
            return positions

        positions = guarded_cached(
            cache_key("quick_trade_position", user_id, credential_id, market_type, symbol),
            _compute_position,
            ttl_sec=8,
            stale_ttl_sec=90,
            timeout_sec=10,
            namespace="quick_trade_position",
            max_concurrent=6,
        )

        logger.info(f"Returning {len(positions)} positions for symbol={symbol}, market_type={market_type}")
        return jsonify({"code": 1, "msg": "success", "data": {"positions": positions}})
    except RequestGuardError as e:
        return jsonify({"code": 0, "msg": str(e), "data": {"positions": []}}), e.status_code
    except Exception as e:
        logger.error(f"get_position failed: {e}")
        return jsonify({"code": 0, "msg": str(e)}), 500


def _normalize_okx_positions_raw(raw: Any) -> Any:
    """
    OKX net-mode rows use ``posSide=net`` with a *signed* ``pos`` (negative = short).
    Attach ``positionSide`` so downstream parsers never default to long when posSide
    is present but not literally ``long``/``short``.
    """
    if not isinstance(raw, dict):
        return raw
    data = raw.get("data")
    if not isinstance(data, list):
        return raw
    out_rows = []
    for item in data:
        if not isinstance(item, dict):
            out_rows.append(item)
            continue
        row = dict(item)
        ps = str(row.get("posSide") or "").strip().lower()
        if ps in ("long", "short"):
            row.setdefault("positionSide", ps.upper())
        elif ps == "net":
            signed = None
            for key in ("pos", "availPos", "posAmt"):
                try:
                    v = float(row.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if abs(v) > 1e-10:
                    signed = v
                    break
            if signed is not None:
                row["positionSide"] = "SHORT" if signed < 0 else "LONG"
        out_rows.append(row)
    out = dict(raw)
    out["data"] = out_rows
    return out


def _extract_signed_position_qty(item: dict) -> float:
    from app.services.live_trading.position_row_parse import extract_signed_position_qty

    return extract_signed_position_qty(item)


def _infer_position_side_from_row(item: dict) -> str:
    from app.services.live_trading.position_row_parse import infer_position_side_from_row

    return infer_position_side_from_row(item)


def _parse_positions(raw: Any) -> list:
    """Best-effort parse positions from exchange response."""
    result = []
    if not raw:
        return result
    try:
        items = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            if isinstance(raw.get("raw"), list):
                items = raw["raw"]
            else:
                data = raw.get("data") or raw.get("result") or raw.get("positions") or []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = data.get("list", []) if "list" in data else [data]
                else:
                    items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            sym_raw = str(
                item.get("symbol")
                or item.get("instId")
                or item.get("contract")
                or item.get("contract_code")
                or ""
            ).strip()
            display_symbol = sym_raw
            if sym_raw and "/" not in sym_raw:
                for sep in ("_", "-"):
                    if sep in sym_raw:
                        parts = sym_raw.split(sep, 1)
                        if len(parts) == 2 and parts[0] and parts[1]:
                            display_symbol = f"{parts[0]}/{parts[1]}"
                        break
            # For OKX, pos is signed in net_mode. Read before abs-only aliases.
            size = _extract_signed_position_qty(item)
            psu = str(item.get("positionSide") or item.get("position_side") or "").strip().upper()
            if psu in ("LONG", "SHORT"):
                try:
                    amt = abs(float(item.get("positionAmt") or item.get("position_amt") or 0.0))
                except (TypeError, ValueError):
                    amt = 0.0
                if amt > 0:
                    size = amt if psu == "LONG" else -amt
            if abs(size) < 1e-10:
                continue

            side = _infer_position_side_from_row(item)

            result.append({
                "symbol": display_symbol,
                "side": side,
                "size": abs(size),
                "entry_price": float(
                    item.get("entryPrice")
                    or item.get("entry_price")
                    or item.get("openPriceAvg")
                    or item.get("avgEntryPrice")
                    or item.get("avgPrice")
                    or item.get("avgCost")
                    or item.get("avgPx")
                    or item.get("openAvgPx")
                    or item.get("accAvgPx")
                    or item.get("cost_open")
                    or item.get("trade_avg_price")
                    or 0
                ),
                "unrealized_pnl": float(
                    item.get("unRealizedProfit")
                    or item.get("unrealizedProfit")
                    or item.get("unrealizedPnl")
                    or item.get("unrealised_pnl")
                    or item.get("upl")
                    or item.get("unrealisedPnl")
                    or item.get("profit_unreal")
                    or item.get("pnl")
                    or 0
                ),
                "leverage": float(item.get("leverage") or item.get("lever") or item.get("lever_rate") or item.get("cross_leverage_limit") or 1),
                "mark_price": float(
                    item.get("markPrice")
                    or item.get("mark_price")
                    or item.get("markPx")
                    or item.get("last_price")
                    or item.get("last")
                    or item.get("indexPrice")
                    or 0
                ),
            })
    except Exception as e:
        logger.warning(f"_parse_positions error: {e}")
    return result


def _quick_trade_net_base_qty(
    user_id: int,
    credential_id: int,
    symbol: str,
    market_type: str,
    position_side: str,
) -> float:
    """
    Best-effort net base-asset qty from qd_quick_trades.

    Long positions use filled buy minus sell; short positions use sell minus buy.

    Used when user chooses to close only the portion accumulated via Quick Trade, not manual exchange orders.
    Imperfect if the user also traded the same symbol elsewhere or records are incomplete.
    """
    mt = (market_type or "swap").strip().lower()
    ps = (position_side or "").strip().lower()
    sym = str(symbol or "").strip()
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN side = 'buy' THEN filled_amount ELSE 0 END), 0) AS b,
              COALESCE(SUM(CASE WHEN side = 'sell' THEN filled_amount ELSE 0 END), 0) AS s
            FROM qd_quick_trades
            WHERE user_id = %s AND credential_id = %s AND symbol = %s AND market_type = %s
              AND status = 'filled' AND COALESCE(filled_amount, 0) > 0
            """,
            (int(user_id), int(credential_id), sym, mt),
        )
        row = cur.fetchone() or {}
        cur.close()
    buy_sum = float(row.get("b") or 0)
    sell_sum = float(row.get("s") or 0)
    if ps == "long":
        net = buy_sum - sell_sum
    elif ps == "short":
        net = sell_sum - buy_sum
    else:
        net = 0.0
    return max(0.0, float(net))


@quick_trade_blp.route('/close-position', methods=['POST'])
@login_required
def close_position():
    """
    Close an existing position.
    
    Body JSON:
      credential_id  (int)    - saved exchange credential ID
      symbol         (str)    - e.g. "BTC/USDT"
      market_type    (str)    - "swap" / "spot" (default: swap)
      size           (float)  - position size to close (optional, defaults to full position)
      close_scope    (str)    - "full" (default) or "system_tracked" (swap only: min(position, net from qd_quick_trades))
      position_side  (str)    - optional "long" / "short"; required when both directions exist for the same symbol
      source         (str)    - "ai_radar" / "ai_analysis" / "indicator" / "manual"
    """
    try:
        user_id = g.user_id
        body = request.get_json(force=True, silent=True) or {}
        
        credential_id = int(body.get("credential_id") or 0)
        symbol = str(body.get("symbol") or "").strip()
        market_type = str(body.get("market_type") or "swap").strip().lower()
        close_size = float(body.get("size") or 0)  # 0 means close full position
        source = str(body.get("source") or "manual").strip()
        close_scope_raw = str(body.get("close_scope") or body.get("closeScope") or "full").strip().lower()
        if close_scope_raw in ("system", "system_tracked", "quick_trade", "app"):
            close_scope = "system_tracked"
        else:
            close_scope = "full"
        
        # ---- validation ----
        if not credential_id:
            return jsonify({"code": 0, "msg": "Missing credential_id"}), 400
        if not symbol:
            return jsonify({"code": 0, "msg": "Missing symbol"}), 400
        
        if market_type in ("futures", "future", "perp", "perpetual"):
            market_type = "swap"
        
        # ---- build exchange client ----
        exchange_config = build_exchange_config(credential_id, user_id, {
            "market_type": market_type,
        })
        exchange_id = (exchange_config.get("exchange_id") or "").strip().lower()
        if not exchange_id:
            return jsonify({"code": 0, "msg": "Invalid credential: missing exchange_id"}), 400

        qt_rej = _reject_quick_trade_if_desktop_broker(exchange_id)
        if qt_rej is not None:
            return qt_rej

        client = create_exchange_client(exchange_config, market_type=market_type)
        
        # ---- get current position ----
        positions = []
        try:
            raw = _fetch_exchange_positions_raw(
                client, exchange_config, symbol=symbol, market_type=market_type
            )
            positions = _parse_positions(raw)
        except Exception as pe:
            logger.warning(f"Position fetch failed: {pe}")
        
        if not positions:
            return jsonify({"code": 0, "msg": f"No position found for {symbol}"}), 404

        want_side = str(body.get("position_side") or body.get("close_side") or "").strip().lower()
        if want_side not in ("", "long", "short"):
            want_side = ""

        matches: list = []
        for pos in positions:
            pos_symbol = pos.get("symbol", "").strip()
            if not quick_trade_symbols_match(symbol, pos_symbol):
                continue
            ps = str(pos.get("side") or "").strip().lower()
            if want_side in ("long", "short"):
                if ps == want_side:
                    matches.append(pos)
            else:
                matches.append(pos)

        position = None
        if len(matches) == 1:
            position = matches[0]
        elif len(matches) > 1:
            if want_side in ("long", "short"):
                position = matches[0]
            else:
                return jsonify(
                    {
                        "code": 0,
                        "msg": "Both long and short positions exist for this symbol. Set position_side to long or short.",
                    }
                ), 400
        if not position:
            return jsonify({"code": 0, "msg": f"No position found for {symbol}"}), 404

        position_side = str(position.get("side") or "").strip().lower()
        position_size = float(position.get("size") or 0)
        
        if position_size <= 0:
            return jsonify({"code": 0, "msg": "Position size is zero or invalid"}), 400
        
        if close_scope == "system_tracked" and market_type != "swap":
            return jsonify({"code": 0, "msg": "system_tracked close_scope is only supported for swap/perp"}), 400

        tracked_net = 0.0
        if close_scope == "system_tracked":
            tracked_net = _quick_trade_net_base_qty(
                user_id, credential_id, symbol, market_type, position_side=position_side
            )
            if tracked_net <= 0:
                return jsonify(
                    {
                        "code": 0,
                        "msg": "No filled Quick Trade volume found for this symbol; use full close or check history.",
                    }
                ), 400

        # Determine close size
        if close_size > 0:
            actual_close_size = min(close_size, position_size)
        elif close_scope == "system_tracked":
            actual_close_size = min(tracked_net, position_size)
            logger.info(
                "close_position system_tracked: symbol=%s side=%s position=%s tracked_net=%s close=%s",
                symbol,
                position.get("side"),
                position_size,
                tracked_net,
                actual_close_size,
            )
        else:
            actual_close_size = position_size
        if actual_close_size > position_size:
            actual_close_size = position_size
        if actual_close_size <= 0:
            return jsonify({"code": 0, "msg": "Close size is zero"}), 400

        if market_type == "spot":
            from app.services.live_trading.spot_sizing import clamp_spot_close_quantity

            adjusted, spot_meta = clamp_spot_close_quantity(
                client, symbol=symbol, requested_qty=actual_close_size
            )
            if adjusted <= 0:
                return jsonify(
                    {
                        "code": 0,
                        "msg": "Available spot balance is too low to close this position. Fees may have reduced the sellable amount.",
                    }
                ), 400
            if spot_meta.get("adjusted"):
                logger.info(
                    "quick_trade spot close adjusted: symbol=%s requested=%s final=%s meta=%s",
                    symbol,
                    actual_close_size,
                    adjusted,
                    spot_meta,
                )
            actual_close_size = adjusted
        
        # ---- determine signal type based on position side ----
        if market_type == "spot":
            # Spot only supports long positions
            if position_side != "long":
                return jsonify({"code": 0, "msg": "Spot market only supports closing long positions"}), 400
            signal_type = "close_long"
        else:
            # Swap: close_long or close_short
            if position_side == "long":
                signal_type = "close_long"
            elif position_side == "short":
                signal_type = "close_short"
            else:
                return jsonify({"code": 0, "msg": f"Unknown position side: {position_side}"}), 400
        
        # ---- place close order ----
        from app.services.live_trading.execution import place_order_from_signal
        
        # Generate client_order_id
        timestamp_suffix = str(int(time.time()))[-6:]
        uuid_suffix = uuid.uuid4().hex[:8]
        client_order_id = f"qtc{timestamp_suffix}{uuid_suffix}"  # 'c' for close
        
        result = place_order_from_signal(
            client=client,
            signal_type=signal_type,
            symbol=symbol,
            amount=actual_close_size,  # Use position size directly (already in base qty)
            market_type=market_type,
            exchange_config=exchange_config,
            client_order_id=client_order_id,
            quote_amount=0,
        )
        
        # ---- extract result ----
        exchange_order_id = str(getattr(result, "exchange_order_id", "") or "")
        filled = float(getattr(result, "filled", 0) or 0)
        avg_fill = float(getattr(result, "avg_price", 0) or 0)
        raw = getattr(result, "raw", {}) or {}

        # ---- best-effort post-place enrichment (fee + accurate filled/avg) ----
        # See the matching block in /place-order; close-position orders need
        # the same wait_for_fill pass so the resulting Quick Trade row carries
        # the realised commission.
        commission = 0.0
        commission_ccy = ""
        if exchange_order_id:
            enrich = enrich_fill(
                client,
                order_id=exchange_order_id,
                symbol=symbol,
                market_type=market_type,
            )
            if enrich.get("filled", 0.0) > 0:
                filled = float(enrich["filled"])
            if enrich.get("avg_price", 0.0) > 0:
                avg_fill = float(enrich["avg_price"])
            commission = float(enrich.get("fee") or 0.0)
            commission_ccy = str(enrich.get("fee_ccy") or "")

        # ---- calculate USDT amount for recording ----
        # Convert base asset quantity to USDT amount for consistent recording
        # amount (USDT) = base_qty * price
        usdt_amount = actual_close_size * avg_fill if avg_fill > 0 else 0
        # If price is not available, try to use entry price or mark price as fallback
        if usdt_amount <= 0:
            entry_price = float(position.get("entry_price") or 0)
            mark_price = float(position.get("mark_price") or 0)
            fallback_price = mark_price if mark_price > 0 else entry_price
            if fallback_price > 0:
                usdt_amount = actual_close_size * fallback_price
        
        # ---- record trade ----
        trade_id = _record_quick_trade(
            user_id=user_id,
            credential_id=credential_id,
            exchange_id=exchange_id,
            symbol=symbol,
            side="sell" if position_side == "long" else "buy",  # Opposite of position side
            order_type="market",
            amount=usdt_amount,  # Record USDT amount, not base asset quantity
            price=avg_fill,
            leverage=float(position.get("leverage") or 1),
            market_type=market_type,
            tp_price=0,
            sl_price=0,
            status="filled" if filled > 0 else "submitted",
            exchange_order_id=exchange_order_id,
            filled=filled,
            avg_price=avg_fill,
            error_msg="",
            source=source,
            raw_result=raw,
            commission=commission,
            commission_ccy=commission_ccy,
        )
        
        return jsonify({
            "code": 1,
            "msg": "Position closed successfully",
            "data": {
                "trade_id": trade_id,
                "exchange_order_id": exchange_order_id,
                "filled": filled,
                "avg_price": avg_fill,
                "closed_size": actual_close_size,
                "position_side": position_side,
                "close_scope": close_scope,
                "tracked_net_base": tracked_net if close_scope == "system_tracked" else None,
                "status": "filled" if filled > 0 else "submitted",
            },
        })
        
    except Exception as e:
        logger.error(f"close_position failed: {e}")
        logger.error(traceback.format_exc())
        err_str = str(e)
        hint = parse_trade_error_hint(err_str)
        resp: Dict[str, Any] = {"code": 0, "msg": err_str}
        if hint:
            resp["error_hint"] = hint
        return jsonify(resp), 500


@quick_trade_blp.route('/history', methods=['GET'])
@login_required
def get_history():
    """
    Get quick trade history for the current user.

    Query: limit (int, default 50), offset (int, default 0)
    """
    try:
        user_id = g.user_id
        limit = min(int(request.args.get("limit") or 50), 200)
        offset = int(request.args.get("offset") or 0)

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT id, exchange_id, symbol, side, order_type, amount, price,
                       leverage, market_type, tp_price, sl_price, status,
                       exchange_order_id, filled_amount, avg_fill_price,
                       commission, commission_ccy,
                       error_msg, source, created_at
                FROM qd_quick_trades
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (user_id, limit, offset),
            )
            rows = cur.fetchall() or []
            cur.close()

        trades = []
        for r in rows:
            trades.append({
                "id": r.get("id"),
                "exchange_id": r.get("exchange_id") or "",
                "symbol": r.get("symbol") or "",
                "side": r.get("side") or "",
                "order_type": r.get("order_type") or "market",
                "amount": float(r.get("amount") or 0),
                "price": float(r.get("price") or 0),
                "leverage": int(r.get("leverage") or 1),
                "market_type": r.get("market_type") or "swap",
                "tp_price": float(r.get("tp_price") or 0),
                "sl_price": float(r.get("sl_price") or 0),
                "status": r.get("status") or "",
                "exchange_order_id": r.get("exchange_order_id") or "",
                "filled_amount": float(r.get("filled_amount") or 0),
                "avg_fill_price": float(r.get("avg_fill_price") or 0),
                "commission": float(r.get("commission") or 0),
                "commission_ccy": r.get("commission_ccy") or "",
                "error_msg": r.get("error_msg") or "",
                "source": r.get("source") or "",
                "created_at": str(r.get("created_at") or ""),
            })

        return jsonify({"code": 1, "msg": "success", "data": {"trades": trades}})
    except Exception as e:
        logger.error(f"get_history failed: {e}")
        return jsonify({"code": 0, "msg": str(e)}), 500

# openapi-compat: legacy import name
quick_trade_bp = quick_trade_blp

