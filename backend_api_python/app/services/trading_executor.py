"""
实时交易执行服务
"""
import time
import threading
import traceback
import os
try:
    import resource  # Linux/Unix only
except Exception:
    resource = None
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import json
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import pandas as pd
import numpy as np
import ccxt

from app.utils.logger import get_logger
from app.utils.db import get_db_connection
from app.data_sources import DataSourceFactory
from app.services.kline import KlineService
from app.services.indicator_params import IndicatorParamsParser, IndicatorCaller

logger = get_logger(__name__)


class TradingExecutor:
    """实时交易执行器 (Signal Provider Mode)"""
    
    def __init__(self):
        # 不再使用全局连接，改为每次使用时从连接池获取
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
        self.kline_service = KlineService()   # K线服务（带缓存）
        
        # 单实例线程上限，避免无限制创建线程导致 can't start new thread/OOM
        self.max_threads = int(os.getenv('STRATEGY_MAX_THREADS', '64'))
        
        # 确保数据库字段存在
        self._ensure_db_columns()

    def _ensure_db_columns(self):
        """确保必要的数据库字段存在（支持 SQLite 和 PostgreSQL）"""
        try:
            db_type = os.getenv('DB_TYPE', 'sqlite').lower()
            with get_db_connection() as db:
                cursor = db.cursor()
                col_names = set()

                if db_type == 'postgresql':
                    # PostgreSQL: 使用 information_schema 查询列
                    try:
                        cursor.execute("""
                            SELECT column_name FROM information_schema.columns 
                            WHERE table_name = 'qd_strategy_positions'
                        """)
                        cols = cursor.fetchall() or []
                        col_names = {c.get('column_name') or c.get('COLUMN_NAME') for c in cols if isinstance(c, dict)}
                    except Exception:
                        col_names = set()
                else:
                    # SQLite: 使用 PRAGMA table_info
                    try:
                        cursor.execute("PRAGMA table_info(qd_strategy_positions)")
                        cols = cursor.fetchall() or []
                        col_names = {c.get('name') for c in cols if isinstance(c, dict)}
                    except Exception:
                        col_names = set()

                if 'highest_price' not in col_names:
                    logger.info(f"Adding highest_price column to qd_strategy_positions ({db_type})...")
                    if db_type == 'postgresql':
                        cursor.execute("ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS highest_price DOUBLE PRECISION DEFAULT 0")
                    else:
                        cursor.execute("ALTER TABLE qd_strategy_positions ADD COLUMN highest_price REAL DEFAULT 0")
                    db.commit()
                    logger.info("highest_price column added")

                if 'lowest_price' not in col_names:
                    logger.info(f"Adding lowest_price column to qd_strategy_positions ({db_type})...")
                    if db_type == 'postgresql':
                        cursor.execute("ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS lowest_price DOUBLE PRECISION DEFAULT 0")
                    else:
                        cursor.execute("ALTER TABLE qd_strategy_positions ADD COLUMN lowest_price REAL DEFAULT 0")
                    db.commit()
                    logger.info("lowest_price column added")

                cursor.close()
        except Exception as e:
            logger.error(f"Failed to check/ensure DB columns: {str(e)}")

    def _normalize_trade_symbol(self, exchange: Any, symbol: str, market_type: str, exchange_id: str) -> str:
        """
        将数据库/配置里的 symbol 规范化为交易所合约可用的 CCXT symbol。

        典型场景：OKX 永续统一符号通常是 `BNB/USDT:USDT`，但前端/数据库可能传 `BNB/USDT`。
        """
        try:
            # 新系统：仅支持 swap(合约永续) / spot(现货)
            if market_type != 'swap':
                return symbol
            if not symbol or ':' in symbol:
                return symbol
            if not getattr(exchange, 'markets', None):
                return symbol

            # 如果 symbol 本身就是合约市场，直接返回
            try:
                m = exchange.market(symbol)
                if m and (m.get('swap') or m.get('future') or m.get('contract')):
                    return symbol
            except Exception:
                pass

            # OKX/部分交易所：永续常见为 BASE/QUOTE:QUOTE 或 BASE/QUOTE:USDT
            if '/' not in symbol:
                return symbol
            base, quote = symbol.split('/', 1)
            candidates = []
            if quote:
                candidates.append(f"{base}/{quote}:{quote}")
                if quote.upper() != 'USDT':
                    candidates.append(f"{base}/{quote}:USDT")

            for cand in candidates:
                if cand in exchange.markets:
                    cm = exchange.markets[cand]
                    if cm and (cm.get('swap') or cm.get('future') or cm.get('contract')):
                        logger.info(f"symbol normalized: {symbol} -> {cand} (exchange={exchange_id}, market_type={market_type})")
                        return cand

            return symbol
        except Exception:
            return symbol

    def _log_resource_status(self, prefix: str = ""):
        """调试：记录线程/内存使用，便于定位 can't start new thread 根因"""
        try:
            import psutil  # 如果有安装则使用更精确的指标
            p = psutil.Process()
            mem = p.memory_info().rss / 1024 / 1024
            th = p.num_threads()
            logger.warning(f"{prefix}resource status: memory={mem:.1f}MB, threads={th}, "
                           f"running_strategies={len(self.running_strategies)}")
        except Exception:
            try:
                th = threading.active_count()
                # 从 /proc/self/status 读取 VmRSS（适用于 Linux 容器）
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
            print(str(msg or ""), flush=True)
        except Exception:
            pass

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

    def _is_signal_allowed(self, state: str, signal_type: str) -> bool:
        """
        Enforce strict state machine:
        - flat: only open_long/open_short
        - long: only add_long/close_long
        - short: only add_short/close_short
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
        Convert a percent-like value into ratio in [0, 1].
        Accepts both 0~1 and 0~100 inputs.
        """
        try:
            x = float(v if v is not None else default)
        except Exception:
            x = float(default or 0.0)
        if x > 1.0:
            x = x / 100.0
        if x < 0:
            x = 0.0
        if x > 1.0:
            x = 1.0
        return float(x)

    def _build_cfg_from_trading_config(self, trading_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a backtest-modal compatible config dict for indicator scripts.

        Frontend (trading assistant) stores most params as flat keys under `trading_config`.
        Backtest service expects nested structure: cfg.risk/cfg.scale/cfg.position (camelCase).

        We provide BOTH:
        - `trading_config`: the original flat dict (so existing scripts keep working)
        - `cfg`: a normalized nested dict (so scripts can reuse backtest-style helpers)
        """
        tc = trading_config or {}

        # Risk / trailing
        stop_loss_pct = self._to_ratio(tc.get("stop_loss_pct"))
        take_profit_pct = self._to_ratio(tc.get("take_profit_pct"))
        trailing_enabled = bool(tc.get("trailing_enabled"))
        trailing_stop_pct = self._to_ratio(tc.get("trailing_stop_pct"))
        trailing_activation_pct = self._to_ratio(tc.get("trailing_activation_pct"))

        # Position sizing
        entry_pct = self._to_ratio(tc.get("entry_pct"))

        # Scale-in
        trend_add_enabled = bool(tc.get("trend_add_enabled"))
        trend_add_step_pct = self._to_ratio(tc.get("trend_add_step_pct"))
        trend_add_size_pct = self._to_ratio(tc.get("trend_add_size_pct"))
        trend_add_max_times = int(tc.get("trend_add_max_times") or 0)

        dca_add_enabled = bool(tc.get("dca_add_enabled"))
        dca_add_step_pct = self._to_ratio(tc.get("dca_add_step_pct"))
        dca_add_size_pct = self._to_ratio(tc.get("dca_add_size_pct"))
        dca_add_max_times = int(tc.get("dca_add_max_times") or 0)

        # Scale-out / reduce
        trend_reduce_enabled = bool(tc.get("trend_reduce_enabled"))
        trend_reduce_step_pct = self._to_ratio(tc.get("trend_reduce_step_pct"))
        trend_reduce_size_pct = self._to_ratio(tc.get("trend_reduce_size_pct"))
        trend_reduce_max_times = int(tc.get("trend_reduce_max_times") or 0)

        adverse_reduce_enabled = bool(tc.get("adverse_reduce_enabled"))
        adverse_reduce_step_pct = self._to_ratio(tc.get("adverse_reduce_step_pct"))
        adverse_reduce_size_pct = self._to_ratio(tc.get("adverse_reduce_size_pct"))
        adverse_reduce_max_times = int(tc.get("adverse_reduce_max_times") or 0)

        return {
            "risk": {
                "stopLossPct": stop_loss_pct,
                "takeProfitPct": take_profit_pct,
                "trailing": {
                    "enabled": trailing_enabled,
                    "pct": trailing_stop_pct,
                    "activationPct": trailing_activation_pct,
                },
            },
            "position": {
                "entryPct": entry_pct,
            },
            "scale": {
                "trendAdd": {
                    "enabled": trend_add_enabled,
                    "stepPct": trend_add_step_pct,
                    "sizePct": trend_add_size_pct,
                    "maxTimes": trend_add_max_times,
                },
                "dcaAdd": {
                    "enabled": dca_add_enabled,
                    "stepPct": dca_add_step_pct,
                    "sizePct": dca_add_size_pct,
                    "maxTimes": dca_add_max_times,
                },
                "trendReduce": {
                    "enabled": trend_reduce_enabled,
                    "stepPct": trend_reduce_step_pct,
                    "sizePct": trend_reduce_size_pct,
                    "maxTimes": trend_reduce_max_times,
                },
                "adverseReduce": {
                    "enabled": adverse_reduce_enabled,
                    "stepPct": adverse_reduce_step_pct,
                    "sizePct": adverse_reduce_size_pct,
                    "maxTimes": adverse_reduce_max_times,
                },
            },
        }
    
    def start_strategy(self, strategy_id: int) -> bool:
        """
        启动策略
        
        Args:
            strategy_id: 策略ID
            
        Returns:
            是否成功
        """
        try:
            with self.lock:
                # 清理已退出的线程，防止计数膨胀
                stale_ids = [sid for sid, th in self.running_strategies.items() if not th.is_alive()]
                for sid in stale_ids:
                    del self.running_strategies[sid]

                if len(self.running_strategies) >= self.max_threads:
                    logger.error(
                        f"Thread limit reached ({self.max_threads}); refuse to start strategy {strategy_id}. "
                        f"Reduce running strategies or increase STRATEGY_MAX_THREADS."
                    )
                    self._log_resource_status(prefix="start_denied: ")
                    return False

                if strategy_id in self.running_strategies:
                    logger.warning(f"Strategy {strategy_id} is already running")
                    return False
                
                # 创建并启动线程
                thread = threading.Thread(
                    target=self._run_strategy_loop,
                    args=(strategy_id,),
                    daemon=True
                )
                try:
                    thread.start()
                except Exception as e:
                    # 捕获 can't start new thread 等异常，记录资源状态
                    self._log_resource_status(prefix="启动异常")
                    raise e
                self.running_strategies[strategy_id] = thread
                
                logger.info(f"Strategy {strategy_id} started")
                self._console_print(f"[strategy:{strategy_id}] started")
                return True
                
        except Exception as e:
            logger.error(f"Failed to start strategy {strategy_id}: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    def stop_strategy(self, strategy_id: int) -> bool:
        """
        停止策略
        
        Args:
            strategy_id: 策略ID
            
        Returns:
            是否成功
        """
        try:
            with self.lock:
                if strategy_id not in self.running_strategies:
                    logger.warning(f"Strategy {strategy_id} is not running")
                    return False
                
                # 标记策略为停止状态
                with get_db_connection() as db:
                    cursor = db.cursor()
                    cursor.execute(
                        "UPDATE qd_strategies_trading SET status = 'stopped' WHERE id = %s",
                        (strategy_id,)
                    )
                    db.commit()
                    cursor.close()
                
                # 从运行列表中移除（线程会在下次循环检查状态时退出）
                del self.running_strategies[strategy_id]
                
                logger.info(f"Strategy {strategy_id} stopped")
                self._console_print(f"[strategy:{strategy_id}] stopped (requested)")
                return True
                
        except Exception as e:
            logger.error(f"Failed to stop strategy {strategy_id}: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    def _run_strategy_loop(self, strategy_id: int):
        """
        策略运行循环
        
        Args:
            strategy_id: 策略ID
        """
        logger.info(f"Strategy {strategy_id} loop starting")
        self._console_print(f"[strategy:{strategy_id}] loop initializing")
        
        try:
            # 加载策略配置
            strategy = self._load_strategy(strategy_id)
            if not strategy:
                logger.error(f"Strategy {strategy_id} not found")
                return
            
            if strategy['strategy_type'] != 'IndicatorStrategy':
                logger.error(f"Strategy {strategy_id} has unsupported strategy_type for realtime execution: {strategy['strategy_type']}")
                return
            
            # 初始化策略状态
            trading_config = strategy['trading_config']
            indicator_config = strategy['indicator_config']
            ai_model_config = strategy.get('ai_model_config') or {}
            execution_mode = (strategy.get('execution_mode') or 'signal').strip().lower()
            if execution_mode not in ['signal', 'live']:
                execution_mode = 'signal'
            notification_config = strategy.get('notification_config') or {}
            strategy_name = strategy.get('strategy_name') or f"strategy_{int(strategy_id)}"
            symbol = trading_config.get('symbol', '')
            timeframe = trading_config.get('timeframe', '1H')
            
            # 安全获取 leverage 和 trade_direction
            try:
                leverage_val = trading_config.get('leverage', 1)
                if isinstance(leverage_val, (list, tuple)):
                    leverage_val = leverage_val[0] if leverage_val else 1
                leverage = float(leverage_val)
            except:
                logger.warning(f"Strategy {strategy_id} invalid leverage format, reset to 1: {trading_config.get('leverage')}")
                leverage = 1.0
            
            # 获取市场类型，默认为合约
            # 根据杠杆自动判断：杠杆=1为现货，杠杆>1为合约
            market_type = trading_config.get('market_type', 'swap')
            if market_type not in ['swap', 'spot']:
                logger.error(f"Strategy {strategy_id} invalid market_type={market_type} (only swap/spot supported); refusing to start")
                return
            
            # 根据杠杆自动调整市场类型
            if leverage == 1.0:
                market_type = 'spot'  # 现货固定1倍杠杆
                logger.info(f"Strategy {strategy_id} leverage=1; auto-switch market_type to spot")
            else:
                # 合约市场：统一使用 swap（永续），避免 futures/delivery 混淆导致持仓/下单查错市场
                market_type = 'swap'
                logger.info(f"Strategy {strategy_id} derivatives trading; normalize market_type to: {market_type}")
            
            # 根据市场类型限制杠杆
            if market_type == 'spot':
                leverage = 1.0  # 现货固定1倍杠杆
            elif leverage < 1:
                leverage = 1.0
            elif leverage > 125:
                leverage = 125.0
                logger.warning(f"Strategy {strategy_id} leverage > 125; capped to 125")
            
            # 获取交易方向，现货只能做多
            trade_direction = trading_config.get('trade_direction', 'long')
            if market_type == 'spot':
                trade_direction = 'long'  # 现货只能做多
                logger.info(f"Strategy {strategy_id} spot trading; force trade_direction=long")

            # 获取市场类别（Crypto, USStock, Forex, Futures, AShare, HShare）
            # 这决定了使用哪个数据源来获取价格和K线数据
            market_category = (strategy.get('market_category') or 'Crypto').strip()
            logger.info(f"Strategy {strategy_id} market_category: {market_category}")

            # 初始化交易所连接（信号模式下无需真实连接）
            exchange = None
            
            # 安全获取 initial_capital
            try:
                initial_capital_val = strategy.get('initial_capital', 1000)
                if isinstance(initial_capital_val, (list, tuple)):
                    initial_capital_val = initial_capital_val[0] if initial_capital_val else 1000
                initial_capital = float(initial_capital_val)
            except:
                logger.warning(f"Strategy {strategy_id} invalid initial_capital format, reset to 1000: {strategy.get('initial_capital')}")
                initial_capital = 1000.0
            
            # 净值会在首次更新持仓时自动计算和更新
            
            # 获取指标代码
            indicator_id = indicator_config.get('indicator_id')
            indicator_code = indicator_config.get('indicator_code', '')
            
            # 如果代码为空，尝试从数据库获取
            if not indicator_code and indicator_id:
                indicator_code = self._get_indicator_code_from_db(indicator_id)
            
            if not indicator_code:
                logger.error(f"Strategy {strategy_id} indicator_code is empty")
                return
            
            # 确保 indicator_code 是字符串（处理 JSON 转义问题）
            if not isinstance(indicator_code, str):
                indicator_code = str(indicator_code)
            
            # 处理可能的 JSON 转义问题
            if '\\n' in indicator_code and '\n' not in indicator_code:
                try:
                    import json
                    decoded = json.loads(f'"{indicator_code}"')
                    if isinstance(decoded, str):
                        indicator_code = decoded
                        logger.info(f"Strategy {strategy_id} decoded escaped indicator_code")
                except Exception as e:
                    logger.warning(f"Strategy {strategy_id} JSON decode failed; falling back to manual unescape: {str(e)}")
                    indicator_code = (
                        indicator_code
                        .replace('\\n', '\n')
                        .replace('\\t', '\t')
                        .replace('\\r', '\r')
                        .replace('\\"', '"')
                        .replace("\\'", "'")
                        .replace('\\\\', '\\')
                    )
            
            # ============================================
            # 初始化阶段：获取历史K线并计算指标
            # ============================================
            # logger.info(f"策略 {strategy_id} 初始化：获取历史K线数据...")
            history_limit = int(os.getenv('K_LINE_HISTORY_GET_NUMBER', 500))
            klines = self._fetch_latest_kline(symbol, timeframe, limit=history_limit, market_category=market_category)
            if not klines or len(klines) < 2:
                logger.error(f"Strategy {strategy_id} failed to fetch K-lines")
                return
            logger.info(rf'Strategy {strategy_id} history kline number: {len(klines)}')
            
            # 转换为DataFrame
            df = self._klines_to_dataframe(klines)
            if len(df) == 0:
                logger.error(f"Strategy {strategy_id} K-lines are empty after normalization")
                return

            # ============================================
            # 启动时：完全依赖本地数据库的持仓状态（虚拟持仓）
            # ============================================
            # 信号模式下，不再同步交易所持仓
            pass

            # 获取当前持仓最高价（从本地数据库读取）
            current_pos_list = self._get_current_positions(strategy_id, symbol)
            initial_highest = 0.0
            initial_position = 0  # 0=无持仓, 1=多头, -1=空头
            initial_avg_entry_price = 0.0
            initial_position_count = 0
            initial_last_add_price = 0.0
            
            if current_pos_list:
                pos = current_pos_list[0]  # 取第一个持仓（单向持仓模式）
                initial_highest = float(pos.get('highest_price', 0) or 0)
                pos_side = pos.get('side', 'long')
                initial_position = 1 if pos_side == 'long' else -1
                initial_avg_entry_price = float(pos.get('entry_price', 0) or 0)
                initial_position_count = 1  # 简化处理，假设是单笔持仓
                initial_last_add_price = initial_avg_entry_price

            # 关键诊断日志：确认指标是否拿到了持仓状态
            logger.info(
                f"策略 {strategy_id} 指标注入持仓状态: count={len(current_pos_list)}, "
                f"position={initial_position}, entry_price={initial_avg_entry_price}, highest={initial_highest}"
            )

            # 执行指标代码，获取信号和触发价格
            indicator_result = self._execute_indicator_with_prices(
                indicator_code, df, trading_config, 
                initial_highest_price=initial_highest,
                initial_position=initial_position,
                initial_avg_entry_price=initial_avg_entry_price,
                initial_position_count=initial_position_count,
                initial_last_add_price=initial_last_add_price
            )
            if indicator_result is None:
                logger.error(f"Strategy {strategy_id} indicator execution failed")
                return
            
            # 提取信号和触发价格
            pending_signals = indicator_result.get('pending_signals', [])  # 待触发的信号列表
            last_kline_time = indicator_result.get('last_kline_time', 0)  # 最后一根K线的时间
            
            logger.info(f"Strategy {strategy_id} initialized; pending_signals={len(pending_signals)}")
            if pending_signals:
                logger.info(f"Initial signals: {pending_signals}")
            
            # ============================================
            # Main loop: unified tick cadence (default: 10s)
            # ============================================
            # One tick = fetch current price once + evaluate triggers once + (if needed) refresh K-lines / recalc indicator.
            # Note: `pending_orders` scanning stays at 1s (see PendingOrderWorker) to reduce live dispatch latency.
            try:
                # Global-only (no per-strategy override)
                tick_interval_sec = int(os.getenv('STRATEGY_TICK_INTERVAL_SEC', '10'))
            except Exception:
                tick_interval_sec = 10
            if tick_interval_sec < 1:
                tick_interval_sec = 1

            last_tick_time = 0.0
            last_kline_update_time = time.time()
            
            # 计算K线周期（秒）
            from app.data_sources.base import TIMEFRAME_SECONDS
            timeframe_seconds = TIMEFRAME_SECONDS.get(timeframe, 3600)
            kline_update_interval = timeframe_seconds  # 每个K线周期更新一次
            
            while True:
                try:
                    # 检查策略状态
                    if not self._is_strategy_running(strategy_id):
                        logger.info(f"Strategy {strategy_id} stopped")
                        break
                    
                    current_time = time.time()

                    # Sleep until next tick to avoid CPU spin.
                    if last_tick_time > 0:
                        sleep_sec = (last_tick_time + tick_interval_sec) - current_time
                        if sleep_sec > 0:
                            time.sleep(min(sleep_sec, 1.0))
                            continue
                    last_tick_time = current_time

                    # ============================================
                    # 0. 虚拟持仓模式，无需同步交易所
                    # ============================================
                    # pass
                    
                    # ============================================
                    # 1. Fetch current price once per tick
                    # ============================================
                    current_price = self._fetch_current_price(exchange, symbol, market_type=market_type, market_category=market_category)
                    if current_price is None:
                        logger.warning(f"Strategy {strategy_id} failed to fetch current price for {market_category}:{symbol}")
                        continue

                    # ============================================
                    # 2. 检查是否需要更新K线（每个K线周期更新一次，从API拉取）
                    # ============================================
                    if current_time - last_kline_update_time >= kline_update_interval:
                        klines = self._fetch_latest_kline(symbol, timeframe, limit=history_limit, market_category=market_category)
                        if klines and len(klines) >= 2:
                            df = self._klines_to_dataframe(klines)
                            if len(df) > 0:
                                current_pos_list = self._get_current_positions(strategy_id, symbol)
                                initial_highest = 0.0
                                initial_position = 0
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

                                indicator_result = self._execute_indicator_with_prices(
                                    indicator_code, df, trading_config,
                                    initial_highest_price=initial_highest,
                                    initial_position=initial_position,
                                    initial_avg_entry_price=initial_avg_entry_price,
                                    initial_position_count=initial_position_count,
                                    initial_last_add_price=initial_last_add_price
                                )
                                if indicator_result:
                                    pending_signals = indicator_result.get('pending_signals', [])
                                    last_kline_time = indicator_result.get('last_kline_time', 0)
                                    new_hp = indicator_result.get('new_highest_price', 0)

                                    last_kline_update_time = current_time

                                    # 更新 highest_price（使用最新 close 作为 current_price 的近似）
                                    if new_hp > 0 and current_pos_list:
                                        current_close = float(df['close'].iloc[-1])
                                        for p in current_pos_list:
                                            self._update_position(
                                                strategy_id, p['symbol'], p['side'],
                                                float(p['size']), float(p['entry_price']),
                                                current_close,
                                                highest_price=new_hp
                                            )
                    else:
                        # ============================================
                        # 3. 非K线更新tick：用当前价更新最后一根K线并重算指标（统一tick节奏）
                        # ============================================
                        if 'df' in locals() and df is not None and len(df) > 0:
                            try:
                                realtime_df = df.copy()
                                realtime_df = self._update_dataframe_with_current_price(realtime_df, current_price, timeframe)

                                current_pos_list = self._get_current_positions(strategy_id, symbol)
                                initial_highest = 0.0
                                initial_position = 0
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

                                indicator_result = self._execute_indicator_with_prices(
                                    indicator_code, realtime_df, trading_config,
                                    initial_highest_price=initial_highest,
                                    initial_position=initial_position,
                                    initial_avg_entry_price=initial_avg_entry_price,
                                    initial_position_count=initial_position_count,
                                    initial_last_add_price=initial_last_add_price
                                )
                                if indicator_result:
                                    pending_signals = indicator_result.get('pending_signals', [])
                                    new_hp = indicator_result.get('new_highest_price', 0)

                                    if new_hp > 0 and current_pos_list:
                                        for p in current_pos_list:
                                            self._update_position(
                                                strategy_id, p['symbol'], p['side'],
                                                float(p['size']), float(p['entry_price']),
                                                current_price,
                                                highest_price=new_hp
                                            )
                            except Exception as e:
                                logger.warning(f"Strategy {strategy_id} realtime indicator recompute failed: {str(e)}")
                    
                    # ============================================
                    # 4. Evaluate triggers once per tick
                    # ============================================
                    # 优化点4: 信号有效期清理 (Signal Expiration)
                    current_ts = int(time.time())
                    if pending_signals:
                        expiration_threshold = timeframe_seconds * 2
                        valid_signals = []
                        for s in pending_signals:
                            signal_time = s.get('timestamp', 0)
                            if signal_time == 0 or (current_ts - signal_time) < expiration_threshold:
                                valid_signals.append(s)
                            else:
                                logger.warning(f"Signal expired and removed: {s}")
                        if len(valid_signals) != len(pending_signals):
                            pending_signals = valid_signals

                    # Unified cadence log: at most once per tick.
                    if pending_signals:
                        logger.info(f"[monitoring] strategy={strategy_id} price={current_price}, pending_signals={len(pending_signals)}")

                    # 检查是否有待触发的信号
                    triggered_signals = []
                    signals_to_remove = []
                        
                    for signal_info in pending_signals:
                        signal_type = signal_info.get('type')  # 'open_long', 'close_long', 'open_short', 'close_short'
                        trigger_price = signal_info.get('trigger_price', 0)
                        
                        # 检查价格是否触发
                        triggered = False

                        # 【关键修复】平仓/止损止盈信号默认“立即触发”
                        exit_trigger_mode = trading_config.get('exit_trigger_mode', 'immediate')  # 'immediate' or 'price'
                        if signal_type in ['close_long', 'close_short'] and exit_trigger_mode == 'immediate':
                            triggered = True
                        
                        # 【可选】开仓/加仓信号是否“立即触发”
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
                    )
                    if risk_tp:
                        triggered_signals.append(risk_tp)

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
                        
                    # 从待触发列表中移除已触发的信号
                    for signal_info in signals_to_remove:
                        if signal_info in pending_signals:
                            pending_signals.remove(signal_info)
                        
                    # 执行触发的信号
                    if triggered_signals:
                        logger.info(f"Strategy {strategy_id} triggered signals: {triggered_signals}")

                        current_positions = self._get_current_positions(strategy_id, symbol)
                        state = self._position_state(current_positions)

                        # Strict state machine + priority:
                        # - Only allow signals matching current state (flat/long/short).
                        # - Always prefer close_* over open_*/add_*.
                        # - Execute at most ONE signal per tick to avoid duplicated/re-entrant orders.
                        candidates = [s for s in triggered_signals if self._is_signal_allowed(state, s.get('type'))]

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

                        selected = None
                        now_i = int(time.time())
                        for s in candidates:
                            stype = s.get("type")
                            sts = int(s.get("timestamp") or 0)
                            if self._should_skip_signal_once_per_candle(
                                strategy_id=strategy_id,
                                symbol=symbol,
                                signal_type=str(stype or ""),
                                signal_ts=sts,
                                timeframe_seconds=int(timeframe_seconds or 60),
                                now_ts=now_i,
                            ):
                                continue
                            selected = s
                            break

                        if selected:
                            signal_type = selected.get('type')
                            position_size = selected.get('position_size', 0)
                            trigger_price = selected.get('trigger_price', current_price)
                            execute_price = trigger_price if trigger_price > 0 else current_price
                            signal_ts = int(selected.get("timestamp") or 0)

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
                                execution_mode=execution_mode,
                                notification_config=notification_config,
                                trading_config=trading_config,
                                ai_model_config=ai_model_config,
                            )
                            if ok:
                                logger.info(f"Strategy {strategy_id} signal executed: {signal_type} @ {execute_price}")
                                # Notify portfolio positions linked to this symbol
                                try:
                                    from app.services.portfolio_monitor import notify_strategy_signal_for_positions
                                    notify_strategy_signal_for_positions(
                                        market=market_type or 'Crypto',
                                        symbol=symbol,
                                        signal_type=signal_type,
                                        signal_detail=f"策略: {strategy_name}\n信号: {signal_type}\n价格: {execute_price:.4f}"
                                    )
                                except Exception as link_e:
                                    logger.warning(f"Strategy signal linkage notification failed: {link_e}")
                            else:
                                logger.warning(f"Strategy {strategy_id} signal rejected/failed: {signal_type}")

                    # Update positions once per tick.
                    self._update_positions(strategy_id, symbol, current_price)

                    # Heartbeat for UI observability (once per tick).
                    self._console_print(
                        f"[strategy:{strategy_id}] tick price={float(current_price or 0.0):.8f} pending_signals={len(pending_signals or [])}"
                    )
                    
                except Exception as e:
                    logger.error(f"Strategy {strategy_id} loop error: {str(e)}")
                    logger.error(traceback.format_exc())
                    self._console_print(f"[strategy:{strategy_id}] loop error: {e}")
                    time.sleep(5)
                    
        except Exception as e:
            logger.error(f"Strategy {strategy_id} crashed: {str(e)}")
            logger.error(traceback.format_exc())
            self._console_print(f"[strategy:{strategy_id}] fatal error: {e}")
        finally:
            # 清理
            with self.lock:
                if strategy_id in self.running_strategies:
                    del self.running_strategies[strategy_id]
            self._console_print(f"[strategy:{strategy_id}] loop exited")
            logger.info(f"Strategy {strategy_id} loop exited")
    
    def _sync_positions_with_exchange(self, strategy_id: int, exchange: Any, symbol: str, market_type: str):
        """
        [Depracated] 信号模式下无需同步交易所持仓
        """
        pass

    def _load_strategy(self, strategy_id: int) -> Optional[Dict[str, Any]]:
        """Load strategy config (local deployment: no encryption/decryption)."""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                query = """
                    SELECT 
                        id, strategy_name, strategy_type, status,
                        initial_capital, leverage, decide_interval,
                        execution_mode, notification_config,
                        indicator_config, exchange_config, trading_config, ai_model_config,
                        market_category
                    FROM qd_strategies_trading
                    WHERE id = %s
                """
                cursor.execute(query, (strategy_id,))
                strategy = cursor.fetchone()
                cursor.close()
            
            if strategy:
                # 解析JSON字段
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
                        # 尝试直接解析 JSON（向后兼容）
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
        """检查策略是否在运行"""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute(
                    "SELECT status FROM qd_strategies_trading WHERE id = %s",
                    (strategy_id,)
                )
                result = cursor.fetchone()
                cursor.close()
                return result and result.get('status') == 'running'
        except:
            return False
    
    def _init_exchange(
        self,
        exchange_config: Dict[str, Any],
        market_type: str = None,
        leverage: float = None,
        strategy_id: int = None
    ) -> Optional[ccxt.Exchange]:
        """(Mock) 信号模式不需要真实交易所连接"""
        return None
    
    def _fetch_latest_kline(self, symbol: str, timeframe: str, limit: int = 500, market_category: str = 'Crypto') -> List[Dict[str, Any]]:
        """获取最新K线数据（优先从缓存获取）
        
        Args:
            symbol: 交易对/代码
            timeframe: 时间周期
            limit: 数据条数
            market_category: 市场类型 (Crypto, USStock, Forex, Futures, AShare, HShare)
        """
        try:
            # 使用 KlineService 获取K线数据（自动处理缓存）
            return self.kline_service.get_kline(
                market=market_category,
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                before_time=int(time.time())
            )
        except Exception as e:
            logger.error(f"Failed to fetch K-lines for {market_category}:{symbol}: {str(e)}")
            return []
    
    def _fetch_current_price(self, exchange: Any, symbol: str, market_type: str = None, market_category: str = 'Crypto') -> Optional[float]:
        """获取当前价格 (根据 market_category 选择正确的数据源)
        
        Args:
            exchange: 交易所实例（信号模式下为 None）
            symbol: 交易对/代码
            market_type: 交易类型 (swap/spot)
            market_category: 市场类型 (Crypto, USStock, Forex, Futures, AShare, HShare)
        """
        # Local in-memory cache first
        cache_key = f"{market_category}:{(symbol or '').strip().upper()}"
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
            # 根据 market_category 选择正确的数据源
            # 支持: Crypto, USStock, Forex, Futures, AShare, HShare
            ticker = DataSourceFactory.get_ticker(market_category, symbol)
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
        """
        服务端兜底止损：当价格穿透止损线时，直接生成 close_long/close_short 信号。

        目的：防止“指标回放逻辑导致最后一根K线没有 close_* 信号”或“插针反弹导致二次触发条件不满足”时不止损。
        """
        try:
            if trading_config is None:
                return None

            enabled = trading_config.get('enable_server_side_stop_loss', True)
            if str(enabled).lower() in ['0', 'false', 'no', 'off']:
                return None

            # 获取当前持仓（使用本地数据库记录作为风控依据）
            current_positions = self._get_current_positions(strategy_id, symbol)
            if not current_positions:
                return None

            pos = current_positions[0]
            side = pos.get('side')
            if side not in ['long', 'short']:
                return None

            entry_price = float(pos.get('entry_price', 0) or 0)
            if entry_price <= 0 or current_price <= 0:
                return None

            # Stop-loss is config-driven: if stop_loss_pct is not set or <= 0, do NOT stop-loss.
            sl_cfg = trading_config.get('stop_loss_pct', 0)
            sl = 0.0
            try:
                sl_cfg = float(sl_cfg or 0)
                if sl_cfg > 1:
                    sl = sl_cfg / 100.0
                else:
                    sl = sl_cfg
            except Exception:
                sl = 0.0

            if sl <= 0:
                return None

            # Align with backtest semantics: risk percentages are defined on margin PnL,
            # so we convert to price move threshold by dividing by leverage.
            lev = max(1.0, float(leverage or 1.0))
            sl = sl / lev

            # Use candle start timestamp to deduplicate exit attempts within a candle.
            now_ts = int(time.time())
            tf = int(timeframe_seconds or 60)
            candle_ts = int(now_ts // tf) * tf

            # 多头：跌破止损线
            if side == 'long':
                stop_line = entry_price * (1 - sl)
                if current_price <= stop_line:
                    return {
                        'type': 'close_long',
                        'trigger_price': 0,  # 立即触发（由 exit_trigger_mode 控制）
                        'position_size': 0,
                        'timestamp': candle_ts,
                        'reason': 'server_stop_loss',
                        'stop_loss_price': stop_line,
                    }
            # 空头：突破止损线
            elif side == 'short':
                stop_line = entry_price * (1 + sl)
                if current_price >= stop_line:
                    return {
                        'type': 'close_short',
                        'trigger_price': 0,
                        'position_size': 0,
                        'timestamp': candle_ts,
                        'reason': 'server_stop_loss',
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
    ) -> Optional[Dict[str, Any]]:
        """
        Server-side exits driven by trading_config (no indicator script required):
        - Fixed take-profit: take_profit_pct
        - Trailing stop: trailing_enabled + trailing_stop_pct + trailing_activation_pct

        Semantics align with BacktestService:
        - Percentages are defined on margin PnL; effective price threshold = pct / leverage.
        - When trailing is enabled, fixed take-profit is disabled to avoid ambiguity.
        """
        try:
            if not trading_config:
                return None

            current_positions = self._get_current_positions(strategy_id, symbol)
            if not current_positions:
                return None

            pos = current_positions[0]
            side = (pos.get('side') or '').strip().lower()
            if side not in ['long', 'short']:
                return None

            entry_price = float(pos.get('entry_price', 0) or 0)
            if entry_price <= 0 or current_price <= 0:
                return None

            lev = max(1.0, float(leverage or 1.0))

            tp = self._to_ratio(trading_config.get('take_profit_pct'))
            trailing_enabled = bool(trading_config.get('trailing_enabled'))
            trailing_pct = self._to_ratio(trading_config.get('trailing_stop_pct'))
            trailing_act = self._to_ratio(trading_config.get('trailing_activation_pct'))

            tp_eff = (tp / lev) if tp > 0 else 0.0
            trailing_pct_eff = (trailing_pct / lev) if trailing_pct > 0 else 0.0
            trailing_act_eff = (trailing_act / lev) if trailing_act > 0 else 0.0

            # Conflict rule: when trailing is enabled, fixed TP is disabled.
            if trailing_enabled and trailing_pct_eff > 0:
                tp_eff = 0.0
                # If activationPct is missing, reuse take_profit_pct as activation threshold.
                if trailing_act_eff <= 0 and tp > 0:
                    trailing_act_eff = tp / lev

            now_ts = int(time.time())
            tf = int(timeframe_seconds or 60)
            candle_ts = int(now_ts // tf) * tf

            # Highest/lowest tracking (persisted in DB so restart continues trailing correctly)
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

            # Persist best-effort
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
                )
            except Exception:
                pass

            # 1) Trailing stop
            if trailing_enabled and trailing_pct_eff > 0:
                if side == 'long':
                    active = True
                    if trailing_act_eff > 0:
                        active = hp >= entry_price * (1 + trailing_act_eff)
                    if active:
                        stop_line = hp * (1 - trailing_pct_eff)
                        if current_price <= stop_line:
                            return {
                                'type': 'close_long',
                                'trigger_price': 0,
                                'position_size': 0,
                                'timestamp': candle_ts,
                                'reason': 'server_trailing_stop',
                                'trailing_stop_price': stop_line,
                                'highest_price': hp,
                            }
                else:
                    active = True
                    if trailing_act_eff > 0:
                        active = lp <= entry_price * (1 - trailing_act_eff)
                    if active:
                        stop_line = lp * (1 + trailing_pct_eff)
                        if current_price >= stop_line:
                            return {
                                'type': 'close_short',
                                'trigger_price': 0,
                                'position_size': 0,
                                'timestamp': candle_ts,
                                'reason': 'server_trailing_stop',
                                'trailing_stop_price': stop_line,
                                'lowest_price': lp,
                            }

            # 2) Fixed take-profit (only when trailing is disabled)
            if tp_eff > 0:
                if side == 'long':
                    tp_line = entry_price * (1 + tp_eff)
                    if current_price >= tp_line:
                        return {
                            'type': 'close_long',
                            'trigger_price': 0,
                            'position_size': 0,
                            'timestamp': candle_ts,
                            'reason': 'server_take_profit',
                            'take_profit_price': tp_line,
                        }
                else:
                    tp_line = entry_price * (1 - tp_eff)
                    if current_price <= tp_line:
                        return {
                            'type': 'close_short',
                            'trigger_price': 0,
                            'position_size': 0,
                            'timestamp': candle_ts,
                            'reason': 'server_take_profit',
                            'take_profit_price': tp_line,
                        }

            return None
        except Exception:
            return None
    
    def _klines_to_dataframe(self, klines: List[Dict[str, Any]]) -> pd.DataFrame:
        """将K线数据转换为DataFrame"""
        if not klines:
            # 返回空的 DataFrame，包含正确的列
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
        
        # 创建 DataFrame
        df = pd.DataFrame(klines)
        
        # Convert time column.
        # IMPORTANT: use UTC tz-aware index to avoid timezone skew when computing candle boundaries.
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
            df = df.set_index('time')
        elif 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True)
            df = df.set_index('timestamp')
        
        # 确保只包含需要的列
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        available_columns = [col for col in required_columns if col in df.columns]
        if not available_columns:
            logger.warning("K-lines are missing required columns")
            return pd.DataFrame(columns=required_columns)
        
        df = df[available_columns]
        
        # 强制转换所有数值列为 float64 类型
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                # 先转换为数值类型，然后强制转换为 float64
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
        
        # 删除包含 NaN 的行
        df = df.dropna()
        
        return df

    def _update_dataframe_with_current_price(self, df: pd.DataFrame, current_price: float, timeframe: str) -> pd.DataFrame:
        """
        使用当前价格更新DataFrame的最后一根K线（用于实时计算）
        """
        if df is None or len(df) == 0:
            return df
            
        try:
            # 获取最后一根K线的时间
            last_time = df.index[-1]
            
            # 计算当前时间对应的K线起始时间
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
            
            # 计算当前价格所属的 K 线开始时间
            current_period_start = int(now_ts // tf_seconds) * tf_seconds
            
            # 检查最后一根K线是否就是当前周期的
            if abs(last_ts - current_period_start) < 2:
                # 更新最后一根
                df.iloc[-1, df.columns.get_loc('close')] = current_price
                df.iloc[-1, df.columns.get_loc('high')] = max(df.iloc[-1]['high'], current_price)
                df.iloc[-1, df.columns.get_loc('low')] = min(df.iloc[-1]['low'], current_price)
            elif current_period_start > last_ts:
                # 追加新行
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
    
    def _execute_indicator_with_prices(
        self, indicator_code: str, df: pd.DataFrame, trading_config: Dict[str, Any], 
        initial_highest_price: float = 0.0,
        initial_position: int = 0,
        initial_avg_entry_price: float = 0.0,
        initial_position_count: int = 0,
        initial_last_add_price: float = 0.0
    ) -> Optional[Dict[str, Any]]:
        """
        执行指标代码并提取待触发的信号和价格
        """
        try:
            # 执行指标代码
            executed_df, exec_env = self._execute_indicator_df(
                indicator_code, df, trading_config, 
                initial_highest_price=initial_highest_price,
                initial_position=initial_position,
                initial_avg_entry_price=initial_avg_entry_price,
                initial_position_count=initial_position_count,
                initial_last_add_price=initial_last_add_price
            )
            if executed_df is None:
                return None
            
            # 提取最新的 highest_price
            new_highest_price = exec_env.get('highest_price', 0.0)
            
            # 提取最后一根K线的时间
            last_kline_time = int(df.index[-1].timestamp()) if hasattr(df.index[-1], 'timestamp') else int(time.time())
            
            # 提取待触发的信号
            pending_signals = []
            
            # Supported indicator signal formats:
            # - Preferred (simple): df['buy'], df['sell'] as boolean
            # - Internal (4-way): df['open_long'], df['close_long'], df['open_short'], df['close_short'] as boolean
            if all(col in executed_df.columns for col in ['buy', 'sell']) and not all(col in executed_df.columns for col in ['open_long', 'close_long', 'open_short', 'close_short']):
                # Normalize buy/sell into 4-way columns for execution.
                td = trading_config.get('trade_direction', trading_config.get('tradeDirection', 'both'))
                td = str(td or 'both').lower()
                if td not in ['long', 'short', 'both']:
                    td = 'both'

                buy = executed_df['buy'].fillna(False).astype(bool)
                sell = executed_df['sell'].fillna(False).astype(bool)

                executed_df = executed_df.copy()
                if td == 'long':
                    executed_df['open_long'] = buy
                    executed_df['close_long'] = sell
                    executed_df['open_short'] = False
                    executed_df['close_short'] = False
                elif td == 'short':
                    executed_df['open_long'] = False
                    executed_df['close_long'] = False
                    executed_df['open_short'] = sell
                    executed_df['close_short'] = buy
                else:
                    executed_df['open_long'] = buy
                    executed_df['close_short'] = buy
                    executed_df['open_short'] = sell
                    executed_df['close_long'] = sell

            # Check for 4-way columns after normalization
            if all(col in executed_df.columns for col in ['open_long', 'close_long', 'open_short', 'close_short']):
                # 优化点3: 防“信号闪烁” (Repainting)
                signal_mode = trading_config.get('signal_mode', 'confirmed') # 'confirmed' or 'aggressive'
                exit_signal_mode = trading_config.get('exit_signal_mode', 'aggressive') # 'confirmed' or 'aggressive'
                
                entry_check_set = set()
                exit_check_set = set()
                
                if len(executed_df) > 1:
                    # 始终检查上一根已完成K线
                    entry_check_set.add(len(executed_df) - 2)
                    exit_check_set.add(len(executed_df) - 2)
                
                if signal_mode == 'aggressive' and len(executed_df) > 0:
                    entry_check_set.add(len(executed_df) - 1)
                
                if exit_signal_mode == 'aggressive' and len(executed_df) > 0:
                    exit_check_set.add(len(executed_df) - 1)
                
                # 统一遍历索引（保持确定性排序）
                check_indices = sorted(entry_check_set.union(exit_check_set), reverse=True)
                
                for idx in check_indices:
                    # 获取该K线的收盘价（作为默认触发价）
                    close_price = float(executed_df['close'].iloc[idx])
                    # 该信号的时间戳
                    signal_timestamp = int(executed_df.index[idx].timestamp()) if hasattr(executed_df.index[idx], 'timestamp') else last_kline_time
                    
                    # 开多信号（仅在 entry_check_set 中检查）
                    if idx in entry_check_set and executed_df['open_long'].iloc[idx]:
                        trigger_price = close_price
                        position_size = 0.08
                        if 'position_size' in executed_df.columns:
                            pos_size = executed_df['position_size'].iloc[idx]
                            if pos_size > 0:
                                position_size = float(pos_size)
                        
                        if not any(s['type'] == 'open_long' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'open_long',
                                'trigger_price': trigger_price,
                                'position_size': position_size,
                                'timestamp': signal_timestamp
                            })
                    
                    # 平多信号
                    if idx in exit_check_set and executed_df['close_long'].iloc[idx]:
                        trigger_price = close_price
                        if not any(s['type'] == 'close_long' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'close_long',
                                'trigger_price': trigger_price,
                                'position_size': 0,
                                'timestamp': signal_timestamp
                            })
                    
                    # 开空信号
                    if idx in entry_check_set and executed_df['open_short'].iloc[idx]:
                        trigger_price = close_price
                        position_size = 0.08
                        if 'position_size' in executed_df.columns:
                            pos_size = executed_df['position_size'].iloc[idx]
                            if pos_size > 0:
                                position_size = float(pos_size)
                        
                        if not any(s['type'] == 'open_short' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'open_short',
                                'trigger_price': trigger_price,
                                'position_size': position_size,
                                'timestamp': signal_timestamp
                            })
                    
                    # 平空信号
                    if idx in exit_check_set and executed_df['close_short'].iloc[idx]:
                        trigger_price = close_price
                        if not any(s['type'] == 'close_short' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'close_short',
                                'trigger_price': trigger_price,
                                'position_size': 0,
                                'timestamp': signal_timestamp
                            })
                            
                    # 加多信号
                    if idx in entry_check_set and 'add_long' in executed_df.columns and executed_df['add_long'].iloc[idx]:
                        trigger_price = close_price
                        position_size = 0.06
                        if 'position_size' in executed_df.columns:
                            pos_size = executed_df['position_size'].iloc[idx]
                            if pos_size > 0:
                                position_size = float(pos_size)

                        if not any(s['type'] == 'add_long' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'add_long',
                                'trigger_price': trigger_price,
                                'position_size': position_size,
                                'timestamp': signal_timestamp
                            })
                            
                    # 加空信号
                    if idx in entry_check_set and 'add_short' in executed_df.columns and executed_df['add_short'].iloc[idx]:
                        trigger_price = close_price
                        position_size = 0.06
                        if 'position_size' in executed_df.columns:
                            pos_size = executed_df['position_size'].iloc[idx]
                            if pos_size > 0:
                                position_size = float(pos_size)

                        if not any(s['type'] == 'add_short' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'add_short',
                                'trigger_price': trigger_price,
                                'position_size': position_size,
                                'timestamp': signal_timestamp
                            })

                    # Reduce / scale-out signals (optional)
                    # These are used by position management rules (trend/adverse reduce) and should be treated as exits.
                    if idx in exit_check_set and 'reduce_long' in executed_df.columns and executed_df['reduce_long'].iloc[idx]:
                        trigger_price = close_price
                        reduce_pct = 0.1
                        if 'reduce_size' in executed_df.columns:
                            try:
                                reduce_pct = float(executed_df['reduce_size'].iloc[idx] or 0)
                            except Exception:
                                reduce_pct = 0.1
                        elif 'position_size' in executed_df.columns:
                            try:
                                reduce_pct = float(executed_df['position_size'].iloc[idx] or 0)
                            except Exception:
                                reduce_pct = 0.1
                        if reduce_pct <= 0:
                            reduce_pct = 0.1
                        if not any(s['type'] == 'reduce_long' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'reduce_long',
                                'trigger_price': trigger_price,
                                'position_size': reduce_pct,
                                'timestamp': signal_timestamp
                            })

                    if idx in exit_check_set and 'reduce_short' in executed_df.columns and executed_df['reduce_short'].iloc[idx]:
                        trigger_price = close_price
                        reduce_pct = 0.1
                        if 'reduce_size' in executed_df.columns:
                            try:
                                reduce_pct = float(executed_df['reduce_size'].iloc[idx] or 0)
                            except Exception:
                                reduce_pct = 0.1
                        elif 'position_size' in executed_df.columns:
                            try:
                                reduce_pct = float(executed_df['position_size'].iloc[idx] or 0)
                            except Exception:
                                reduce_pct = 0.1
                        if reduce_pct <= 0:
                            reduce_pct = 0.1
                        if not any(s['type'] == 'reduce_short' and s.get('timestamp') == signal_timestamp for s in pending_signals):
                            pending_signals.append({
                                'type': 'reduce_short',
                                'trigger_price': trigger_price,
                                'position_size': reduce_pct,
                                'timestamp': signal_timestamp
                            })
            
            return {
                'pending_signals': pending_signals,
                'last_kline_time': last_kline_time,
                'new_highest_price': new_highest_price
            }
            
        except Exception as e:
            logger.error(f"Failed to execute indicator and extract prices: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    def _execute_indicator_df(
        self, indicator_code: str, df: pd.DataFrame, trading_config: Dict[str, Any], 
        initial_highest_price: float = 0.0,
        initial_position: int = 0,
        initial_avg_entry_price: float = 0.0,
        initial_position_count: int = 0,
        initial_last_add_price: float = 0.0
    ) -> tuple[Optional[pd.DataFrame], dict]:
        """执行指标代码，返回执行后的DataFrame和执行环境"""
        try:
            # 确保 DataFrame 的所有数值列都是 float64 类型
            df = df.copy()
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    if not pd.api.types.is_numeric_dtype(df[col]):
                        df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
                    else:
                        df[col] = df[col].astype('float64')
            
            # 删除包含 NaN 的行
            df = df.dropna()
            
            if len(df) == 0:
                logger.warning("DataFrame is empty; cannot execute indicator script")
                return None, {}
            
            # 初始化信号Series
            signals = pd.Series(0, index=df.index, dtype='float64')
            
            # 准备执行环境
            # Expose the full trading config to indicator scripts so frontend parameters
            # (scale-in/out, position sizing, risk params) can be used directly.
            # Also provide a backtest-modal compatible nested config object: cfg.risk/cfg.scale/cfg.position.
            tc = dict(trading_config or {})
            cfg = self._build_cfg_from_trading_config(tc)
            
            # === 指标参数支持 ===
            # 从 trading_config 获取用户设置的指标参数
            user_indicator_params = tc.get('indicator_params', {})
            # 解析指标代码中声明的参数
            declared_params = IndicatorParamsParser.parse_params(indicator_code)
            # 合并参数（用户值优先，否则使用默认值）
            merged_params = IndicatorParamsParser.merge_params(declared_params, user_indicator_params)
            
            # === 指标调用器支持 ===
            # 获取用户ID和指标ID（用于 call_indicator 权限检查）
            user_id = tc.get('user_id', 1)
            indicator_id = tc.get('indicator_id')
            indicator_caller = IndicatorCaller(user_id, indicator_id)
            
            local_vars = {
                'df': df,
                'open': df['open'].astype('float64'),
                'high': df['high'].astype('float64'),
                'low': df['low'].astype('float64'),
                'close': df['close'].astype('float64'),
                'volume': df['volume'].astype('float64'),
                'signals': signals,
                'np': np,
                'pd': pd,
                'trading_config': tc,
                'config': tc,  # alias
                'cfg': cfg,    # normalized nested config
                'params': merged_params,  # 指标参数 (新增)
                'call_indicator': indicator_caller.call_indicator,  # 调用其他指标 (新增)
                'leverage': float(trading_config.get('leverage', 1)),
                'initial_capital': float(trading_config.get('initial_capital', 1000)),
                'commission': 0.001,
                'trade_direction': str(trading_config.get('trade_direction', 'long')),
                'initial_highest_price': float(initial_highest_price),
                'initial_position': int(initial_position),
                'initial_avg_entry_price': float(initial_avg_entry_price),
                'initial_position_count': int(initial_position_count),
                'initial_last_add_price': float(initial_last_add_price)
            }
            
            import builtins
            def safe_import(name, *args, **kwargs):
                allowed_modules = ['numpy', 'pandas', 'math', 'json', 'time']
                if name in allowed_modules or name.split('.')[0] in allowed_modules:
                    return builtins.__import__(name, *args, **kwargs)
                raise ImportError(f"不允许导入模块: {name}")
            
            safe_builtins = {k: getattr(builtins, k) for k in dir(builtins) 
                           if not k.startswith('_') and k not in [
                               'eval', 'exec', 'compile', 'open', 'input',
                               'help', 'exit', 'quit', '__import__',
                               'copyright', 'credits', 'license'
                           ]}
            safe_builtins['__import__'] = safe_import
            
            exec_env = local_vars.copy()
            exec_env['__builtins__'] = safe_builtins
            
            pre_import_code = "import numpy as np\nimport pandas as pd\n"
            exec(pre_import_code, exec_env)
            
            # 这里的 safe_exec_code 假设已存在
            exec(indicator_code, exec_env)
            
            executed_df = exec_env.get('df', df)

            # Validation: if chart signals are provided, df['buy']/df['sell'] must exist for execution normalization.
            output_obj = exec_env.get('output')
            has_output_signals = isinstance(output_obj, dict) and isinstance(output_obj.get('signals'), list) and len(output_obj.get('signals')) > 0
            if has_output_signals and not all(col in executed_df.columns for col in ['buy', 'sell']):
                raise ValueError(
                    "Invalid indicator script: output['signals'] is provided, but df['buy'] and df['sell'] are missing. "
                    "Please set df['buy'] and df['sell'] as boolean columns (len == len(df))."
                )
            
            return executed_df, exec_env
            
        except Exception as e:
            logger.error(f"Failed to execute indicator script: {str(e)}")
            logger.error(traceback.format_exc())
            return None, {}
    
    def _execute_indicator(self, indicator_code: str, df: pd.DataFrame, trading_config: Dict[str, Any]) -> Optional[Any]:
        """兼容旧版本"""
        executed_df, _ = self._execute_indicator_df(indicator_code, df, trading_config)
        if executed_df is None:
            return None
        return 0

    def _get_current_positions(self, strategy_id: int, symbol: str) -> List[Dict[str, Any]]:
        """获取当前持仓（支持symbol规范化匹配）"""
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
                    # 简化匹配逻辑：只匹配前缀
                    if pos['symbol'].split(':')[0] == symbol.split(':')[0]:
                        matched_positions.append(pos)
                
                cursor.close()
                return matched_positions
        except Exception as e:
            logger.error(f"Failed to fetch positions: {str(e)}")
            return []

    def _execute_trading_logic(self, *args, **kwargs):
        """已废弃"""
        pass
    
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
        execution_mode: str = 'signal',
        notification_config: Optional[Dict[str, Any]] = None,
        trading_config: Optional[Dict[str, Any]] = None,
        ai_model_config: Optional[Dict[str, Any]] = None,
        signal_ts: int = 0,
    ):
        """执行具体的交易信号"""
        try:
            # Hard state-machine guard (double safety in addition to loop-level filtering).
            state = self._position_state(current_positions)
            if not self._is_signal_allowed(state, signal_type):
                return False

            # 1. 检查交易方向限制
            if market_type == 'spot' and 'short' in signal_type:
                 return False

            sig = (signal_type or "").strip().lower()

            # 1.1 开仓 AI 过滤（仅 open_*）
            if sig in ("open_long", "open_short") and self._is_entry_ai_filter_enabled(ai_model_config=ai_model_config, trading_config=trading_config):
                ok_ai, ai_info = self._entry_ai_filter_allows(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    signal_type=sig,
                    ai_model_config=ai_model_config,
                    trading_config=trading_config,
                )
                if not ok_ai:
                    # Best-effort persist a browser notification so UI can show "HOLD due to AI filter".
                    reason = (ai_info or {}).get("reason") or "ai_filter_rejected"
                    ai_decision = (ai_info or {}).get("ai_decision") or ""
                    title = f"AI过滤拦截开仓 | {symbol}"
                    msg = f"策略信号={sig}，AI决策={ai_decision or 'UNKNOWN'}，原因={reason}；已HOLD（不下单）"
                    self._persist_browser_notification(
                        strategy_id=strategy_id,
                        symbol=symbol,
                        signal_type="ai_filter_hold",
                        title=title,
                        message=msg,
                        payload={
                            "event": "qd.ai_filter",
                            "strategy_id": int(strategy_id),
                            "strategy_name": str(strategy_name or ""),
                            "symbol": str(symbol or ""),
                            "signal_type": str(sig),
                            "ai_decision": str(ai_decision),
                            "reason": str(reason),
                            "signal_ts": int(signal_ts or 0),
                        },
                    )
                    logger.info(
                        f"AI entry filter rejected: strategy_id={strategy_id} symbol={symbol} signal={sig} ai={ai_decision} reason={reason}"
                    )
                    return False

            # 2. 计算下单数量
            available_capital = self._get_available_capital(strategy_id, initial_capital)
            
            amount = 0.0

            # Frontend position sizing alignment:
            # - open_* uses entry_pct from trading_config if provided (0~1 or 0~100 are both accepted)
            if sig in ("open_long", "open_short") and isinstance(trading_config, dict):
                ep = trading_config.get("entry_pct")
                if ep is not None:
                    position_size = self._to_ratio(ep, default=position_size if position_size is not None else 0.0)

            # Open / add sizing: position_size is treated as capital ratio in [0,1].
            if ('open' in sig or 'add' in sig):
                 if position_size is None or float(position_size) <= 0:
                     position_size = 0.05
                 position_ratio = self._to_ratio(position_size, default=0.05)
                 if market_type == 'spot':
                     amount = available_capital * position_ratio / current_price
                 else:
                     # Futures sizing: treat available_capital as margin budget.
                     # Notional = margin * leverage, so base quantity = (margin * leverage) / price.
                     amount = (available_capital * position_ratio * leverage) / current_price

            # Reduce sizing: position_size is treated as a reduce ratio (close X% of current position).
            if sig in ("reduce_long", "reduce_short"):
                pos_side = "long" if "long" in sig else "short"
                pos = next((p for p in current_positions if (p.get('side') or '').strip().lower() == pos_side), None)
                if not pos:
                    return False
                cur_size = float(pos.get("size") or 0.0)
                if cur_size <= 0:
                    return False
                reduce_ratio = self._to_ratio(position_size, default=0.1)
                reduce_amount = cur_size * reduce_ratio
                # If reduce is effectively full, treat as close_*.
                if reduce_amount >= cur_size * 0.999:
                    sig = "close_long" if pos_side == "long" else "close_short"
                    signal_type = sig
                    amount = cur_size
                else:
                    amount = reduce_amount
            
            # 3. 检查反向持仓（单向持仓逻辑）
            # ... (简化处理，假设无反向或由用户处理) ...

            # 4. Execute order enqueue (PendingOrderWorker will dispatch notifications in signal mode)
            if 'close' in sig:
                # 平仓逻辑：找到对应持仓大小
                pos = next((p for p in current_positions if p.get('side') and p['side'] in signal_type), None)
                if not pos:
                    return False
                amount = float(pos['size'] or 0.0)
                if amount <= 0:
                    return False

            if amount <= 0 and ('open' in signal_type or 'add' in signal_type):
                return False
            
            order_result = self._execute_exchange_order(
                exchange=exchange,
                strategy_id=strategy_id,
                symbol=symbol,
                signal_type=signal_type,
                amount=amount,
                ref_price=float(current_price or 0.0),
                market_type=market_type,
                market_category=market_category,
                leverage=leverage,
                execution_mode=execution_mode,
                notification_config=notification_config,
                signal_ts=int(signal_ts or 0),
            )
            
            if order_result and order_result.get('success'):
                # For live execution, the order is only enqueued here.
                # The actual fill/trade/position updates are performed by PendingOrderWorker.
                if str(execution_mode or "").strip().lower() == "live":
                    return True

                # 更新数据库状态 (signal mode / local simulation)
                if 'open' in sig or 'add' in sig:
                    self._record_trade(
                        strategy_id=strategy_id, symbol=symbol, type=signal_type,
                        price=current_price, amount=amount, value=amount*current_price
                    )
                    side = 'short' if 'short' in signal_type else 'long'
                    
                    # 查找现有持仓以计算均价
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
                elif sig.startswith("reduce_"):
                    # Partial scale-out: reduce position size, keep entry price unchanged.
                    # 信号模式下计算部分平仓盈亏
                    side = 'short' if 'short' in signal_type else 'long'
                    old_pos = next((p for p in current_positions if p.get('side') == side), None)
                    if not old_pos:
                        return True
                    old_size = float(old_pos.get('size') or 0.0)
                    old_entry = float(old_pos.get('entry_price') or 0.0)
                    
                    # 计算减仓部分的盈亏（信号模式下，不含手续费）
                    reduce_profit = None
                    if old_entry > 0 and amount > 0:
                        if side == 'long':
                            reduce_profit = (current_price - old_entry) * amount
                        else:
                            reduce_profit = (old_entry - current_price) * amount
                    
                    self._record_trade(
                        strategy_id=strategy_id, symbol=symbol, type=signal_type,
                        price=current_price, amount=amount, value=amount*current_price,
                        profit=reduce_profit
                    )
                    
                    new_size = max(0.0, old_size - float(amount or 0.0))
                    if new_size <= old_size * 0.001:
                        self._close_position(strategy_id, symbol, side)
                    else:
                        self._update_position(
                            strategy_id=strategy_id, symbol=symbol, side=side,
                            size=new_size, entry_price=old_entry, current_price=current_price
                        )
                elif 'close' in sig:
                    # 信号模式下计算平仓盈亏
                    side = 'short' if 'short' in signal_type else 'long'
                    old_pos = next((p for p in current_positions if p.get('side') == side), None)
                    
                    # 计算盈亏（信号模式下，不含手续费）
                    close_profit = None
                    if old_pos:
                        entry_price = float(old_pos.get('entry_price') or 0)
                        if entry_price > 0 and amount > 0:
                            if side == 'long':
                                close_profit = (current_price - entry_price) * amount
                            else:
                                close_profit = (entry_price - current_price) * amount
                    
                    self._record_trade(
                        strategy_id=strategy_id, symbol=symbol, type=signal_type,
                        price=current_price, amount=amount, value=amount*current_price,
                        profit=close_profit
                    )
                    self._close_position(strategy_id, symbol, side)

                return True

            return False
            
        except Exception as e:
            logger.error(f"Failed to execute signal: {e}")
            return False

    def _is_entry_ai_filter_enabled(self, *, ai_model_config: Optional[Dict[str, Any]], trading_config: Optional[Dict[str, Any]]) -> bool:
        """Detect whether the strategy enabled 'AI filter on entry (open positions only)'."""
        amc = ai_model_config if isinstance(ai_model_config, dict) else {}
        tc = trading_config if isinstance(trading_config, dict) else {}

        # Accept multiple key names for forward/backward compatibility.
        candidates = [
            amc.get("entry_ai_filter_enabled"),
            amc.get("entryAiFilterEnabled"),
            amc.get("ai_filter_enabled"),
            amc.get("aiFilterEnabled"),
            amc.get("enable_ai_filter"),
            amc.get("enableAiFilter"),
            tc.get("entry_ai_filter_enabled"),
            tc.get("ai_filter_enabled"),
            tc.get("enable_ai_filter"),
            tc.get("enableAiFilter"),
        ]
        for v in candidates:
            if v is None:
                continue
            if isinstance(v, bool):
                return bool(v)
            s = str(v).strip().lower()
            if s in ("1", "true", "yes", "y", "on", "enabled"):
                return True
            if s in ("0", "false", "no", "n", "off", "disabled"):
                return False
        return False

    def _entry_ai_filter_allows(
        self,
        *,
        strategy_id: int,
        symbol: str,
        signal_type: str,
        ai_model_config: Optional[Dict[str, Any]],
        trading_config: Optional[Dict[str, Any]],
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Run internal AI analysis and decide whether an entry signal is allowed.

        Returns:
          (allowed, info)
          - allowed: True -> proceed; False -> hold (reject open)
          - info: {ai_decision, reason, analysis_error?}
        """
        amc = ai_model_config if isinstance(ai_model_config, dict) else {}
        tc = trading_config if isinstance(trading_config, dict) else {}

        # Market for AnalysisService. Live trading executor is Crypto-focused.
        market = str(amc.get("market") or amc.get("analysis_market") or "Crypto").strip() or "Crypto"

        # Optional model override (OpenRouter model id)
        model = amc.get("model") or amc.get("openrouter_model") or amc.get("openrouterModel") or None
        model = str(model).strip() if model else None

        # Prefer zh-CN for local UI; can be overridden.
        language = amc.get("language") or amc.get("lang") or tc.get("language") or "zh-CN"
        language = str(language or "zh-CN")

        try:
            # 使用新的 FastAnalysisService (单次LLM调用，更快更稳定)
            from app.services.fast_analysis import get_fast_analysis_service

            service = get_fast_analysis_service()
            result = service.analyze(market, symbol, language, model=model)

            if isinstance(result, dict) and result.get("error"):
                return False, {"ai_decision": "", "reason": "analysis_error", "analysis_error": str(result.get("error") or "")}

            # FastAnalysisService 直接返回 decision 字段
            ai_dec = str(result.get("decision", "")).strip().upper()
            if not ai_dec or ai_dec not in ("BUY", "SELL", "HOLD"):
                return False, {"ai_decision": ai_dec, "reason": "missing_ai_decision"}

            expected = "BUY" if signal_type == "open_long" else "SELL"
            confidence = result.get("confidence", 50)
            summary = result.get("summary", "")
            
            if ai_dec == expected:
                return True, {"ai_decision": ai_dec, "reason": "match", "confidence": confidence, "summary": summary}
            if ai_dec == "HOLD":
                return False, {"ai_decision": ai_dec, "reason": "ai_hold", "confidence": confidence, "summary": summary}
            return False, {"ai_decision": ai_dec, "reason": "direction_mismatch", "confidence": confidence, "summary": summary}
        except Exception as e:
            return False, {"ai_decision": "", "reason": "analysis_exception", "analysis_error": str(e)}

    def _extract_ai_trade_decision(self, analysis_result: Any) -> str:
        """
        Normalize AI analysis output into one of: BUY / SELL / HOLD / "".
        We primarily look at final_decision.decision, with fallbacks.
        """
        if not isinstance(analysis_result, dict):
            return ""

        def _pick(*paths: str) -> str:
            for p in paths:
                cur: Any = analysis_result
                ok = True
                for k in p.split("."):
                    if not isinstance(cur, dict):
                        ok = False
                        break
                    cur = cur.get(k)
                if ok and cur is not None:
                    s = str(cur).strip()
                    if s:
                        return s
            return ""

        raw = _pick("final_decision.decision", "trader_decision.decision", "decision", "final.decision")
        s = raw.strip().upper()
        if not s:
            return ""

        # Common variants / synonyms
        if "BUY" in s or s == "LONG" or "LONG" in s:
            return "BUY"
        if "SELL" in s or s == "SHORT" or "SHORT" in s:
            return "SELL"
        if "HOLD" in s or "WAIT" in s or "NEUTRAL" in s:
            return "HOLD"
        return s if s in ("BUY", "SELL", "HOLD") else ""

    def _persist_browser_notification(
        self,
        *,
        strategy_id: int,
        symbol: str,
        signal_type: str,
        title: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
        user_id: int = None,
    ) -> None:
        """Best-effort persist notification row for the frontend '通知' panel (browser channel)."""
        try:
            now = int(time.time())
            # Get user_id from strategy if not provided
            if user_id is None:
                try:
                    with get_db_connection() as db:
                        cur = db.cursor()
                        cur.execute("SELECT user_id FROM qd_strategies_trading WHERE id = ?", (strategy_id,))
                        row = cur.fetchone()
                        cur.close()
                    user_id = int((row or {}).get('user_id') or 1)
                except Exception:
                    user_id = 1
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO qd_strategy_notifications
                    (user_id, strategy_id, symbol, signal_type, channels, title, message, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW())
                    """,
                    (
                        int(user_id),
                        int(strategy_id),
                        str(symbol or ""),
                        str(signal_type or ""),
                        "browser",
                        str(title or ""),
                        str(message or ""),
                        json.dumps(payload or {}, ensure_ascii=False),
                    ),
                )
                db.commit()
                cur.close()
        except Exception as e:
            logger.warning(f"persist_browser_notification failed: {e}")

    def _execute_exchange_order(
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
        # Order execution params (order_mode, maker_wait_sec, maker_offset_bps) are now
        # configured via environment variables: ORDER_MODE, MAKER_WAIT_SEC, MAKER_OFFSET_BPS
        # These parameters are kept for backward compatibility but will be ignored.
        order_mode: str = None,
        maker_wait_sec: float = None,
        maker_retries: int = 3,
        close_fallback_to_market: bool = True,
        open_fallback_to_market: bool = True,
        execution_mode: str = 'signal',
        notification_config: Optional[Dict[str, Any]] = None,
        signal_ts: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Convert a signal into a concrete pending order and enqueue it into DB.

        A separate worker will poll `pending_orders` and dispatch:
        - execution_mode='signal': dispatch notifications (no real trading).
        - execution_mode='live': reserved for future live trading execution (not implemented).

        Note: Order execution settings (order_mode, maker_wait_sec, maker_offset_bps) are now
        configured via environment variables and not passed from strategy config.
        """
        try:
            # Reference price at enqueue time: use current tick price if provided to avoid extra fetch.
            if ref_price is None:
                ref_price = self._fetch_current_price(None, symbol, market_category=market_category) or 0.0
            ref_price = float(ref_price or 0.0)

            extra_payload = {
                "ref_price": float(ref_price or 0.0),
                "signal_ts": int(signal_ts or 0),
                "stop_loss_price": float(stop_loss_price or 0.0) if stop_loss_price is not None else 0.0,
                "take_profit_price": float(take_profit_price or 0.0) if take_profit_price is not None else 0.0,
                "margin_mode": str(margin_mode or "cross"),
                # Order execution params moved to env config (ORDER_MODE, MAKER_WAIT_SEC, MAKER_OFFSET_BPS)
                "maker_retries": int(maker_retries or 0),
                "close_fallback_to_market": bool(close_fallback_to_market),
                "open_fallback_to_market": bool(open_fallback_to_market),
            }
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

            with get_db_connection() as db:
                cur = db.cursor()

                # Extra dedup/cooldown guard (DB-based, more rigorous than local position state):
                # The indicator recompute runs on a fixed tick cadence, and some strategies may keep emitting the same
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

                    if strict_candle_dedup:
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
                     created_at, updated_at, processed_at, sent_at)
                    VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s,
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
                    ),
                )
                pending_id = cur.lastrowid
                db.commit()
                cur.close()
            return int(pending_id) if pending_id is not None else None
        except Exception as e:
            logger.error(f"enqueue_pending_order failed: {e}")
            return None

    def _place_stop_loss_order(self, *args, **kwargs):
        pass

    def _get_available_capital(self, strategy_id: int, initial_capital: float) -> float:
        """获取可用资金"""
        return initial_capital

    def _calculate_current_equity(self, strategy_id: int, initial_capital: float) -> float:
        return initial_capital

    def _record_trade(self, strategy_id: int, symbol: str, type: str, price: float, amount: float, value: float, profit: float = None, commission: float = None):
        """记录交易到数据库"""
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
                query = """
                    INSERT INTO qd_strategy_trades (
                        user_id, strategy_id, symbol, type, price, amount, value, commission, profit, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                """
                cursor.execute(query, (user_id, strategy_id, symbol, type, price, amount, value, commission or 0, profit))
                db.commit()
                cursor.close()
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
    ):
        """更新持仓状态"""
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
                # 简化：直接 Update 或 Insert
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
        """平仓：删除持仓记录"""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute("DELETE FROM qd_strategy_positions WHERE strategy_id = %s AND symbol = %s AND side = %s", (strategy_id, symbol, side))
                db.commit()
                cursor.close()
        except Exception as e:
            logger.error(f"Failed to close position: {e}")
    
    def _delete_position_by_id(self, position_id: int):
         pass

    def _update_positions(self, strategy_id: int, symbol: str, current_price: float):
        """更新所有持仓的当前价格"""
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute("UPDATE qd_strategy_positions SET current_price = %s WHERE strategy_id = %s AND symbol = %s", (current_price, strategy_id, symbol))
                db.commit()
                cursor.close()
        except Exception:
            pass
            
    def _get_indicator_code_from_db(self, indicator_id: int) -> Optional[str]:
        try:
            with get_db_connection() as db:
                cursor = db.cursor()
                cursor.execute("SELECT code FROM qd_indicator_codes WHERE id = %s", (indicator_id,))
                result = cursor.fetchone()
                return result['code'] if result else None
        except:
            return None
