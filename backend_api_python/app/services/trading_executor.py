"""Live trading executor service."""
import time
import threading
import traceback
import os
import re
try:
    import resource  # Linux/Unix only
except Exception:
    resource = None
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import json
import pandas as pd
import numpy as np

from app.utils.logger import get_logger
from app.utils.db import get_db_connection
from app.utils.strategy_runtime_logs import append_strategy_log
from app.utils.risk_guard import DEFAULT_TAKER_FEE_RATE, trailing_exit_locks_net_profit
from app.data_sources import DataSourceFactory, UnsupportedMarketError
from app.services.kline import KlineService
from app.services.indicator_params import StrategyConfigParser
from app.services.strategy_warmup import (
    live_warmup_status,
    required_live_history_limit,
)
from app.services.strategy_contract import resolve_script_strategy_contract
from app.services.trading_execution_modes import (
    coerce_bool,
    kline_boundary_poll_offset_sec,
    next_kline_boundary_poll_ts as compute_next_kline_boundary_poll_ts,
    normalize_trading_execution_modes as normalize_execution_modes,
)
from app.services.strategy_script_runtime import (
    ScriptBar,
    StrategyScriptContext,
    compile_strategy_script_handlers,
)
from app.utils.safe_exec import TimeoutError as SafeExecTimeoutError, timeout_context

logger = get_logger(__name__)


class ScriptCallbackTimeout(RuntimeError):
    """Raised when user script callbacks exceed the live runtime budget."""

    pass


def _coerce_bool(value: Any, default: bool = False) -> bool:
    return coerce_bool(value, default)


def _kline_boundary_poll_offset_sec() -> float:
    return kline_boundary_poll_offset_sec()


def next_kline_boundary_poll_ts(
    now_ts: float,
    timeframe_seconds: int,
    offset_sec: Optional[float] = None,
) -> float:
    return compute_next_kline_boundary_poll_ts(now_ts, timeframe_seconds, offset_sec)


def normalize_trading_execution_modes(trading_config: Optional[Dict[str, Any]]) -> None:
    normalize_execution_modes(trading_config)


class TradingExecutor:
    """Live trading executor in signal-provider mode."""
    
    def __init__(self):
        self.running_strategies = {}  # {strategy_id: thread}
        self.lock = threading.Lock()
        # Local-only lightweight in-memory price cache (symbol -> (price, expiry_ts)).
        # This replaces the old Redis-based PriceCache for local deployments.
        self._price_cache = {}
        self._price_cache_lock = threading.Lock()
        # Default to 10s to match the unified tick cadence.
        self._price_cache_ttl_sec = int(os.getenv("PRICE_CACHE_TTL_SEC", "10"))

        # In-memory signal de-dup cache to prevent repeated orders on the same candle signal.
        # Keyed by (strategy_id, symbol, signal_type, signal_timestamp).
        self._signal_dedup = {}  # type: Dict[int, Dict[str, float]]
        self._signal_dedup_lock = threading.Lock()
        self.kline_service = KlineService()
        self._console_tick_last_ts: Dict[int, float] = {}
        self._console_tick_lock = threading.Lock()
        self._runtime_heartbeat_last_ts: Dict[int, float] = {}
        self._runtime_heartbeat_lock = threading.Lock()
        try:
            self._console_tick_interval_sec = max(1, int(os.getenv("STRATEGY_TICK_LOG_INTERVAL_SEC", "60")))
        except Exception:
            self._console_tick_interval_sec = 60
        
        self.max_threads = int(os.getenv('STRATEGY_MAX_THREADS', '64'))
        try:
            self.script_callback_timeout_sec = max(1, int(os.getenv("STRATEGY_SCRIPT_CALLBACK_TIMEOUT_SEC", "5")))
        except Exception:
            self.script_callback_timeout_sec = 5
        try:
            self.script_max_consecutive_timeouts = max(1, int(os.getenv("STRATEGY_SCRIPT_MAX_CONSECUTIVE_TIMEOUTS", "3")))
        except Exception:
            self.script_max_consecutive_timeouts = 3
        self._last_start_failure: str = ""
        self._last_exit_reason: Dict[int, str] = {}

        # Per-strategy exchange fee-rate cache: {strategy_id: {"maker": float, "taker": float}}
        self._exchange_fee_cache: Dict[int, Optional[Dict[str, float]]] = {}
        self._exchange_fee_cache_lock = threading.Lock()
        
        self._ensure_db_columns()

    def _run_script_callback_with_timeout(self, strategy_id: int, phase: str, callback, *args):
        """Run user script callbacks with a live-loop timeout budget."""
        timeout_sec = int(getattr(self, "script_callback_timeout_sec", 5) or 5)
        try:
            with timeout_context(timeout_sec):
                return callback(*args)
        except SafeExecTimeoutError as exc:
            message = f"Script {phase} timed out after {timeout_sec}s"
            logger.error("Strategy %s %s", strategy_id, message)
            try:
                append_strategy_log(strategy_id, "error", message)
            except Exception:
                pass
            raise ScriptCallbackTimeout(message) from exc

    def _ensure_db_columns(self):
        """Ensure required PostgreSQL columns exist."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                col_names = set()

                try:
                    cursor.execute("""
                        SELECT column_name FROM information_schema.columns 
                        WHERE table_name = 'qd_strategy_positions'
                    """)
                    cols = cursor.fetchall() or []
                    col_names = {c.get('column_name') or c.get('COLUMN_NAME') for c in cols if isinstance(c, dict)}
                except Exception:
                    col_names = set()

                if 'highest_price' not in col_names:
                    logger.info("Adding highest_price column to qd_strategy_positions...")
                    cursor.execute("ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS highest_price DOUBLE PRECISION DEFAULT 0")
                    db.commit()
                    logger.info("highest_price column added")

                if 'lowest_price' not in col_names:
                    logger.info("Adding lowest_price column to qd_strategy_positions...")
                    cursor.execute("ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS lowest_price DOUBLE PRECISION DEFAULT 0")
                    db.commit()
                    logger.info("lowest_price column added")

                trade_col_names = set()
                try:
                    cursor.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'qd_strategy_trades'
                    """)
                    trade_cols = cursor.fetchall() or []
                    trade_col_names = {c.get('column_name') or c.get('COLUMN_NAME') for c in trade_cols if isinstance(c, dict)}
                except Exception:
                    trade_col_names = set()

                if 'close_reason' not in trade_col_names:
                    logger.info("Adding close_reason column to qd_strategy_trades...")
                    cursor.execute(
                        "ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS close_reason VARCHAR(64) DEFAULT ''"
                    )
                    db.commit()
                    logger.info("close_reason column added")

                cursor.close()
        except Exception as e:
            logger.error(f"Failed to check/ensure DB columns: {str(e)}")
        try:
            from app.services.live_trading.records import ensure_position_ledger_schema

            ensure_position_ledger_schema()
        except Exception as e:
            logger.warning("ensure_position_ledger_schema failed: %s", e)
        try:
            from app.services.strategy_runtime.schema import ensure_strategy_runtime_schema

            ensure_strategy_runtime_schema()
        except Exception as e:
            logger.warning("ensure_strategy_runtime_schema failed: %s", e)

    def _log_resource_status(self, prefix: str = ""):
        """Log process resource usage when strategy threads fail to start."""
        try:
            import psutil
            p = psutil.Process()
            mem = p.memory_info().rss / 1024 / 1024
            th = p.num_threads()
            logger.warning(f"{prefix}resource status: memory={mem:.1f}MB, threads={th}, "
                           f"running_strategies={len(self.running_strategies)}")
        except Exception:
            try:
                th = threading.active_count()
                vmrss = None
                try:
                    with open('/proc/self/status') as f:
                        for line in f:
                            if line.startswith('VmRSS:'):
                                vmrss = line.split()[1:3]  # e.g. ['123456', 'kB']
                                break
                except Exception:
                    pass
                vmrss_str = f"{vmrss[0]}{vmrss[1]}" if vmrss else "N/A"
                logger.warning(f"{prefix}resource status: VmRSS={vmrss_str}, active_threads={th}, "
                               f"running_strategies={len(self.running_strategies)}")
            except Exception:
                pass

    def _console_print(self, msg: str) -> None:
        """
        Local-only observability: print to stdout so user can see strategy status in console.
        """
        try:
            text = str(msg or "")
            if "] tick price=" in text:
                m = re.match(r"\[strategy:(\d+)\]\s+tick\b", text)
                if m:
                    sid = int(m.group(1))
                    now = time.monotonic()
                    with self._console_tick_lock:
                        last = self._console_tick_last_ts.get(sid, 0.0)
                        if last > 0 and now - last < self._console_tick_interval_sec:
                            return
                        self._console_tick_last_ts[sid] = now
            print(text, flush=True)
        except Exception:
            pass
    def _record_runtime_heartbeat(
        self,
        *,
        strategy_id: int,
        strategy_run_id: int,
        symbol: str,
        price: float,
        pending_signal_count: int,
        status: str = "healthy",
        last_error: str = "",
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        with self._runtime_heartbeat_lock:
            last = float(self._runtime_heartbeat_last_ts.get(int(strategy_id), 0.0) or 0.0)
            if not force and last > 0 and now - last < 30.0:
                return
            self._runtime_heartbeat_last_ts[int(strategy_id)] = now
        try:
            from app.services.strategy_runtime.health import record_runtime_heartbeat

            record_runtime_heartbeat(
                strategy_id=int(strategy_id),
                strategy_run_id=int(strategy_run_id or 0),
                symbol=str(symbol or ""),
                price=float(price or 0.0),
                pending_signal_count=int(pending_signal_count or 0),
                status=str(status or "healthy"),
                last_error=str(last_error or ""),
            )
        except Exception as exc:
            logger.debug("runtime heartbeat skipped: %s", exc)

    def _position_state(self, positions: List[Dict[str, Any]]) -> str:
        """
        Return current position state for a strategy+symbol in local single-position mode.

        Returns: 'flat' | 'long' | 'short'
        """
        try:
            if not positions:
                return "flat"
            # Local mode assumes single-direction position per symbol.
            side = (positions[0].get("side") or "").strip().lower()
            if side in ("long", "short"):
                return side
        except Exception:
            pass
        return "flat"

    @staticmethod
    def _symbol_match_key(symbol: str) -> str:
        return str(symbol or "").split(":")[0].strip()

    def _inflight_open_side(self, strategy_id: int, symbol: str) -> Optional[str]:
        """
        Return 'long' or 'short' when an open_* order is pending/processing for
        this strategy+symbol, else None.
        """
        sym_key = self._symbol_match_key(symbol)
        if not sym_key:
            return None
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    SELECT signal_type, symbol
                    FROM pending_orders
                    WHERE strategy_id = %s
                      AND status IN ('pending', 'processing')
                      AND signal_type IN ('open_long', 'open_short')
                    ORDER BY id DESC
                    LIMIT 20
                    """,
                    (int(strategy_id),),
                )
                rows = cur.fetchall() or []
                cur.close()
            for row in rows:
                row_sym = self._symbol_match_key(str(row.get("symbol") or ""))
                if row_sym != sym_key:
                    continue
                sig = str(row.get("signal_type") or "").strip().lower()
                if sig == "open_long":
                    return "long"
                if sig == "open_short":
                    return "short"
        except Exception as e:
            logger.debug("inflight open lookup failed sid=%s: %s", strategy_id, e)
        return None

    def _effective_position_state(
        self,
        strategy_id: int,
        symbol: str,
        positions: List[Dict[str, Any]],
    ) -> str:
        """Local DB state plus in-flight open orders (live dedup guard)."""
        state = self._position_state(positions)
        if state != "flat":
            return state
        inflight = self._inflight_open_side(strategy_id, symbol)
        return inflight or "flat"

    @staticmethod
    def _is_live_script_hydrate_candidate(trading_config: Optional[Dict[str, Any]]) -> bool:
        tc = trading_config if isinstance(trading_config, dict) else {}
        if str(tc.get("execution_mode") or "live").strip().lower() != "live":
            return False
        bot_type = str(tc.get("bot_type") or "").strip().lower()
        if bot_type == "grid":
            return True
        is_bot_script = bool(
            bot_type in ("martingale", "dca")
            or tc.get("strategy_mode") == "bot"
        )
        return not is_bot_script

    def _is_signal_allowed(
        self,
        state: str,
        signal_type: str,
    ) -> bool:
        """
        Enforce strict state machine:
        - flat: only open_long/open_short
        - long: only add_long/close_long
        - short: only add_short/close_short

        Explicit four-way indicator and script signals may flip by first closing the
        opposing leg, then opening the requested side.
        """
        st = (state or "flat").strip().lower()
        sig = (signal_type or "").strip().lower()
        if st == "flat":
            return sig in ("open_long", "open_short")
        if st == "long":
            return sig in ("add_long", "reduce_long", "close_long")
        if st == "short":
            return sig in ("add_short", "reduce_short", "close_short")
        return False

    def _signal_priority(self, signal_type: str) -> int:
        """
        Lower value = higher priority. We always close before (re)opening/adding.
        """
        sig = (signal_type or "").strip().lower()
        if sig.startswith("close_"):
            return 0
        if sig.startswith("reduce_"):
            return 1
        if sig.startswith("open_"):
            return 2
        if sig.startswith("add_"):
            return 3
        return 99

    def _dedup_key(self, strategy_id: int, symbol: str, signal_type: str, signal_ts: int) -> str:
        sym = (symbol or "").strip().upper()
        if ":" in sym:
            sym = sym.split(":", 1)[0]
        return f"{int(strategy_id)}|{sym}|{(signal_type or '').strip().lower()}|{int(signal_ts or 0)}"

    def _should_skip_signal_once_per_candle(
        self,
        strategy_id: int,
        symbol: str,
        signal_type: str,
        signal_ts: int,
        timeframe_seconds: int,
        now_ts: Optional[int] = None,
    ) -> bool:
        """
        Prevent repeated orders for the same candle signal across ticks.

        This is especially important for 'confirmed' signals that point to the previous closed candle:
        the signal timestamp stays constant for the entire next candle, so without de-dup the system
        would re-enqueue the same order every tick.
        """
        try:
            now = int(now_ts or time.time())
            tf = int(timeframe_seconds or 0)
            if tf <= 0:
                tf = 60
            # Keep keys long enough to cover at least the next candle.
            ttl_sec = max(tf * 2, 120)
            expiry = float(now + ttl_sec)
            key = self._dedup_key(strategy_id, symbol, signal_type, int(signal_ts or 0))

            with self._signal_dedup_lock:
                bucket = self._signal_dedup.get(int(strategy_id))
                if bucket is None:
                    bucket = {}
                    self._signal_dedup[int(strategy_id)] = bucket

                # Opportunistic cleanup
                stale = [k for k, exp in bucket.items() if float(exp) <= now]
                for k in stale[:512]:
                    try:
                        del bucket[k]
                    except Exception:
                        pass

                exp = bucket.get(key)
                if exp is not None and float(exp) > now:
                    return True

                # Reserve the key (best-effort). Caller may still fail to enqueue; that's acceptable
                # because repeated failures should not flood the queue.
                bucket[key] = expiry
                return False
        except Exception:
            return False

    def _to_ratio(self, v: Any, default: float = 0.0) -> float:
        """
        Convert a stored percent value into ratio in [0, 1].

        Convention (single source of truth): ``trading_config.*_pct`` fields
        store percent (e.g. ``9`` means 9%, ``0.01`` means 0.01%). This is
        the same unit the snapshot resolver and the bot wizard already
        produce.

        promoted sub-1% inputs (0.01, 0.5, etc.) to ratio interpretation
        (1%, 50%), which broke strategies needing < 1% SL / TP and was
        the only place left in the system that did that guessing.
        """
        try:
            x = float(v if v is not None else default)
        except Exception:
            x = float(default or 0.0)
        if x < 0:
            return 0.0
        x = x / 100.0
        if x > 1.0:
            return 1.0
        return float(x)

    def _code_strategy_cfg(self, trading_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        tc = trading_config if isinstance(trading_config, dict) else {}
        code_cfg = tc.get("_strategy_cfg_from_code")
        return code_cfg if isinstance(code_cfg, dict) else {}

    def _exit_owner_from_trading_config(self, trading_config: Optional[Dict[str, Any]]) -> str:
        tc = trading_config if isinstance(trading_config, dict) else {}
        code_cfg = self._code_strategy_cfg(tc)
        owner = (
            code_cfg.get("exitOwner")
            or code_cfg.get("exit_owner")
            or tc.get("exit_owner")
            or tc.get("exitOwner")
            or ""
        )
        return str(owner or "").strip().lower()

    def _strategy_owns_exits(self, trading_config: Optional[Dict[str, Any]]) -> bool:
        return self._exit_owner_from_trading_config(trading_config) == "indicator"

    def _risk_params_from_trading_config(self, trading_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Resolve risk/position ratios for live execution.
        Risk controls are code-owned: live execution never reads runtime
        stop/take/trailing fields from the strategy row.
        """
        code_cfg = self._code_strategy_cfg(trading_config)
        if code_cfg and ("risk" in code_cfg or "position" in code_cfg):
            risk = code_cfg.get("risk") or {}
            trailing = risk.get("trailing") or {}
            pos = code_cfg.get("position") or {}
            return {
                "entry_ratio": float(
                    pos.get("entryPct")
                    if pos.get("entryPct") is not None
                    else StrategyConfigParser.normalize_entry_ratio(None)
                ),
                "stop_loss_ratio": float(risk.get("stopLossPct") or 0),
                "take_profit_ratio": float(risk.get("takeProfitPct") or 0),
                "trailing_enabled": bool(trailing.get("enabled")),
                "trailing_stop_ratio": float(trailing.get("pct") or 0),
                "trailing_activation_ratio": float(trailing.get("activationPct") or 0),
            }

        return {
            "entry_ratio": StrategyConfigParser.normalize_entry_ratio(None),
            "stop_loss_ratio": 0.0,
            "take_profit_ratio": 0.0,
            "trailing_enabled": False,
            "trailing_stop_ratio": 0.0,
            "trailing_activation_ratio": 0.0,
        }

    def start_strategy(self, strategy_id: int) -> bool:
        """Start a strategy worker thread."""
        try:
            with self.lock:
                self._last_start_failure = ""
                stale_ids = [sid for sid, th in self.running_strategies.items() if not th.is_alive()]
                for sid in stale_ids:
                    del self.running_strategies[sid]

                if len(self.running_strategies) >= self.max_threads:
                    n = len(self.running_strategies)
                    self._last_start_failure = (
                        f"Thread limit reached ({self.max_threads}); running={n}. "
                        "Reduce running strategies or increase STRATEGY_MAX_THREADS."
                    )
                    logger.error(
                        f"Thread limit reached ({self.max_threads}); refuse to start strategy {strategy_id}. "
                        f"Reduce running strategies or increase STRATEGY_MAX_THREADS."
                    )
                    self._log_resource_status(prefix="start_denied: ")
                    return False

                if strategy_id in self.running_strategies:
                    self._last_start_failure = "Strategy is already running."
                    logger.warning(f"Strategy {strategy_id} is already running")
                    return False
                
                thread = threading.Thread(
                    target=self._run_strategy_loop,
                    args=(strategy_id,),
                    daemon=True
                )
                try:
                    thread.start()
                except Exception as e:
                    self._last_start_failure = f"Failed to start strategy thread: {e}"
                    self._log_resource_status(prefix="thread_start_failed: ")
                    raise e
                self.running_strategies[strategy_id] = thread
                
                logger.info(f"Strategy {strategy_id} started")
                self._console_print(f"[strategy:{strategy_id}] started")
                append_strategy_log(strategy_id, "info", "Strategy execution thread started")
                return True
                
        except Exception as e:
            self._last_start_failure = self._last_start_failure or f"Failed to start strategy: {e}"
            logger.error(f"Failed to start strategy {strategy_id}: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def _fetch_recent_strategy_log_hint(self, strategy_id: int) -> str:
        """Best-effort: read recent runtime log for start-failure diagnosis."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    SELECT message FROM qd_strategy_logs
                    WHERE strategy_id = %s
                    ORDER BY timestamp DESC, id DESC
                    LIMIT 8
                    """,
                    (int(strategy_id),),
                )
                rows = cur.fetchall() or []
                cur.close()
            skip = {
                "strategy execution thread started",
                "strategy execution loop exited",
            }
            for row in rows:
                msg = str((row or {}).get("message") or "").strip()
                if not msg:
                    continue
                low = msg.lower()
                if low in skip:
                    continue
                if "auto-stopped:" in low:
                    return msg.split(":", 1)[-1].strip()[:500]
                return msg[:500]
        except Exception:
            pass
        return ""

    def wait_strategy_running(self, strategy_id: int, timeout: float = 3.0) -> Tuple[bool, str]:
        """
        Poll briefly after start_strategy() to catch threads that exit during init.
        Returns (still_running, hint_if_not).
        """
        sid = int(strategy_id)
        deadline = time.monotonic() + max(0.5, float(timeout))
        while time.monotonic() < deadline:
            with self.lock:
                th = self.running_strategies.get(sid)
                alive = th is not None and th.is_alive()
            if not alive:
                reason = (self._last_exit_reason.pop(sid, None) or "").strip()
                if not reason:
                    reason = self._fetch_recent_strategy_log_hint(sid)
                return False, reason or (
                    "Execution thread exited. Common causes: empty strategy script/indicator, "
                    "K-line fetch failure, or live trading is not supported for this type."
                )
            time.sleep(0.25)
        with self.lock:
            th = self.running_strategies.get(sid)
            alive = th is not None and th.is_alive()
        if alive:
            return True, ""
        reason = (self._last_exit_reason.pop(sid, None) or "").strip()
        if not reason:
            reason = self._fetch_recent_strategy_log_hint(sid)
        return False, reason or "Execution thread exited before it reported running."
    
    def stop_strategy(self, strategy_id: int, *, persist_status: bool = True) -> bool:
        """Stop a strategy worker thread."""
        try:
            with self.lock:
                had_thread = strategy_id in self.running_strategies

                if persist_status:
                    # Always mark DB stopped (also when auto-stop runs without a live thread).
                    with get_db_connection() as db:
                        cursor = db.cursor()
                        cursor.execute(
                            "UPDATE qd_strategies_trading SET status = 'stopped' WHERE id = %s",
                            (strategy_id,),
                        )
                        db.commit()
                        cursor.close()

                if had_thread:
                    del self.running_strategies[strategy_id]
                    self._exchange_fee_cache.pop(strategy_id, None)
                    try:
                        from app.services.grid.runner import shutdown_grid_for_strategy

                        shutdown_grid_for_strategy(strategy_id)
                    except Exception:
                        pass
                    logger.info(f"Strategy {strategy_id} stopped")
                    self._console_print(f"[strategy:{strategy_id}] stopped (requested)")
                    append_strategy_log(strategy_id, "info", "Strategy stop requested (run flag cleared)")
                else:
                    logger.info(f"Strategy {strategy_id} marked stopped in DB (no active thread)")
                    try:
                        from app.services.grid.runner import shutdown_grid_for_strategy

                        shutdown_grid_for_strategy(strategy_id)
                    except Exception:
                        pass
                return True
                
        except Exception as e:
            logger.error(f"Failed to stop strategy {strategy_id}: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def _df_to_script_exec_df(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.reset_index()
        c0 = out.columns[0]
        if c0 != 'time':
            out.rename(columns={c0: 'time'}, inplace=True)
        return out

    def _script_default_position_ratio(self, trading_config: Dict[str, Any]) -> float:
        try:
            entry_ratio = self._risk_params_from_trading_config(trading_config).get("entry_ratio")
            if entry_ratio is not None and float(entry_ratio) > 0:
                return float(entry_ratio)
        except Exception:
            pass
        return 0.06

    def _hydrate_script_ctx_from_positions(
        self,
        ctx: StrategyScriptContext,
        strategy_id: int,
        symbol: str,
        initial_capital: Optional[float] = None,
        current_price: Optional[float] = None,
        trading_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        ctx.position.clear_position()
        pl = self._get_current_positions(strategy_id, symbol)
        # DB stores long/short legs as separate rows keyed by (strategy_id,
        # symbol, side); hydrate both so hedge-mode strategies (neutral grid)
        # see independent ctx.position.long_size / short_size.
        if pl:
            for p in pl:
                side = (p.get('side') or '').strip().lower()
                size = float(p.get('size') or 0)
                ep = float(p.get('entry_price') or 0)
                if size <= 0:
                    continue
                if side == 'long':
                    ctx.position.open_long(ep, size)
                elif side == 'short':
                    ctx.position.open_short(ep, size)

        # Live script/grid: when DB is empty/stale, fall back to the exchange book.
        tc = trading_config if isinstance(trading_config, dict) else {}
        if self._is_live_script_hydrate_candidate(tc):
            self._hydrate_grid_ctx_from_exchange_best_effort(
                ctx,
                strategy_id=strategy_id,
                symbol=symbol,
                current_price=current_price,
                trading_config=tc,
                db_had_long=ctx.position.has_long(),
                db_had_short=ctx.position.has_short(),
            )
            pl = self._get_current_positions(strategy_id, symbol)
        try:
            if initial_capital is not None and float(initial_capital) > 0:
                eq = self._calculate_current_equity(
                    strategy_id,
                    float(initial_capital),
                    current_positions=pl,
                    current_price=current_price,
                    symbol=symbol,
                )
                ctx.balance = float(eq)
                ctx.equity = float(eq)
        except Exception:
            pass
    def _hydrate_grid_ctx_from_exchange_best_effort(
        self,
        ctx: StrategyScriptContext,
        *,
        strategy_id: int,
        symbol: str,
        current_price: Optional[float],
        trading_config: Dict[str, Any],
        db_had_long: bool,
        db_had_short: bool,
    ) -> None:
        """Fill missing grid legs from the exchange when local DB snapshot is empty."""
        if db_had_long and db_had_short:
            return
        try:
            from app.services.exchange_execution import load_strategy_configs, resolve_exchange_config

            sc = load_strategy_configs(int(strategy_id))
            raw_ex = trading_config.get("exchange_config") or sc.get("exchange_config") or {}
            ex_cfg = resolve_exchange_config(
                raw_ex if isinstance(raw_ex, dict) else {},
                user_id=int(sc.get("user_id") or 1),
            )
        except Exception as e:
            logger.warning("Grid exchange hydrate resolve failed for sid=%s: %s", strategy_id, e)
            return
        if not isinstance(ex_cfg, dict) or not (ex_cfg.get("api_key") or ex_cfg.get("apiKey")):
            return
        market_type = str(trading_config.get("market_type") or "swap").strip().lower()
        try:
            from app.services.live_trading.factory import create_client
            from app.services.live_trading.position_query import query_exchange_position_size

            client = create_client(ex_cfg, market_type=market_type)
            ref_px = float(current_price or 0.0)
            for side in ("long", "short"):
                if side == "long" and db_had_long:
                    continue
                if side == "short" and db_had_short:
                    continue
                sz = query_exchange_position_size(
                    client=client,
                    symbol=str(symbol or ""),
                    pos_side=side,
                    market_type=market_type,
                    exchange_config=ex_cfg,
                )
                if sz <= 0:
                    continue
                if side == "long":
                    ctx.position.open_long(ref_px, sz)
                else:
                    ctx.position.open_short(ref_px, sz)
                try:
                    from app.services.live_trading.records import upsert_position

                    upsert_position(
                        strategy_id=int(strategy_id),
                        symbol=str(symbol or ""),
                        side=side,
                        size=float(sz),
                        entry_price=float(ref_px or 0.0),
                        current_price=float(ref_px or 0.0),
                    )
                except Exception:
                    pass
                logger.info(
                    "Exchange hydrate from book: %s %s size=%s (db missing leg)",
                    symbol,
                    side,
                    sz,
                )
        except Exception as e:
            logger.warning("Grid exchange hydrate skipped for %s: %s", symbol, e)

    def _init_script_strategy_context(
        self,
        strategy_id: int,
        df: pd.DataFrame,
        trading_config: Dict[str, Any],
        initial_capital: float,
        strategy_run_id: int = 0,
        symbol: str = "",
        user_id: int = 0,
        ai_model_config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[StrategyScriptContext, Optional[pd.Timestamp]]:
        df_exec = self._df_to_script_exec_df(df)
        ctx = StrategyScriptContext(
            df_exec,
            float(initial_capital or 0),
            strategy_id=int(strategy_id or 0),
            strategy_run_id=int(strategy_run_id or 0),
            symbol=str(symbol or ""),
        )
        raw = (trading_config or {}).get('script_runtime_state') or {}
        params = raw.get('params') if isinstance(raw, dict) else {}
        persisted = dict(params) if isinstance(params, dict) else {}
        tp = (trading_config or {}).get('script_template_params')
        template_params = dict(tp) if isinstance(tp, dict) else {}
        bp = (trading_config or {}).get('bot_params')
        bot_params = dict(bp) if isinstance(bp, dict) else {}
        ctx._params = self._sanitize_script_runtime_params({**persisted, **template_params, **bot_params})
        ctx.set_runtime_config(trading_config or {}, initial_balance=initial_capital)
        from app.services.ai_decision import LiveAIDecisionClient

        ctx.bind_ai(LiveAIDecisionClient(
            user_id=int(user_id or 0),
            strategy_id=int(strategy_id or 0),
            strategy_run_id=int(strategy_run_id or 0),
            model_config=ai_model_config or {},
            runtime=ctx.runtime,
        ))
        if ctx.direction in ('long', 'short', 'both'):
            ctx._params['direction'] = ctx.direction
        last_ts = None
        ts_s = raw.get('last_closed_bar_ts') if isinstance(raw, dict) else None
        if ts_s:
            try:
                last_ts = pd.Timestamp(ts_s)
                if last_ts.tzinfo is None:
                    last_ts = last_ts.tz_localize('UTC')
                else:
                    last_ts = last_ts.tz_convert('UTC')
            except Exception:
                last_ts = None
        return ctx, last_ts

    def _sanitize_script_runtime_params(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(params, dict):
            return {}
        out: Dict[str, Any] = {}
        for key, value in params.items():
            name = str(key or "").strip()
            if not name:
                continue
            try:
                numeric = float(value)
            except Exception:
                out[name] = value
                continue
            if not np.isfinite(numeric):
                continue
            out[name] = numeric
        return out

    def _persist_script_runtime_state(self, strategy_id: int, closed_ts: Any, params: Dict[str, Any]) -> None:
        try:
            safe_params = json.loads(json.dumps(params or {}, default=str))
        except Exception:
            safe_params = {}
        ts_str = ''
        try:
            if closed_ts is not None:
                ts_str = pd.Timestamp(closed_ts).isoformat()
        except Exception:
            ts_str = ''
        state = {'last_closed_bar_ts': ts_str, 'params': safe_params}
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute("SELECT trading_config FROM qd_strategies_trading WHERE id = %s", (strategy_id,))
                row = cur.fetchone()
                if not row:
                    cur.close()
                    return
                tc = row.get('trading_config')
                if isinstance(tc, str) and tc.strip():
                    try:
                        tc = json.loads(tc)
                    except Exception:
                        tc = {}
                elif not isinstance(tc, dict):
                    tc = {}
                tc['script_runtime_state'] = state
                cur.execute(
                    "UPDATE qd_strategies_trading SET trading_config = %s WHERE id = %s",
                    (json.dumps(tc, ensure_ascii=False), strategy_id),
                )
                db.commit()
                cur.close()
        except Exception as e:
            logger.warning(f"Persist script runtime state failed: {e}")

    def _bot_type_key(self, trading_config: Optional[Dict[str, Any]]) -> str:
        return str((trading_config or {}).get("bot_type") or "").strip().lower()

    def _is_live_grid_resting(
        self,
        trading_config: Optional[Dict[str, Any]],
        execution_mode: str,
        market_category: str = "Crypto",
    ) -> bool:
        """Live grid bots always use the resting limit-order engine."""
        if str(execution_mode or "").strip().lower() != "live":
            return False
        if self._bot_type_key(trading_config) != "grid":
            return False
        mc = str(market_category or "Crypto").strip()
        return mc in ("Crypto", "Forex", "Futures")

    def _grid_enqueue_market(
        self,
        strategy_id: int,
        symbol: str,
        signal_type: str,
        usdt_amount: float,
        price: float,
        reason: str,
        *,
        trading_config: Dict[str, Any],
        execution_mode: str,
        market_type: str,
        market_category: str,
        leverage: float,
        notification_config: Dict[str, Any],
        kline_exchange_id: Optional[str],
    ) -> bool:
        try:
            lev = float(leverage or 1.0)
            qty = (float(usdt_amount or 0) * lev / float(price)) if price > 0 and market_type != "spot" else (float(usdt_amount or 0) / float(price) if price > 0 else 0)
            if signal_type.startswith("close_"):
                qty = 0
            bp = trading_config if isinstance(trading_config, dict) else {}
            order_mode = str(bp.get("order_mode") or (bp.get("bot_params") or {}).get("orderMode") or "market")
            res = self._submit_signal_order(
                exchange=None,
                strategy_id=strategy_id,
                symbol=symbol,
                signal_type=signal_type,
                amount=qty if not signal_type.startswith("close_") else 0,
                ref_price=float(price or 0),
                market_type=market_type,
                market_category=market_category,
                leverage=lev,
                execution_mode=execution_mode,
                notification_config=notification_config,
                signal_reason=reason,
                signal_ts=int(time.time()),
                price_exchange_id=kline_exchange_id,
                order_mode=order_mode if order_mode != "maker" else "market",
                strategy_run_id=int((trading_config or {}).get("_strategy_run_id") or 0),
            )
            return bool(res and res.get("success"))
        except Exception as e:
            logger.warning("grid enqueue market sid=%s: %s", strategy_id, e)
            return False

    def _setup_grid_resting_runner(
        self,
        strategy_id: int,
        symbol: str,
        trading_config: Dict[str, Any],
        exchange_config: Dict[str, Any],
        *,
        user_id: int = 1,
        initial_capital: float,
        execution_mode: str,
        market_type: str,
        market_category: str,
        leverage: float,
        notification_config: Dict[str, Any],
        kline_exchange_id: Optional[str],
    ):
        from app.services.grid.runner import GridRestingRunner
        from app.services.exchange_execution import resolve_exchange_config
        from app.services.live_trading.factory import create_client

        ex_cfg = resolve_exchange_config(
            exchange_config if isinstance(exchange_config, dict) else {},
            user_id=int(user_id or 1),
        )
        mt = str(market_type or "swap")

        def _create_client():
            return create_client(ex_cfg, market_type=mt)

        def _enqueue(sig: str, usdt: float, px: float, reason: str) -> bool:
            return self._grid_enqueue_market(
                strategy_id,
                symbol,
                sig,
                usdt,
                px,
                reason,
                trading_config=trading_config,
                execution_mode=execution_mode,
                market_type=mt,
                market_category=market_category,
                leverage=leverage,
                notification_config=notification_config,
                kline_exchange_id=kline_exchange_id,
            )

        def _risk_exits(px: float):
            return self._grid_bot_risk_exits(
                strategy_id=strategy_id,
                symbol=symbol,
                current_price=float(px),
                trading_config=trading_config,
                timeframe_seconds=60,
                initial_capital=float(initial_capital or 0),
            )

        return GridRestingRunner(
            strategy_id,
            symbol,
            trading_config,
            ex_cfg,
            user_id=int(user_id or 1),
            initial_capital=float(initial_capital or 0),
            enqueue_market_fn=_enqueue,
            create_client_fn=_create_client,
            risk_exit_fn=_risk_exits,
        )

    def _bot_has_market_guards(self, trading_config: Optional[Dict[str, Any]]) -> bool:
        return self._bot_type_key(trading_config) in ("grid", "martingale")

    def _prepare_grid_bot_before_bar(
        self,
        script_ctx: StrategyScriptContext,
        trading_config: Dict[str, Any],
        *,
        price: float,
        high: float,
        low: float,
        is_closed_bar: bool,
    ) -> None:
        if not self._bot_has_market_guards(trading_config):
            return
        try:
            from app.services.bot_scripts.grid_runtime import prepare_bot_market_guards

            bars_df = getattr(script_ctx, "_bars_df", None)
            prepare_bot_market_guards(
                self._bot_type_key(trading_config),
                script_ctx._params,
                price=float(price or 0),
                high=float(high or price or 0),
                low=float(low or price or 0),
                bars_df=bars_df,
                is_closed_bar=bool(is_closed_bar),
            )
        except Exception as e:
            logger.warning(f"Bot market-guard prepare failed: {e}")

    def _post_process_grid_bot_signals(
        self,
        signals: List[Dict[str, Any]],
        script_ctx: StrategyScriptContext,
        trading_config: Dict[str, Any],
        *,
        price: float,
        timestamp: int,
    ) -> List[Dict[str, Any]]:
        if not self._bot_has_market_guards(trading_config):
            return signals
        try:
            from app.services.bot_scripts.grid_runtime import (
                filter_grid_signals_under_waterfall,
                inject_waterfall_close_signal,
            )

            params = script_ctx._params if isinstance(script_ctx._params, dict) else {}
            pos = script_ctx.position
            has_long = False
            has_short = False
            try:
                if int(pos) > 0:
                    has_long = True
                elif int(pos) < 0:
                    has_short = True
            except Exception:
                side = str((pos.get("side") if isinstance(pos, dict) else getattr(pos, "side", "")) or "").lower()
                has_long = side == "long" and float((pos.get("size") if isinstance(pos, dict) else getattr(pos, "size", 0)) or 0) > 0
                has_short = side == "short" and float((pos.get("size") if isinstance(pos, dict) else getattr(pos, "size", 0)) or 0) > 0

            out = filter_grid_signals_under_waterfall(list(signals or []), params)
            return inject_waterfall_close_signal(
                out,
                params,
                has_long=has_long,
                has_short=has_short,
                price=float(price or 0),
                timestamp=int(timestamp or 0),
            )
        except Exception as e:
            logger.warning(f"Bot market-guard signal post-process failed: {e}")
            return signals

    def _script_orders_to_execution_signals(
        self,
        ctx: StrategyScriptContext,
        trade_direction: str,
        bar_close: float,
        closed_ts: pd.Timestamp,
        trading_config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        td = str(trade_direction or 'both').lower()
        if td not in ('long', 'short', 'both'):
            td = 'both'
        default_ratio = self._script_default_position_ratio(trading_config)
        try:
            ts_i = int(closed_ts.timestamp())
        except Exception:
            ts_i = int(time.time())

        bot_type = (trading_config or {}).get('bot_type', '')
        is_grid_bot = bot_type in ('grid', 'dca')

        out: List[Dict[str, Any]] = []
        trig = float(bar_close or 0)
        try:
            is_bot_script = bool(
                (trading_config or {}).get('bot_type')
                or (trading_config or {}).get('strategy_mode') == 'bot'
            )
        except Exception:
            is_bot_script = False
        try:
            leverage = float((trading_config or {}).get('leverage') or 1) or 1.0
        except Exception:
            leverage = 1.0
        market_type = str((trading_config or {}).get('market_type') or 'swap').lower()

        def _to_local_qty(value: float, ref_price: float, *, from_order_amount: bool) -> float:
            if ref_price is None or ref_price <= 0 or value is None or value <= 0:
                return 0.0
            try:
                explicit_quote = float(order.get('script_quote_amount') or 0.0)
                if explicit_quote > 0:
                    lev = leverage if market_type != 'spot' else 1.0
                    return explicit_quote * lev / float(ref_price)
            except Exception:
                pass
            try:
                explicit_base = float(order.get('script_base_qty') or 0.0)
                if explicit_base > 0:
                    return explicit_base
            except Exception:
                pass
            if is_bot_script and from_order_amount:
                lev = leverage if market_type != 'spot' else 1.0
                return float(value) * lev / float(ref_price)
            if is_bot_script and float(value) > 1.0:
                lev = leverage if market_type != 'spot' else 1.0
                return float(value) * lev / float(ref_price)
            return float(value)

        def _script_quote_extra() -> Dict[str, Any]:
            """Bot scripts pass quote notional via ctx.buy/sell(amount=...)."""
            try:
                explicit_quote = float(order.get('script_quote_amount') or 0.0)
                if explicit_quote > 0:
                    return {'script_quote_amount': explicit_quote}
            except Exception:
                pass
            if (not is_bot_script) or raw_amt is None:
                return {}
            try:
                if float(raw_amt) > 0:
                    return {'script_quote_amount': float(raw_amt)}
            except Exception:
                pass
            return {}

        def _script_qty_extra() -> Dict[str, Any]:
            """Non-bot scripts pass base-asset qty via ctx.buy/sell; honor it live like backtest."""
            try:
                explicit_base = float(order.get('script_base_qty') or 0.0)
                if explicit_base > 0:
                    return {'script_base_qty': explicit_base}
            except Exception:
                pass
            try:
                if float(order.get('script_quote_amount') or 0.0) > 0:
                    return {}
            except Exception:
                pass
            if is_bot_script or raw_amt is None:
                return {}
            try:
                if float(raw_amt) > 0 and local_qty > 0:
                    return {'script_base_qty': float(local_qty)}
            except Exception:
                pass
            return {}

        def _emit(sig: Dict[str, Any], reason_override: Optional[str]) -> None:
            if reason_override:
                sig.setdefault('reason', reason_override)
            sig.update(_script_quote_extra())
            sig.update(_script_qty_extra())
            if runtime_extra:
                sig.update(runtime_extra)
            out.append(sig)

        for order in list(ctx._orders or []):
            intent = str(order.get('intent') or '').lower()
            reason_hint = order.get('reason')
            runtime_extra = {}
            for meta_key in (
                'strategy_run_id',
                'basket_id',
                'basket_order_db_id',
                'order_intent_id',
                'idempotency_key',
                'layer_index',
                'order_index',
                'execution_algo',
                'order_type',
                'limit_price',
            ):
                if order.get(meta_key) not in (None, ''):
                    runtime_extra[meta_key] = order.get(meta_key)
            try:
                order_price = float(order.get('price') or bar_close or 0)
            except Exception:
                order_price = trig
            execution_algo_value = str(order.get('execution_algo') or '').strip().lower()
            if execution_algo_value in ('limit', 'limit_then_market', 'maker', 'maker_then_market'):
                runtime_extra.setdefault('order_type', 'limit')
                runtime_extra.setdefault(
                    'limit_price',
                    float(order.get('limit_price') or order_price or 0.0),
                )
            raw_amt = order.get('amount')
            pos_ratio = default_ratio
            if raw_amt is not None:
                try:
                    v = float(raw_amt)
                    if v > 0:
                        pos_ratio = v
                except Exception:
                    pass
            ref_px = order_price if order_price > 0 else trig
            local_qty = _to_local_qty(pos_ratio, ref_px, from_order_amount=(raw_amt is not None))

            if intent == 'close_long':
                close_qty = local_qty
                if close_qty <= 0 and ctx.position.has_long():
                    close_qty = ctx.position.long_size
                if close_qty <= 0:
                    continue
                avg_entry = 0.0
                if ctx.position.has_long():
                    _, avg_entry = ctx.position.reduce_long(close_qty)
                _emit({
                    'type': 'close_long', 'trigger_price': ref_px,
                    'position_size': pos_ratio if local_qty else 0,
                    'timestamp': ts_i, 'matched_entry_price': avg_entry,
                }, reason_hint or ('grid_reduce_long' if is_grid_bot else None))
                continue

            if intent == 'close_short':
                close_qty = local_qty
                if close_qty <= 0 and ctx.position.has_short():
                    close_qty = ctx.position.short_size
                if close_qty <= 0:
                    continue
                avg_entry = 0.0
                if ctx.position.has_short():
                    _, avg_entry = ctx.position.reduce_short(close_qty)
                _emit({
                    'type': 'close_short', 'trigger_price': ref_px,
                    'position_size': pos_ratio if local_qty else 0,
                    'timestamp': ts_i, 'matched_entry_price': avg_entry,
                }, reason_hint or ('grid_reduce_short' if is_grid_bot else None))
                continue
            if intent in ('open_long', 'add_long'):
                has_long = ctx.position.has_long()
                if td not in ('long', 'both') or (intent == 'add_long' and not has_long) or (intent == 'open_long' and has_long and not is_bot_script):
                    continue
                sig_type = 'add_long' if has_long else 'open_long'
                ctx.position.open_long(ref_px, local_qty)
                _emit({
                    'type': sig_type, 'trigger_price': ref_px, 'position_size': pos_ratio,
                    'timestamp': ts_i,
                }, reason_hint)
                continue
            if intent in ('open_short', 'add_short'):
                has_short = ctx.position.has_short()
                if td not in ('short', 'both') or (intent == 'add_short' and not has_short) or (intent == 'open_short' and has_short and not is_bot_script):
                    continue
                sig_type = 'add_short' if has_short else 'open_short'
                ctx.position.open_short(ref_px, local_qty)
                _emit({
                    'type': sig_type, 'trigger_price': ref_px, 'position_size': pos_ratio,
                    'timestamp': ts_i,
                }, reason_hint)
                continue
        return out

    def _script_evaluate_new_closed_bar(
        self,
        df: pd.DataFrame,
        ctx: StrategyScriptContext,
        on_bar,
        trade_direction: str,
        last_closed_ts: Optional[pd.Timestamp],
        strategy_id: int,
        symbol: str,
        trading_config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[pd.Timestamp]]:
        if df is None or len(df) < 2:
            return [], last_closed_ts
        closed_ts = df.index[-2]
        try:
            if last_closed_ts is not None and closed_ts <= last_closed_ts:
                return [], last_closed_ts
        except Exception:
            pass
        df_exec = self._df_to_script_exec_df(df)
        pos = len(df) - 2
        ctx._bars_df = df_exec.iloc[:pos + 1]
        ctx.current_index = int(pos)
        row = df_exec.iloc[pos]
        _init_cap = (trading_config or {}).get('initial_capital')
        _bar_close_for_hydrate = None
        try:
            _bar_close_for_hydrate = float(row.get('close') or 0)
        except Exception:
            _bar_close_for_hydrate = None
        self._hydrate_script_ctx_from_positions(
            ctx, strategy_id, symbol,
            initial_capital=_init_cap,
            current_price=_bar_close_for_hydrate,
            trading_config=trading_config,
        )
        ctx._orders.clear()
        bar = ScriptBar(
            open=float(row.get('open') or 0),
            high=float(row.get('high') or 0),
            low=float(row.get('low') or 0),
            close=float(row.get('close') or 0),
            volume=float(row.get('volume') or 0),
            timestamp=row.get('time'),
        )
        self._prepare_grid_bot_before_bar(
            ctx, trading_config,
            price=float(bar.close or 0),
            high=float(bar.high or bar.close or 0),
            low=float(bar.low or bar.close or 0),
            is_closed_bar=True,
        )
        try:
            self._run_script_callback_with_timeout(strategy_id, "on_bar", on_bar, ctx, bar)
        except ScriptCallbackTimeout:
            raise
        except Exception as e:
            logger.error(f"Strategy {strategy_id} script on_bar error: {e}")
            logger.error(traceback.format_exc())
            return [], last_closed_ts
        finally:
            self._flush_ctx_logs(strategy_id, ctx)
        bar_close = float(row.get('close') or 0)
        pending = self._script_orders_to_execution_signals(ctx, trade_direction, bar_close, closed_ts, trading_config)
        try:
            ts_i = int(closed_ts.timestamp())
        except Exception:
            ts_i = int(time.time())
        pending = self._post_process_grid_bot_signals(
            pending, ctx, trading_config, price=bar_close, timestamp=ts_i,
        )
        self._persist_script_runtime_state(strategy_id, closed_ts, ctx._params)
        ctx.flush_state()
        logger.info(f"Strategy {strategy_id} script closed bar {closed_ts} -> {len(pending)} signal(s)")
        return pending, closed_ts

    def _flush_ctx_logs(self, strategy_id: int, ctx: StrategyScriptContext) -> None:
        """Flush ``ctx.log()`` lines into ``qd_strategy_logs`` for the strategy UI."""
        if ctx is None:
            return
        try:
            logs = ctx.flush_logs()
        except Exception as e:
            logger.debug(f"Strategy {strategy_id} flush_logs skipped: {e}")
            return
        for log in logs:
            append_strategy_log(strategy_id, "info", log)

    def _script_evaluate_in_progress_bar(
        self,
        df: pd.DataFrame,
        ctx: StrategyScriptContext,
        on_bar,
        trade_direction: str,
        strategy_id: int,
        symbol: str,
        trading_config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Evaluate the forming last bar when strict_mode is off."""
        if df is None or len(df) < 1:
            return []
        df_exec = self._df_to_script_exec_df(df)
        ctx._bars_df = df_exec
        pos = len(df) - 1
        ctx.current_index = int(pos)
        row = df_exec.iloc[pos]
        _init_cap = (trading_config or {}).get("initial_capital")
        _bar_close_for_hydrate = None
        try:
            _bar_close_for_hydrate = float(row.get("close") or 0)
        except Exception:
            _bar_close_for_hydrate = None
        self._hydrate_script_ctx_from_positions(
            ctx, strategy_id, symbol,
            initial_capital=_init_cap,
            current_price=_bar_close_for_hydrate,
            trading_config=trading_config,
        )
        ctx._orders.clear()
        bar_ts = df.index[pos]
        bar = ScriptBar(
            open=float(row.get("open") or 0),
            high=float(row.get("high") or 0),
            low=float(row.get("low") or 0),
            close=float(row.get("close") or 0),
            volume=float(row.get("volume") or 0),
            timestamp=row.get("time"),
        )
        self._prepare_grid_bot_before_bar(
            ctx, trading_config,
            price=float(bar.close or 0),
            high=float(bar.high or bar.close or 0),
            low=float(bar.low or bar.close or 0),
            is_closed_bar=False,
        )
        try:
            self._run_script_callback_with_timeout(strategy_id, "in-progress on_bar", on_bar, ctx, bar)
        except ScriptCallbackTimeout:
            raise
        except Exception as e:
            logger.error(f"Strategy {strategy_id} script in-progress on_bar error: {e}")
            logger.error(traceback.format_exc())
            return []
        finally:
            self._flush_ctx_logs(strategy_id, ctx)
        bar_close = float(row.get("close") or 0)
        pending = self._script_orders_to_execution_signals(
            ctx, trade_direction, bar_close, bar_ts, trading_config,
        )
        try:
            ts_i = int(bar_ts.timestamp())
        except Exception:
            ts_i = int(time.time())
        pending = self._post_process_grid_bot_signals(
            pending, ctx, trading_config, price=bar_close, timestamp=ts_i,
        )
        self._persist_script_runtime_state(strategy_id, None, ctx._params)
        ctx.flush_state()
        if pending:
            logger.info(
                f"Strategy {strategy_id} script in-progress bar {bar_ts} -> {len(pending)} signal(s)"
            )
        return pending
    
    def _run_strategy_loop(self, strategy_id: int):
        """Run one strategy loop until it is stopped or exits."""
        logger.info(f"Strategy {strategy_id} loop starting")
        self._console_print(f"[strategy:{strategy_id}] loop initializing")
        
        # Auto-stop policy: prevent endless error spam when a strategy is no longer runnable
        try:
            max_consecutive_errors = int(os.getenv("STRATEGY_MAX_CONSECUTIVE_ERRORS", "5"))
        except Exception:
            max_consecutive_errors = 5
        if max_consecutive_errors < 1:
            max_consecutive_errors = 1
        consecutive_errors = 0
        consecutive_script_timeouts = 0
        exit_reason: str = ""

        def _set_db_stopped_best_effort(reason: str) -> None:
            """Best-effort: mark strategy stopped to avoid zombie 'running' status."""
            try:
                with get_db_connection() as db:
                    cur = db.cursor()
                    cur.execute(
                        "UPDATE qd_strategies_trading SET status = 'stopped' WHERE id = %s AND status = 'running'",
                        (int(strategy_id),),
                    )
                    db.commit()
                    cur.close()
            except Exception:
                pass
            try:
                if reason:
                    append_strategy_log(strategy_id, "error", f"Auto-stopped: {reason}")
            except Exception:
                pass

        def _abort_loop(reason: str) -> None:
            nonlocal exit_reason
            exit_reason = reason
            logger.error(f"Strategy {strategy_id} abort: {reason}")
            _set_db_stopped_best_effort(reason)

        def _unexpected_exit_reason() -> str:
            return (
                "thread exited unexpectedly without a recorded reason; "
                "check process restart, resource limits, or an unhandled loop exit"
            )

        def _is_fatal_error(err: Exception, msg: str) -> bool:
            # Config errors from data sources should stop immediately.
            if isinstance(err, UnsupportedMarketError):
                return True
            m = (msg or "").lower()
            if not m:
                return False
            # IBKR disabled in SaaS/cloud installs.
            if "disabled ibkr" in m:
                return True
            # Broker gateway not reachable (Docker 127.0.0.1, TWS down, etc.)
            if any(
                t in m
                for t in (
                    "connection refused",
                    "connect call failed",
                    "errno 111",
                    "failed to connect to ibkr",
                    "make sure api port on tws",
                )
            ):
                return True
            # Common auth/permission failures (API key expired/invalid).
            fatal_tokens = [
                "invalid api", "api key", "apikey", "secret", "signature",
                "authentication", "unauthorized", "forbidden", "permission",
                "invalid_key", "invalid key",
                '"code":-2015', "-2015", "50111", "40018",
            ]
            if any(t in m for t in fatal_tokens):
                return True
            # Symbol/product not found (delisted / not supported).
            symbol_tokens = [
                "symbol not found", "unknown symbol", "invalid symbol",
                "instrument not found", "product not found", "does not exist",
                "delist", "delisted", "not supported",
            ]
            if any(t in m for t in symbol_tokens):
                return True
            return False

        try:
            grid_resting_runner = None
            use_grid_resting = False
            strategy = self._load_strategy(strategy_id)
            if not strategy:
                _abort_loop("strategy not found")
                return
            
            stype = strategy.get('strategy_type') or ''
            if stype != 'ScriptStrategy':
                _abort_loop(
                    "Indicators are chart-only. Convert the indicator to a ScriptStrategy before live trading."
                )
                return
            is_script = True

            trading_config = strategy['trading_config']
            normalize_trading_execution_modes(trading_config)
            logger.info(
                f"Strategy {strategy_id} execution modes: strict_mode={trading_config.get('strict_mode')}, "
                f"signal_mode={trading_config.get('signal_mode')}, "
                f"entry_trigger_mode={trading_config.get('entry_trigger_mode')}, "
                f"exit_signal_mode={trading_config.get('exit_signal_mode')}"
            )
            # `strict_mode` opts the strategy into "backtest-equivalent" semantics:
            # closed-bar signals only (drop in-progress bar) and a confirmed exit
            # signal (no aggressive intra-bar close). This reduces the drift
            # between backtest and live but typically delays entries/exits by
            # one full bar. Both knobs default to existing behaviour when
            # strict_mode is unset.
            strict_mode = bool(trading_config.get('strict_mode', False))
            execution_mode = (strategy.get('execution_mode') or 'signal').strip().lower()
            if execution_mode not in ['signal', 'live']:
                execution_mode = 'signal'
            strategy_mode = (strategy.get('strategy_mode') or 'script').strip().lower()
            is_bot_mode = strategy_mode == 'bot'
            notification_config = strategy.get('notification_config') or {}
            strategy_name = strategy.get('strategy_name') or f"strategy_{int(strategy_id)}"
            # Strategy owner: used to scope cross-feature notifications (e.g. portfolio
            # linkage) to the user who actually runs this strategy. Without it, a signal
            # from user A's strategy would leak to every user holding the same symbol.
            try:
                strategy_user_id = int(strategy.get('user_id') or 0) or None
            except (TypeError, ValueError):
                strategy_user_id = None
            symbol = (
                trading_config.get('symbol')
                or trading_config.get('trading_pair')
                or strategy.get('symbol')
                or ''
            )
            timeframe = (
                trading_config.get('timeframe')
                or strategy.get('timeframe')
                or '1H'
            )
            if isinstance(trading_config, dict):
                trading_config.setdefault('symbol', symbol)
                trading_config.setdefault('timeframe', timeframe)
            
            try:
                leverage_val = trading_config.get('leverage', strategy.get('leverage', 1))
                if isinstance(leverage_val, (list, tuple)):
                    leverage_val = leverage_val[0] if leverage_val else 1
                leverage = float(leverage_val)
            except:
                logger.warning(f"Strategy {strategy_id} invalid leverage format, reset to 1: {trading_config.get('leverage')}")
                leverage = 1.0
            
            market_type = trading_config.get('market_type') or strategy.get('market_type') or 'swap'
            if market_type not in ['swap', 'spot']:
                _abort_loop(f"invalid market_type={market_type} (only swap/spot supported)")
                return
            if market_type == 'swap':
                logger.info(f"Strategy {strategy_id} derivatives trading; normalize market_type to: swap")
            
            if market_type == 'spot':
                leverage = 1.0
            elif leverage < 1:
                leverage = 1.0
            elif leverage > 125:
                leverage = 125.0
                logger.warning(f"Strategy {strategy_id} leverage > 125; capped to 125")
            
            trade_direction = (
                trading_config.get('trade_direction')
                or trading_config.get('tradeDirection')
                or strategy.get('trade_direction')
                or 'long'
            )
            if market_type == 'spot':
                trade_direction = 'long'
                if isinstance(trading_config, dict):
                    trading_config['trade_direction'] = 'long'
                logger.info(f"Strategy {strategy_id} spot trading; force trade_direction=long")

            market_category = (strategy.get('market_category') or 'Crypto').strip()
            logger.info(f"Strategy {strategy_id} market_category: {market_category}")

            try:
                initial_capital_val = strategy.get('initial_capital', 1000)
                if isinstance(initial_capital_val, (list, tuple)):
                    initial_capital_val = initial_capital_val[0] if initial_capital_val else 1000
                initial_capital = float(initial_capital_val)
            except Exception:
                logger.warning(f"Strategy {strategy_id} invalid initial_capital format, reset to 1000: {strategy.get('initial_capital')}")
                initial_capital = 1000.0

            strategy_code = ''
            on_init_script = None
            on_bar_script = None
            strategy_run_id = 0
            startup_candle_count = 0

            if is_script:
                strategy_code = (strategy.get('strategy_code') or '').strip()
                if not strategy_code:
                    try:
                        script_source_id = None
                        if isinstance(trading_config, dict):
                            script_source_id = trading_config.get('script_source_id') or trading_config.get('scriptSourceId')
                        if script_source_id:
                            from app.services.script_source import get_script_source_service
                            source = get_script_source_service().get_source(
                                int(script_source_id),
                                user_id=int(strategy.get('user_id') or 1),
                            )
                            strategy_code = ((source or {}).get('code') or '').strip()
                    except Exception as e:
                        logger.warning(f"Strategy {strategy_id} script source lookup failed: {e}")
                if not strategy_code:
                    _abort_loop("strategy_code is empty")
                    return
                if '\\n' in strategy_code and '\n' not in strategy_code:
                    try:
                        decoded = json.loads(f'"{strategy_code}"')
                        if isinstance(decoded, str):
                            strategy_code = decoded
                    except Exception:
                        strategy_code = (
                            strategy_code.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
                            .replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')
                        )
                script_contract = resolve_script_strategy_contract(strategy_code, trading_config)
                script_code_cfg = script_contract['codeConfig']
                startup_candle_count = int(script_contract['startupCandleCount'] or 0)
                if script_code_cfg:
                    trading_config = dict(trading_config or {})
                    trading_config["_strategy_cfg_from_code"] = script_code_cfg
                    if script_code_cfg.get("exitOwner"):
                        trading_config["exit_owner"] = script_code_cfg.get("exitOwner")
                    strategy["trading_config"] = trading_config
                trading_config['startup_candle_count'] = startup_candle_count
                script_timeframe = script_code_cfg.get("timeframe") if isinstance(script_code_cfg, dict) else None
                if script_timeframe:
                    timeframe = str(script_timeframe)
                    trading_config["timeframe"] = timeframe
                    strategy["trading_config"] = trading_config
                try:
                    on_init_script, on_bar_script = compile_strategy_script_handlers(strategy_code)
                except Exception as e:
                    _abort_loop(f"script compile failed: {e}")
                    logger.error(traceback.format_exc())
                    return
                try:
                    from app.services.strategy_runtime.identity import ensure_strategy_run

                    ex_cfg_for_run = strategy.get('exchange_config') or {}
                    if isinstance(ex_cfg_for_run, str) and ex_cfg_for_run.strip():
                        try:
                            ex_cfg_for_run = json.loads(ex_cfg_for_run)
                        except Exception:
                            ex_cfg_for_run = {}
                    if not isinstance(ex_cfg_for_run, dict):
                        ex_cfg_for_run = {}
                    strategy_runtime_run = ensure_strategy_run(
                        strategy_id=int(strategy_id),
                        user_id=int(strategy.get('user_id') or 1),
                        code=strategy_code,
                        parameter_snapshot=trading_config if isinstance(trading_config, dict) else {},
                        source_version_id=str((trading_config or {}).get('script_source_id') or (trading_config or {}).get('scriptSourceId') or ''),
                        exchange_id=str(ex_cfg_for_run.get('exchange_id') or ex_cfg_for_run.get('exchangeId') or ''),
                        credential_id=int(ex_cfg_for_run.get('credential_id') or ex_cfg_for_run.get('credentials_id') or 0),
                        symbol=str(symbol or ''),
                        market_type=str(market_type or 'swap'),
                        position_mode=str((trading_config or {}).get('position_mode') or (trading_config or {}).get('positionMode') or ''),
                    )
                    strategy_run_id = int(strategy_runtime_run.strategy_run_id or 0)
                    if isinstance(trading_config, dict):
                        trading_config['_strategy_run_id'] = strategy_run_id
                        trading_config['_strategy_runtime_epoch'] = int(strategy_runtime_run.runtime_epoch or 0)
                except Exception as e:
                    logger.warning(f"Strategy {strategy_id} runtime run init failed: {e}")
            # Resolve credential references before any strategy branch.
            exchange_config = strategy.get('exchange_config') or {}
            try:
                from app.services.exchange_execution import resolve_exchange_config

                exchange_config = resolve_exchange_config(
                    exchange_config if isinstance(exchange_config, dict) else {},
                    user_id=int(strategy_user_id or strategy.get('user_id') or 1),
                )
                strategy['exchange_config'] = exchange_config
            except Exception as e:
                logger.warning(f"Strategy {strategy_id} resolve exchange_config failed: {e}")
            if isinstance(trading_config, dict):
                trading_config.setdefault('execution_mode', execution_mode)
                if exchange_config:
                    trading_config['exchange_config'] = exchange_config

            exchange = None

            kline_exchange_id, kline_market_type = self._live_crypto_kline_params(
                market_category=market_category,
                market_type=market_type,
                execution_mode=execution_mode,
                exchange_config=exchange_config,
                trading_config=trading_config,
                user_id=int(strategy_user_id or strategy.get('user_id') or 1),
            )
            self._log_crypto_kline_source(
                strategy_id, market_category, execution_mode, kline_exchange_id, kline_market_type
            )
            if exchange_config and (exchange_config.get('api_key') or exchange_config.get('apiKey')):
                try:
                    self._query_exchange_fee_rate(strategy_id, exchange_config, symbol, market_type)
                except Exception as e:
                    logger.debug(f"Strategy {strategy_id} skipped fee-rate query: {e}")

            # ============================================
            # ============================================
            history_limit = int(os.getenv('K_LINE_HISTORY_GET_NUMBER', 500))
            if is_script:
                history_limit = required_live_history_limit(history_limit, startup_candle_count)
            klines = self._fetch_latest_kline(
                symbol, timeframe, limit=history_limit, market_category=market_category,
                exchange_id=kline_exchange_id, market_type=kline_market_type,
            )
            if not klines or len(klines) < 2:
                _abort_loop(f"failed to fetch K-lines for {market_category}:{symbol} {timeframe} via {kline_exchange_id or 'default'}/{kline_market_type or 'default'} (need at least 2 bars)")
                return
            warmup_status = live_warmup_status(len(klines), startup_candle_count)
            if is_script and not warmup_status['ready']:
                _abort_loop(
                    f"STRATEGY_WARMUP_NOT_READY required={warmup_status['required']} "
                    f"completed={warmup_status['completed']} missing={warmup_status['missing']}"
                )
                return
            logger.info(rf'Strategy {strategy_id} history kline number: {len(klines)}')
            
            df = self._klines_to_dataframe(klines)
            if len(df) == 0:
                _abort_loop("K-lines are empty after normalization")
                return
            # ============================================
            # ============================================
            if execution_mode == 'live':
                try:
                    logger.info(f"Strategy {strategy_id} syncing positions before live loop")
                    from app import get_pending_order_worker
                    worker = get_pending_order_worker()
                    if worker and hasattr(worker, '_sync_positions_best_effort'):
                        worker._sync_positions_best_effort(target_strategy_id=strategy_id)
                        logger.info(f"Strategy {strategy_id} position sync completed")
                except Exception as e:
                    logger.warning(f"Strategy {strategy_id} position sync failed: {e}")

            current_pos_list = self._get_current_positions(strategy_id, symbol)
            initial_highest = 0.0
            initial_position = 0  # 0=flat, 1=long, -1=short
            initial_avg_entry_price = 0.0
            initial_position_count = 0
            initial_last_add_price = 0.0
            
            if current_pos_list:
                pos = current_pos_list[0]
                initial_highest = float(pos.get('highest_price', 0) or 0)
                pos_side = pos.get('side', 'long')
                initial_position = 1 if pos_side == 'long' else -1
                initial_avg_entry_price = float(pos.get('entry_price', 0) or 0)
                initial_position_count = 1
                initial_last_add_price = initial_avg_entry_price

            logger.info(
                f"Strategy {strategy_id} initial local position: count={len(current_pos_list)}, "
                f"position={initial_position}, entry_price={initial_avg_entry_price}, highest={initial_highest}"
            )

            script_ctx = None
            last_script_closed_ts = None
            if is_script:
                script_ctx, last_script_closed_ts = self._init_script_strategy_context(
                    strategy_id,
                    df,
                    trading_config,
                    initial_capital,
                    strategy_run_id,
                    symbol,
                    user_id=int(strategy_user_id or strategy.get('user_id') or 0),
                    ai_model_config=strategy.get('ai_model_config') or {},
                )
                script_ctx.startup_candle_count = startup_candle_count
                script_ctx.warmup_bars_seen = min(startup_candle_count, int(warmup_status['completed']))
                script_ctx.is_warming_up = False
                script_ctx.is_ready = True
                script_ctx.runtime.update({
                    'startup_candle_count': startup_candle_count,
                    'warmup_bars_seen': script_ctx.warmup_bars_seen,
                    'is_warming_up': False,
                    'is_ready': True,
                })
                if on_init_script:
                    self._hydrate_script_ctx_from_positions(
                        script_ctx, strategy_id, symbol,
                        initial_capital=initial_capital,
                        current_price=(float(df['close'].iloc[-1]) if df is not None and len(df) > 0 else None),
                        trading_config=trading_config,
                    )
                    try:
                        self._run_script_callback_with_timeout(strategy_id, "on_init", on_init_script, script_ctx)
                    except ScriptCallbackTimeout as e:
                        _abort_loop(str(e))
                        return
                    except Exception as e:
                        logger.error(f"Strategy {strategy_id} on_init error: {e}")
                        logger.error(traceback.format_exc())
                    finally:
                        self._flush_ctx_logs(strategy_id, script_ctx)
                robot_definition = script_ctx.runtime.get('robot_definition') if isinstance(script_ctx.runtime, dict) else None
                if isinstance(robot_definition, dict):
                    robot_type = str(robot_definition.get('robot_type') or '').strip().lower()
                    robot_config = robot_definition.get('config')
                    if robot_type == 'grid' and self._bot_type_key(trading_config) == 'grid':
                        from app.services.strategy_runtime.executors import executor_runtime_params

                        trading_config['bot_params'] = executor_runtime_params(robot_type, robot_config)
                        trading_config['executor_config'] = dict(robot_config)
                        append_strategy_log(
                            strategy_id,
                            'info',
                            'Grid runtime configuration compiled from strategy source code',
                        )
                try:
                    pending_signals, last_script_closed_ts = self._script_evaluate_new_closed_bar(
                        df, script_ctx, on_bar_script, trade_direction,
                        last_script_closed_ts, strategy_id, symbol, trading_config,
                    )
                except ScriptCallbackTimeout as e:
                    _abort_loop(str(e))
                    return
                if not strict_mode and len(df) > 0:
                    try:
                        init_price = float(df['close'].iloc[-1])
                        rt_df = self._update_dataframe_with_current_price(
                            df.copy(), init_price, timeframe,
                        )
                        ip_sig = self._script_evaluate_in_progress_bar(
                            rt_df, script_ctx, on_bar_script, trade_direction,
                            strategy_id, symbol, trading_config,
                        )
                        if ip_sig:
                            pending_signals = ip_sig
                    except ScriptCallbackTimeout as e:
                        _abort_loop(str(e))
                        return
                    except Exception as e:
                        logger.warning(
                            f"Strategy {strategy_id} script init in-progress eval failed: {e}"
                        )
                try:
                    last_kline_time = int(df.index[-1].timestamp())
                except Exception:
                    last_kline_time = int(time.time())
            logger.info(f"Strategy {strategy_id} initialized; pending_signals={len(pending_signals)}")
            if pending_signals:
                logger.info(f"Initial signals: {pending_signals}")

            grid_resting_runner = None
            use_grid_resting = self._is_live_grid_resting(trading_config, execution_mode, market_category)
            if self._bot_type_key(trading_config) == "grid" and execution_mode == "live" and not use_grid_resting:
                _abort_loop(
                    f"Live grid requires resting engine; unsupported market_category={market_category}"
                )
                return
            if use_grid_resting:
                try:
                    init_px = float(df['close'].iloc[-1]) if df is not None and len(df) > 0 else 0.0
                    grid_resting_runner = self._setup_grid_resting_runner(
                        strategy_id,
                        symbol,
                        trading_config,
                        exchange_config,
                        user_id=int(strategy_user_id or strategy.get('user_id') or 1),
                        initial_capital=initial_capital,
                        execution_mode=execution_mode,
                        market_type=market_type,
                        market_category=market_category,
                        leverage=leverage,
                        notification_config=notification_config,
                        kline_exchange_id=kline_exchange_id,
                    )
                    ok_gr, err_gr = grid_resting_runner.startup(init_px, bars_df=df)
                    if not ok_gr:
                        _abort_loop(f"grid resting startup failed: {err_gr}")
                        return
                    if grid_resting_runner.should_stop:
                        _abort_loop(f"Grid auto-stopped during startup: {grid_resting_runner.stop_reason or 'grid resting engine requested stop'}")
                        return
                    pending_signals = []
                    append_strategy_log(
                        strategy_id,
                        "info",
                        f"Grid resting live active on {symbol} (limit orders + fill poller)",
                    )
                except Exception as e:
                    _abort_loop(f"grid resting setup failed: {e}")
                    return

            append_strategy_log(
                strategy_id,
                "info",
                f"Live loop ready {symbol} {timeframe}, pending signals: {len(pending_signals or [])}",
            )
            
            # ============================================
            # Main loop: tick cadence (P1-2)
            # ============================================
            # One tick = fetch current price once + evaluate triggers once + refresh script signals when a bar closes.
            # Note: `pending_orders` scanning stays at 1s (see PendingOrderWorker) to reduce live dispatch latency.
            #
            #   1. trading_config.tick_interval_sec: per-strategy override.
            #   2. Grid/DCA bots default to 1s (their fills are price-cross
            #      driven, a 10s poll would routinely miss grid lines on
            #      volatile pairs).
            #   3. STRATEGY_TICK_INTERVAL_SEC env var, fallback 10s.
            try:
                env_tick = int(os.getenv('STRATEGY_TICK_INTERVAL_SEC', '10'))
            except Exception:
                env_tick = 10

            _bot_type_for_tick = str((trading_config or {}).get('bot_type') or '').strip().lower()
            # Grid bots use a fixed server-side tick (price-driven); not user-configurable.
            if _bot_type_for_tick == 'grid':
                try:
                    tick_interval_sec = max(1, int(os.getenv('GRID_STRATEGY_TICK_SEC', '1')))
                except Exception:
                    tick_interval_sec = 1
            else:
                tick_interval_sec = None
                try:
                    tc_override = (trading_config or {}).get('tick_interval_sec')
                    if tc_override is not None:
                        tick_interval_sec = int(tc_override)
                except Exception:
                    tick_interval_sec = None
                if tick_interval_sec is None and _bot_type_for_tick == 'dca':
                    tick_interval_sec = 1
                if tick_interval_sec is None:
                    tick_interval_sec = env_tick
            if tick_interval_sec < 1:
                tick_interval_sec = 1

            last_tick_time = 0.0

            from app.data_sources.base import TIMEFRAME_SECONDS
            timeframe_seconds = TIMEFRAME_SECONDS.get(timeframe, 3600)

            kline_poll_offset = _kline_boundary_poll_offset_sec()
            next_kline_poll_at = next_kline_boundary_poll_ts(
                time.time(), timeframe_seconds, kline_poll_offset,
            )
            logger.info(
                f"Strategy {strategy_id} K-line poll aligned to bar boundaries "
                f"(tf={timeframe}, offset={kline_poll_offset}s, next={datetime.fromtimestamp(next_kline_poll_at).isoformat()})"
            )
            
            while True:
                try:
                    if not self._is_strategy_running(strategy_id):
                        exit_reason = exit_reason or "run flag cleared / status stopped"
                        logger.info(f"Strategy {strategy_id} stopped")
                        break
                    
                    current_time = time.time()

                    # Sleep until next tick to avoid CPU spin. Cap each
                    # sleep at the tick interval (or 1s, whichever is smaller)
                    # so a stop-strategy command is honoured promptly even on
                    # long intervals.
                    if last_tick_time > 0:
                        sleep_sec = (last_tick_time + tick_interval_sec) - current_time
                        if sleep_sec > 0:
                            time.sleep(min(sleep_sec, max(0.05, min(1.0, float(tick_interval_sec)))))
                            continue
                    last_tick_time = current_time

                    # ============================================
                    # ============================================
                    # pass
                    
                    # ============================================
                    # 1. Fetch current price once per tick
                    # ============================================
                    current_price = self._fetch_current_price(
                        exchange, symbol, market_type=market_type, market_category=market_category,
                        exchange_id=kline_exchange_id, kline_market_type=kline_market_type,
                    )
                    if current_price is None:
                        logger.warning(f"Strategy {strategy_id} failed to fetch current price for {market_category}:{symbol}")
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            exit_reason = (
                                f"failed to fetch price for {market_category}:{symbol} "
                                f"({consecutive_errors}/{max_consecutive_errors})"
                            )
                            logger.error(f"Strategy {strategy_id} {exit_reason}; stopping")
                            self._console_print(f"[strategy:{strategy_id}] auto-stopping: {exit_reason}")
                            _set_db_stopped_best_effort(exit_reason)
                            break
                        continue

                    # ============================================
                    # ============================================
                    if current_time >= next_kline_poll_at:
                        klines = self._fetch_latest_kline(
                            symbol, timeframe, limit=history_limit, market_category=market_category,
                            exchange_id=kline_exchange_id, market_type=kline_market_type,
                        )
                        try:
                            if klines and len(klines) >= 2:
                                df = self._klines_to_dataframe(klines)
                                if len(df) > 0:
                                    if is_script:
                                        if use_grid_resting and grid_resting_runner is not None:
                                            try:
                                                bar_h = float(df['high'].iloc[-1])
                                                bar_l = float(df['low'].iloc[-1])
                                                grid_resting_runner.tick(
                                                    float(current_price),
                                                    high=bar_h,
                                                    low=bar_l,
                                                    bars_df=df,
                                                    is_closed_bar=True,
                                                )
                                            except Exception as e:
                                                logger.warning(
                                                    f"Strategy {strategy_id} grid resting kline tick error: {e}"
                                                )
                                            pending_signals = []
                                            if grid_resting_runner.should_stop:
                                                exit_reason = f"Grid auto-stopped: {grid_resting_runner.stop_reason or 'engine requested stop'}"
                                                logger.error(f"Strategy {strategy_id} {exit_reason}")
                                                _set_db_stopped_best_effort(exit_reason)
                                                break
                                            try:
                                                last_kline_time = int(df.index[-1].timestamp())
                                            except Exception:
                                                last_kline_time = int(time.time())
                                        elif self._bot_type_key(trading_config) != "grid":
                                            new_sig, last_script_closed_ts = self._script_evaluate_new_closed_bar(
                                                df, script_ctx, on_bar_script, trade_direction,
                                                last_script_closed_ts, strategy_id, symbol, trading_config,
                                            )
                                            pending_signals = new_sig
                                            if not strict_mode:
                                                try:
                                                    rt_df = self._update_dataframe_with_current_price(
                                                        df.copy(), current_price, timeframe,
                                                    )
                                                    ip_sig = self._script_evaluate_in_progress_bar(
                                                        rt_df, script_ctx, on_bar_script, trade_direction,
                                                        strategy_id, symbol, trading_config,
                                                    )
                                                    if ip_sig:
                                                        pending_signals = ip_sig
                                                except ScriptCallbackTimeout:
                                                    raise
                                                except Exception as e:
                                                    logger.warning(
                                                        f"Strategy {strategy_id} script kline in-progress eval failed: {e}"
                                                    )
                                            try:
                                                last_kline_time = int(df.index[-1].timestamp())
                                            except Exception:
                                                last_kline_time = int(time.time())
                        finally:
                            next_kline_poll_at = next_kline_boundary_poll_ts(
                                max(current_time, next_kline_poll_at),
                                timeframe_seconds,
                                kline_poll_offset,
                            )
                    else:
                        # ============================================
                        # ============================================
                        # 3a. Grid resting live: limit-order engine
                        if use_grid_resting and grid_resting_runner is not None:
                            try:
                                grid_resting_runner.tick(
                                    float(current_price),
                                    high=float(current_price),
                                    low=float(current_price),
                                    bars_df=df if 'df' in locals() else None,
                                )
                                pending_signals = []
                            except Exception as e:
                                logger.warning(f"Strategy {strategy_id} grid resting tick error: {e}")
                            if grid_resting_runner.should_stop:
                                exit_reason = f"Grid auto-stopped: {grid_resting_runner.stop_reason or 'engine requested stop'}"
                                logger.error(f"Strategy {strategy_id} {exit_reason}")
                                _set_db_stopped_best_effort(exit_reason)
                                break
                        # 3a2. Bot-mode scripts (martingale / DCA tick; grid uses resting engine)
                        elif (
                            is_script
                            and is_bot_mode
                            and on_bar_script
                            and script_ctx is not None
                            and self._bot_type_key(trading_config) != "grid"
                        ):
                            try:
                                self._hydrate_script_ctx_from_positions(
                                    script_ctx, strategy_id, symbol,
                                    initial_capital=initial_capital,
                                    current_price=float(current_price),
                                    trading_config=trading_config,
                                )
                                script_ctx._orders.clear()
                                tick_bar = ScriptBar(
                                    open=float(current_price),
                                    high=float(current_price),
                                    low=float(current_price),
                                    close=float(current_price),
                                    volume=0,
                                    timestamp=int(time.time()),
                                )
                                self._prepare_grid_bot_before_bar(
                                    script_ctx, trading_config,
                                    price=float(current_price),
                                    high=float(current_price),
                                    low=float(current_price),
                                    is_closed_bar=False,
                                )
                                try:
                                    self._run_script_callback_with_timeout(
                                        strategy_id, "bot tick on_bar", on_bar_script, script_ctx, tick_bar
                                    )
                                finally:
                                    self._flush_ctx_logs(strategy_id, script_ctx)
                                if script_ctx._orders:
                                    tick_ts = pd.Timestamp.now(tz='UTC')
                                    new_sig = self._script_orders_to_execution_signals(
                                        script_ctx, trade_direction, float(current_price), tick_ts, trading_config,
                                    )
                                    try:
                                        tick_ts_i = int(tick_ts.timestamp())
                                    except Exception:
                                        tick_ts_i = int(time.time())
                                    new_sig = self._post_process_grid_bot_signals(
                                        new_sig, script_ctx, trading_config,
                                        price=float(current_price), timestamp=tick_ts_i,
                                    )
                                    if new_sig:
                                        pending_signals = new_sig
                                        self._persist_script_runtime_state(strategy_id, tick_ts, script_ctx._params)
                                        script_ctx.flush_state()
                                        logger.info(f"Strategy {strategy_id} bot tick -> {len(new_sig)} signal(s)")
                                    else:
                                        self._persist_script_runtime_state(strategy_id, None, script_ctx._params)
                                        script_ctx.flush_state()
                                else:
                                    self._persist_script_runtime_state(strategy_id, None, script_ctx._params)
                                    script_ctx.flush_state()
                            except Exception as e:
                                if isinstance(e, ScriptCallbackTimeout):
                                    raise
                                logger.warning(f"Strategy {strategy_id} bot tick on_bar error: {e}")

                        # 3a2. Non-bot scripts: evaluate forming bar when strict mode is off
                        elif (
                            is_script
                            and not is_bot_mode
                            and not strict_mode
                            and on_bar_script
                            and script_ctx is not None
                            and 'df' in locals()
                            and df is not None
                            and len(df) > 0
                        ):
                            try:
                                rt_df = self._update_dataframe_with_current_price(
                                    df.copy(), current_price, timeframe,
                                )
                                new_sig = self._script_evaluate_in_progress_bar(
                                    rt_df, script_ctx, on_bar_script, trade_direction,
                                    strategy_id, symbol, trading_config,
                                )
                                if new_sig:
                                    pending_signals = new_sig
                            except ScriptCallbackTimeout:
                                raise
                            except Exception as e:
                                logger.warning(
                                    f"Strategy {strategy_id} script in-progress recompute failed: {e}"
                                )

                    # ============================================
                    # 4. Evaluate triggers once per tick
                    # ============================================
                    current_ts = int(time.time())
                    if pending_signals:
                        expiration_threshold = timeframe_seconds * 2
                        valid_signals = []
                        for s in pending_signals:
                            signal_time = s.get('timestamp', 0)
                            if signal_time == 0 or (current_ts - signal_time) < expiration_threshold:
                                valid_signals.append(s)
                            else:
                                logger.debug(f"Signal expired and removed: {s}")
                        if len(valid_signals) != len(pending_signals):
                            pending_signals = valid_signals

                    # Unified cadence log: at most once per tick.
                    if pending_signals:
                        logger.info(f"[monitoring] strategy={strategy_id} price={current_price}, pending_signals={len(pending_signals)}")

                    triggered_signals = []
                    signals_to_remove = []
                        
                    for signal_info in pending_signals:
                        signal_type = signal_info.get('type')  # 'open_long', 'close_long', 'open_short', 'close_short'
                        trigger_price = signal_info.get('trigger_price', 0)
                        
                        triggered = False

                        # Bot-mode scripts (grid / DCA / martingale) handle their own
                        # timing inside on_bar; execute signals immediately.
                        if is_bot_mode:
                            triggered = True

                        exit_trigger_mode = trading_config.get('exit_trigger_mode', 'immediate')  # 'immediate' or 'price'
                        if signal_type in ['close_long', 'close_short'] and exit_trigger_mode == 'immediate':
                            triggered = True
                        
                        entry_trigger_mode = trading_config.get('entry_trigger_mode', 'price')  # 'price' or 'immediate'
                        if signal_type in ['open_long', 'open_short', 'add_long', 'add_short'] and entry_trigger_mode == 'immediate':
                            triggered = True

                        if trigger_price > 0:
                            if signal_type in ['open_long', 'close_short', 'add_long']:
                                if current_price >= trigger_price:
                                    triggered = True
                            elif signal_type in ['open_short', 'close_long', 'add_short']:
                                if current_price <= trigger_price:
                                    triggered = True
                        else:
                            triggered = True
                        
                        if triggered:
                            triggered_signals.append(signal_info)
                            signals_to_remove.append(signal_info)

                    # ============================================
                    # 4.1 Server-side exits (config-driven): SL / TP / trailing
                    # ============================================
                    # Note: stop-loss is only applied when stop_loss_pct > 0. No default fallback.
                    risk_tp = self._server_side_take_profit_or_trailing_signal(
                        strategy_id=strategy_id,
                        symbol=symbol,
                        current_price=float(current_price),
                        market_type=market_type,
                        leverage=float(leverage),
                        trading_config=trading_config,
                        timeframe_seconds=int(timeframe_seconds or 60),
                        execution_mode=execution_mode,
                    )
                    if risk_tp:
                        triggered_signals.append(risk_tp)
                        # Server exit already handled the leg; drop stale indicator close_* pending.
                        risk_close = str(risk_tp.get('type') or '').strip().lower()
                        if risk_close in ('close_long', 'close_short'):
                            pending_signals = [
                                s for s in pending_signals
                                if str(s.get('type') or '').strip().lower() != risk_close
                            ]

                    risk_sl = self._server_side_stop_loss_signal(
                        strategy_id=strategy_id,
                        symbol=symbol,
                        current_price=float(current_price),
                        market_type=market_type,
                        leverage=float(leverage),
                        trading_config=trading_config,
                        timeframe_seconds=int(timeframe_seconds or 60),
                    )
                    if risk_sl:
                        triggered_signals.append(risk_sl)
                        risk_close = str(risk_sl.get('type') or '').strip().lower()
                        if risk_close in ('close_long', 'close_short'):
                            pending_signals = [
                                s for s in pending_signals
                                if str(s.get('type') or '').strip().lower() != risk_close
                            ]
                    # Grid / DCA bot risk exits; resting grid handles risk inside runner.tick.
                    grid_exits = []
                    if not use_grid_resting:
                        grid_exits = self._grid_bot_risk_exits(
                            strategy_id=strategy_id,
                            symbol=symbol,
                            current_price=float(current_price),
                            trading_config=trading_config,
                            timeframe_seconds=int(timeframe_seconds or 60),
                            initial_capital=float(initial_capital or 0),
                        )
                    if grid_exits:
                        triggered_signals.extend(grid_exits)
                        types_to_drop = {
                            str(s.get('type') or '').strip().lower() for s in grid_exits
                        }
                        if types_to_drop:
                            pending_signals = [
                                s for s in pending_signals
                                if str(s.get('type') or '').strip().lower() not in types_to_drop
                            ]

                    for signal_info in signals_to_remove:
                        if signal_info in pending_signals:
                            pending_signals.remove(signal_info)
                        
                    if triggered_signals:
                        if not self._is_strategy_running(strategy_id):
                            exit_reason = exit_reason or "run flag cleared before signal execution"
                            logger.info(f"Strategy {strategy_id} stop requested before signal execution; dropping triggered signals")
                            break

                        logger.info(f"Strategy {strategy_id} triggered signals: {triggered_signals}")

                        current_positions = self._get_current_positions(strategy_id, symbol)
                        state = self._effective_position_state(strategy_id, symbol, current_positions)

                        # Strict state machine + priority:
                        # - Only allow signals matching current state (flat/long/short).
                        # - Always prefer close_* over open_*/add_*.
                        # - Bot-mode may need multiple state transitions in one tick
                        #   (e.g. grid partial take-profit / reverse across levels),
                        #   while normal scripts execute at most one signal.
                        if is_bot_mode:
                            candidates = list(triggered_signals)
                        else:
                            candidates = [
                                s for s in triggered_signals
                                if self._is_signal_allowed(state, s.get('type'))
                            ]

                        # If both directions are present while flat, choose by trade_direction (deterministic).
                        if state == "flat" and candidates:
                            td = (trade_direction or "both").strip().lower()
                            if td == "long":
                                candidates = [s for s in candidates if s.get("type") == "open_long"]
                            elif td == "short":
                                candidates = [s for s in candidates if s.get("type") == "open_short"]

                        candidates = sorted(
                            candidates,
                            key=lambda s: (
                                self._signal_priority(s.get("type")),
                                int(s.get("timestamp") or 0),
                                str(s.get("type") or ""),
                            ),
                        )

                        now_i = int(time.time())
                        execution_batch: List[Dict[str, Any]] = []
                        for s in candidates:
                            stype = s.get("type")
                            sts = int(s.get("timestamp") or 0)
                            if (not is_bot_mode) and self._should_skip_signal_once_per_candle(
                                strategy_id=strategy_id,
                                symbol=symbol,
                                signal_type=str(stype or ""),
                                signal_ts=sts,
                                timeframe_seconds=int(timeframe_seconds or 60),
                                now_ts=now_i,
                            ):
                                continue
                            execution_batch.append(s)
                            if not is_bot_mode:
                                break

                        stop_requested_during_execution = False
                        for selected in execution_batch:
                            if not self._is_strategy_running(strategy_id):
                                exit_reason = exit_reason or "run flag cleared during signal execution"
                                stop_requested_during_execution = True
                                logger.info(f"Strategy {strategy_id} stop requested during signal execution; remaining signals dropped")
                                break
                            signal_type = selected.get('type')
                            position_size = selected.get('position_size', 0)
                            trigger_price = selected.get('trigger_price', current_price)
                            execute_price = trigger_price if trigger_price > 0 else current_price
                            signal_ts = int(selected.get("timestamp") or 0)
                            current_positions = self._get_current_positions(strategy_id, symbol)

                            if not self._is_signal_allowed(
                                self._effective_position_state(strategy_id, symbol, current_positions),
                                signal_type,
                            ):
                                continue

                            ok = self._execute_signal(
                                strategy_id=strategy_id,
                                strategy_name=strategy_name,
                                exchange=exchange,
                                symbol=symbol,
                                current_price=execute_price,
                                signal_type=signal_type,
                                position_size=position_size,
                                signal_ts=signal_ts,
                                current_positions=current_positions,
                                trade_direction=trade_direction,
                                leverage=leverage,
                                initial_capital=initial_capital,
                                market_type=market_type,
                                market_category=market_category,
                                price_exchange_id=kline_exchange_id,
                                execution_mode=execution_mode,
                                notification_config=notification_config,
                                trading_config=trading_config,
                                stop_loss_price=selected.get("stop_loss_price"),
                                take_profit_price=selected.get("take_profit_price"),
                                signal_reason=selected.get("reason"),
                                matched_entry_price=selected.get("matched_entry_price"),
                                trailing_stop_price=selected.get("trailing_stop_price"),
                                script_base_qty=selected.get("script_base_qty"),
                                script_quote_amount=selected.get("script_quote_amount"),
                                strategy_run_id=int(selected.get("strategy_run_id") or ((trading_config or {}).get("_strategy_run_id") if isinstance(trading_config, dict) else 0) or 0),
                                order_intent_id=int(selected.get("order_intent_id") or 0),
                                idempotency_key=str(selected.get("idempotency_key") or ""),
                                basket_id=str(selected.get("basket_id") or ""),
                                basket_order_db_id=int(selected.get("basket_order_db_id") or 0),
                                layer_index=int(selected.get("layer_index") or 0),
                                order_index=int(selected.get("order_index") or 0),
                                execution_algo=str(selected.get("execution_algo") or ""),
                                order_type=str(selected.get("order_type") or ""),
                                limit_price=float(selected.get("limit_price") or 0.0),
                            )
                            if ok:
                                logger.info(f"Strategy {strategy_id} signal executed: {signal_type} @ {execute_price}")
                                append_strategy_log(
                                    strategy_id,
                                    "signal",
                                    f"Signal submitted: {signal_type} @ {float(execute_price or 0):.6f}{self._signal_reason_log_suffix(selected)}",
                                )
                                # Notify portfolio positions linked to this symbol.
                                # IMPORTANT: scope to the strategy owner only. Without
                                # `user_id`, the callee would fan out to every user
                                # holding the same symbol and leak the strategy name /
                                # signal details across tenants.
                                try:
                                    from app.services.portfolio_monitor import notify_strategy_signal_for_positions
                                    if strategy_user_id:
                                        notify_strategy_signal_for_positions(
                                            market=market_type or 'Crypto',
                                            symbol=symbol,
                                            signal_type=signal_type,
                                            signal_detail=f"Strategy: {strategy_name}\nSignal: {signal_type}\nPrice: {execute_price:.4f}",
                                            user_id=strategy_user_id,
                                        )
                                    else:
                                        logger.warning(
                                            f"Strategy {strategy_id} missing owner user_id; "
                                            f"skipping portfolio linkage notification to avoid cross-user broadcast"
                                        )
                                except Exception as link_e:
                                    logger.warning(f"Strategy signal linkage notification failed: {link_e}")
                            else:
                                logger.warning(f"Strategy {strategy_id} signal rejected/failed: {signal_type}")
                                append_strategy_log(
                                    strategy_id,
                                    "error",
                                    f"Signal rejected or not executed: {signal_type}",
                                )
                        if stop_requested_during_execution:
                            break

                    # Update positions once per tick.
                    self._update_positions(strategy_id, symbol, current_price)

                    # Heartbeat for UI observability (once per tick).
                    self._console_print(
                        f"[strategy:{strategy_id}] tick price={float(current_price or 0.0):.8f} pending_signals={len(pending_signals or [])}"
                    )
                    self._record_runtime_heartbeat(
                        strategy_id=int(strategy_id),
                        strategy_run_id=int(strategy_run_id or 0),
                        symbol=str(symbol or ""),
                        price=float(current_price or 0.0),
                        pending_signal_count=len(pending_signals or []),
                    )

                    # Successful tick: reset consecutive error counter.
                    consecutive_errors = 0
                    consecutive_script_timeouts = 0
                    
                except Exception as e:
                    msg = str(e)
                    consecutive_errors += 1
                    if isinstance(e, ScriptCallbackTimeout):
                        consecutive_script_timeouts += 1
                    else:
                        consecutive_script_timeouts = 0
                    logger.error(f"Strategy {strategy_id} loop error ({consecutive_errors}/{max_consecutive_errors}): {msg}")
                    logger.error(traceback.format_exc())
                    self._console_print(f"[strategy:{strategy_id}] loop error: {e}")
                    try:
                        append_strategy_log(strategy_id, "error", f"Loop error: {e}")
                    except Exception:
                        pass

                    fatal = _is_fatal_error(e, msg)
                    script_timeout_limit_hit = (
                        isinstance(e, ScriptCallbackTimeout)
                        and consecutive_script_timeouts >= self.script_max_consecutive_timeouts
                    )
                    if fatal or script_timeout_limit_hit or consecutive_errors >= max_consecutive_errors:
                        if fatal and isinstance(e, UnsupportedMarketError):
                            exit_reason = (
                                f"Unsupported market type: {getattr(e, 'market', '')}. "
                                f"Please set strategy market_category/market to one of: "
                                f"Crypto/USStock/CNStock/HKStock/Forex/Futures/MOEX."
                            )
                        elif script_timeout_limit_hit:
                            exit_reason = (
                                f"script callback timeout threshold reached: "
                                f"{consecutive_script_timeouts}/{self.script_max_consecutive_timeouts}"
                            )
                        else:
                            exit_reason = msg if fatal else f"too many consecutive errors: {consecutive_errors}/{max_consecutive_errors}"
                        logger.error(f"Strategy {strategy_id} auto-stopping due to {'fatal error' if fatal else 'error threshold'}: {exit_reason}")
                        self._console_print(f"[strategy:{strategy_id}] auto-stopping: {exit_reason}")
                        _set_db_stopped_best_effort(exit_reason)
                        break

                    time.sleep(5)
                    
        except Exception as e:
            logger.error(f"Strategy {strategy_id} crashed: {str(e)}")
            logger.error(traceback.format_exc())
            self._console_print(f"[strategy:{strategy_id}] fatal error: {e}")
            try:
                append_strategy_log(strategy_id, "error", f"Strategy thread fatal error: {e}")
            except Exception:
                pass
            # Ensure DB state doesn't stay "running" on fatal crash.
            try:
                exit_reason = exit_reason or f"thread fatal error: {e}"
                _set_db_stopped_best_effort(exit_reason)
            except Exception:
                pass
        finally:
            try:
                if grid_resting_runner is not None:
                    grid_resting_runner.shutdown()
            except Exception:
                pass
            try:
                self._last_exit_reason[int(strategy_id)] = (exit_reason or _unexpected_exit_reason()).strip()
            except Exception:
                pass
            with self.lock:
                if strategy_id in self.running_strategies:
                    del self.running_strategies[strategy_id]
            # If the thread exited but DB still says running, mark it stopped to avoid zombie status.
            try:
                with get_db_connection() as db:
                    cur = db.cursor()
                    cur.execute("SELECT status FROM qd_strategies_trading WHERE id = %s", (int(strategy_id),))
                    row = cur.fetchone() or {}
                    cur.close()
                if (row.get("status") or "").strip().lower() == "running":
                    _set_db_stopped_best_effort(exit_reason or _unexpected_exit_reason())
            except Exception:
                pass
            self._console_print(f"[strategy:{strategy_id}] loop exited")
            logger.info(f"Strategy {strategy_id} loop exited")
            try:
                append_strategy_log(strategy_id, "info", "Strategy execution loop exited")
            except Exception:
                pass
    
    def _load_strategy(self, strategy_id: int) -> Optional[Dict[str, Any]]:
        """Load strategy config (local deployment: no encryption/decryption)."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                query = """
                    SELECT
                        id, user_id, strategy_name, strategy_type, status,
                        initial_capital, leverage, decide_interval,
                        execution_mode, notification_config,
                        indicator_config, exchange_config, trading_config, ai_model_config,
                        market_category, strategy_mode, strategy_code
                    FROM qd_strategies_trading
                    WHERE id = %s
                """
                cursor.execute(query, (strategy_id,))
                strategy = cursor.fetchone()
                cursor.close()
            
            if strategy:
                for field in ['indicator_config', 'trading_config', 'notification_config', 'ai_model_config']:
                    if isinstance(strategy.get(field), str):
                        try:
                            strategy[field] = json.loads(strategy[field])
                        except:
                            strategy[field] = {}
                
                # exchange_config: local deployment stores plaintext JSON
                exchange_config_str = strategy.get('exchange_config', '{}')
                if isinstance(exchange_config_str, str) and exchange_config_str:
                    try:
                        strategy['exchange_config'] = json.loads(exchange_config_str)
                    except Exception as e:
                        logger.error(f"Strategy {strategy_id} failed to parse exchange_config: {str(e)}")
                        try:
                            strategy['exchange_config'] = json.loads(exchange_config_str)
                        except:
                            strategy['exchange_config'] = {}
                else:
                    strategy['exchange_config'] = {}
            
            return strategy
            
        except Exception as e:
            logger.error(f"Failed to load strategy config: {str(e)}")
            return None
    
    def _is_strategy_running(self, strategy_id: int) -> bool:
        """Return whether a strategy is currently marked as running."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    "SELECT status FROM qd_strategies_trading WHERE id = %s",
                    (strategy_id,)
                )
                result = cursor.fetchone()
                cursor.close()
                db_status = result and result.get('status') == 'running'
            
            with self.lock:
                thread = self.running_strategies.get(strategy_id)
                thread_running = thread is not None and thread.is_alive()
            
            if db_status and not thread_running:
                logger.warning(f"Strategy {strategy_id} status mismatch: DB=running but thread not running. Updating DB status to stopped.")
                try:
                    with get_db_connection() as db:
                        cursor = db.cursor()
                        cursor.execute(
                            "UPDATE qd_strategies_trading SET status = 'stopped' WHERE id = %s",
                            (strategy_id,)
                        )
                        db.commit()
                        cursor.close()
                except Exception as e:
                    logger.error(f"Failed to update strategy {strategy_id} status to stopped: {e}")
                return False
            
            return db_status and thread_running
        except Exception as e:
            logger.error(f"Error checking strategy {strategy_id} running status: {e}")
            return False
    
    def _query_exchange_fee_rate(
        self,
        strategy_id: int,
        exchange_config: Dict[str, Any],
        symbol: str,
        market_type: str = "swap",
    ) -> Optional[Dict[str, float]]:
        """Query and cache the account's real fee-rate from the exchange."""
        with self._exchange_fee_cache_lock:
            if strategy_id in self._exchange_fee_cache:
                return self._exchange_fee_cache[strategy_id]
        try:
            from app.services.live_trading.factory import query_fee_rate
            result = query_fee_rate(exchange_config, symbol, market_type=market_type)
            with self._exchange_fee_cache_lock:
                self._exchange_fee_cache[strategy_id] = result
            if result:
                logger.info(f"Strategy {strategy_id} exchange fee rate: maker={result['maker']}, taker={result['taker']}")
            return result
        except Exception as e:
            logger.warning(f"Strategy {strategy_id} failed to query exchange fee rate: {e}")
            with self._exchange_fee_cache_lock:
                self._exchange_fee_cache[strategy_id] = None
            return None

    def _effective_taker_fee_rate(
        self,
        strategy_id: int,
        trading_config: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Fee rate used by runtime risk guards and local signal-mode fills."""
        try:
            cached = getattr(self, "_exchange_fee_cache", {}) or {}
            exchange_fee = cached.get(strategy_id)
            if exchange_fee and float(exchange_fee.get("taker") or 0.0) > 0:
                return float(exchange_fee["taker"])
        except Exception:
            pass

        try:
            configured_pct = float((trading_config or {}).get("commission", 0) or 0)
            if configured_pct > 0:
                return max(0.0, min(configured_pct / 100.0, 0.05))
        except Exception:
            pass

        return DEFAULT_TAKER_FEE_RATE

    @staticmethod
    def _live_crypto_kline_params(
        *,
        market_category: str,
        market_type: str,
        execution_mode: str,
        exchange_config: Optional[Dict[str, Any]],
        trading_config: Optional[Dict[str, Any]] = None,
        user_id: int = 1,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve the crypto K-line venue used by live or signal execution."""
        if (market_category or "").strip() != "Crypto":
            return None, None
        mode = (execution_mode or "").strip().lower()
        if mode not in ("live", "signal"):
            return None, None
        from app.data_sources.crypto import resolve_crypto_venue

        cfg = exchange_config if isinstance(exchange_config, dict) else {}
        cred_ref = cfg.get("credential_id") or cfg.get("credentials_id")
        if cred_ref and not (
            cfg.get("exchange_id") or cfg.get("exchangeId") or cfg.get("exchange")
        ):
            try:
                from app.services.exchange_execution import resolve_exchange_config

                cfg = resolve_exchange_config(cfg, user_id=int(user_id or 1))
            except Exception:
                pass

        ex, mt = resolve_crypto_venue(
            exchange_config=cfg,
            trading_config=trading_config,
            market_type=market_type,
        )
        return ex, mt

    @staticmethod
    def _log_crypto_kline_source(
        strategy_id: int,
        market_category: str,
        execution_mode: str,
        kline_exchange_id: Optional[str],
        kline_market_type: Optional[str],
    ) -> None:
        if (market_category or "").strip() != "Crypto":
            return
        mode = (execution_mode or "").strip().lower()
        if mode not in ("live", "signal"):
            return
        if kline_exchange_id:
            logger.info(
                f"Strategy {strategy_id} crypto K-line ({mode}): "
                f"{kline_exchange_id}/{kline_market_type}"
            )
            return
        try:
            from app.config.data_sources import CCXTConfig

            default_ex = (CCXTConfig.DEFAULT_EXCHANGE or "binance").strip().lower()
        except Exception:
            default_ex = "binance"
        if mode == "signal":
            logger.info(
                f"Strategy {strategy_id} signal mode: no exchange selected; "
                f"K-lines use Settings default data source ({default_ex})"
            )
        else:
            logger.warning(
                f"Strategy {strategy_id} live mode: missing exchange_id; "
                "may differ from execution venue; bind an exchange for live trading"
            )

    def _fetch_latest_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        market_category: str = "Crypto",
        exchange_id: Optional[str] = None,
        market_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch latest K-line data, preferring the service cache when available."""
        try:
            return self.kline_service.get_kline(
                market=market_category,
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                before_time=int(time.time()),
                exchange_id=exchange_id,
                market_type=market_type,
            )
        except Exception as e:
            logger.error(f"Failed to fetch K-lines for {market_category}:{symbol}: {str(e)}")
            return []
    
    def _fetch_current_price(
        self,
        exchange: Any,
        symbol: str,
        market_type: str = None,
        market_category: str = "Crypto",
        exchange_id: Optional[str] = None,
        kline_market_type: Optional[str] = None,
    ) -> Optional[float]:
        """Fetch current price from the market data source selected by market_category."""
        mt_key = (kline_market_type or market_type or "").strip().lower()
        ex_key = (exchange_id or "").strip().lower()
        if not ex_key and (market_category or "").strip() == "Crypto":
            try:
                from app.config.data_sources import CCXTConfig

                ex_key = (CCXTConfig.DEFAULT_EXCHANGE or "binance").strip().lower()
            except Exception:
                ex_key = "binance"
        # Local in-memory cache first
        cache_key = f"{market_category}:{ex_key}:{mt_key}:{(symbol or '').strip().upper()}"
        if cache_key and self._price_cache_ttl_sec > 0:
            now = time.time()
            try:
                with self._price_cache_lock:
                    item = self._price_cache.get(cache_key)
                    if item:
                        price, expiry = item
                        if expiry > now:
                            return float(price)
                        # expired
                        del self._price_cache[cache_key]
            except Exception:
                pass
            
        try:
            ticker = DataSourceFactory.get_ticker(
                market_category, symbol, exchange_id=exchange_id, market_type=kline_market_type or market_type
            )
            if ticker:
                price = float(ticker.get('last') or ticker.get('close') or 0)
                if price > 0:
                    if cache_key and self._price_cache_ttl_sec > 0:
                        try:
                            with self._price_cache_lock:
                                self._price_cache[cache_key] = (float(price), time.time() + self._price_cache_ttl_sec)
                        except Exception:
                            pass
                    return price
        except Exception as e:
            logger.warning(f"Failed to fetch price for {market_category}:{symbol}: {e}")
            
        return None

    def _server_side_stop_loss_signal(
        self,
        strategy_id: int,
        symbol: str,
        current_price: float,
        market_type: str,
        leverage: float,
        trading_config: Dict[str, Any],
        timeframe_seconds: int,
    ) -> Optional[Dict[str, Any]]:
        """Generate server-side stop-loss close signals when price crosses stop levels."""
        try:
            if trading_config is None:
                return None
            # Grid / DCA bots use a different risk model; their entry_price is
            # a sliding average across many fills, so "price vs entry %" is
            # meaningless. They are handled by ``_grid_bot_risk_exits`` which is
            # invoked separately in the strategy loop.
            bot_type = str((trading_config or {}).get('bot_type') or '').strip().lower()
            if bot_type in ('grid', 'dca'):
                return None

            if self._strategy_owns_exits(trading_config):
                return None

            if not self._is_server_side_exit_enabled(trading_config, 'enable_server_side_stop_loss'):
                return None

            current_positions = self._get_current_positions(strategy_id, symbol)
            if not current_positions:
                return None

            sl = float(self._risk_params_from_trading_config(trading_config).get("stop_loss_ratio") or 0)
            if sl <= 0:
                return None

            now_ts = int(time.time())
            tf = int(timeframe_seconds or 60)
            candle_ts = int(now_ts // tf) * tf

            for pos in current_positions:
                side = (pos.get('side') or '').strip().lower()
                if side not in ('long', 'short'):
                    continue

                entry_price = float(pos.get('entry_price', 0) or 0)
                if entry_price <= 0 or current_price <= 0:
                    continue

                if side == 'long':
                    stop_line = entry_price * (1 - sl)
                    if current_price <= stop_line:
                        return {
                            'type': 'close_long',
                            'trigger_price': float(current_price),
                            'position_size': float(pos.get('size') or 0.0),
                            'timestamp': candle_ts,
                            'reason': 'server_stop_loss',
                            'matched_entry_price': entry_price,
                            'stop_loss_price': stop_line,
                        }
                else:
                    stop_line = entry_price * (1 + sl)
                    if current_price >= stop_line:
                        return {
                            'type': 'close_short',
                            'trigger_price': float(current_price),
                            'position_size': float(pos.get('size') or 0.0),
                            'timestamp': candle_ts,
                            'reason': 'server_stop_loss',
                            'matched_entry_price': entry_price,
                            'stop_loss_price': stop_line,
                        }

            return None
        except Exception as e:
            logger.warning(f"Strategy {strategy_id} server-side stop-loss check failed: {str(e)}")
            return None

    def _server_side_take_profit_or_trailing_signal(
        self,
        strategy_id: int,
        symbol: str,
        current_price: float,
        market_type: str,
        leverage: float,
        trading_config: Dict[str, Any],
        timeframe_seconds: int,
        execution_mode: str = "signal",
    ) -> Optional[Dict[str, Any]]:
        """
        Server-side exits driven by trading_config / @strategy code annotations:
        - Fixed take-profit: takeProfitPct
        - Trailing stop: trailingEnabled + trailingStopPct + trailingActivationPct

        Semantics align with UnifiedBacktestService:
        - Percentages are the underlying's % price move (0.001 = 0.1%).
        - Leverage does NOT divide or scale trigger thresholds.
        - When trailing is enabled, fixed take-profit is disabled to avoid ambiguity.
        """
        try:
            if not trading_config:
                return None

            bot_type = str((trading_config or {}).get('bot_type') or '').strip().lower()
            if bot_type in ('grid', 'dca'):
                # Grid / DCA bots: see ``_grid_bot_risk_exits``.
                return None

            if self._strategy_owns_exits(trading_config):
                return None

            if not self._is_server_side_exit_enabled(trading_config, 'enable_server_side_take_profit'):
                return None

            current_positions = self._get_current_positions(strategy_id, symbol)
            if not current_positions:
                return None

            # TP / trailing are the underlying's % price move; leverage does not
            # affect trigger thresholds (only PnL magnitude / liquidation).
            risk_params = self._risk_params_from_trading_config(trading_config)
            tp = float(risk_params.get("take_profit_ratio") or 0)
            trailing_enabled = bool(risk_params.get("trailing_enabled"))
            trailing_pct = float(risk_params.get("trailing_stop_ratio") or 0)
            trailing_act = float(risk_params.get("trailing_activation_ratio") or 0)

            tp_eff = tp if tp > 0 else 0.0
            trailing_pct_eff = trailing_pct if trailing_pct > 0 else 0.0
            trailing_act_eff = trailing_act if trailing_act > 0 else 0.0
            trailing_fee_rate = self._effective_taker_fee_rate(strategy_id, trading_config)

            # Conflict rule: when trailing is enabled, fixed TP is disabled.
            if trailing_enabled and trailing_pct_eff > 0:
                tp_eff = 0.0
                if trailing_act_eff <= 0 and tp > 0:
                    trailing_act_eff = tp

            now_ts = int(time.time())
            tf = int(timeframe_seconds or 60)
            candle_ts = int(now_ts // tf) * tf

            for pos in current_positions:
                side = (pos.get('side') or '').strip().lower()
                if side not in ('long', 'short'):
                    continue

                entry_price = float(pos.get('entry_price', 0) or 0)
                if entry_price <= 0 or current_price <= 0:
                    continue

                try:
                    hp = float(pos.get('highest_price') or 0.0)
                except Exception:
                    hp = 0.0
                try:
                    lp = float(pos.get('lowest_price') or 0.0)
                except Exception:
                    lp = 0.0

                if hp <= 0:
                    hp = entry_price
                hp = max(hp, float(current_price))

                if lp <= 0:
                    lp = entry_price
                lp = min(lp, float(current_price))

                try:
                    self._update_position(
                        strategy_id=strategy_id,
                        symbol=pos.get('symbol') or symbol,
                        side=side,
                        size=float(pos.get('size') or 0.0),
                        entry_price=entry_price,
                        current_price=float(current_price),
                        highest_price=hp,
                        lowest_price=lp,
                        execution_mode=execution_mode,
                    )
                except Exception:
                    pass

                if trailing_enabled and trailing_pct_eff > 0:
                    if side == 'long':
                        active = True
                        if trailing_act_eff > 0:
                            active = hp >= entry_price * (1 + trailing_act_eff)
                        if active:
                            stop_line = hp * (1 - trailing_pct_eff)
                            if current_price <= stop_line and trailing_exit_locks_net_profit(
                                "long",
                                entry_price=entry_price,
                                exit_price=float(current_price),
                                fee_rate=trailing_fee_rate,
                            ):
                                return {
                                    'type': 'close_long',
                                    'trigger_price': float(current_price),
                                    'position_size': float(pos.get('size') or 0.0),
                                    'timestamp': candle_ts,
                                    'reason': 'server_trailing_stop',
                                    'matched_entry_price': entry_price,
                                    'trailing_stop_price': stop_line,
                                    'highest_price': hp,
                                }
                    else:
                        active = True
                        if trailing_act_eff > 0:
                            active = lp <= entry_price * (1 - trailing_act_eff)
                        if active:
                            stop_line = lp * (1 + trailing_pct_eff)
                            if current_price >= stop_line and trailing_exit_locks_net_profit(
                                "short",
                                entry_price=entry_price,
                                exit_price=float(current_price),
                                fee_rate=trailing_fee_rate,
                            ):
                                return {
                                    'type': 'close_short',
                                    'trigger_price': float(current_price),
                                    'position_size': float(pos.get('size') or 0.0),
                                    'timestamp': candle_ts,
                                    'reason': 'server_trailing_stop',
                                    'matched_entry_price': entry_price,
                                    'trailing_stop_price': stop_line,
                                    'lowest_price': lp,
                                }

                if tp_eff > 0:
                    if side == 'long':
                        tp_line = entry_price * (1 + tp_eff)
                        if current_price >= tp_line:
                            return {
                                'type': 'close_long',
                                'trigger_price': float(current_price),
                                'position_size': float(pos.get('size') or 0.0),
                                'timestamp': candle_ts,
                                'reason': 'server_take_profit',
                                'matched_entry_price': entry_price,
                                'take_profit_price': tp_line,
                            }
                    else:
                        tp_line = entry_price * (1 - tp_eff)
                        if current_price <= tp_line:
                            return {
                                'type': 'close_short',
                                'trigger_price': float(current_price),
                                'position_size': float(pos.get('size') or 0.0),
                                'timestamp': candle_ts,
                                'reason': 'server_take_profit',
                                'matched_entry_price': entry_price,
                                'take_profit_price': tp_line,
                            }

            return None
        except Exception:
            return None

    def _grid_bot_risk_exits(
        self,
        strategy_id: int,
        symbol: str,
        current_price: float,
        trading_config: Dict[str, Any],
        timeframe_seconds: int,
        initial_capital: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Server-side risk exits dedicated to grid/DCA bots.

        Two complementary trigger families, both designed for a strategy whose
        ``entry_price`` is a noisy sliding average:
        1. **Drawdown / take-profit on account equity**: code-owned risk
           values are interpreted as equity moves vs initial capital.
        2. **Out-of-grid price protection**: ``grid_oob_buffer_pct`` (default
           5%) plus ``upperPrice`` / ``lowerPrice`` from ``bot_params``: if
           price spikes far above or far below the configured grid, close both
           legs to stop the bot from bleeding on a trending breakout.

        Returns *all* close legs in one call (long first, then short) so the
        executor can fan them out as separate exchange orders within the same
        tick.
        """
        try:
            tc = trading_config if isinstance(trading_config, dict) else {}
            bot_type = str(tc.get('bot_type') or '').strip().lower()
            if bot_type not in ('grid', 'dca'):
                return []

            positions = self._get_current_positions(strategy_id, symbol)
            if not positions:
                return []

            has_long = any(
                (str(p.get('side') or '').lower() == 'long' and float(p.get('size') or 0) > 0)
                for p in positions
            )
            has_short = any(
                (str(p.get('side') or '').lower() == 'short' and float(p.get('size') or 0) > 0)
                for p in positions
            )
            if not has_long and not has_short:
                return []

            now_ts = int(time.time())
            tf = int(timeframe_seconds or 60)
            candle_ts = int(now_ts // tf) * tf

            def _close_all(reason: str, **extra: Any) -> List[Dict[str, Any]]:
                exits: List[Dict[str, Any]] = []
                if has_long:
                    exits.append({
                        'type': 'close_long',
                        'trigger_price': 0,
                        'position_size': 0,
                        'timestamp': candle_ts,
                        'reason': reason,
                        **extra,
                    })
                if has_short:
                    exits.append({
                        'type': 'close_short',
                        'trigger_price': 0,
                        'position_size': 0,
                        'timestamp': candle_ts,
                        'reason': reason,
                        **extra,
                    })
                return exits

            # --- 1) Out-of-grid breakout protection -------------------------
            bot_params = tc.get('bot_params') if isinstance(tc.get('bot_params'), dict) else {}
            try:
                upper = float(bot_params.get('upperPrice') or 0)
            except Exception:
                upper = 0.0
            try:
                lower = float(bot_params.get('lowerPrice') or 0)
            except Exception:
                lower = 0.0
            try:
                oob_buf = self._to_ratio(tc.get('grid_oob_buffer_pct'), default=0.05)
            except Exception:
                oob_buf = 0.05

            if upper > 0 and lower > 0 and upper > lower and current_price > 0 and oob_buf > 0:
                if current_price >= upper * (1 + oob_buf):
                    return _close_all(
                        'grid_out_of_bounds_up',
                        oob_threshold=upper * (1 + oob_buf),
                        upper_price=upper,
                    )
                if current_price <= lower * (1 - oob_buf):
                    return _close_all(
                        'grid_out_of_bounds_down',
                        oob_threshold=lower * (1 - oob_buf),
                        lower_price=lower,
                    )

            # --- 2) Equity drawdown / take-profit ---------------------------
            init_cap = float(initial_capital or 0)
            if init_cap <= 0:
                # Fall back to whatever the strategy recorded as starting balance.
                try:
                    with get_db_connection() as db:
                        cur = db.cursor()
                        cur.execute(
                            "SELECT trading_config FROM qd_strategies_trading WHERE id = %s",
                            (strategy_id,),
                        )
                        row = cur.fetchone() or {}
                        cur.close()
                        tc_db = row.get('trading_config')
                        if isinstance(tc_db, str) and tc_db.strip():
                            try:
                                tc_db = json.loads(tc_db)
                            except Exception:
                                tc_db = {}
                        if isinstance(tc_db, dict):
                            init_cap = float(tc_db.get('initial_capital') or 0)
                except Exception:
                    init_cap = 0.0

            risk_params = self._risk_params_from_trading_config(tc)
            sl_pct = float(risk_params.get('stop_loss_ratio') or 0)
            tp_pct = float(risk_params.get('take_profit_ratio') or 0)
            if sl_pct <= 0:
                sl_pct = self._to_ratio(tc.get('stop_loss_pct'), default=0.0)
            if tp_pct <= 0:
                tp_pct = self._to_ratio(tc.get('take_profit_pct'), default=0.0)

            if init_cap > 0 and (sl_pct > 0 or tp_pct > 0):
                equity = self._calculate_current_equity(
                    strategy_id,
                    init_cap,
                    current_positions=positions,
                    current_price=current_price,
                    symbol=symbol,
                )
                pnl_pct = (equity - init_cap) / init_cap

                if sl_pct > 0 and pnl_pct <= -sl_pct:
                    return _close_all(
                        'grid_equity_stop_loss',
                        equity=equity,
                        initial_capital=init_cap,
                        equity_pct=pnl_pct,
                    )
                if tp_pct > 0 and pnl_pct >= tp_pct:
                    return _close_all(
                        'grid_equity_take_profit',
                        equity=equity,
                        initial_capital=init_cap,
                        equity_pct=pnl_pct,
                    )

            return []
        except Exception as e:
            logger.warning(f"Strategy {strategy_id} grid risk-exit check failed: {e}")
            return []

    def _is_server_side_exit_enabled(self, trading_config: Optional[Dict[str, Any]], config_key: str) -> bool:
        """
        Determine if a server-side exit (SL/TP) should be active.

        For non-bot strategies: enabled by default (historical behavior).
        For bot strategies: enabled only when the corresponding pct value > 0,
        since the user explicitly configured it in the risk form.
        """
        tc = trading_config if isinstance(trading_config, dict) else {}
        bot_type = str(tc.get('bot_type') or '').strip().lower()

        if config_key in tc:
            v = tc[config_key]
            if isinstance(v, str):
                return v.strip().lower() not in ['0', 'false', 'no', 'off']
            return bool(v)

        if not bot_type:
            return True

        if config_key == 'enable_server_side_stop_loss':
            sl = float(self._risk_params_from_trading_config(tc).get('stop_loss_ratio') or 0)
            return sl > 0
        if config_key == 'enable_server_side_take_profit':
            risk = self._risk_params_from_trading_config(tc)
            tp = float(risk.get('take_profit_ratio') or 0)
            trailing = bool(risk.get('trailing_enabled')) and float(risk.get('trailing_stop_ratio') or 0) > 0
            return tp > 0 or trailing

        return False
    
    def _klines_to_dataframe(self, klines: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert K-line dictionaries into a numeric DataFrame."""
        if not klines:
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        
        df = pd.DataFrame(klines)
        
        # Convert time column.
        # IMPORTANT: use UTC tz-aware index to avoid timezone skew when computing candle boundaries.
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df = df.set_index('time')
        elif 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
            df = df.set_index('timestamp')
        
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        available_columns = [col for col in required_columns if col in df.columns]
        if not available_columns:
            logger.warning("K-lines are missing required columns")
            return pd.DataFrame(columns=required_columns)
        
        df = df[available_columns]
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
        
        df = df.dropna()
        
        return df

    def _update_dataframe_with_current_price(self, df: pd.DataFrame, current_price: float, timeframe: str) -> pd.DataFrame:
        """Update the last DataFrame candle with the current price for live calculations."""
        if df is None or len(df) == 0:
            return df
            
        try:
            last_time = df.index[-1]
            
            from app.data_sources.base import TIMEFRAME_SECONDS
            timeframe_key = timeframe
            if timeframe_key not in TIMEFRAME_SECONDS:
                timeframe_key = str(timeframe_key).upper()
            if timeframe_key not in TIMEFRAME_SECONDS:
                timeframe_key = str(timeframe_key).lower()
            tf_seconds = TIMEFRAME_SECONDS.get(timeframe_key, 60)
            
            # Use epoch seconds directly to avoid naive datetime timezone conversion issues.
            last_ts = float(last_time.timestamp())
            now_ts = float(time.time())
            
            current_period_start = int(now_ts // tf_seconds) * tf_seconds
            
            if abs(last_ts - current_period_start) < 2:
                df.iloc[-1, df.columns.get_loc('close')] = current_price
                df.iloc[-1, df.columns.get_loc('high')] = max(df.iloc[-1]['high'], current_price)
                df.iloc[-1, df.columns.get_loc('low')] = min(df.iloc[-1]['low'], current_price)
            elif current_period_start > last_ts:
                new_row = pd.DataFrame({
                    'open': [current_price],
                    'high': [current_price],
                    'low': [current_price],
                    'close': [current_price],
                    'volume': [0.0]
                }, index=[pd.to_datetime(current_period_start, unit='s', utc=True)])
                
                df = pd.concat([df, new_row])
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to update realtime candle: {str(e)}")
            return df
    
    def _get_current_positions(self, strategy_id: int, symbol: str) -> List[Dict[str, Any]]:
        """Load current local positions for a strategy and symbol."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                query = """
                    SELECT id, symbol, side, size, entry_price, highest_price, lowest_price
                    FROM qd_strategy_positions
                    WHERE strategy_id = %s
                """
                cursor.execute(query, (strategy_id,))
                all_positions = cursor.fetchall()
                
                matched_positions = []
                for pos in all_positions:
                    if pos['symbol'].split(':')[0] == symbol.split(':')[0]:
                        matched_positions.append(pos)
                
                cursor.close()
                return matched_positions
        except Exception as e:
            logger.error(f"Failed to fetch positions: {str(e)}")
            return []

    def _simulated_open_qty_from_trade_rows(self, strategy_id: int, symbol: str, side: str) -> float:
        """Best-effort net open quantity from signal/paper trade rows.

        ``qd_strategy_positions`` can become stale after manual DB edits or older
        paper-trading bugs. Before recording a simulated close, require a
        corresponding unclosed trade leg so stale position rows cannot create
        ghost close profit.
        """
        side_norm = (side or "").strip().lower()
        if side_norm not in ("long", "short"):
            return 0.0
        sym_key = str(symbol or "").split(":")[0].strip()
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    """
                    SELECT symbol, type, amount
                    FROM qd_strategy_trades
                    WHERE strategy_id = %s
                    ORDER BY id ASC
                    """,
                    (int(strategy_id),),
                )
                rows = cursor.fetchall() or []
                cursor.close()
        except Exception as e:
            logger.warning(f"Failed to calculate simulated open qty: strategy={strategy_id}, err={e}")
            return 0.0

        qty = 0.0
        for row in rows:
            row_symbol = str((row or {}).get("symbol") or "").split(":")[0].strip()
            if row_symbol != sym_key:
                continue
            typ = str((row or {}).get("type") or "").strip().lower()
            amount = float((row or {}).get("amount") or 0.0)
            if amount <= 0:
                continue
            if side_norm == "long":
                if typ in ("open_long", "add_long"):
                    qty += amount
                elif typ in ("close_long", "reduce_long"):
                    qty -= amount
            else:
                if typ in ("open_short", "add_short"):
                    qty += amount
                elif typ in ("close_short", "reduce_short"):
                    qty -= amount
        return max(0.0, qty)

    def _execute_signal(
        self,
        strategy_id: int,
        strategy_name: str,
        exchange: Any,
        symbol: str,
        current_price: float,
        signal_type: str,
        position_size: float,
        current_positions: List[Dict[str, Any]],
        trade_direction: str,
        leverage: int,
        initial_capital: float,
        market_type: str = 'swap',
        market_category: str = 'Crypto',
        margin_mode: str = 'cross',
        stop_loss_price: float = None,
        take_profit_price: float = None,
        signal_reason: str = "",
        matched_entry_price: Optional[float] = None,
        trailing_stop_price: float = None,
        execution_mode: str = 'signal',
        notification_config: Optional[Dict[str, Any]] = None,
        trading_config: Optional[Dict[str, Any]] = None,
        signal_ts: int = 0,
        price_exchange_id: Optional[str] = None,
        script_base_qty: Optional[float] = None,
        script_quote_amount: Optional[float] = None,
        strategy_run_id: int = 0,
        order_intent_id: int = 0,
        idempotency_key: str = "",
        basket_id: str = "",
        basket_order_db_id: int = 0,
        layer_index: int = 0,
        order_index: int = 0,
        execution_algo: str = "",
        order_type: str = "",
        limit_price: float = 0.0,
    ):
        """Generate and persist a trading signal when state checks allow it."""
        try:
            # Hard state-machine guard (double safety in addition to loop-level filtering).
            state = self._effective_position_state(strategy_id, symbol, current_positions)
            if not self._is_signal_allowed(state, signal_type):
                append_strategy_log(strategy_id, "info", f"Signal filtered by state machine: {signal_type} (state={state})")
                return False

            sig = (signal_type or "").strip().lower()

            if market_type == 'spot' and 'short' in signal_type:
                 append_strategy_log(strategy_id, "info", f"Signal rejected: spot market does not support {signal_type}")
                 return False

            # 1.2 Max position limit (risk control)
            if sig in ("open_long", "open_short", "add_long", "add_short"):
                max_pos = float((trading_config or {}).get('max_position') or 0)
                if max_pos > 0:
                    cur_pos_value = self._current_position_value(current_positions, current_price)
                    if cur_pos_value >= max_pos:
                        append_strategy_log(
                            strategy_id, "info",
                            f"Risk: max_position reached ({cur_pos_value:.2f} >= {max_pos:.2f}), blocking {sig}",
                        )
                        return False

            # 1.3 Max daily loss limit (risk control)
            if sig in ("open_long", "open_short", "add_long", "add_short"):
                max_daily = float((trading_config or {}).get('max_daily_loss') or 0)
                if max_daily > 0:
                    daily_pnl = self._get_daily_pnl(strategy_id)
                    if daily_pnl < 0 and abs(daily_pnl) >= max_daily:
                        append_strategy_log(
                            strategy_id, "info",
                            f"Risk: max_daily_loss reached (loss={abs(daily_pnl):.2f} >= {max_daily:.2f}), blocking {sig}",
                        )
                        return False

            available_capital = self._get_available_capital(
                strategy_id,
                initial_capital,
                current_positions=current_positions,
                current_price=current_price,
                symbol=symbol,
            )
            
            amount = 0.0

            bot_type = (trading_config or {}).get('bot_type', '')
            is_bot_script = bool(bot_type)

            try:
                explicit_script_qty = (
                    float(script_base_qty)
                    if script_base_qty is not None and float(script_base_qty) > 0
                    else None
                )
            except Exception:
                explicit_script_qty = None
            try:
                explicit_script_quote = (
                    float(script_quote_amount)
                    if script_quote_amount is not None and float(script_quote_amount) > 0
                    else None
                )
            except Exception:
                explicit_script_quote = None

            sizing_meta: Dict[str, Any] = {}

            # Frontend position sizing alignment:
            # - non-bot open_* uses entry_pct from trading_config if provided
            # - ctx.basket(..., notional=...) / bot ctx.buy(amount=...) pass quote notional
            # - script strategies with ctx.buy(price, qty) pass script_base_qty (base coins)
            entry_ratio_override = None
            if (
                explicit_script_qty is None
                and (not is_bot_script)
                and sig in ("open_long", "open_short")
                and isinstance(trading_config, dict)
            ):
                entry_ratio = self._risk_params_from_trading_config(trading_config).get("entry_ratio")
                if entry_ratio is not None and float(entry_ratio) > 0:
                    position_size = float(entry_ratio)
                    entry_ratio_override = float(entry_ratio)

            # Open / add sizing
            if ('open' in sig or 'add' in sig):
                 if explicit_script_quote is not None:
                     if current_price > 0:
                         if market_type == 'spot':
                             from app.services.live_trading.spot_sizing import scale_spot_open_notional
                             quote_stake = scale_spot_open_notional(float(explicit_script_quote))
                             amount = quote_stake / current_price
                             sizing_meta = {"source": "script_quote", "entry_ratio": None, "quote_notional": quote_stake}
                         else:
                             amount = (float(explicit_script_quote) * leverage) / current_price
                             sizing_meta = {"source": "script_quote", "entry_ratio": None, "quote_notional": float(explicit_script_quote) * float(leverage or 1)}
                 elif explicit_script_qty is not None and not is_bot_script:
                     amount = explicit_script_qty
                     sizing_meta = {"source": "script_base_qty", "entry_ratio": None, "quote_notional": float(amount or 0.0) * float(current_price or 0.0)}
                 elif position_size is None or float(position_size) <= 0:
                     position_size = 0.05

                 if explicit_script_quote is None and explicit_script_qty is None and is_bot_script and float(position_size) > 1.0:
                     # Bot scripts pass amount as absolute USDT notional, not ratio.
                     usdt_notional = float(position_size)
                     if market_type == 'spot':
                         from app.services.live_trading.spot_sizing import scale_spot_open_notional
                         usdt_notional = scale_spot_open_notional(usdt_notional)
                         amount = usdt_notional / current_price
                     else:
                         amount = (usdt_notional * leverage) / current_price
                     sizing_meta = {"source": "bot_quote_notional", "entry_ratio": None, "quote_notional": usdt_notional * (float(leverage or 1) if market_type != 'spot' else 1.0)}
                 elif explicit_script_quote is None and explicit_script_qty is None:
                     use_code_ratios = bool(self._code_strategy_cfg(trading_config))
                     if use_code_ratios and sig in ("open_long", "open_short", "add_long", "add_short"):
                         position_ratio = float(position_size)
                         sizing_source = "code_strategy_entryPct"
                     elif entry_ratio_override is not None:
                         position_ratio = float(entry_ratio_override)
                         sizing_source = "trading_config_entry_pct"
                     else:
                         position_ratio = self._to_ratio(position_size, default=0.05)
                         sizing_source = "signal_position_size"
                     if market_type == 'spot':
                         from app.services.live_trading.spot_sizing import scale_spot_open_notional
                         quote_stake = scale_spot_open_notional(available_capital * position_ratio)
                         amount = quote_stake / current_price
                         quote_notional = quote_stake
                     else:
                         amount = (available_capital * position_ratio * leverage) / current_price
                         quote_notional = available_capital * position_ratio * float(leverage or 1)
                     sizing_meta = {
                         "source": sizing_source,
                         "initial_capital": float(initial_capital or 0.0),
                         "available_capital": float(available_capital or 0.0),
                         "entry_ratio": float(position_ratio or 0.0),
                         "entry_pct": float(position_ratio or 0.0) * 100.0,
                         "leverage": float(leverage or 1.0),
                         "price": float(current_price or 0.0),
                         "quote_notional": float(quote_notional or 0.0),
                     }

            # Reduce sizing: position_size is treated as a reduce ratio (close X% of current position).
            if sig in ("reduce_long", "reduce_short"):
                pos_side = "long" if "long" in sig else "short"
                pos = next((p for p in current_positions if (p.get('side') or '').strip().lower() == pos_side), None)
                if not pos:
                    return False
                cur_size = float(pos.get("size") or 0.0)
                if cur_size <= 0:
                    return False
                if explicit_script_qty is not None:
                    reduce_amount = min(cur_size, float(explicit_script_qty))
                    reduce_ratio = reduce_amount / cur_size if cur_size > 0 else 0.0
                    sizing_meta = {"source": "script_base_qty", "reduce_ratio": float(reduce_ratio)}
                elif explicit_script_quote is not None and current_price > 0:
                    quote_qty = (
                        float(explicit_script_quote) / current_price
                        if market_type == 'spot'
                        else (float(explicit_script_quote) * leverage) / current_price
                    )
                    reduce_amount = min(cur_size, quote_qty)
                    reduce_ratio = reduce_amount / cur_size if cur_size > 0 else 0.0
                    sizing_meta = {"source": "script_quote", "reduce_ratio": float(reduce_ratio), "quote_notional": float(explicit_script_quote)}
                else:
                    reduce_ratio = self._to_ratio(position_size, default=0.5)
                    reduce_amount = cur_size * reduce_ratio
                    sizing_meta = {"source": "signal_position_size", "reduce_ratio": float(reduce_ratio)}
                # If reduce is effectively full, treat as close_*.
                if reduce_amount >= cur_size * 0.999:
                    sig = "close_long" if pos_side == "long" else "close_short"
                    signal_type = sig
                    amount = cur_size
                else:
                    amount = reduce_amount
            

            # 4. Execute order enqueue (PendingOrderWorker will dispatch notifications in signal mode)
            if 'close' in sig:
                pos_side = 'long' if 'long' in sig else 'short'
                pos = next((p for p in current_positions if (p.get('side') or '').strip().lower() == pos_side), None)
                if not pos:
                    append_strategy_log(
                        strategy_id, "info",
                        f"Skip close: no local {pos_side} position for {symbol} ({sig})",
                    )
                    return False
                full_size = float(pos.get('size') or 0.0)
                if full_size <= 0:
                    append_strategy_log(
                        strategy_id, "info",
                        f"Skip close: zero local size for {symbol} ({sig})",
                    )
                    return False

                if is_bot_script and position_size is not None and float(position_size) > 1.0 and current_price > 0:
                    usdt_notional = float(position_size)
                    close_qty = (usdt_notional * leverage) / current_price if market_type != 'spot' else usdt_notional / current_price
                    if close_qty < full_size * 0.99:
                        amount = close_qty
                        sig = f"reduce_{pos_side}"
                        signal_type = sig
                    else:
                        amount = full_size
                elif explicit_script_qty is not None:
                    amount = min(float(explicit_script_qty), full_size)
                    if amount < full_size * 0.999:
                        sig = f"reduce_{pos_side}"
                        signal_type = sig
                else:
                    amount = full_size

            if str(execution_mode or "").strip().lower() == "signal" and (
                sig.startswith("close_") or sig.startswith("reduce_")
            ):
                pos_side = "long" if "long" in sig else "short"
                pos = next((p for p in current_positions if (p.get('side') or '').strip().lower() == pos_side), None)
                local_size = float((pos or {}).get("size") or 0.0)
                open_qty = self._simulated_open_qty_from_trade_rows(strategy_id, symbol, pos_side)
                eps = max(1e-12, local_size * 1e-9)
                if open_qty <= eps:
                    append_strategy_log(
                        strategy_id,
                        "warning",
                        (
                            f"Skip {sig}: no unmatched {pos_side} entry trade for {symbol}; "
                            "purging stale simulated position to prevent ghost close PnL"
                        ),
                    )
                    if local_size > 0:
                        self._close_position(strategy_id, symbol, pos_side)
                    return False
                if amount > open_qty:
                    append_strategy_log(
                        strategy_id,
                        "warning",
                        (
                            f"Clamp {sig}: local_size={local_size:.12f}, "
                            f"trade_open_qty={open_qty:.12f}, requested={amount:.12f}"
                        ),
                    )
                    amount = open_qty
                    if sig.startswith("reduce_"):
                        sig = "close_long" if pos_side == "long" else "close_short"
                        signal_type = sig

            if amount <= 0 and ('open' in signal_type or 'add' in signal_type):
                return False

            if ('open' in sig or 'add' in sig) and current_price > 0:
                try:
                    sizing_meta.update(
                        {
                            "final_qty": float(amount or 0.0),
                            "final_notional": float(amount or 0.0) * float(current_price or 0.0),
                            "market_type": str(market_type or ""),
                            "signal_type": str(signal_type or ""),
                        }
                    )
                    append_strategy_log(
                        strategy_id,
                        "info",
                        (
                            "Order sizing: "
                            f"capital={float(sizing_meta.get('initial_capital') or initial_capital or 0):.4f}, "
                            f"available={float(sizing_meta.get('available_capital') or available_capital or 0):.4f}, "
                            f"entry_pct={float(sizing_meta.get('entry_pct') or 0):.4f}%, "
                            f"leverage={float(leverage or 1):.4f}x, "
                            f"price={float(current_price or 0):.8f}, "
                            f"qty={float(amount or 0):.12f}, "
                            f"notional={float(sizing_meta.get('final_notional') or 0):.4f}, "
                            f"source={sizing_meta.get('source') or 'unknown'}"
                        ),
                    )
                except Exception:
                    pass

            if (explicit_script_qty is not None or explicit_script_quote is not None) and ('open' in sig or 'add' in sig) and current_price > 0:
                requested_notional = float(amount or 0.0) * float(current_price or 0.0)
                max_notional = float(available_capital or 0.0) * (float(leverage or 1.0) if market_type != 'spot' else 1.0)
                if max_notional > 0 and requested_notional > max_notional * 1.000001:
                    append_strategy_log(strategy_id, "info", f"Risk: script order amount exceeds capital ({requested_notional:.2f} > {max_notional:.2f}); check quote/base sizing")
                    return False
            
            bot_order_mode = (trading_config or {}).get('order_mode') or None
            execution_algo_norm = str(execution_algo or "").strip().lower()
            order_type_norm = str(order_type or "").strip().lower()
            if execution_algo_norm == "market":
                bot_order_mode = "market"
            elif execution_algo_norm in ("limit_then_market", "maker", "maker_then_market"):
                bot_order_mode = "maker_then_market"
            elif execution_algo_norm == "limit" or order_type_norm == "limit":
                bot_order_mode = "limit"
            order_result = self._submit_signal_order(
                exchange=exchange,
                strategy_id=strategy_id,
                symbol=symbol,
                signal_type=signal_type,
                amount=amount,
                ref_price=float(current_price or 0.0),
                market_type=market_type,
                market_category=market_category,
                price_exchange_id=price_exchange_id,
                leverage=leverage,
                execution_mode=execution_mode,
                notification_config=notification_config,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                signal_reason=signal_reason,
                trailing_stop_price=trailing_stop_price,
                signal_ts=int(signal_ts or 0),
                order_mode=bot_order_mode,
                execution_algo=execution_algo_norm,
                order_type=order_type_norm,
                limit_price=float(limit_price or (current_price if order_type_norm == "limit" else 0.0) or 0.0),
                sizing_meta=sizing_meta if sizing_meta else None,
                strategy_run_id=int(strategy_run_id or ((trading_config or {}).get('_strategy_run_id') if isinstance(trading_config, dict) else 0) or 0),
                order_intent_id=int(order_intent_id or 0),
                idempotency_key=str(idempotency_key or ""),
                basket_id=str(basket_id or ""),
                basket_order_db_id=int(basket_order_db_id or 0),
                layer_index=int(layer_index or 0),
                order_index=int(order_index or 0),
            )
            
            if order_result and order_result.get('success'):
                # For live execution, the order is only enqueued here.
                # The actual fill/trade/position updates are performed by PendingOrderWorker.
                if str(execution_mode or "").strip().lower() == "live":
                    return True

                # Prefer real exchange fee-rate; fall back to user-configured rate.
                _comm_rate = self._effective_taker_fee_rate(strategy_id, trading_config)
                _est_commission = round(float(current_price or 0) * float(amount or 0) * _comm_rate, 8)
                from app.utils.trade_close_reason import resolve_close_reason_for_record
                _exit_reason = resolve_close_reason_for_record(
                    signal_type,
                    signal_reason=str(signal_reason or ""),
                    trading_config=trading_config,
                )

                if 'open' in sig or 'add' in sig:
                    self._record_trade(
                        strategy_id=strategy_id, symbol=symbol, type=signal_type,
                        price=current_price, amount=amount, value=amount*current_price,
                        commission=_est_commission,
                        matched_entry_price=current_price,
                    )
                    side = 'short' if 'short' in signal_type else 'long'
                    
                    old_pos = next((p for p in current_positions if p['side'] == side), None)
                    new_size = amount
                    new_entry = current_price
                    if old_pos:
                        old_size = float(old_pos['size'])
                        old_entry = float(old_pos['entry_price'])
                        new_size += old_size
                        new_entry = ((old_size * old_entry) + (amount * current_price)) / new_size

                    self._update_position(
                        strategy_id=strategy_id, symbol=symbol, side=side,
                        size=new_size, entry_price=new_entry, current_price=current_price
                    )
                    append_strategy_log(
                        strategy_id, "trade",
                        f"Open position: {signal_type} {symbol} amount={amount:.6f} @ {current_price:.6f}, fee={_est_commission:.6f}",
                    )
                elif sig.startswith("reduce_"):
                    # Partial scale-out: reduce position size, keep entry price unchanged.
                    side = 'short' if 'short' in signal_type else 'long'
                    old_pos = next((p for p in current_positions if p.get('side') == side), None)
                    if not old_pos:
                        return True
                    old_size = float(old_pos.get('size') or 0.0)
                    old_entry = float(old_pos.get('entry_price') or 0.0)
                    
                    reduce_profit = None
                    if old_entry > 0 and amount > 0:
                        if side == 'long':
                            reduce_profit = (current_price - old_entry) * amount
                        else:
                            reduce_profit = (old_entry - current_price) * amount
                        reduce_profit = round(reduce_profit - _est_commission, 8)

                    self._record_trade(
                        strategy_id=strategy_id, symbol=symbol, type=signal_type,
                        price=current_price, amount=amount, value=amount*current_price,
                        profit=reduce_profit, commission=_est_commission,
                        close_reason=_exit_reason,
                        matched_entry_price=old_entry if old_entry > 0 else matched_entry_price,
                    )
                    
                    new_size = max(0.0, old_size - float(amount or 0.0))
                    if new_size <= old_size * 0.001:
                        self._close_position(strategy_id, symbol, side)
                    else:
                        self._update_position(
                            strategy_id=strategy_id, symbol=symbol, side=side,
                            size=new_size, entry_price=old_entry, current_price=current_price
                        )
                    _pstr = f", profit={reduce_profit:.4f}" if reduce_profit is not None else ""
                    append_strategy_log(
                        strategy_id, "trade",
                        f"Reduce position: {signal_type} {symbol} amount={amount:.6f} @ {current_price:.6f}, fee={_est_commission:.6f}{_pstr}",
                    )
                elif 'close' in sig:
                    side = 'short' if 'short' in signal_type else 'long'
                    old_pos = next((p for p in current_positions if p.get('side') == side), None)
                    
                    close_profit = None
                    if old_pos:
                        entry_price = float(old_pos.get('entry_price') or 0)
                        if entry_price > 0 and amount > 0:
                            if side == 'long':
                                close_profit = (current_price - entry_price) * amount
                            else:
                                close_profit = (entry_price - current_price) * amount
                            close_profit = round(close_profit - _est_commission, 8)

                    self._record_trade(
                        strategy_id=strategy_id, symbol=symbol, type=signal_type,
                        price=current_price, amount=amount, value=amount*current_price,
                        profit=close_profit, commission=_est_commission,
                        close_reason=_exit_reason,
                        matched_entry_price=entry_price if old_pos and entry_price > 0 else matched_entry_price,
                    )
                    self._close_position(strategy_id, symbol, side)
                    _pstr = f", profit={close_profit:.4f}" if close_profit is not None else ""
                    append_strategy_log(
                        strategy_id, "trade",
                        f"Close position: {signal_type} {symbol} amount={amount:.6f} @ {current_price:.6f}, fee={_est_commission:.6f}{_pstr}",
                    )

                return True

            _err = (order_result or {}).get("error", "unknown")
            append_strategy_log(strategy_id, "error", f"Order enqueue failed: {signal_type} {symbol}, error={_err}")
            return False
            
        except Exception as e:
            logger.error(f"Failed to execute signal: {e}")
            append_strategy_log(strategy_id, "error", f"Signal execution exception: {signal_type} {symbol}, {e}")
            return False

    def _submit_signal_order(
        self,
        exchange: Any,
        strategy_id: int,
        symbol: str,
        signal_type: str,
        amount: float,
        ref_price: Optional[float] = None,
        market_type: str = 'swap',
        market_category: str = 'Crypto',
        leverage: float = 1.0,
        margin_mode: str = 'cross',
        stop_loss_price: float = None,
        take_profit_price: float = None,
        signal_reason: str = "",
        trailing_stop_price: float = None,
        # Execution hints are persisted for the pending-order worker.
        order_mode: str = None,
        maker_retries: int = 3,
        close_fallback_to_market: bool = True,
        open_fallback_to_market: bool = True,
        execution_mode: str = 'signal',
        notification_config: Optional[Dict[str, Any]] = None,
        signal_ts: int = 0,
        price_exchange_id: Optional[str] = None,
        sizing_meta: Optional[Dict[str, Any]] = None,
        strategy_run_id: int = 0,
        order_intent_id: int = 0,
        idempotency_key: str = "",
        basket_id: str = "",
        basket_order_db_id: int = 0,
        layer_index: int = 0,
        order_index: int = 0,
        execution_algo: str = "",
        order_type: str = "",
        limit_price: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """Enqueue a pending order record; this method does not call exchanges directly."""
        try:
            # Reference price at enqueue time: use current tick price if provided to avoid extra fetch.
            if ref_price is None:
                ref_price = self._fetch_current_price(
                    None,
                    symbol,
                    market_type=market_type,
                    market_category=market_category,
                    exchange_id=price_exchange_id,
                    kline_market_type=market_type,
                ) or 0.0
            ref_price = float(ref_price or 0.0)

            extra_payload = {
                "ref_price": float(ref_price or 0.0),
                "signal_ts": int(signal_ts or 0),
                "stop_loss_price": float(stop_loss_price or 0.0) if stop_loss_price is not None else 0.0,
                "take_profit_price": float(take_profit_price or 0.0) if take_profit_price is not None else 0.0,
                "trailing_stop_price": float(trailing_stop_price or 0.0) if trailing_stop_price is not None else 0.0,
                "reason": str(signal_reason or "").strip(),
                "margin_mode": str(margin_mode or "cross"),
                "maker_retries": int(maker_retries or 0),
                "close_fallback_to_market": bool(close_fallback_to_market),
                "open_fallback_to_market": bool(open_fallback_to_market),
            }
            if order_mode:
                extra_payload["order_mode"] = order_mode
            if execution_algo:
                extra_payload["execution_algo"] = str(execution_algo)
            if order_type:
                extra_payload["order_type"] = str(order_type)
            if float(limit_price or 0.0) > 0:
                extra_payload["limit_price"] = float(limit_price)
            if sizing_meta and isinstance(sizing_meta, dict):
                extra_payload["sizing"] = sizing_meta
            runtime_meta = self._ensure_order_intent_for_enqueue(
                strategy_id=int(strategy_id or 0),
                strategy_run_id=int(strategy_run_id or 0),
                symbol=str(symbol or ""),
                signal_type=str(signal_type or ""),
                signal_ts=int(signal_ts or 0),
                market_type=str(market_type or "swap"),
                amount=float(amount or 0.0),
                ref_price=float(ref_price or 0.0),
                leverage=float(leverage or 1.0),
                order_intent_id=int(order_intent_id or 0),
                idempotency_key=str(idempotency_key or ""),
                basket_id=str(basket_id or ""),
                basket_order_db_id=int(basket_order_db_id or 0),
                layer_index=int(layer_index or 0),
                order_index=int(order_index or 0),
                extra_payload=extra_payload,
            )
            if runtime_meta:
                extra_payload.update(runtime_meta)
            pending_id = self._enqueue_pending_order(
                strategy_id=strategy_id,
                symbol=symbol,
                signal_type=signal_type,
                amount=float(amount or 0.0),
                price=float(ref_price or 0.0),
                signal_ts=int(signal_ts or 0),
                market_type=market_type,
                leverage=float(leverage or 1.0),
                execution_mode=execution_mode,
                notification_config=notification_config,
                extra_payload=extra_payload,
            )

            pending_flag = str(execution_mode or "").strip().lower() == "live"

            # Local "signal provider mode": we keep the local state machine moving forward.
            return {
                'success': True,
                'pending': bool(pending_flag),
                'order_id': f"pending_{pending_id or int(time.time()*1000)}",
                'filled_amount': 0 if pending_flag else amount,
                'filled_base_amount': 0 if pending_flag else amount,
                'filled_price': 0 if pending_flag else ref_price,
                'total_cost': 0 if pending_flag else (float(amount or 0.0) * float(ref_price or 0.0) if ref_price else 0),
                'fee': 0,
                'message': 'Order enqueued to pending_orders'
            }
        except Exception as e:
             logger.error(f"Signal execution failed: {e}")
             return {'success': False, 'error': str(e)}

    def _ensure_order_intent_for_enqueue(
        self,
        *,
        strategy_id: int,
        strategy_run_id: int,
        symbol: str,
        signal_type: str,
        signal_ts: int,
        market_type: str,
        amount: float,
        ref_price: float,
        leverage: float,
        order_intent_id: int = 0,
        idempotency_key: str = "",
        basket_id: str = "",
        basket_order_db_id: int = 0,
        layer_index: int = 0,
        order_index: int = 0,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create or reuse a runtime order intent before queueing work."""
        run_id = int(strategy_run_id or 0)
        if run_id <= 0 and not idempotency_key:
            return {}
        sig = str(signal_type or "").strip().lower()
        try:
            from app.services.strategy_runtime.order_intents import OrderIntentService
            from app.services.strategy_runtime.pipeline import OrderIntentBuilder
            from app.services.strategy_runtime.signals import StrategySignal

            svc = OrderIntentService(strategy_id=int(strategy_id or 0), strategy_run_id=run_id)
            signal = StrategySignal(
                timestamp=int(signal_ts or 0),
                strategy_id=int(strategy_id or 0),
                strategy_run_id=run_id,
                symbol=str(symbol or ""),
                action=sig,
                market_type=str(market_type or "swap"),
                amount=abs(float(amount or 0.0)),
                quote_amount=float((extra_payload or {}).get("script_quote_amount") or 0.0),
                price_hint=float(ref_price or 0.0),
                reason=str((extra_payload or {}).get("reason") or ""),
                source="trading_executor",
                metadata={
                    **dict(extra_payload or {}),
                    "order_type": str((extra_payload or {}).get("order_type") or "market"),
                    "execution_algo": str(
                        (extra_payload or {}).get("execution_algo")
                        or (extra_payload or {}).get("order_type")
                        or "market"
                    ),
                },
            )
            result = OrderIntentBuilder(svc).build(
                signal=signal,
                leverage=float(leverage or 1.0),
                idempotency_key=str(idempotency_key or ""),
                basket_id=str(basket_id or ""),
                basket_order_id=int(basket_order_db_id or 0),
                layer_index=int(layer_index or 0),
                order_index=int(order_index or 0),
                existing_order_intent_id=int(order_intent_id or 0),
                extra_payload=dict(extra_payload or {}),
            )
            return result.runtime_payload
        except Exception as e:
            logger.debug("ensure order intent skipped: %s", e)
            return {}

    def _enqueue_pending_order(
        self,
        strategy_id: int,
        symbol: str,
        signal_type: str,
        amount: float,
        price: float,
        signal_ts: int,
        market_type: str,
        leverage: float,
        execution_mode: str,
        notification_config: Optional[Dict[str, Any]] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """Insert a pending order record and return its id."""
        try:
            now = int(time.time())
            # Local deployment supports both "signal" and "live" (live is executed by PendingOrderWorker).
            mode = (execution_mode or "signal").strip().lower()
            if mode not in ("signal", "live"):
                mode = "signal"

            payload: Dict[str, Any] = {
                "strategy_id": int(strategy_id),
                "symbol": symbol,
                "signal_type": signal_type,
                "market_type": market_type,
                "amount": float(amount or 0.0),
                "price": float(price or 0.0),
                "leverage": float(leverage or 1.0),
                "execution_mode": mode,
                "notification_config": notification_config or {},
                "signal_ts": int(signal_ts or 0),
            }
            if extra_payload and isinstance(extra_payload, dict):
                payload.update(extra_payload)
            strategy_run_id = int(payload.get("strategy_run_id") or 0)
            order_intent_id = int(payload.get("order_intent_id") or 0)
            idempotency_key = str(payload.get("idempotency_key") or "").strip()

            with get_db_connection() as db:
                cur = db.cursor()

                # Extra dedup/cooldown guard (DB-based, more rigorous than local position state):
                # Script evaluation runs on a fixed tick cadence, and some strategies may keep emitting the same
                # entry/exit signal across multiple ticks/candles (especially when orders fail).
                # We prevent spamming the queue by skipping if a very recent identical order already exists.
                #
                # Rules:
                # - If signal_ts is provided (>0), treat (strategy_id, symbol, signal_type, signal_ts) as the canonical
                #   "same candle" key: if any record already exists, do NOT enqueue again.
                # - Otherwise, fall back to the older (strategy_id, symbol, signal_type) cooldown guard.
                cooldown_sec = 30  # keep small; worker already retries the claimed order via attempts/max_attempts
                try:
                    stsig = int(signal_ts or 0)
                    # Strict "same candle" de-dup applies to open and close signals.
                    # Rationale: 
                    # - open_* signals should only trigger once per candle (prevents repeated entries)
                    # - close_* signals should only trigger once per candle (prevents repeated close attempts)
                    # - add_*/reduce_* signals may legitimately trigger multiple times within same candle
                    #   as price evolves for DCA/scaling strategies
                    sig_norm = str(signal_type or "").strip().lower()
                    strict_candle_dedup = stsig > 0 and sig_norm in ("open_long", "open_short", "close_long", "close_short")

                    if idempotency_key:
                        cur.execute(
                            """
                            SELECT id, status, created_at
                            FROM pending_orders
                            WHERE idempotency_key = %s
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (idempotency_key,),
                        )
                    elif strict_candle_dedup:
                        cur.execute(
                            """
                            SELECT id, status, created_at
                            FROM pending_orders
                            WHERE strategy_id = %s
                              AND symbol = %s
                              AND signal_type = %s
                              AND signal_ts = %s
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (int(strategy_id), str(symbol), str(signal_type), int(stsig)),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT id, status, created_at
                            FROM pending_orders
                            WHERE strategy_id = %s
                              AND symbol = %s
                              AND signal_type = %s
                            ORDER BY id DESC
                            LIMIT 1
                            """,
                            (int(strategy_id), str(symbol), str(signal_type)),
                        )
                    last = cur.fetchone() or {}
                    last_id = int(last.get("id") or 0)
                    last_status = str(last.get("status") or "").strip().lower()
                    last_created = int(last.get("created_at") or 0)
                    if last_id > 0:
                        if idempotency_key:
                            logger.info(
                                f"enqueue_pending_order skipped (idempotency): existing id={last_id} "
                                f"strategy_id={strategy_id} key={idempotency_key} status={last_status}"
                            )
                            cur.close()
                            return None
                        if strict_candle_dedup:
                            logger.info(
                                f"enqueue_pending_order skipped (same candle): existing id={last_id} "
                                f"strategy_id={strategy_id} symbol={symbol} signal={signal_type} signal_ts={stsig} status={last_status}"
                            )
                            cur.close()
                            return None
                        if last_status in ("pending", "processing"):
                            logger.info(
                                f"enqueue_pending_order skipped: existing_inflight id={last_id} "
                                f"strategy_id={strategy_id} symbol={symbol} signal={signal_type} status={last_status}"
                            )
                            cur.close()
                            return None
                        if last_created > 0 and (now - last_created) < cooldown_sec:
                            logger.info(
                                f"enqueue_pending_order cooldown: last_id={last_id} last_status={last_status} "
                                f"age_sec={now - last_created} (<{cooldown_sec}) "
                                f"strategy_id={strategy_id} symbol={symbol} signal={signal_type}"
                            )
                            cur.close()
                            return None
                except Exception:
                    # Best-effort only; do not block enqueue on dedup query errors.
                    pass

                # Get user_id from strategy
                user_id = 1
                try:
                    cur.execute("SELECT user_id FROM qd_strategies_trading WHERE id = %s", (strategy_id,))
                    row = cur.fetchone()
                    user_id = int((row or {}).get('user_id') or 1)
                except Exception:
                    pass

                cur.execute(
                    """
                    INSERT INTO pending_orders
                    (user_id, strategy_id, symbol, signal_type, signal_ts, market_type, order_type, amount, price,
                     execution_mode, status, priority, attempts, max_attempts, last_error, payload_json,
                     strategy_run_id, order_intent_id, idempotency_key,
                     created_at, updated_at, processed_at, sent_at)
                    VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s,
                     NOW(), NOW(), NULL, NULL)
                    """,
                    (
                        int(user_id),
                        int(strategy_id),
                        symbol,
                        signal_type,
                        int(signal_ts or 0),
                        market_type or 'swap',
                        'market',
                        float(amount or 0.0),
                        float(price or 0.0),
                        mode,
                        'pending',
                        0,
                        0,
                        10,
                        '',
                        json.dumps(payload, ensure_ascii=False),
                        strategy_run_id,
                        order_intent_id,
                        idempotency_key,
                    ),
                )
                pending_id = cur.lastrowid
                db.commit()
                cur.close()
            return int(pending_id) if pending_id is not None else None
        except Exception as e:
            logger.error(f"enqueue_pending_order failed: {e}")
            return None

    @staticmethod
    def _signal_reason_log_suffix(signal: Optional[Dict[str, Any]]) -> str:
        info = signal if isinstance(signal, dict) else {}
        reason = str(info.get("reason") or "").strip()
        if not reason:
            return ""

        parts = [f"reason={reason}"]
        for key, label in (
            ("stop_loss_price", "sl"),
            ("take_profit_price", "tp"),
            ("trailing_stop_price", "trail"),
        ):
            value = info.get(key)
            if value is None:
                continue
            try:
                fv = float(value)
            except Exception:
                continue
            if fv > 0:
                parts.append(f"{label}={fv:.6f}")
        return f", {', '.join(parts)}"

    def _get_available_capital(
        self,
        strategy_id: int,
        initial_capital: float,
        current_positions: Optional[List[Dict[str, Any]]] = None,
        current_price: Optional[float] = None,
        symbol: str = "",
    ) -> float:
        """Calculate remaining strategy capital after realized and open-position PnL."""
        return self._calculate_current_equity(
            strategy_id,
            initial_capital,
            current_positions=current_positions,
            current_price=current_price,
            symbol=symbol,
        )

    def _calculate_current_equity(
        self,
        strategy_id: int,
        initial_capital: float,
        current_positions: Optional[List[Dict[str, Any]]] = None,
        current_price: Optional[float] = None,
        symbol: str = "",
    ) -> float:
        realized_pnl = 0.0
        unrealized_pnl = 0.0
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(profit, 0) - COALESCE(commission, 0)), 0) AS realized_pnl
                    FROM qd_strategy_trades
                    WHERE strategy_id = %s
                    """,
                    (strategy_id,)
                )
                row = cursor.fetchone() or {}
                realized_pnl = float(row.get('realized_pnl') or 0.0)
                cursor.close()
        except Exception as e:
            logger.warning(f"Failed to calculate realized pnl for strategy {strategy_id}: {e}")

        positions = list(current_positions or [])
        if not positions:
            try:
                positions = self._get_all_positions(strategy_id) or []
            except Exception:
                positions = []

        normalized_symbol = (symbol or "").split(':')[0]
        for pos in positions:
            try:
                side = str(pos.get('side') or '').strip().lower()
                size = float(pos.get('size') or 0.0)
                entry_price = float(pos.get('entry_price') or 0.0)
                if size <= 0 or entry_price <= 0 or side not in ('long', 'short'):
                    continue

                mark_price = pos.get('current_price')
                pos_symbol = str(pos.get('symbol') or '')
                if current_price and normalized_symbol and pos_symbol.split(':')[0] == normalized_symbol:
                    mark_price = current_price
                mark_price = float(mark_price or 0.0)
                if mark_price <= 0:
                    continue

                if side == 'long':
                    unrealized_pnl += (mark_price - entry_price) * size
                else:
                    unrealized_pnl += (entry_price - mark_price) * size
            except Exception:
                continue

        equity = float(initial_capital or 0.0) + realized_pnl + unrealized_pnl
        return max(0.0, equity)

    def _current_position_value(
        self,
        current_positions: Optional[List[Dict[str, Any]]],
        current_price: Optional[float],
    ) -> float:
        """Calculate total USDT notional of all open positions."""
        total = 0.0
        for pos in (current_positions or []):
            try:
                size = float(pos.get("size") or 0)
                entry = float(pos.get("entry_price") or 0)
                mark = float(current_price or entry or 0)
                if size > 0 and mark > 0:
                    total += size * mark
            except Exception:
                continue
        return total

    def _get_daily_pnl(self, strategy_id: int) -> float:
        """Get today's realized PnL (profit minus fees) for the strategy."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(COALESCE(profit, 0) - COALESCE(commission, 0)), 0) AS daily_pnl
                    FROM qd_strategy_trades
                    WHERE strategy_id = %s AND created_at::date = CURRENT_DATE
                    """,
                    (strategy_id,),
                )
                row = cursor.fetchone() or {}
                cursor.close()
                return float(row.get("daily_pnl") or 0.0)
        except Exception as e:
            logger.warning(f"Failed to get daily pnl for strategy {strategy_id}: {e}")
            return 0.0

    def _record_trade(
        self,
        strategy_id: int,
        symbol: str,
        type: str,
        price: float,
        amount: float,
        value: float,
        profit: float = None,
        commission: float = None,
        close_reason: str = "",
        matched_entry_price: Optional[float] = None,
        grid_matched_profit: Optional[float] = None,
    ):
        """Record a simulated signal-mode trade into the shared trade table."""
        try:
            from app.services.live_trading.leg_context import resolve_leg_context
            from app.services.live_trading.records import record_trade

            leg = resolve_leg_context(
                strategy_id=int(strategy_id),
                symbol=str(symbol or ""),
                fill_source="signal_sim",
            )
            record_trade(
                strategy_id=int(strategy_id),
                symbol=str(symbol or ""),
                trade_type=str(type or ""),
                price=float(price or 0.0),
                amount=float(amount or 0.0),
                commission=float(commission or 0.0),
                profit=profit,
                close_reason=str(close_reason or ""),
                matched_entry_price=matched_entry_price,
                grid_matched_profit=grid_matched_profit,
                leg=leg,
            )
        except Exception as e:
            logger.error(f"Failed to record trade: {e}")

    def _update_position(
        self,
        strategy_id: int,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        current_price: float,
        highest_price: float = 0.0,
        lowest_price: float = 0.0,
        execution_mode: str = "signal",
    ):
        """Update local position state for signal-mode execution."""
        mode = str(execution_mode or "signal").strip().lower()
        if mode == "live":
            # Live size/entry is owned by PendingOrderWorker + position sync.
            # Only patch trailing markers on rows that still exist.
            try:
                from app.services.live_trading.records import patch_position_markers

                patch_position_markers(
                    strategy_id=int(strategy_id),
                    symbol=str(symbol or ""),
                    side=str(side or ""),
                    current_price=float(current_price or 0.0),
                    highest_price=float(highest_price or 0.0),
                    lowest_price=float(lowest_price or 0.0),
                )
            except Exception as e:
                logger.warning("patch_position_markers failed sid=%s: %s", strategy_id, e)
            return
        try:
            # Get user_id from strategy
            user_id = 1
            with get_db_connection() as db:
                cursor = db.cursor()
                try:
                    cursor.execute("SELECT user_id FROM qd_strategies_trading WHERE id = %s", (strategy_id,))
                    row = cursor.fetchone()
                    user_id = int((row or {}).get('user_id') or 1)
                except Exception:
                    pass
                upsert_query = """
                    INSERT INTO qd_strategy_positions (
                        user_id, strategy_id, symbol, side, size, entry_price, current_price, highest_price, lowest_price, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    ) ON CONFLICT(strategy_id, symbol, side) DO UPDATE SET
                        size = excluded.size,
                        entry_price = excluded.entry_price,
                        current_price = excluded.current_price,
                        highest_price = CASE WHEN excluded.highest_price > 0 THEN excluded.highest_price ELSE qd_strategy_positions.highest_price END,
                        lowest_price = CASE WHEN excluded.lowest_price > 0 THEN excluded.lowest_price ELSE qd_strategy_positions.lowest_price END,
                        updated_at = NOW()
                """
                cursor.execute(upsert_query, (
                    user_id, strategy_id, symbol, side, size, entry_price, current_price, highest_price, lowest_price
                ))
                db.commit()
                cursor.close()
        except Exception as e:
            logger.error(f"Failed to update position: {e}")

    def _close_position(self, strategy_id: int, symbol: str, side: str):
        """Delete a local position row by strategy, symbol, and side."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute("DELETE FROM qd_strategy_positions WHERE strategy_id = %s AND symbol = %s AND side = %s", (strategy_id, symbol, side))
                db.commit()
                cursor.close()
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
    
    def _update_positions(self, strategy_id: int, symbol: str, current_price: float):
        """Update current price on local position rows for a symbol."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute("UPDATE qd_strategy_positions SET current_price = %s WHERE strategy_id = %s AND symbol = %s", (current_price, strategy_id, symbol))
                db.commit()
                cursor.close()
        except Exception:
            pass
