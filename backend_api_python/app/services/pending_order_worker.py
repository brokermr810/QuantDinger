"""
Pending order worker.

This worker polls `pending_orders` periodically and dispatches orders based on `execution_mode`:
- signal: send notifications (no real trading).
- live: dispatch normalized live orders through exchange and broker clients.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.services.signal_notifier import SignalNotifier
from app.services.exchange_execution import load_strategy_configs, resolve_exchange_config, safe_exchange_config_for_log
from app.services.live_trading.execution import place_order_from_signal
from app.services.live_trading.factory import create_client
from app.services.live_trading.records import (
    ensure_position_ledger_schema,
    normalize_strategy_symbol,
    strategy_allowed_symbols,
)
from app.services.live_trading.strategy_position_sync import (
    strategy_uses_fill_ledger,
)
from app.services.live_trading.account_positions import (
    account_legs_from_exchange_maps,
    sync_account_positions,
)
from app.services.live_trading.adapters import LiveOrderPhaseAdapter
from app.services.live_trading.contracts import OrderIntent
from app.services.live_trading.executors import (
    LimitThenMarketExecutor,
    MarketOrderExecutor,
    RestingLimitExecutor,
)
from app.services.live_trading.leg_context import (
    credential_id_from_exchange_config,
)
from app.services.live_trading.position_query import resolve_reduce_only_quantity
from app.utils.pnl import calc_notional_value
from app.services.live_trading.base import LiveTradingError, is_file_descriptor_exhausted
from app.services.pending_orders.fill_records import (
    persist_strategy_fill,
    trade_close_reason_from_payload,
)
from app.services.pending_orders.live_order_support import (
    FillAccumulator,
    LiveOrderNotifier,
    LiveOrderRejected,
    build_live_order_context,
    console_print,
    make_client_order_id,
    signal_to_side_pos_reduce,
)
from app.services.pending_orders.live_order_phases import (
    maker_limit_price,
)
from app.services.grid.exchange_orders import query_grid_order_fill
from app.services.pending_orders.position_sync_cache import (
    exchange_sync_backoff_sec,
    get_position_sync_snapshot,
    invalidate_position_sync_snapshot_for_exchange,
    is_exchange_rate_limit_error,
    is_exchange_sync_backoff,
    position_sync_cache_key,
    set_exchange_sync_backoff,
    set_position_sync_snapshot,
)
from app.services.pending_orders.sent_order_recovery import (
    normalize_live_order_status,
    tracked_fill_baseline,
)
from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.okx import OkxClient
from app.services.live_trading.bitget import BitgetMixClient
from app.services.live_trading.bitget_spot import BitgetSpotClient
from app.services.live_trading.bybit import BybitClient
from app.services.live_trading.coinbase_exchange import CoinbaseExchangeClient
from app.services.live_trading.kraken import KrakenClient
from app.services.live_trading.kraken_futures import KrakenFuturesClient
from app.services.live_trading.gate import GateSpotClient, GateUsdtFuturesClient
from app.services.live_trading.htx import HtxClient
from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.utils.strategy_runtime_logs import append_strategy_log
from app.services.strategy_lifecycle import (
    auto_stop_live_strategy,
    is_fatal_exchange_error,
    should_skip_position_sync,
)

# Lazy import IBKR to avoid ImportError if ib_insync not installed
IBKRClient = None


# Lazy import Alpaca to avoid ImportError if alpaca-py not installed
AlpacaClient = None

logger = get_logger(__name__)

ALPACA_FILL_DELTA_EPSILON = 1e-8
_POSITION_SYNC_FD_BACKOFF_UNTIL = 0.0


def _position_sync_fd_backoff_sec() -> float:
    try:
        return max(30.0, float(os.getenv("POSITION_SYNC_FD_BACKOFF_SEC", "90")))
    except Exception:
        return 90.0


def _is_position_sync_fd_backoff_active() -> bool:
    return time.time() < float(_POSITION_SYNC_FD_BACKOFF_UNTIL or 0.0)


def _activate_position_sync_fd_backoff(reason: str) -> None:
    global _POSITION_SYNC_FD_BACKOFF_UNTIL
    seconds = _position_sync_fd_backoff_sec()
    _POSITION_SYNC_FD_BACKOFF_UNTIL = time.time() + seconds
    logger.error(
        "[PositionSync] process file descriptors exhausted; pausing exchange position sync for %ss. error=%s",
        int(seconds),
        reason,
    )

class PendingOrderWorker:
    def __init__(self, poll_interval_sec: float = 1.0, batch_size: int = 50):
        self.poll_interval_sec = float(poll_interval_sec)
        self.batch_size = int(batch_size)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._notifier = SignalNotifier()

        # Reclaim stuck orders (e.g. if the worker crashed after claiming an order).
        try:
            self._stale_processing_sec = int(os.getenv("PENDING_ORDER_STALE_SEC", "90"))
        except Exception:
            self._stale_processing_sec = 90

        # Position sync self-check (best-effort): keep local positions aligned with exchange.
        self._position_sync_enabled = os.getenv("POSITION_SYNC_ENABLED", "true").lower() == "true"
        self._position_sync_interval_sec = float(os.getenv("POSITION_SYNC_INTERVAL_SEC", "30"))
        self._last_position_sync_ts = 0.0
        logger.info(f"PendingOrderWorker: sync_enabled={self._position_sync_enabled}, interval={self._position_sync_interval_sec}s")

    def start(self) -> bool:
        with self._lock:
            try:
                ensure_position_ledger_schema()
            except Exception as e:
                logger.warning("ensure_position_ledger_schema failed: %s", e)
            try:
                from app.services.strategy_runtime.schema import ensure_strategy_runtime_schema

                ensure_strategy_runtime_schema()
            except Exception as e:
                logger.warning("ensure_strategy_runtime_schema failed: %s", e)
            if self._thread and self._thread.is_alive():
                return True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="PendingOrderWorker", daemon=True)
            self._thread.start()
            logger.info("PendingOrderWorker started")
            return True

    def stop(self, timeout_sec: float = 5.0) -> None:
        with self._lock:
            self._stop_event.set()
            th = self._thread
        if th and th.is_alive():
            th.join(timeout=timeout_sec)
        logger.info("PendingOrderWorker stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.warning(f"PendingOrderWorker tick error: {e}")
            time.sleep(self.poll_interval_sec)

    def _tick(self) -> None:
        # logger.info(f"[PendingOrderWorker] _tick start. last_sync={self._last_position_sync_ts}")
        self._sync_alpaca_sent_orders()
        self._sync_live_sent_orders()
        orders = self._fetch_pending_orders(limit=self.batch_size)
        # logger.info(f"[PendingOrderWorker] orders fetched: {len(orders)}")
        if not orders:
            self._maybe_sync_positions()
            return

        for o in orders:
            oid = o.get("id")
            if not oid:
                continue

            # Mark processing (best-effort)
            if not self._mark_processing(order_id=int(oid)):
                continue

            try:
                self._dispatch_one(o)
            except Exception as e:
                self._mark_failed(order_id=int(oid), error=str(e))

        self._maybe_sync_positions()

    def _maybe_sync_positions(self) -> None:
        if not self._position_sync_enabled:
            return
        now = time.time()
        if self._position_sync_interval_sec <= 0:
            return
        if now - float(self._last_position_sync_ts or 0.0) < float(self._position_sync_interval_sec):
            return
        logger.debug(f"[PendingOrderWorker] Triggering sync... (now={now}, last={self._last_position_sync_ts})")
        self._last_position_sync_ts = now
        try:
            self._sync_positions_best_effort()
        except Exception as e:
            logger.debug(f"position sync skipped/failed: {e}")

    def _sync_positions_best_effort(self, target_strategy_id: Optional[int] = None) -> None:
        """
        Best-effort reconciliation:
        - If exchange position is flat, delete local row from qd_strategy_positions.
        - If exchange position size differs, update local size (optional best-effort).

        This prevents "ghost positions" when positions are closed externally on the exchange.
        """
        if _is_position_sync_fd_backoff_active():
            logger.debug("[PositionSync] skipped: file-descriptor backoff active")
            return

        # 1) Load local positions (filtered if target_strategy_id is provided).
        logger.debug(f"[PositionSync] Entering _sync_positions_best_effort for target={target_strategy_id}")
        with get_db_connection() as db:
            cur = db.cursor()
            if target_strategy_id:
                cur.execute(
                    "SELECT id, strategy_id, symbol, side, size, entry_price FROM qd_strategy_positions WHERE strategy_id = %s ORDER BY updated_at DESC", 
                    (int(target_strategy_id),)
                )
            else:
                cur.execute("SELECT id, strategy_id, symbol, side, size, entry_price FROM qd_strategy_positions ORDER BY updated_at DESC")
            rows = cur.fetchall() or []
            cur.close()

        # Removed early return to allow syncing active strategies even if local DB is empty.
        # if not rows and not target_strategy_id:
        #    return

        # Group by strategy_id for efficient exchange queries.
        sid_to_rows: Dict[int, List[Dict[str, Any]]] = {}
        for r in rows:
            sid = int(r.get("strategy_id") or 0)
            if sid <= 0:
                continue
            sid_to_rows.setdefault(sid, []).append(r)
        
        # If targeted sync but no local rows found, we assume user might have opened position externally 
        # but DB is empty. However, without knowing *which* symbol to check, we can't easily auto-discover 
        # unless we fetch ALL positions from exchange for that strategy.
        # But `load_strategy_configs(sid)` gives us the exchange keys. 
        # If target_strategy_id is set but sid_to_rows is empty, add it so the
        # logic below still enters and calls client.get_positions().
        if target_strategy_id and target_strategy_id not in sid_to_rows:
             sid_to_rows[target_strategy_id] = []

        # [Log Fix] Load all ACTIVE LIVE strategies to ensure we sync/log them even if local DB is empty.
        # Otherwise, if we have no local positions, we would silently skip the exchange check.
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                # Fetch all strategies configured for LIVE execution
                cur.execute("SELECT id FROM qd_strategies_trading WHERE status = 'running' AND execution_mode = 'live'")
                active_rows = cur.fetchall() or []
                cur.close()
            
            logger.debug(f"[PositionSync] Found {len(active_rows)} active live strategies in DB.")
            for _ar in active_rows:
                _sid = int(_ar.get("id") or 0)
                if _sid <= 0 or should_skip_position_sync(_sid):
                    continue
                if _sid not in sid_to_rows:
                    if target_strategy_id and target_strategy_id != _sid:
                        continue
                    sid_to_rows[_sid] = []
        except Exception as e:
            logger.error(f"Failed to load active strategies for sync: {e}", exc_info=True)

        # 2) Reconcile per strategy
        for sid, plist in sid_to_rows.items():
            if target_strategy_id and sid != target_strategy_id:
                continue
            if should_skip_position_sync(int(sid)):
                continue
            try:
                sc = load_strategy_configs(int(sid))
                exec_mode = (sc.get("execution_mode") or "").strip().lower()
                bot_type = str(
                    sc.get("bot_type")
                    or (sc.get("trading_config") or {}).get("bot_type")
                    or ""
                ).strip().lower()
                if strategy_uses_fill_ledger(sc):
                    logger.debug(
                        "[PositionSync] Strategy %s skipped: fill-ledger strategy (L3)",
                        sid,
                    )
                    continue
                if exec_mode != "live":
                    logger.debug(f"[PositionSync] Strategy {sid} skipped: execution_mode='{exec_mode}'")
                    continue
                sync_user_id = int(sc.get("user_id") or 1)
                exchange_config = resolve_exchange_config(sc.get("exchange_config") or {}, user_id=sync_user_id)
                safe_cfg = safe_exchange_config_for_log(exchange_config)
                
                # Signal mode may not have an exchange configured.
                exchange_id = str(exchange_config.get("exchange_id") or "").strip().lower()
                if not exchange_id:
                    logger.debug(f"[PositionSync] Strategy {sid} skipped: exchange_id is empty (signal mode or no exchange config)")
                    continue
                
                market_type = (sc.get("market_type") or exchange_config.get("market_type") or "swap")
                market_type = str(market_type or "swap").strip().lower()
                if market_type in ("futures", "future", "perp", "perpetual"):
                    market_type = "swap"
                
                # Get strategy's trading symbol(s) to filter positions
                # Only sync positions for symbols that this strategy actually trades
                allowed_symbols = strategy_allowed_symbols(sc)

                # Lazy import IBKR / Alpaca clients here so the elif chain
                # below can rely on isinstance() checks without paying the import
                # cost on systems that don't ship those broker libs.
                global IBKRClient
                if IBKRClient is None:
                    try:
                        from app.services.ibkr_trading import IBKRClient as _IBKRClient
                        IBKRClient = _IBKRClient
                    except ImportError:
                        pass

                global AlpacaClient
                if AlpacaClient is None:
                    try:
                        from app.services.alpaca_trading import AlpacaClient as _AlpacaClient
                        AlpacaClient = _AlpacaClient
                    except ImportError:
                        pass

                cache_key = position_sync_cache_key(sync_user_id, exchange_id, market_type, exchange_config)
                cached_snap = get_position_sync_snapshot(cache_key)
                exch_size: Dict[str, Dict[str, float]] = {}
                exch_entry_price: Dict[str, Dict[str, float]] = {}
                exch_inst_id: Dict[str, Dict[str, str]] = {}

                if cached_snap is not None:
                    exch_size, exch_entry_price, exch_inst_id = cached_snap
                else:
                    if is_exchange_sync_backoff(cache_key):
                        logger.warning(
                            "[PositionSync] Strategy %s skipped: %s sync backoff active (key=%s)",
                            sid,
                            exchange_id,
                            cache_key,
                        )
                        continue

                    # Try to create the client; skip strategies with invalid exchange config.
                    try:
                        client = create_client(exchange_config, market_type=market_type)
                    except Exception as e:
                        msg = str(e)
                        if is_fatal_exchange_error(msg):
                            logger.error(
                                "[PositionSync] Strategy %s fatal client error; auto-stopping. error=%s",
                                sid,
                                msg,
                            )
                            auto_stop_live_strategy(int(sid), msg, source="position_sync_client")
                        else:
                            logger.debug(
                                f"[PositionSync] Strategy {sid} skipped: failed to create client (exchange_id={exchange_id}): {e}"
                            )
                        continue

                    if isinstance(client, BinanceFuturesClient) and market_type == "swap":
                        try:
                            all_pos = client.get_positions() or []
                        except Exception as e:
                            msg = str(e)
                            if is_file_descriptor_exhausted(e):
                                set_exchange_sync_backoff(cache_key, seconds=_position_sync_fd_backoff_sec())
                                _activate_position_sync_fd_backoff(msg)
                                return
                            if is_fatal_exchange_error(msg):
                                logger.error(f"[PositionSync] Strategy {sid} fatal auth error; auto-stopping. error={msg}")
                                auto_stop_live_strategy(int(sid), msg, source="position_sync_binance")
                                continue
                            if is_exchange_rate_limit_error(msg):
                                set_exchange_sync_backoff(cache_key)
                                logger.error(
                                    "[PositionSync] Binance rate limit for key=%s; backing off %ss. error=%s",
                                    cache_key,
                                    int(exchange_sync_backoff_sec()),
                                    msg,
                                )
                                continue
                            logger.error(f"[PositionSync] Strategy {sid} get_positions failed: {msg}", exc_info=True)
                            continue
                        if isinstance(all_pos, dict) and "raw" in all_pos:
                            all_pos = all_pos["raw"]

                        if isinstance(all_pos, list):
                            for p in all_pos:
                                sym = str(p.get("symbol") or "").strip().upper()
                                try:
                                    amt = float(p.get("positionAmt") or 0.0)
                                    ep = float(p.get("entryPrice") or 0.0)
                                except Exception:
                                    amt = 0.0
                                    ep = 0.0
                                if not sym or abs(amt) <= 0:
                                    continue
                                hb_sym = sym
                                if hb_sym.endswith("USDT") and len(hb_sym) > 4 and "/" not in hb_sym:
                                    hb_sym = f"{hb_sym[:-4]}/USDT"
                                side = "long" if amt > 0 else "short"
                                exch_size.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = abs(float(amt))
                                exch_entry_price.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = abs(float(ep))


                    elif isinstance(client, OkxClient) and market_type == "swap":
                        try:
                            resp = client.get_positions()
                        except Exception as e:
                            # Fatal auth/config errors should auto-stop the strategy to avoid endless spam.
                            # Typical OKX response: HTTP 401 {"msg":"Invalid OK-ACCESS-KEY","code":"50111"}
                            msg = str(e)
                            m = msg.lower()
                            if is_file_descriptor_exhausted(e):
                                set_exchange_sync_backoff(cache_key, seconds=_position_sync_fd_backoff_sec())
                                _activate_position_sync_fd_backoff(msg)
                                return
                            if is_fatal_exchange_error(msg):
                                logger.error(f"[PositionSync] Strategy {sid} fatal auth error; auto-stopping. error={msg}")
                                auto_stop_live_strategy(int(sid), msg, source="position_sync_okx")
                                continue
                            # Non-fatal: keep syncing other strategies, but don't crash the worker loop.
                            logger.error(f"[PositionSync] Strategy {sid} get_positions failed: {msg}", exc_info=True)
                            continue
                        data = (resp.get("data") or []) if isinstance(resp, dict) else []
                        if isinstance(data, list):
                            for p in data:
                                inst_id = str(p.get("instId") or "")
                                pos_side = str(p.get("posSide") or "").lower()
                                try:
                                    pos = float(p.get("pos") or 0.0)
                                except Exception:
                                    pos = 0.0
                                if not inst_id or abs(pos) <= 0:
                                    continue
                                # instId: BTC-USDT-SWAP -> BTC/USDT
                                hb_sym = inst_id.replace("-SWAP", "").replace("-", "/")
                                if pos_side == "long":
                                    side = "long"
                                elif pos_side == "short":
                                    side = "short"
                                elif pos_side == "net":
                                    side = "long" if pos > 0 else "short"
                                else:
                                    side = "long" if pos > 0 else "short"
                                # IMPORTANT: OKX swap positions `pos` is in contracts, but our system uses base-asset quantity.
                                # Convert contracts -> base using ctVal when available.
                                qty_base = abs(float(pos))
                                try:
                                    inst = client.get_instrument(inst_type="SWAP", inst_id=inst_id) or {}
                                    ct_val = float(inst.get("ctVal") or 0.0)
                                    if ct_val > 0:
                                        qty_base = qty_base * ct_val
                                except Exception:
                                    pass
                                exch_size.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = float(qty_base)
                                exch_inst_id.setdefault(hb_sym, {"long": "", "short": ""})[side] = inst_id

                                # Extract entry price from OKX position data
                                # OKX API returns avgPx (average price) or avgPxEp (average price in equity) for positions
                                try:
                                    # Try avgPx first (average entry price)
                                    avg_px = p.get("avgPx")
                                    if avg_px:
                                        entry_price = float(avg_px)
                                    else:
                                        # Fallback to avgPxEp (average price in equity)
                                        avg_px_ep = p.get("avgPxEp")
                                        if avg_px_ep:
                                            entry_price = float(avg_px_ep)
                                        else:
                                            # Fallback to last price if available
                                            last_px = p.get("last")
                                            entry_price = float(last_px) if last_px else 0.0
                                
                                    if entry_price > 0:
                                        exch_entry_price.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = entry_price
                                        logger.debug(f"[PositionSync] OKX {hb_sym} {side}: entry_price={entry_price} from avgPx={p.get('avgPx')} or avgPxEp={p.get('avgPxEp')}")
                                    else:
                                        logger.warning(f"[PositionSync] OKX {hb_sym} {side}: Could not extract entry price from position data: {p}")
                                except Exception as e:
                                    logger.warning(f"[PositionSync] Failed to extract entry price for OKX {hb_sym} {side}: {e}")
                                    # Don't set entry_price, will remain 0.0

                    elif isinstance(client, BitgetMixClient) and market_type == "swap":
                        product_type = str(exchange_config.get("product_type") or exchange_config.get("productType") or "USDT-FUTURES")
                        resp = client.get_positions(product_type=product_type)
                        data = resp.get("data") if isinstance(resp, dict) else None
                        if isinstance(data, list):
                            for p in data:
                                sym = str(p.get("symbol") or "")
                                hold_side = str(p.get("holdSide") or "").lower()
                                try:
                                    total = float(p.get("total") or 0.0)
                                except Exception:
                                    total = 0.0
                                if not sym or abs(total) <= 0:
                                    continue
                                hb_sym = sym.upper()
                                if hb_sym.endswith("USDT") and len(hb_sym) > 4 and "/" not in hb_sym:
                                    hb_sym = f"{hb_sym[:-4]}/USDT"
                                side = "long" if hold_side == "long" else "short"
                                exch_size.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = abs(float(total))
                                try:
                                    ep = float(p.get("openPriceAvg") or p.get("averageOpenPrice") or 0.0)
                                    if ep > 0:
                                        exch_entry_price.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = ep
                                except Exception:
                                    pass

                    elif isinstance(client, BybitClient) and market_type == "swap":
                        # Bybit v5 requires symbol or settleCoin; use USDT for full linear book.
                        resp = client.get_positions(settle_coin="USDT")
                        lst = (((resp.get("result") or {}).get("list")) if isinstance(resp, dict) else None) or []
                        if isinstance(lst, list):
                            for p in lst:
                                if not isinstance(p, dict):
                                    continue
                                sym = str(p.get("symbol") or "").strip().upper()
                                side0 = str(p.get("side") or "").strip().lower()  # Buy/Sell
                                try:
                                    sz = float(p.get("size") or 0.0)
                                except Exception:
                                    sz = 0.0
                                if not sym or abs(sz) <= 0:
                                    continue
                                hb_sym = sym
                                if hb_sym.endswith("USDT") and len(hb_sym) > 4 and "/" not in hb_sym:
                                    hb_sym = f"{hb_sym[:-4]}/USDT"
                                side = "long" if side0 == "buy" else ("short" if side0 == "sell" else ("long" if sz > 0 else "short"))
                                exch_size.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = abs(float(sz))
                                try:
                                    ep = float(p.get("avgPrice") or p.get("entryPrice") or 0.0)
                                    if ep > 0:
                                        exch_entry_price.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = ep
                                except Exception:
                                    pass

                    elif isinstance(client, GateUsdtFuturesClient) and market_type == "swap":
                        resp = client.get_positions()
                        items = resp if isinstance(resp, list) else []
                        if isinstance(items, list):
                            for p in items:
                                if not isinstance(p, dict):
                                    continue
                                contract = str(p.get("contract") or "").strip()
                                try:
                                    sz_ct = float(p.get("size") or 0.0)  # contracts, signed
                                except Exception:
                                    sz_ct = 0.0
                                if not contract or abs(sz_ct) <= 0:
                                    continue
                                hb_sym = contract.replace("_", "/")
                                side = "long" if sz_ct > 0 else "short"
                                # Convert contracts -> base using quanto_multiplier.
                                qty_base = abs(sz_ct)
                                try:
                                    meta = client.get_contract(contract=contract) or {}
                                    qm = float(meta.get("quanto_multiplier") or meta.get("contract_size") or 0.0)
                                    if qm > 0:
                                        qty_base = qty_base * qm
                                except Exception:
                                    pass
                                exch_size.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = float(qty_base)
                                try:
                                    ep = float(p.get("entry_price") or p.get("open_price") or 0.0)
                                    if ep > 0:
                                        exch_entry_price.setdefault(hb_sym, {"long": 0.0, "short": 0.0})[side] = ep
                                except Exception:
                                    pass

                    elif isinstance(client, KrakenFuturesClient) and market_type == "swap":
                        resp = client.get_open_positions()
                        positions = (resp.get("openPositions") if isinstance(resp, dict) else None) or (resp.get("open_positions") if isinstance(resp, dict) else None) or []
                        if isinstance(positions, list):
                            for p in positions:
                                if not isinstance(p, dict):
                                    continue
                                sym = str(p.get("symbol") or p.get("instrument") or "").strip()
                                try:
                                    sz = float(p.get("size") or p.get("positionSize") or 0.0)
                                except Exception:
                                    sz = 0.0
                                if not sym or abs(sz) <= 0:
                                    continue
                                side = "long" if sz > 0 else "short"
                                exch_size.setdefault(sym, {"long": 0.0, "short": 0.0})[side] = abs(float(sz))
                                try:
                                    ep = float(p.get("price") or p.get("avgPrice") or 0.0)
                                    if ep > 0:
                                        exch_entry_price.setdefault(sym, {"long": 0.0, "short": 0.0})[side] = ep
                                except Exception:
                                    pass

                    elif IBKRClient is not None and isinstance(client, IBKRClient):
                        # IBKR US-stock positions. `quantity` is signed: >0 = long, <0 = short.
                        # We currently only enforce long-only entries (see _execute_ibkr_order),
                        # but still mirror short rows so reconciliation does not orphan them
                        # if the user had pre-existing inventory in TWS.
                        try:
                            positions = client.get_positions() or []
                        except Exception as e:
                            msg = str(e)
                            if is_file_descriptor_exhausted(e):
                                set_exchange_sync_backoff(cache_key, seconds=_position_sync_fd_backoff_sec())
                                _activate_position_sync_fd_backoff(msg)
                                return
                            if is_fatal_exchange_error(msg):
                                logger.error(
                                    "[PositionSync] Strategy %s IBKR fatal error; auto-stopping. error=%s",
                                    sid,
                                    msg,
                                )
                                auto_stop_live_strategy(int(sid), msg, source="position_sync_ibkr")
                            else:
                                logger.error(f"[PositionSync] Strategy {sid} IBKR get_positions failed: {e}", exc_info=True)
                            continue
                        if isinstance(positions, list):
                            for p in positions:
                                if not isinstance(p, dict):
                                    continue
                                sym = str(p.get("symbol") or p.get("ib_symbol") or "").strip()
                                try:
                                    qty = float(p.get("quantity") or 0.0)
                                except Exception:
                                    qty = 0.0
                                try:
                                    avg = float(p.get("avgCost") or 0.0)
                                except Exception:
                                    avg = 0.0
                                if not sym or abs(qty) <= 0:
                                    continue
                                side = "long" if qty > 0 else "short"
                                exch_size.setdefault(sym, {"long": 0.0, "short": 0.0})[side] = abs(qty)
                                if avg > 0:
                                    exch_entry_price.setdefault(sym, {"long": 0.0, "short": 0.0})[side] = avg
                        # Continue to reconciliation logic below

                    elif AlpacaClient is not None and isinstance(client, AlpacaClient):
                        # Alpaca positions cover both US stocks and crypto. The client
                        # already returns a normalized `side` string ("long" / "short")
                        # plus `quantity` and `avgCost`. Crypto symbols come through as
                        # "BTC/USD" is the same format the strategy stores, so no extra
                        # normalization is needed here.
                        try:
                            positions = client.get_positions() or []
                        except Exception as e:
                            if is_file_descriptor_exhausted(e):
                                set_exchange_sync_backoff(cache_key, seconds=_position_sync_fd_backoff_sec())
                                _activate_position_sync_fd_backoff(str(e))
                                return
                            logger.error(f"[PositionSync] Strategy {sid} Alpaca get_positions failed: {e}", exc_info=True)
                            continue
                        if isinstance(positions, list):
                            for p in positions:
                                if not isinstance(p, dict):
                                    continue
                                sym = str(p.get("symbol") or "").strip()
                                try:
                                    qty = float(p.get("quantity") or 0.0)
                                except Exception:
                                    qty = 0.0
                                try:
                                    avg = float(p.get("avgCost") or 0.0)
                                except Exception:
                                    avg = 0.0
                                if not sym or abs(qty) <= 0:
                                    continue
                                side_str = str(p.get("side") or "").strip().lower()
                                if side_str not in ("long", "short"):
                                    side_str = "long" if qty > 0 else "short"
                                exch_size.setdefault(sym, {"long": 0.0, "short": 0.0})[side_str] = abs(qty)
                                if avg > 0:
                                    exch_entry_price.setdefault(sym, {"long": 0.0, "short": 0.0})[side_str] = avg
                        # Continue to reconciliation logic below

                    elif market_type == "spot":
                        from app.services.live_trading.spot_wallet_snapshot import list_spot_wallet_positions

                        try:
                            spot_rows = list_spot_wallet_positions(client) or []
                        except Exception as e:
                            if is_file_descriptor_exhausted(e):
                                set_exchange_sync_backoff(cache_key, seconds=_position_sync_fd_backoff_sec())
                                _activate_position_sync_fd_backoff(str(e))
                                return
                            logger.error(
                                f"[PositionSync] Strategy {sid} spot wallet sync failed: {e}",
                                exc_info=True,
                            )
                            continue
                        for row in spot_rows:
                            if not isinstance(row, dict):
                                continue
                            sym = normalize_strategy_symbol(str(row.get("symbol") or "")) or str(
                                row.get("symbol") or ""
                            ).strip()
                            side = str(row.get("side") or "long").strip().lower()
                            try:
                                sz = float(row.get("size") or 0.0)
                            except Exception:
                                sz = 0.0
                            if not sym or side not in ("long", "short") or sz <= 1e-12:
                                continue
                            exch_size.setdefault(sym, {"long": 0.0, "short": 0.0})[side] = sz
                            ep = float(row.get("entry_price") or 0.0)
                            if ep > 0:
                                exch_entry_price.setdefault(sym, {"long": 0.0, "short": 0.0})[side] = ep
                            iid = str(row.get("inst_id") or "")
                            if iid:
                                exch_inst_id.setdefault(sym, {"long": "", "short": ""})[side] = iid

                    else:
                        logger.debug(f"position sync: skip unsupported market/client: sid={sid}, cfg={safe_cfg}, market_type={market_type}, client={type(client)}")
                        continue

                    set_position_sync_snapshot(cache_key, exch_size, exch_entry_price, exch_inst_id)
                    try:
                        cred_id = credential_id_from_exchange_config(exchange_config)
                        legs = account_legs_from_exchange_maps(
                            exch_size, exch_entry_price, exch_inst_id
                        )
                        sync_account_positions(
                            user_id=int(sync_user_id),
                            credential_id=cred_id,
                            exchange_id=str(exchange_id or ""),
                            market_type=str(market_type or "swap"),
                            legs=legs,
                        )
                    except Exception as l1_err:
                        logger.warning("[PositionSync] L1 account sync failed key=%s: %s", cache_key, l1_err)

                # [DEBUG] Log all normalized exchange keys for inspection
                logger.debug(f"[PositionSync] Strategy {sid} Exchange Keys: {list(exch_size.keys())}")

                # [Log Optimization] Log current positions each sync cycle (see POSITION_SYNC_INTERVAL_SEC)
                pos_summary_parts = []
                for _sym, _sides in exch_size.items():
                    for _side_key, _qty in _sides.items():
                        if _qty > 0:
                            _ep = exch_entry_price.get(_sym, {}).get(_side_key, 0.0)
                            pos_summary_parts.append(f"{_sym} {_side_key} size={_qty} entry={_ep}")

                if pos_summary_parts:
                    logger.debug(f"[PositionSync] Strategy {sid} ({safe_cfg.get('exchange_id', 'unknown')}) positions: {'; '.join(pos_summary_parts)}")
                else:
                    logger.debug(f"[PositionSync] Strategy {sid} ({safe_cfg.get('exchange_id', 'unknown')}) has NO positions on exchange.")

                # Keep exchange truth in L1 only. Strategy positions (L3) must be
                # produced by that strategy's own fills, otherwise two live
                # strategies sharing ETH/USDT would both inherit the same
                # exchange account position.
            except Exception as e:
                msg = str(e)
                if is_file_descriptor_exhausted(e):
                    _activate_position_sync_fd_backoff(msg)
                    return
                if is_fatal_exchange_error(msg):
                    logger.error(f"[PositionSync] Strategy {sid} fatal error; auto-stopping. error={msg}", exc_info=True)
                    auto_stop_live_strategy(int(sid), msg, source="position_sync")
                else:
                    logger.error(f"position sync: strategy_id={sid} failed: {e}", exc_info=True)

    def _sync_alpaca_sent_orders(self, limit: int = 50) -> None:
        rows = self._fetch_alpaca_sent_orders(limit=limit)
        for row in rows:
            try:
                self._sync_one_alpaca_sent_order(row)
            except Exception as e:
                logger.warning(
                    "Alpaca fill sync failed: pending_id=%s err=%s",
                    row.get("id"),
                    e,
                )

    def _fetch_alpaca_sent_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            try:
                stale_sec = int(self._stale_processing_sec or 0)
            except Exception:
                stale_sec = 0
            if stale_sec > 0:
                with get_db_connection() as db:
                    cur = db.cursor()
                    cur.execute(
                        """
                        UPDATE pending_orders
                        SET status = 'sent',
                            dispatch_note = 'alpaca_fill_sync:requeued_stale_sync',
                            updated_at = NOW()
                        WHERE status = 'syncing'
                          AND LOWER(COALESCE(exchange_id, '')) = 'alpaca'
                          AND updated_at < NOW() - (%s * INTERVAL '1 second')
                        """,
                        (stale_sec,),
                    )
                    db.commit()
                    cur.close()
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM pending_orders
                    WHERE status = 'sent'
                      AND LOWER(COALESCE(exchange_id, '')) = 'alpaca'
                      AND COALESCE(exchange_order_id, '') <> ''
                    ORDER BY sent_at ASC NULLS FIRST, id ASC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall() or []
                cur.close()
            return rows
        except Exception as e:
            logger.warning("fetch_alpaca_sent_orders failed: %s", e)
            return []

    def _claim_alpaca_sent_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Atomically claim one Alpaca sent order for fill sync."""
        if int(order_id or 0) <= 0:
            return None
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    UPDATE pending_orders
                    SET status = 'syncing',
                        dispatch_note = 'alpaca_fill_sync:syncing',
                        updated_at = NOW()
                    WHERE id = %s
                      AND status = 'sent'
                      AND LOWER(COALESCE(exchange_id, '')) = 'alpaca'
                      AND COALESCE(exchange_order_id, '') <> ''
                    RETURNING *
                    """,
                    (int(order_id),),
                )
                row = cur.fetchone()
                db.commit()
                cur.close()
            return row if isinstance(row, dict) else None
        except Exception as e:
            logger.warning("claim_alpaca_sent_order failed: pending_id=%s err=%s", order_id, e)
            return None

    def _sync_one_alpaca_sent_order(self, row: Dict[str, Any]) -> None:
        order_id = int(row.get("id") or 0)
        if order_id <= 0:
            return
        claimed = self._claim_alpaca_sent_order(order_id)
        if not claimed:
            return
        row = claimed
        exchange_order_id = str(row.get("exchange_order_id") or "").strip()
        if not exchange_order_id:
            return

        payload = {}
        payload_json = row.get("payload_json") or ""
        if isinstance(payload_json, str) and payload_json.strip():
            try:
                payload = json.loads(payload_json) or {}
            except Exception:
                payload = {}

        strategy_id = int(payload.get("strategy_id") or row.get("strategy_id") or 0)
        if strategy_id <= 0:
            return

        sc = load_strategy_configs(strategy_id)
        exchange_config = resolve_exchange_config(sc.get("exchange_config") or {}, user_id=int(sc.get("user_id") or 1))
        if str(exchange_config.get("exchange_id") or "").strip().lower() != "alpaca":
            return

        try:
            client = create_client(exchange_config)
        except Exception as e:
            logger.warning("Alpaca fill sync create_client failed: pending_id=%s err=%s", order_id, e)
            return

        global AlpacaClient
        if AlpacaClient is None:
            try:
                from app.services.alpaca_trading import AlpacaClient as _AlpacaClient
                AlpacaClient = _AlpacaClient
            except Exception:
                AlpacaClient = None
        if AlpacaClient is None or not isinstance(client, AlpacaClient):
            return

        result = client.get_order_status(exchange_order_id)
        status = str(result.status or "").strip().lower()
        cumulative_filled = float(result.filled or 0.0)
        cumulative_avg = float(result.avg_price or 0.0)
        previous_filled = float(row.get("filled") or 0.0)
        previous_avg = float(row.get("avg_price") or 0.0)
        raw_json = json.dumps(result.raw or {}, ensure_ascii=False)

        delta = cumulative_filled - previous_filled
        if delta > ALPACA_FILL_DELTA_EPSILON and cumulative_avg > 0:
            delta_avg = cumulative_avg
            if previous_filled > 0 and previous_avg > 0:
                delta_notional = cumulative_filled * cumulative_avg - previous_filled * previous_avg
                if delta_notional > 0:
                    delta_avg = delta_notional / delta

            signal_type = payload.get("signal_type") or row.get("signal_type")
            symbol = payload.get("symbol") or row.get("symbol")
            market_category = str(
                sc.get("market_category")
                or (sc.get("trading_config") or {}).get("market_category")
                or "USStock"
            )
            market_type_for_client = "crypto" if market_category.lower() in ("crypto", "cryptocurrency") else "USStock"
            profit, _matched_entry = persist_strategy_fill(
                strategy_id=strategy_id,
                symbol=str(symbol or ""),
                signal_type=str(signal_type or ""),
                filled=float(delta),
                avg_price=float(delta_avg),
                exchange_config=exchange_config,
                market_type=market_type_for_client,
                order_id=order_id,
                fill_source="worker_alpaca_fill_sync",
                close_reason=trade_close_reason_from_payload(payload, str(signal_type or "")),
                strategy_run_id=int(payload.get("strategy_run_id") or row.get("strategy_run_id") or 0),
                order_intent_id=int(payload.get("order_intent_id") or row.get("order_intent_id") or 0),
                basket_id=str(payload.get("basket_id") or ""),
                exchange_id="alpaca",
                exchange_order_id=str(exchange_order_id or ""),
                raw_fill=result.raw or {},
            )
            _pstr = f", profit={profit:.4f}" if profit is not None else ""
            append_strategy_log(
                strategy_id,
                "trade",
                f"Alpaca fill synced: {signal_type} {symbol} filled={delta:.6f} @ {delta_avg:.6f}{_pstr}",
            )

        final_statuses = {"filled", "canceled", "cancelled", "rejected", "expired"}
        new_status = "sent"
        if status == "filled":
            new_status = "filled"
        elif status in ("canceled", "cancelled"):
            new_status = "cancelled"
        elif status in ("rejected", "expired"):
            new_status = "failed"

        self._update_alpaca_sent_order_snapshot(
            order_id=order_id,
            status=new_status,
            exchange_status=status,
            filled=cumulative_filled,
            avg_price=cumulative_avg,
            exchange_response_json=raw_json,
            final=status in final_statuses,
        )

    def _update_alpaca_sent_order_snapshot(
        self,
        *,
        order_id: int,
        status: str,
        exchange_status: str,
        filled: float,
        avg_price: float,
        exchange_response_json: str,
        final: bool,
    ) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE pending_orders
                SET status = %s,
                    last_error = CASE WHEN %s = 'failed' THEN %s ELSE '' END,
                    dispatch_note = %s,
                    filled = %s,
                    avg_price = %s,
                    exchange_response_json = %s,
                    executed_at = CASE WHEN %s THEN NOW() ELSE executed_at END,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    str(status or "sent"),
                    str(status or "sent"),
                    str(exchange_status or ""),
                    f"alpaca_fill_sync:{exchange_status or 'unknown'}",
                    float(filled or 0.0),
                    float(avg_price or 0.0),
                    str(exchange_response_json or ""),
                    bool(final and float(filled or 0.0) > 0),
                    int(order_id),
                ),
            )
            cur.execute(
                """
                UPDATE strategy_order_intents soi
                SET status = CASE
                        WHEN %s = 'filled' THEN 'filled'
                        WHEN %s = 'failed' THEN 'rejected'
                        WHEN %s = 'cancelled' THEN 'cancelled'
                        WHEN %s > 0 THEN 'partially_filled'
                        ELSE 'submitted'
                    END,
                    exchange_order_id = COALESCE(NULLIF(po.exchange_order_id, ''), soi.exchange_order_id),
                    updated_at = NOW()
                FROM pending_orders po
                WHERE po.id = %s
                  AND po.order_intent_id = soi.id
                """,
                (
                    str(status or "sent"),
                    str(status or "sent"),
                    str(status or "sent"),
                    float(filled or 0.0),
                    int(order_id),
                ),
            )
            db.commit()
            cur.close()

    def _sync_live_sent_orders(self, limit: int = 50) -> None:
        """Reconcile submitted crypto orders, including durable resting limits."""
        rows = self._fetch_live_sent_orders(limit=limit)
        for row in rows:
            try:
                self._sync_one_live_sent_order(row)
            except Exception as exc:
                logger.warning(
                    "Live fill sync failed: pending_id=%s exchange=%s err=%s",
                    row.get("id"),
                    row.get("exchange_id"),
                    exc,
                )

    def _fetch_live_sent_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            stale_sec = max(0, int(self._stale_processing_sec or 0))
            with get_db_connection() as db:
                cur = db.cursor()
                if stale_sec > 0:
                    cur.execute(
                        """
                        UPDATE pending_orders
                        SET status = 'sent',
                            dispatch_note = 'live_fill_sync:requeued_stale_sync',
                            updated_at = NOW()
                        WHERE status = 'syncing'
                          AND LOWER(COALESCE(exchange_id, '')) <> 'alpaca'
                          AND updated_at < NOW() - (%s * INTERVAL '1 second')
                        """,
                        (stale_sec,),
                    )
                    db.commit()
                cur.execute(
                    """
                    SELECT *
                    FROM pending_orders
                    WHERE status = 'sent'
                      AND LOWER(COALESCE(exchange_id, '')) <> 'alpaca'
                      AND COALESCE(exchange_id, '') <> ''
                      AND COALESCE(exchange_order_id, '') <> ''
                    ORDER BY sent_at ASC NULLS FIRST, id ASC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall() or []
                cur.close()
            return rows
        except Exception as exc:
            logger.warning("fetch_live_sent_orders failed: %s", exc)
            return []

    def _claim_live_sent_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        if int(order_id or 0) <= 0:
            return None
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE pending_orders
                SET status = 'syncing',
                    dispatch_note = 'live_fill_sync:syncing',
                    updated_at = NOW()
                WHERE id = %s
                  AND status = 'sent'
                  AND LOWER(COALESCE(exchange_id, '')) <> 'alpaca'
                  AND COALESCE(exchange_order_id, '') <> ''
                RETURNING *
                """,
                (int(order_id),),
            )
            row = cur.fetchone()
            db.commit()
            cur.close()
        return row if isinstance(row, dict) else None

    def _sync_one_live_sent_order(self, row: Dict[str, Any]) -> None:
        order_id = int(row.get("id") or 0)
        claimed = self._claim_live_sent_order(order_id)
        if not claimed:
            return
        row = claimed
        payload: Dict[str, Any] = {}
        try:
            payload = json.loads(str(row.get("payload_json") or "{}")) or {}
        except Exception:
            payload = {}

        strategy_id = int(payload.get("strategy_id") or row.get("strategy_id") or 0)
        symbol = str(payload.get("symbol") or row.get("symbol") or "").strip()
        market_type = str(payload.get("market_type") or row.get("market_type") or "swap").strip().lower()
        exchange_order_id = str(row.get("exchange_order_id") or "").strip()
        exchange_id = str(row.get("exchange_id") or "").strip().lower()
        if strategy_id <= 0 or not symbol or not exchange_order_id:
            self._mark_failed(order_id=order_id, error="live_fill_sync_invalid_order_context")
            return

        sc = load_strategy_configs(strategy_id)
        exchange_config = resolve_exchange_config(
            sc.get("exchange_config") or {},
            user_id=int(sc.get("user_id") or row.get("user_id") or 1),
        )
        try:
            client = create_client(exchange_config, market_type=market_type)
            if exchange_id == "ibkr" and hasattr(client, "get_order_status"):
                broker_result = client.get_order_status(exchange_order_id)
                cumulative_filled = float(broker_result.filled or 0.0)
                cumulative_avg = float(broker_result.avg_price or 0.0)
                exchange_status = normalize_live_order_status(broker_result.status)
            else:
                cumulative_filled, cumulative_avg, exchange_status = query_grid_order_fill(
                    client,
                    symbol=symbol,
                    market_type=market_type,
                    exchange_order_id=exchange_order_id,
                    client_order_id="",
                    exchange_config=exchange_config,
                )
        except Exception as exc:
            self._update_live_sent_order_snapshot(
                order_id=order_id,
                status="sent",
                exchange_status="sync_error",
                filled=float(row.get("filled") or 0.0),
                avg_price=float(row.get("avg_price") or 0.0),
                exchange_response_json=json.dumps({"error": str(exc)}, ensure_ascii=False),
            )
            return

        cumulative_filled = max(0.0, float(cumulative_filled or 0.0))
        cumulative_avg = max(0.0, float(cumulative_avg or 0.0))
        exchange_status = str(exchange_status or "unknown").strip().lower()
        previous_filled = max(0.0, float(row.get("filled") or 0.0))
        previous_avg = max(0.0, float(row.get("avg_price") or 0.0))
        tracked_previous_filled, tracked_previous_avg = tracked_fill_baseline(
            row,
            exchange_order_id=exchange_order_id,
            previous_filled=previous_filled,
            previous_avg=previous_avg,
        )
        delta = cumulative_filled - tracked_previous_filled
        aggregate_filled = previous_filled
        aggregate_avg = previous_avg

        if delta > ALPACA_FILL_DELTA_EPSILON and cumulative_avg > 0:
            delta_avg = cumulative_avg
            if tracked_previous_filled > 0 and tracked_previous_avg > 0:
                delta_notional = (
                    cumulative_filled * cumulative_avg
                    - tracked_previous_filled * tracked_previous_avg
                )
                if delta_notional > 0:
                    delta_avg = delta_notional / delta
            if previous_filled > 0 and previous_avg > 0:
                aggregate_notional = previous_filled * previous_avg + delta * delta_avg
                aggregate_filled = previous_filled + delta
                aggregate_avg = aggregate_notional / aggregate_filled
            else:
                aggregate_filled = previous_filled + delta
                aggregate_avg = delta_avg
            signal_type = str(payload.get("signal_type") or row.get("signal_type") or "")
            persist_strategy_fill(
                strategy_id=strategy_id,
                symbol=symbol,
                signal_type=signal_type,
                filled=delta,
                avg_price=delta_avg,
                exchange_config=exchange_config,
                market_type=market_type,
                order_id=order_id,
                fill_source="worker_live_fill_sync",
                close_reason=trade_close_reason_from_payload(payload, signal_type),
                strategy_run_id=int(payload.get("strategy_run_id") or row.get("strategy_run_id") or 0),
                order_intent_id=int(payload.get("order_intent_id") or row.get("order_intent_id") or 0),
                basket_id=str(payload.get("basket_id") or ""),
                exchange_id=exchange_id,
                exchange_order_id=exchange_order_id,
                raw_fill={"status": exchange_status, "cumulative_filled": cumulative_filled},
            )
            append_strategy_log(
                strategy_id,
                "trade",
                f"Exchange fill synced: {signal_type} {symbol} filled={delta:.6f} @ {delta_avg:.6f}",
            )

        if delta > ALPACA_FILL_DELTA_EPSILON and cumulative_avg <= 0:
            exchange_status = "fill_price_missing"

        if delta <= ALPACA_FILL_DELTA_EPSILON:
            aggregate_filled = previous_filled
            aggregate_avg = previous_avg

        queue_status = "sent"
        if exchange_status == "filled" and cumulative_avg > 0:
            queue_status = "filled"
        elif exchange_status == "cancelled":
            queue_status = "cancelled"

        self._update_live_sent_order_snapshot(
            order_id=order_id,
            status=queue_status,
            exchange_status=exchange_status,
            filled=aggregate_filled,
            avg_price=aggregate_avg,
            exchange_response_json=json.dumps(
                {
                    "status": exchange_status,
                    "filled": aggregate_filled,
                    "avg_price": aggregate_avg,
                    "live_fill_sync": {
                        "tracked_filled": cumulative_filled,
                        "tracked_avg_price": cumulative_avg,
                    },
                },
                ensure_ascii=False,
            ),
        )

    def _update_live_sent_order_snapshot(
        self,
        *,
        order_id: int,
        status: str,
        exchange_status: str,
        filled: float,
        avg_price: float,
        exchange_response_json: str,
    ) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE pending_orders
                SET status = %s,
                    dispatch_note = %s,
                    filled = %s,
                    avg_price = %s,
                    exchange_response_json = %s,
                    executed_at = CASE WHEN %s > 0 THEN COALESCE(executed_at, NOW()) ELSE executed_at END,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    str(status or "sent"),
                    f"live_fill_sync:{exchange_status or 'unknown'}",
                    float(filled or 0.0),
                    float(avg_price or 0.0),
                    str(exchange_response_json or ""),
                    float(filled or 0.0),
                    int(order_id),
                ),
            )
            cur.execute(
                """
                UPDATE strategy_order_intents soi
                SET status = CASE
                        WHEN %s = 'filled' THEN 'filled'
                        WHEN %s = 'cancelled' THEN 'cancelled'
                        WHEN %s > 0 THEN 'partially_filled'
                        ELSE 'submitted'
                    END,
                    exchange_order_id = COALESCE(NULLIF(po.exchange_order_id, ''), soi.exchange_order_id),
                    updated_at = NOW()
                FROM pending_orders po
                WHERE po.id = %s
                  AND po.order_intent_id = soi.id
                """,
                (
                    str(status or "sent"),
                    str(status or "sent"),
                    float(filled or 0.0),
                    int(order_id),
                ),
            )
            db.commit()
            cur.close()

    def _fetch_pending_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            # Best-effort: requeue stale "processing" rows to avoid deadlocks after crashes.
            try:
                stale_sec = int(self._stale_processing_sec or 0)
            except Exception:
                stale_sec = 0
            if stale_sec > 0:
                with get_db_connection() as db:
                    cur = db.cursor()
                    cur.execute(
                        """
                        UPDATE pending_orders
                        SET status = 'pending',
                            updated_at = NOW(),
                            dispatch_note = CASE
                                WHEN dispatch_note IS NULL OR dispatch_note = '' THEN 'requeued_stale_processing'
                                ELSE dispatch_note
                            END
                        WHERE status = 'processing'
                          AND (updated_at IS NULL OR updated_at < NOW() - INTERVAL '%s seconds')
                          AND (attempts < max_attempts)
                        """,
                        (stale_sec,),
                    )
                    db.commit()
                    cur.close()

            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    SELECT *
                    FROM pending_orders
                    WHERE status = 'pending'
                      AND (attempts < max_attempts)
                    ORDER BY priority DESC, id ASC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall() or []
                cur.close()
            return rows
        except Exception as e:
            logger.warning(f"fetch_pending_orders failed: {e}")
            return []

    def _mark_processing(self, order_id: int) -> bool:
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                # Only claim if still pending to avoid double-processing.
                cur.execute(
                    """
                    UPDATE pending_orders
                    SET status = 'processing',
                        attempts = COALESCE(attempts, 0) + 1,
                        processed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s AND status = 'pending'
                    """,
                    (int(order_id),),
                )
                claimed = getattr(cur, "rowcount", None)
                db.commit()
                cur.close()
            # Only treat as success if we actually changed a row.
            if claimed is None:
                return True
            return int(claimed) > 0
        except Exception as e:
            logger.warning(f"mark_processing failed: id={order_id}, err={e}")
            return False

    def _dispatch_one(self, order_row: Dict[str, Any]) -> None:
        order_id = int(order_row["id"])
        mode = (order_row.get("execution_mode") or "signal").strip().lower()
        payload_json = order_row.get("payload_json") or ""

        payload: Dict[str, Any] = {}
        if payload_json and isinstance(payload_json, str):
            try:
                payload = json.loads(payload_json) or {}
            except Exception:
                payload = {}

        signal_type = payload.get("signal_type") or order_row.get("signal_type")
        symbol = payload.get("symbol") or order_row.get("symbol")
        strategy_id = payload.get("strategy_id") or order_row.get("strategy_id")
        price = float(payload.get("price") or order_row.get("price") or 0.0)
        amount = float(payload.get("amount") or order_row.get("amount") or 0.0)
        direction = "short" if "short" in str(signal_type) else "long"
        notification_config = payload.get("notification_config") or {}
        strategy_name = str(payload.get("strategy_name") or "").strip()
        if not strategy_name:
            # Best-effort: load from DB for nicer notifications.
            strategy_name = self._load_strategy_name(int(strategy_id or 0)) if strategy_id else ""
        if not strategy_name:
            strategy_name = f"Strategy_{strategy_id}"

        # If the queued record is legacy ("signal") but the strategy is configured as live,
        # automatically upgrade it to live execution to keep the system moving.
        try:
            if mode != "live" and strategy_id:
                sc = load_strategy_configs(int(strategy_id))
                if (sc.get("execution_mode") or "").strip().lower() == "live":
                    mode = "live"
        except Exception:
            pass

        if mode == "signal":
            # Signal-only mode: dispatch notifications (no real trading).
            # Note: notification_config is stored in payload_json at enqueue time; fallback to DB if missing.
            if (not notification_config) and strategy_id:
                notification_config = self._load_notification_config(int(strategy_id))

            stake_quote = calc_notional_value(float(price or 0.0), float(amount or 0.0)) or float(amount or 0.0)
            results = self._notifier.notify_signal(
                strategy_id=int(strategy_id or 0),
                strategy_name=str(strategy_name or ""),
                symbol=str(symbol or ""),
                signal_type=str(signal_type or ""),
                price=float(price or 0.0),
                stake_amount=float(stake_quote),
                direction=str(direction or "long"),
                notification_config=notification_config if isinstance(notification_config, dict) else {},
                extra={"pending_order_id": order_id, "mode": mode},
            )

            attempted = list(results.keys())
            ok_channels = [c for c, r in results.items() if (r or {}).get("ok")]
            fail_channels = [c for c, r in results.items() if not (r or {}).get("ok")]

            if ok_channels:
                note = f"notified_ok={','.join(ok_channels)}"
                if fail_channels:
                    note += f";fail={','.join(fail_channels)}"
                self._mark_sent(order_id=order_id, note=note[:200])
                append_strategy_log(
                    int(strategy_id or 0), "signal",
                    f"Signal notification sent: {signal_type} {symbol} @ {price:.6f}, channels={','.join(ok_channels)}",
                )
            else:
                # Nothing succeeded -> mark failed with a compact error summary.
                first_err = ""
                for c in attempted:
                    err = (results.get(c) or {}).get("error") or ""
                    if err:
                        first_err = f"{c}:{err}"
                        break
                self._mark_failed(order_id=order_id, error=first_err or "notify_failed")
                append_strategy_log(
                    int(strategy_id or 0), "error",
                    f"Signal notification failed: {signal_type} {symbol}, error={first_err or 'notify_failed'}",
                )
            return

        if mode == "live":
            self._execute_live_order(order_id=order_id, order_row=order_row, payload=payload)
            return

        self._mark_failed(order_id=order_id, error=f"unsupported_execution_mode:{mode}")

    def _load_notification_config(self, strategy_id: int) -> Dict[str, Any]:
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    "SELECT notification_config FROM qd_strategies_trading WHERE id = ?",
                    (int(strategy_id),),
                )
                row = cur.fetchone() or {}
                cur.close()
            s = row.get("notification_config") or ""
            if isinstance(s, dict):
                return s
            if isinstance(s, str) and s.strip():
                try:
                    obj = json.loads(s)
                    return obj if isinstance(obj, dict) else {}
                except Exception:
                    return {}
            return {}
        except Exception:
            return {}

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _estimate_min_order_notional(
        self,
        client: Any,
        *,
        symbol: str,
        price: float,
        market_order: bool = True,
    ) -> Tuple[float, float]:
        """Best-effort minQty/minNotional estimate from live client filters."""
        px = float(price or 0.0)
        if px <= 0 or client is None:
            return 0.0, 0.0
        try:
            if not hasattr(client, "get_symbol_filters"):
                return 0.0, 0.0
            filters = client.get_symbol_filters(symbol=symbol) or {}
            lot = {}
            if isinstance(filters.get("MARKET_LOT_SIZE"), dict) and market_order:
                lot = filters.get("MARKET_LOT_SIZE") or {}
                try:
                    if float(lot.get("minQty") or 0) <= 0:
                        lot = filters.get("LOT_SIZE") or lot
                except Exception:
                    pass
            if not lot and isinstance(filters.get("LOT_SIZE"), dict):
                lot = filters.get("LOT_SIZE") or {}
            min_qty = self._as_float((lot or {}).get("minQty"), 0.0)

            min_notional = 0.0
            notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
            if isinstance(notional_filter, dict):
                min_notional = self._as_float(
                    notional_filter.get("notional")
                    or notional_filter.get("minNotional")
                    or notional_filter.get("minNotionalValue"),
                    0.0,
                )
            if min_qty > 0:
                min_notional = max(min_notional, min_qty * px)
            return max(0.0, min_qty), max(0.0, min_notional)
        except Exception:
            return 0.0, 0.0

    def _friendly_order_error(
        self,
        error: Any,
        *,
        client: Any,
        exchange_id: str,
        symbol: str,
        signal_type: str,
        amount: float,
        price: float,
        payload: Dict[str, Any],
    ) -> str:
        raw = str(error or "")
        lower = raw.lower()
        is_size_error = bool(
            re.search(r"below|step|minqty|min qty|minsize|min size|min_notional|minnotional|invalid (qty|quantity|size|amount)", lower)
        )
        if not is_size_error:
            return raw

        px = float(price or payload.get("ref_price") or 0.0)
        qty = float(amount or 0.0)
        actual_notional = qty * px if px > 0 else 0.0
        min_qty, min_notional = self._estimate_min_order_notional(
            client,
            symbol=str(symbol or ""),
            price=px,
            market_order=True,
        )
        sizing = payload.get("sizing") if isinstance(payload, dict) else {}
        sizing = sizing if isinstance(sizing, dict) else {}
        source = str(sizing.get("source") or "unknown")
        entry_pct = sizing.get("entry_pct")
        capital = sizing.get("initial_capital")
        leverage = sizing.get("leverage") or payload.get("leverage")

        parts = [
            raw,
            (
                f"actual notional is about {actual_notional:.4f} USDT"
                if actual_notional > 0
                else f"actual order quantity is {qty:.12f}"
            ),
        ]
        if min_notional > 0:
            parts.append(f"minimum notional is about {min_notional:.4f} USDT at the current price")
        elif min_qty > 0:
            parts.append(f"exchange minimum quantity is about {min_qty:.12f}")
        if capital is not None or entry_pct is not None or leverage is not None:
            parts.append(
                "sizing="
                f"capital={self._as_float(capital, 0.0):.4f}, "
                f"entry_pct={self._as_float(entry_pct, 0.0):.4f}%, "
                f"leverage={self._as_float(leverage, 1.0):.4f}x, "
                f"source={source}"
            )
        parts.append("Increase capital, entry percentage, or leverage, or choose a symbol that meets the minimum order size.")
        return "; ".join(parts)

    def _log_live_order_sizing(
        self,
        *,
        strategy_id: int,
        client: Any,
        symbol: str,
        signal_type: str,
        reduce_only: bool,
        amount: float,
        ref_price: float,
        leverage: float,
        payload: Dict[str, Any],
        phases: Dict[str, Any],
    ) -> None:
        if reduce_only or signal_type not in ("open_long", "open_short", "add_long", "add_short"):
            return
        try:
            min_qty, min_notional = self._estimate_min_order_notional(
                client,
                symbol=str(symbol or ""),
                price=float(ref_price or 0.0),
                market_order=True,
            )
            sizing = payload.get("sizing") if isinstance(payload, dict) else {}
            sizing = sizing if isinstance(sizing, dict) else {}
            append_strategy_log(
                strategy_id,
                "info",
                (
                    "Live order sizing: "
                    f"capital={self._as_float(sizing.get('initial_capital'), 0.0):.4f}, "
                    f"entry_pct={self._as_float(sizing.get('entry_pct'), 0.0):.4f}%, "
                    f"leverage={self._as_float(sizing.get('leverage') or leverage, 1.0):.4f}x, "
                    f"price={float(ref_price or 0.0):.8f}, "
                    f"final_qty={float(amount or 0.0):.12f}, "
                    f"min_qty={float(min_qty or 0.0):.12f}, "
                    f"min_notional={float(min_notional or 0.0):.4f}, "
                    f"source={sizing.get('source') or 'unknown'}"
                ),
            )
            phases["sizing_check"] = {
                "amount": float(amount or 0.0),
                "ref_price": float(ref_price or 0.0),
                "min_qty": float(min_qty or 0.0),
                "min_notional": float(min_notional or 0.0),
                "sizing": sizing,
            }
        except Exception:
            return

    def _load_strategy_name(self, strategy_id: int) -> str:
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute("SELECT strategy_name FROM qd_strategies_trading WHERE id = ?", (int(strategy_id),))
                row = cur.fetchone() or {}
                cur.close()
            return str(row.get("strategy_name") or "").strip()
        except Exception:
            return ""

    def _execute_live_order(self, *, order_id: int, order_row: Dict[str, Any], payload: Dict[str, Any]) -> None:
        """
        Execute a pending order using direct exchange REST clients (no ccxt).
        """
        _console_print = console_print

        try:
            ctx = build_live_order_context(
                order_id=order_id,
                order_row=order_row,
                payload=payload,
                load_strategy_configs=load_strategy_configs,
                resolve_exchange_config=resolve_exchange_config,
                safe_exchange_config_for_log=safe_exchange_config_for_log,
            )
        except LiveOrderRejected as rejected:
            self._mark_failed(order_id=order_id, error=rejected.error)
            if rejected.console_message:
                _console_print(rejected.console_message)
            if rejected.strategy_id > 0:
                live_notifier = LiveOrderNotifier(
                    order_id=order_id,
                    strategy_id=rejected.strategy_id,
                    order_row=order_row,
                    payload=payload,
                    notifier=self._notifier,
                    load_notification_config=self._load_notification_config,
                    load_strategy_name=self._load_strategy_name,
                )
                live_notifier.notify(status="failed", error=rejected.error)
                if rejected.strategy_log:
                    append_strategy_log(rejected.strategy_id, "error", rejected.strategy_log)
            return

        strategy_id = ctx.strategy_id
        signal_type = ctx.signal_type
        symbol = ctx.symbol
        amount = ctx.amount
        cfg = ctx.cfg
        exchange_config = ctx.exchange_config
        safe_cfg = ctx.safe_exchange_config
        exchange_id = ctx.exchange_id
        market_category = ctx.market_category
        market_type = ctx.market_type

        live_notifier = LiveOrderNotifier(
            order_id=order_id,
            strategy_id=strategy_id,
            order_row=order_row,
            payload=payload,
            notifier=self._notifier,
            load_notification_config=self._load_notification_config,
            load_strategy_name=self._load_strategy_name,
        )
        _notify_live_best_effort = live_notifier.notify

        client = None
        try:
            client = create_client(exchange_config, market_type=market_type)
        except Exception as e:
            self._mark_failed(order_id=order_id, error=f"create_client_failed:{e}")
            _console_print(f"[worker] create_client_failed: strategy_id={strategy_id} pending_id={order_id} err={e}")
            _notify_live_best_effort(status="failed", error=f"create_client_failed:{e}")
            append_strategy_log(strategy_id, "error", f"Exchange client creation failed ({exchange_id}): {e}")
            if is_fatal_exchange_error(str(e)):
                auto_stop_live_strategy(int(strategy_id), str(e), source="pending_order_client")
            return

        # Check if this is an IBKR client (US stocks)
        global IBKRClient
        if IBKRClient is None:
            try:
                from app.services.ibkr_trading import IBKRClient as _IBKRClient
                IBKRClient = _IBKRClient
            except ImportError:
                pass

        if IBKRClient is not None and isinstance(client, IBKRClient):
            # Execute IBKR order (separate flow for stocks)
            self._execute_ibkr_order(
                order_id=order_id,
                order_row=order_row,
                payload=payload,
                client=client,
                strategy_id=strategy_id,
                exchange_config=exchange_config,
                _notify_live_best_effort=_notify_live_best_effort,
                _console_print=_console_print,
            )
            return

        global AlpacaClient
        if AlpacaClient is None:
            try:
                from app.services.alpaca_trading import AlpacaClient as _AlpacaClient
                AlpacaClient = _AlpacaClient
            except ImportError:
                pass

        if AlpacaClient is not None and isinstance(client, AlpacaClient):
            self._execute_alpaca_order(
                order_id=order_id,
                order_row=order_row,
                payload=payload,
                client=client,
                strategy_id=strategy_id,
                exchange_config=exchange_config,
                market_category=market_category,
                _notify_live_best_effort=_notify_live_best_effort,
                _console_print=_console_print,
            )
            return

        client_oid = make_client_order_id(exchange_id=exchange_id, strategy_id=strategy_id, order_id=order_id)
        sig = str(signal_type or "").strip().lower()
        # Spot does not support short signals in this system.
        if market_type == "spot" and "short" in sig:
            self._mark_failed(order_id=order_id, error="spot_market_does_not_support_short_signals")
            _console_print(f"[worker] order rejected: strategy_id={strategy_id} pending_id={order_id} spot short not supported")
            _notify_live_best_effort(status="failed", error="spot_market_does_not_support_short_signals")
            append_strategy_log(strategy_id, "error", f"Order rejected: spot market does not support short signals ({symbol} {signal_type})")
            return

        # Unified maker->market fallback settings
        # Priority: payload config > environment variable > default value
        _default_order_mode = os.getenv("ORDER_MODE", "market").strip().lower()
        _default_maker_wait_sec = float(os.getenv("MAKER_WAIT_SEC", "10"))
        _default_maker_offset_bps = float(os.getenv("MAKER_OFFSET_BPS", "2"))

        order_mode = str(payload.get("order_mode") or payload.get("orderMode") or _default_order_mode).strip().lower()
        execution_algo = str(payload.get("execution_algo") or "").strip().lower()
        if execution_algo == "market":
            order_mode = "market"
        elif execution_algo in ("limit_then_market", "maker", "maker_then_market"):
            order_mode = "maker_then_market"
        elif execution_algo == "limit":
            order_mode = "limit"
        maker_wait_sec = float(payload.get("maker_wait_sec") or payload.get("makerWaitSec") or _default_maker_wait_sec)
        maker_offset_bps = float(payload.get("maker_offset_bps") or payload.get("makerOffsetBps") or _default_maker_offset_bps)
        if maker_wait_sec <= 0:
            maker_wait_sec = _default_maker_wait_sec if _default_maker_wait_sec > 0 else 10.0
        if maker_offset_bps < 0:
            maker_offset_bps = 0.0
        maker_offset = maker_offset_bps / 10000.0

        ref_price = float(payload.get("ref_price") or payload.get("price") or order_row.get("price") or 0.0)

        side, pos_side, reduce_only = signal_to_side_pos_reduce(signal_type)

        from app.services.live_trading.position_query import query_exchange_position_size

        pre_position_qty = 0.0
        try:
            pre_position_qty = float(
                query_exchange_position_size(
                    client=client,
                    symbol=str(symbol),
                    pos_side=str(pos_side or ""),
                    market_type=str(market_type or "swap"),
                    exchange_config=exchange_config if isinstance(exchange_config, dict) else {},
                )
                or 0.0
            )
        except Exception as e:
            logger.debug("pre_position_qty snapshot failed pending_id=%s: %s", order_id, e)

        # Leverage handling (best-effort):
        # - For OKX swap, leverage must be set via private endpoint; otherwise exchange defaults apply.
        # - For other exchanges, leverage setting is not implemented yet in this local client.
        leverage = payload.get("leverage")
        if leverage is None:
            leverage = cfg.get("leverage")
        try:
            leverage = float(leverage or 1.0)
        except Exception:
            leverage = 1.0
        if leverage <= 0:
            leverage = 1.0

        # [FEATURE] Sync positions before execution to ensure size is checking against reality
        # The user requested to sync before EVERY live order to prevent mismatch.
        try:
            logger.info(f"[Sync] Triggering pre-execution sync for strategy {strategy_id} before order {order_id}")
            self._sync_positions_best_effort(target_strategy_id=strategy_id)
        except Exception as e:
            logger.warning(f"Pre-execution sync failed: {e}")

        # Collect raw exchange interactions / intermediate states for debugging & persistence.
        phases: Dict[str, Any] = {"pre_position_qty": pre_position_qty}

        # Close/reduce: cap to DB size; if DB empty, fall back to live exchange position.
        if reduce_only:
            try:
                amount, close_meta = resolve_reduce_only_quantity(
                    strategy_id=int(strategy_id),
                    symbol=str(symbol or ""),
                    pos_side=str(pos_side or ""),
                    requested_amount=float(amount or 0.0),
                    client=client,
                    market_type=str(market_type or "swap"),
                    exchange_config=exchange_config,
                )
                if close_meta:
                    phases["close_size_resolve"] = close_meta
            except Exception as e:
                logger.error(f"[RiskControl] Failed to resolve close quantity: {e}")
                phases["close_size_resolve_error"] = str(e)

        # Ensure ref price exists (used by maker pricing, fallbacks, and local DB snapshots).
        if ref_price <= 0:
            try:
                if isinstance(client, BinanceFuturesClient):
                    ref_price = float(client.get_mark_price(symbol=str(symbol)) or 0.0)
            except Exception:
                pass

        # Binance Futures leverage is per-symbol on the exchange side.
        # If we do not set it, Binance may keep default 1x and the user will observe
        # margin ~= notional (i.e., "margin = invested * leverage" when we sized using leverage).
        if isinstance(client, BinanceFuturesClient) and market_type == "swap":
            try:
                client.set_leverage(symbol=str(symbol), leverage=float(leverage or 1.0))
                phases["set_leverage"] = {"exchange": "binance", "symbol": str(symbol), "leverage": float(leverage or 1.0)}
            except Exception as e:
                # Safer default: do NOT place orders with an unintended leverage.
                err = f"binance_set_leverage_failed:{e}"
                logger.warning(f"live leverage set failed: pending_id={order_id}, strategy_id={strategy_id}, cfg={safe_cfg}, err={e}")
                self._mark_failed(order_id=order_id, error=err)
                _console_print(f"[worker] order rejected: strategy_id={strategy_id} pending_id={order_id} {err}")
                _notify_live_best_effort(status="failed", error=err, amount_hint=amount, price_hint=ref_price)
                append_strategy_log(strategy_id, "error", f"Binance set leverage failed for {symbol}: {e}")
                return

        fills = FillAccumulator()

        # Spot close: cap to exchange free base (fees often make DB size > sellable free).
        if reduce_only and market_type == "spot" and side == "sell":
            try:
                from app.services.live_trading.spot_sizing import clamp_spot_close_quantity

                new_amt, spot_meta = clamp_spot_close_quantity(
                    client, symbol=str(symbol), requested_qty=float(amount or 0.0)
                )
                if spot_meta.get("adjusted"):
                    phases["spot_close_adjustment"] = spot_meta
                amount = new_amt
            except Exception as e:
                logger.warning(
                    "Spot close amount adjustment failed: pending_id=%s, err=%s", order_id, e
                )
                phases["spot_close_adjust_error"] = str(e)

        spot_quote_amt = 0.0
        spot_market_buy_uses_quote = False
        if market_type == "spot":
            try:
                from app.services.live_trading.spot_sizing import prepare_spot_live_order_sizes

                amount, spot_quote_amt, spot_market_buy_uses_quote = prepare_spot_live_order_sizes(
                    client,
                    symbol=str(symbol),
                    side=side,
                    reduce_only=reduce_only,
                    base_qty=float(amount or 0.0),
                    ref_price=ref_price,
                )
                phases["spot_prepare"] = {
                    "base_qty": amount,
                    "quote_amt": spot_quote_amt,
                    "market_buy_uses_quote": spot_market_buy_uses_quote,
                }
            except Exception as e:
                logger.warning(
                    "Spot size prepare failed: pending_id=%s, err=%s", order_id, e
                )
                phases["spot_prepare_error"] = str(e)

        self._log_live_order_sizing(
            strategy_id=strategy_id,
            client=client,
            symbol=symbol,
            signal_type=signal_type,
            reduce_only=reduce_only,
            amount=amount,
            ref_price=ref_price,
            leverage=leverage,
            payload=payload,
            phases=phases,
        )

        # Decide if we should use limit-first flow.
        use_limit_first = order_mode in ("maker", "limit", "limit_first", "maker_then_market")

        remaining = float(amount or 0.0)
        # Close/reduce: DB may lag right after open or trailing; re-sync + re-query exchange once.
        if (
            remaining <= 0
            and reduce_only
            and not (spot_market_buy_uses_quote and spot_quote_amt > 0)
        ):
            phases["close_size_retry"] = {"trigger": "zero_after_first_resolve"}
            try:
                logger.info(
                    "[CloseRetry] Close qty is 0 for strategy=%s %s %s; re-syncing positions",
                    strategy_id,
                    symbol,
                    signal_type,
                )
                self._sync_positions_best_effort(target_strategy_id=strategy_id)
                amount, retry_meta = resolve_reduce_only_quantity(
                    strategy_id=int(strategy_id),
                    symbol=str(symbol or ""),
                    pos_side=str(pos_side or ""),
                    requested_amount=float(payload.get("amount") or order_row.get("amount") or 0.0),
                    client=client,
                    market_type=str(market_type or "swap"),
                    exchange_config=exchange_config,
                )
                if retry_meta:
                    phases["close_size_retry"].update(retry_meta)
                remaining = float(amount or 0.0)
                if remaining > 0:
                    logger.info(
                        "[CloseRetry] Resolved close qty=%s for strategy=%s %s %s",
                        remaining,
                        strategy_id,
                        symbol,
                        signal_type,
                    )
            except Exception as e:
                logger.warning(
                    "[CloseRetry] Re-sync/resolve failed: pending_id=%s strategy=%s err=%s",
                    order_id,
                    strategy_id,
                    e,
                )
                phases["close_size_retry"]["error"] = str(e)

        if remaining <= 0 and not (spot_market_buy_uses_quote and spot_quote_amt > 0):
            friendly_error = self._friendly_order_error(
                "invalid amount",
                client=client,
                exchange_id=exchange_id,
                symbol=symbol,
                signal_type=signal_type,
                amount=amount,
                price=ref_price,
                payload=payload,
            )
            self._mark_failed(order_id=order_id, error=friendly_error)
            _notify_live_best_effort(status="failed", error=friendly_error, amount_hint=amount)
            if reduce_only:
                append_strategy_log(
                    strategy_id,
                    "error",
                    f"Order rejected: {friendly_error} for {symbol} {signal_type} "
                    f"(no position after sync; check exchange/DB alignment)",
                )
            else:
                append_strategy_log(
                    strategy_id,
                    "error",
                    f"Order rejected: {friendly_error} for {symbol} {signal_type}",
                )
            return

        limit_order_id = ""
        limit_client_oid = ""
        market_order_id = ""
        market_client_oid = make_client_order_id(
            exchange_id=exchange_id,
            strategy_id=strategy_id,
            order_id=order_id,
            phase="mkt",
        )
        try:
            limit_price = 0.0
            if execution_algo == "limit" or use_limit_first:
                explicit_limit_price = float(payload.get("limit_price") or 0.0)
                limit_price = explicit_limit_price or maker_limit_price(
                    ref_price=ref_price,
                    side=side,
                    maker_offset=maker_offset,
                )
                limit_client_oid = make_client_order_id(
                    exchange_id=exchange_id,
                    strategy_id=strategy_id,
                    order_id=order_id,
                    phase="lmt",
                )
            adapter = LiveOrderPhaseAdapter(
                client=client,
                exchange_id=exchange_id,
                payload=payload,
                exchange_config=exchange_config,
                order_mode=order_mode,
                ref_price=ref_price,
                spot_quote_amt=spot_quote_amt,
                spot_market_buy_uses_quote=spot_market_buy_uses_quote,
            )
            intent = OrderIntent(
                symbol=str(symbol),
                side=side,
                quantity=float(remaining or 0.0),
                market_type=market_type,
                price=float(limit_price or 0.0),
                pos_side=pos_side,
                reduce_only=reduce_only,
                client_order_id=market_client_oid,
                fallback_client_order_id=market_client_oid,
                leverage=leverage,
                margin_mode=str(payload.get("margin_mode") or payload.get("td_mode") or "cross"),
                exchange_config=exchange_config,
            )
            if execution_algo == "limit":
                intent = OrderIntent(
                    symbol=intent.symbol,
                    side=intent.side,
                    quantity=intent.quantity,
                    market_type=intent.market_type,
                    price=intent.price,
                    pos_side=intent.pos_side,
                    reduce_only=intent.reduce_only,
                    client_order_id=limit_client_oid,
                    fallback_client_order_id=market_client_oid,
                    leverage=intent.leverage,
                    margin_mode=intent.margin_mode,
                    exchange_config=intent.exchange_config,
                )
                execution_result = RestingLimitExecutor(adapter).execute(intent)
                limit_order_id = str(execution_result.exchange_order_id or "")
            elif use_limit_first:
                intent = OrderIntent(
                    symbol=intent.symbol,
                    side=intent.side,
                    quantity=intent.quantity,
                    market_type=intent.market_type,
                    price=intent.price,
                    pos_side=intent.pos_side,
                    reduce_only=intent.reduce_only,
                    client_order_id=limit_client_oid,
                    fallback_client_order_id=market_client_oid,
                    leverage=intent.leverage,
                    margin_mode=intent.margin_mode,
                    exchange_config=intent.exchange_config,
                )
                execution_result = LimitThenMarketExecutor(
                    adapter,
                    max_wait_sec=maker_wait_sec,
                    fallback_to_market=bool(
                        payload.get(
                            "close_fallback_to_market" if reduce_only else "open_fallback_to_market",
                            True,
                        )
                    ),
                ).execute(intent)
            else:
                execution_result = MarketOrderExecutor(adapter).execute(intent)
            phases["executor"] = execution_result.raw
            if not execution_result.success:
                friendly_error = self._friendly_order_error(
                    execution_result.error,
                    client=client,
                    exchange_id=exchange_id,
                    symbol=symbol,
                    signal_type=signal_type,
                    amount=amount,
                    price=ref_price,
                    payload=payload,
                )
                self._mark_failed(order_id=order_id, error=friendly_error)
                _console_print(f"[worker] order failed: strategy_id={strategy_id} pending_id={order_id} err={friendly_error}")
                _notify_live_best_effort(status="failed", error=friendly_error, amount_hint=amount, price_hint=ref_price)
                append_strategy_log(strategy_id, "error", f"Exchange order failed ({exchange_id} {symbol} {signal_type}): {friendly_error}")
                return
            fills.apply_fill(float(execution_result.filled_qty or 0.0), float(execution_result.avg_price or 0.0))
            if execution_algo != "limit":
                market_order_id = str(execution_result.exchange_order_id or "")
        except LiveTradingError as e:
            logger.warning(f"live executor failed: pending_id={order_id}, strategy_id={strategy_id}, cfg={safe_cfg}, err={e}")
            friendly_error = self._friendly_order_error(
                e,
                client=client,
                exchange_id=exchange_id,
                symbol=symbol,
                signal_type=signal_type,
                amount=amount,
                price=ref_price,
                payload=payload,
            )
            self._mark_failed(order_id=order_id, error=friendly_error)
            _console_print(f"[worker] order failed: strategy_id={strategy_id} pending_id={order_id} err={friendly_error}")
            _notify_live_best_effort(status="failed", error=friendly_error, amount_hint=amount, price_hint=ref_price)
            append_strategy_log(strategy_id, "error", f"Exchange order failed ({exchange_id} {symbol} {signal_type}): {friendly_error}")
            return
        except Exception as e:
            logger.warning(f"live executor unexpected error: pending_id={order_id}, strategy_id={strategy_id}, cfg={safe_cfg}, err={e}")
            self._mark_failed(order_id=order_id, error=str(e))
            _console_print(f"[worker] order unexpected error: strategy_id={strategy_id} pending_id={order_id} err={e}")
            _notify_live_best_effort(status="failed", error=str(e), amount_hint=amount, price_hint=ref_price)
            append_strategy_log(strategy_id, "error", f"Unexpected order error ({exchange_id} {symbol} {signal_type}): {e}")
            return

        # Build final result (best-effort); live path never fabricates fill qty from request amount.
        filled_final = float(fills.total_base or 0.0)
        avg_final = float(fills.avg_price() or 0.0)

        ex_oid_for_recovery = str(market_order_id or limit_order_id or "")
        coid_for_recovery = str(
            market_client_oid if market_order_id else (limit_client_oid if limit_order_id else "")
        )
        if filled_final <= 0 and ex_oid_for_recovery:
            from app.services.live_trading.fill_recovery import try_recover_zero_fill

            rec_filled, rec_avg, rec_src = try_recover_zero_fill(
                client,
                symbol=str(symbol),
                market_type=str(market_type or "swap"),
                exchange_config=exchange_config if isinstance(exchange_config, dict) else {},
                exchange_order_id=ex_oid_for_recovery,
                client_order_id=coid_for_recovery,
                requested_qty=float(amount or 0.0),
                signal_type=str(signal_type or ""),
                pos_side=str(pos_side or ""),
                pre_position_qty=float(pre_position_qty or 0.0),
                ref_price=float(ref_price or 0.0),
            )
            if rec_filled > 0:
                filled_final = rec_filled
                avg_final = rec_avg if rec_avg > 0 else float(ref_price or 0.0)
                phases["fill_recovery"] = {
                    "source": rec_src,
                    "filled": rec_filled,
                    "avg_price": avg_final,
                    "exchange_order_id": ex_oid_for_recovery,
                }
                append_strategy_log(
                    strategy_id,
                    "info",
                    f"Fill recovered ({rec_src}): {signal_type} {symbol} qty={rec_filled:.6f} @ ~{avg_final:.4f}",
                )

        res = type("Tmp", (), {"exchange_id": str(exchange_config.get("exchange_id") or ""), "exchange_order_id": str(market_order_id or limit_order_id), "raw": phases, "filled": filled_final, "avg_price": avg_final})()

        executed_at = int(time.time())
        filled = filled_final
        avg_price = avg_final
        post_query: Dict[str, Any] = phases

        # Persist queue result first (idempotency / observability).
        try:
            self._mark_sent(
                order_id=order_id,
                note="live_order_sent",
                exchange_id=res.exchange_id,
                exchange_order_id=res.exchange_order_id,
                exchange_response_json=json.dumps({"phases": (post_query or {})}, ensure_ascii=False),
                filled=filled,
                avg_price=avg_price,
                executed_at=executed_at if filled > 0 else None,
                final_filled=bool(amount > 0 and filled >= amount * 0.999999),
            )
            _console_print(f"[worker] order sent: strategy_id={strategy_id} pending_id={order_id} exchange={res.exchange_id} order_id={res.exchange_order_id} filled={filled} avg={avg_price}")
        except Exception as e:
            logger.warning(f"mark_sent failed: pending_id={order_id}, err={e}")

        # Record trade + update local position snapshot (best-effort).
        try:
            if filled > 0 and avg_price > 0:
                logger.info(
                    f"live record begin: pending_id={order_id} strategy_id={strategy_id} symbol={symbol} "
                    f"signal={signal_type} filled={filled} avg_price={avg_price} fee={fills.total_fee} fee_ccy={fills.fee_ccy}"
                )
                _close_reason = trade_close_reason_from_payload(payload, str(signal_type))
                profit, matched_entry = persist_strategy_fill(
                        strategy_id=int(strategy_id),
                        symbol=str(symbol),
                        signal_type=str(signal_type),
                        filled=float(filled),
                        avg_price=float(avg_price),
                        exchange_config=exchange_config,
                        market_type=str(market_type or "swap"),
                        order_id=int(order_id),
                        fill_source="worker",
                        commission=float(fills.total_fee or 0.0),
                        commission_ccy=str(fills.fee_ccy or "").strip().upper(),
                        close_reason=_close_reason,
                        strategy_run_id=int(payload.get("strategy_run_id") or order_row.get("strategy_run_id") or 0),
                        order_intent_id=int(payload.get("order_intent_id") or order_row.get("order_intent_id") or 0),
                        basket_id=str(payload.get("basket_id") or ""),
                        exchange_id=str(res.exchange_id or ""),
                        exchange_order_id=str(res.exchange_order_id or ""),
                        raw_fill=post_query or {},
                    )
                logger.info(f"live record done: pending_id={order_id} strategy_id={strategy_id} symbol={symbol} signal={signal_type}")
                _profit_str = f", profit={profit:.4f}" if profit is not None else ""
                _fee_str = f", fee={fills.total_fee:.6f} {fills.fee_ccy}" if fills.total_fee > 0 else ""
                _reason_parts = []
                _reason = str(payload.get("reason") or "").strip()
                if _reason:
                    _reason_parts.append(f"reason={_reason}")
                for _key, _label in (
                    ("stop_loss_price", "sl"),
                    ("take_profit_price", "tp"),
                    ("trailing_stop_price", "trail"),
                ):
                    try:
                        _v = float(payload.get(_key) or 0.0)
                    except Exception:
                        _v = 0.0
                    if _v > 0:
                        _reason_parts.append(f"{_label}={_v:.6f}")
                _reason_str = f", {', '.join(_reason_parts)}" if _reason_parts else ""
                append_strategy_log(
                    strategy_id, "trade",
                    f"Trade executed: {signal_type} {symbol} filled={filled:.6f} @ {avg_price:.6f}{_fee_str}{_profit_str}{_reason_str} (exchange={res.exchange_id})",
                )
        except Exception as e:
            logger.warning(f"record_trade/update_position failed: pending_id={order_id}, err={e}")

        # Notify live results (best-effort; does not affect execution).
        _notify_live_best_effort(
            status="sent",
            exchange_id=res.exchange_id,
            exchange_order_id=res.exchange_order_id,
            price_hint=avg_price if avg_price > 0 else ref_price,
            amount_hint=filled if filled > 0 else amount,
        )

    def _execute_ibkr_order(
        self,
        *,
        order_id: int,
        order_row: Dict[str, Any],
        payload: Dict[str, Any],
        client,  # IBKRClient instance
        strategy_id: int,
        exchange_config: Dict[str, Any],
        _notify_live_best_effort,
        _console_print,
    ) -> None:
        """
        Execute order via Interactive Brokers for US stocks.

        Simplified flow compared to crypto (no maker->market fallback):
        - Place market order directly
        - Wait for fill
        - Record trade
        """
        signal_type = payload.get("signal_type") or order_row.get("signal_type")
        symbol = payload.get("symbol") or order_row.get("symbol")
        amount = float(payload.get("amount") or order_row.get("amount") or 0.0)
        ref_price = float(payload.get("ref_price") or payload.get("price") or order_row.get("price") or 0.0)

        sig = str(signal_type or "").strip().lower()

        # Stocks: no short selling in basic implementation
        if "short" in sig:
            self._mark_failed(order_id=order_id, error="ibkr_stock_short_not_supported")
            _console_print(f"[worker] IBKR order rejected: strategy_id={strategy_id} pending_id={order_id} short not supported")
            _notify_live_best_effort(status="failed", error="ibkr_stock_short_not_supported")
            return

        # Map signal to action (include stop/tp/trailing aliases)
        if sig in ("open_long", "add_long"):
            action = "buy"
        elif sig in ("close_long", "reduce_long", "close_long_stop", "close_long_profit", "close_long_trailing"):
            action = "sell"
        else:
            self._mark_failed(order_id=order_id, error=f"ibkr_unsupported_signal:{signal_type}")
            _console_print(f"[worker] IBKR order rejected: strategy_id={strategy_id} pending_id={order_id} unsupported signal {signal_type}")
            _notify_live_best_effort(status="failed", error=f"ibkr_unsupported_signal:{signal_type}")
            return

        # Get market type (USStock)
        market_type = str(
            payload.get("market_type") or
            payload.get("market_category") or
            exchange_config.get("market_type") or
            exchange_config.get("market_category") or
            "USStock"
        ).strip()

        try:
            # Place market order via IBKR
            result = client.place_market_order(
                symbol=symbol,
                side=action,
                quantity=amount,
                market_type=market_type,
            )

            if not result.success:
                self._mark_failed(order_id=order_id, error=f"ibkr_order_failed:{result.message}")
                _console_print(f"[worker] IBKR order failed: strategy_id={strategy_id} pending_id={order_id} err={result.message}")
                _notify_live_best_effort(status="failed", error=f"ibkr_order_failed:{result.message}")
                append_strategy_log(strategy_id, "error", f"IBKR order failed ({symbol} {signal_type}): {result.message}")
                return

            filled = float(result.filled or 0.0)
            avg_price = float(result.avg_price or 0.0)
            exchange_order_id = str(result.order_id or "")

            executed_at = int(time.time())

            # Mark order as sent
            self._mark_sent(
                order_id=order_id,
                note="ibkr_order_sent",
                exchange_id="ibkr",
                exchange_order_id=exchange_order_id,
                exchange_response_json=json.dumps(result.raw or {}, ensure_ascii=False),
                filled=filled,
                avg_price=avg_price,
                executed_at=executed_at if filled > 0 else None,
                final_filled=bool(amount > 0 and filled >= amount * 0.999999 and avg_price > 0),
            )
            _console_print(f"[worker] IBKR order sent: strategy_id={strategy_id} pending_id={order_id} order_id={exchange_order_id} filled={filled} avg={avg_price}")

            # Record trade and update position
            try:
                if filled > 0 and avg_price > 0:
                    logger.info(
                        f"IBKR record begin: pending_id={order_id} strategy_id={strategy_id} symbol={symbol} "
                        f"signal={signal_type} filled={filled} avg_price={avg_price}"
                    )
                    profit, matched_entry = persist_strategy_fill(
                        strategy_id=int(strategy_id),
                        symbol=str(symbol),
                        signal_type=str(signal_type),
                        filled=float(filled),
                        avg_price=float(avg_price),
                        exchange_config=exchange_config,
                        market_type=str(market_type or "USStock"),
                        order_id=int(order_id),
                        fill_source="worker_ibkr",
                        close_reason=trade_close_reason_from_payload(payload, str(signal_type)),
                        strategy_run_id=int(payload.get("strategy_run_id") or order_row.get("strategy_run_id") or 0),
                        order_intent_id=int(payload.get("order_intent_id") or order_row.get("order_intent_id") or 0),
                        basket_id=str(payload.get("basket_id") or ""),
                        exchange_id="ibkr",
                        exchange_order_id=str(exchange_order_id or ""),
                        raw_fill=result.raw or {},
                    )
                    logger.info(f"IBKR record done: pending_id={order_id} strategy_id={strategy_id} symbol={symbol}")
                    _pstr = f", profit={profit:.4f}" if profit is not None else ""
                    append_strategy_log(
                        strategy_id, "trade",
                        f"Trade executed: {signal_type} {symbol} filled={filled:.6f} @ {avg_price:.6f}{_pstr} (exchange=ibkr)",
                    )
            except Exception as e:
                logger.warning(f"IBKR record_trade/update_position failed: pending_id={order_id}, err={e}")

            # Notify success
            _notify_live_best_effort(
                status="sent",
                exchange_id="ibkr",
                exchange_order_id=exchange_order_id,
                price_hint=avg_price,
                amount_hint=filled,
            )

        except Exception as e:
            logger.error(f"IBKR order execution failed: pending_id={order_id}, strategy_id={strategy_id}, err={e}")
            self._mark_failed(order_id=order_id, error=f"ibkr_exception:{e}")
            _console_print(f"[worker] IBKR order exception: strategy_id={strategy_id} pending_id={order_id} err={e}")
            _notify_live_best_effort(status="failed", error=str(e))
            append_strategy_log(strategy_id, "error", f"IBKR order exception ({symbol} {signal_type}): {e}")
            if is_fatal_exchange_error(str(e)):
                auto_stop_live_strategy(int(strategy_id), str(e), source="ibkr_order")

    def _execute_alpaca_order(
        self,
        *,
        order_id: int,
        order_row: Dict[str, Any],
        payload: Dict[str, Any],
        client,  # AlpacaClient instance
        strategy_id: int,
        exchange_config: Dict[str, Any],
        market_category: str,
        _notify_live_best_effort,
        _console_print,
    ) -> None:
        """
        Execute order via Alpaca for US stocks (USStock) or crypto.

        Mirrors `_execute_ibkr_order`: market order, brief poll for fill,
        record trade, mark sent. Long-only; short signals are rejected.
        """
        signal_type = payload.get("signal_type") or order_row.get("signal_type")
        symbol = payload.get("symbol") or order_row.get("symbol")
        amount = float(payload.get("amount") or order_row.get("amount") or 0.0)
        ref_price = float(payload.get("ref_price") or payload.get("price") or order_row.get("price") or 0.0)

        sig = str(signal_type or "").strip().lower()

        if "short" in sig:
            self._mark_failed(order_id=order_id, error="alpaca_short_not_supported")
            _console_print(f"[worker] Alpaca order rejected: strategy_id={strategy_id} pending_id={order_id} short not supported")
            _notify_live_best_effort(status="failed", error="alpaca_short_not_supported")
            return

        if sig in ("open_long", "add_long"):
            action = "buy"
        elif sig in ("close_long", "reduce_long", "close_long_stop", "close_long_profit", "close_long_trailing"):
            action = "sell"
        else:
            self._mark_failed(order_id=order_id, error=f"alpaca_unsupported_signal:{signal_type}")
            _console_print(f"[worker] Alpaca order rejected: strategy_id={strategy_id} pending_id={order_id} unsupported signal {signal_type}")
            _notify_live_best_effort(status="failed", error=f"alpaca_unsupported_signal:{signal_type}")
            return

        # Decide stock vs crypto leg of the Alpaca account based on the
        # strategy's market_category (USStock by default).
        mc = (market_category or "USStock").strip()
        market_type_for_client = "crypto" if mc.lower() in ("crypto", "cryptocurrency") else "USStock"

        try:
            result = client.place_market_order(
                symbol=symbol,
                side=action,
                quantity=amount,
                market_type=market_type_for_client,
            )

            if not result.success:
                self._mark_failed(order_id=order_id, error=f"alpaca_order_failed:{result.message}")
                _console_print(f"[worker] Alpaca order failed: strategy_id={strategy_id} pending_id={order_id} err={result.message}")
                _notify_live_best_effort(status="failed", error=f"alpaca_order_failed:{result.message}")
                append_strategy_log(strategy_id, "error", f"Alpaca order failed ({symbol} {signal_type}): {result.message}")
                return

            filled = float(result.filled or 0.0)
            avg_price = float(result.avg_price or 0.0)
            exchange_order_id = str(result.order_id or "")

            if avg_price <= 0 and ref_price > 0:
                if filled > 0:
                    logger.warning(
                        f"[worker] Alpaca order avg_price=0, using ref_price={ref_price} as fallback: "
                        f"strategy_id={strategy_id} pending_id={order_id}"
                    )
                    avg_price = ref_price
                else:
                    logger.info(
                        f"[worker] Alpaca order submitted but not filled yet: "
                        f"strategy_id={strategy_id} pending_id={order_id} status={result.status}"
                    )

            executed_at = int(time.time())

            self._mark_sent(
                order_id=order_id,
                note="alpaca_order_sent",
                exchange_id="alpaca",
                exchange_order_id=exchange_order_id,
                exchange_response_json=json.dumps(result.raw or {}, ensure_ascii=False),
                filled=filled,
                avg_price=avg_price,
                executed_at=executed_at if filled > 0 else None,
                final_filled=bool(amount > 0 and filled >= amount * 0.999999 and avg_price > 0),
            )
            _console_print(
                f"[worker] Alpaca order sent: strategy_id={strategy_id} pending_id={order_id} "
                f"order_id={exchange_order_id} filled={filled} avg={avg_price}"
            )

            try:
                if filled > 0 and avg_price > 0:
                    profit, matched_entry = persist_strategy_fill(
                        strategy_id=int(strategy_id),
                        symbol=str(symbol),
                        signal_type=str(signal_type),
                        filled=float(filled),
                        avg_price=float(avg_price),
                        exchange_config=exchange_config,
                        market_type=str(market_type_for_client or "USStock"),
                        order_id=int(order_id),
                        fill_source="worker_alpaca",
                        close_reason=trade_close_reason_from_payload(payload, str(signal_type)),
                        strategy_run_id=int(payload.get("strategy_run_id") or order_row.get("strategy_run_id") or 0),
                        order_intent_id=int(payload.get("order_intent_id") or order_row.get("order_intent_id") or 0),
                        basket_id=str(payload.get("basket_id") or ""),
                        exchange_id="alpaca",
                        exchange_order_id=str(exchange_order_id or ""),
                        raw_fill=result.raw or {},
                    )
                    logger.info(f"Alpaca record done: pending_id={order_id} strategy_id={strategy_id} symbol={symbol}")
                    _pstr = f", profit={profit:.4f}" if profit is not None else ""
                    append_strategy_log(
                        strategy_id, "trade",
                        f"Trade executed: {signal_type} {symbol} filled={filled:.6f} @ {avg_price:.6f}{_pstr} (exchange=alpaca)",
                    )
                else:
                    append_strategy_log(
                        strategy_id, "info",
                        f"Alpaca order submitted: {signal_type} {symbol} status={result.status or 'submitted'}, awaiting fill",
                    )
            except Exception as e:
                logger.warning(f"Alpaca record_trade/update_position failed: pending_id={order_id}, err={e}")

            _notify_live_best_effort(
                status="sent",
                exchange_id="alpaca",
                exchange_order_id=exchange_order_id,
                price_hint=avg_price,
                amount_hint=filled,
            )

        except Exception as e:
            logger.error(f"Alpaca order execution failed: pending_id={order_id}, strategy_id={strategy_id}, err={e}")
            self._mark_failed(order_id=order_id, error=f"alpaca_exception:{e}")
            _console_print(f"[worker] Alpaca order exception: strategy_id={strategy_id} pending_id={order_id} err={e}")
            _notify_live_best_effort(status="failed", error=str(e))
            append_strategy_log(strategy_id, "error", f"Alpaca order exception ({symbol} {signal_type}): {e}")

    def _mark_sent(
        self,
        order_id: int,
        note: str = "",
        exchange_id: str = "",
        exchange_order_id: str = "",
        exchange_response_json: str = "",
        filled: float = 0.0,
        avg_price: float = 0.0,
        executed_at: Optional[int] = None,
        final_filled: bool = False,
    ) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            # Use NOW() for timestamp fields; executed_at is set to NOW() if provided, else NULL
            cur.execute(
                """
                UPDATE pending_orders
                SET status = CASE WHEN %s THEN 'filled' ELSE 'sent' END,
                    last_error = %s,
                    dispatch_note = %s,
                    sent_at = NOW(),
                    executed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                    exchange_id = %s,
                    exchange_order_id = %s,
                    exchange_response_json = %s,
                    filled = %s,
                    avg_price = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    bool(final_filled),
                    "",
                    str(note or ""),
                    executed_at is not None,  # Boolean flag for CASE WHEN
                    str(exchange_id or ""),
                    str(exchange_order_id or ""),
                    str(exchange_response_json or ""),
                    float(filled or 0.0),
                    float(avg_price or 0.0),
                    int(order_id),
                ),
            )
            cur.execute(
                """
                UPDATE strategy_order_intents soi
                SET status = CASE
                        WHEN %s THEN 'filled'
                        WHEN %s > 0 THEN 'partially_filled'
                        ELSE 'submitted'
                    END,
                    exchange_order_id = COALESCE(NULLIF(po.exchange_order_id, ''), soi.exchange_order_id),
                    updated_at = NOW()
                FROM pending_orders po
                WHERE po.id = %s
                  AND po.order_intent_id = soi.id
                """,
                (bool(final_filled), float(filled or 0.0), int(order_id)),
            )
            db.commit()
            cur.close()

    def _mark_failed(self, order_id: int, error: str) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE pending_orders
                SET status = 'failed',
                    last_error = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (str(error or "failed"), int(order_id)),
            )
            cur.execute(
                """
                UPDATE strategy_order_intents soi
                SET status = 'rejected',
                    updated_at = NOW()
                FROM pending_orders po
                WHERE po.id = %s
                  AND po.order_intent_id = soi.id
                """,
                (int(order_id),),
            )
            db.commit()
            cur.close()

    def _mark_deferred(self, order_id: int, reason: str) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE pending_orders
                SET status = 'deferred',
                    last_error = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (str(reason or "deferred"), int(order_id)),
            )
            db.commit()
            cur.close()
