
"""
SQLite 数据库连接工具 (本地化适配版)
"""
import sqlite3
import os
import threading
import shutil
from typing import Optional, Any, List, Dict
from contextlib import contextmanager
from app.utils.logger import get_logger

logger = get_logger(__name__)

# SQLite 主库路径解析
#
# 目标默认行为：把主库放到 `backend_api_python/data/quantdinger.db`
# 兼容旧行为：老版本会在 `backend_api_python/quantdinger.db` 建库
_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DEFAULT_DB_FILE = os.path.join(_BASE_DIR, 'data', 'quantdinger.db')
_LEGACY_DB_FILE = os.path.join(_BASE_DIR, 'quantdinger.db')


def _get_db_file() -> str:
    """
    Resolve SQLite DB file path.

    Priority:
    - SQLITE_DATABASE_FILE env (Docker 推荐：/app/data/quantdinger.db)
    - default: backend_api_python/data/quantdinger.db (local recommended)

    Also performs a best-effort one-time migration:
    If the configured/default path doesn't exist but legacy db exists, copy legacy to configured/default path.
    """
    env_path = os.getenv('SQLITE_DATABASE_FILE')
    db_path = (env_path or '').strip() or _DEFAULT_DB_FILE

    # Ensure parent dir exists
    parent = os.path.dirname(db_path)
    if parent and not os.path.exists(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception:
            pass

    # Best-effort migration from legacy path
    try:
        if os.path.abspath(db_path) != os.path.abspath(_LEGACY_DB_FILE):
            if (not os.path.exists(db_path)) and os.path.exists(_LEGACY_DB_FILE):
                shutil.copy2(_LEGACY_DB_FILE, db_path)
                logger.info(f"Migrated SQLite DB from legacy path to {db_path}")
    except Exception as e:
        logger.warning(f"SQLite DB migration skipped/failed: {e}")

    return db_path

# 线程锁，用于简单的并发控制（SQLite 对写操作有限制）
_db_lock = threading.Lock()

def _init_db_schema(conn):
    """初始化数据库表结构"""
    cursor = conn.cursor()

    def ensure_columns(table: str, columns: Dict[str, str]) -> None:
        """
        Ensure columns exist for an existing SQLite table (simple migration).
        columns: {column_name: "TYPE DEFAULT ..."}
        """
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cursor.fetchall() or []}  # row[1] is column name
            for col, ddl in columns.items():
                if col in existing:
                    continue
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        except Exception as e:
            logger.warning(f"ensure_columns failed for table={table}: {e}")
    
    # 1. 策略表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_strategies_trading (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_name TEXT NOT NULL,
        strategy_type TEXT DEFAULT 'IndicatorStrategy',
        market_category TEXT DEFAULT 'Crypto',
        execution_mode TEXT DEFAULT 'signal',
        notification_config TEXT DEFAULT '', -- JSON string
        status TEXT DEFAULT 'stopped',
        symbol TEXT,
        timeframe TEXT,
        initial_capital REAL DEFAULT 1000,
        leverage INTEGER DEFAULT 1,
        market_type TEXT DEFAULT 'swap',
        exchange_config TEXT,  -- JSON string
        indicator_config TEXT, -- JSON string
        trading_config TEXT,   -- JSON string
        ai_model_config TEXT,  -- JSON string
        decide_interval INTEGER DEFAULT 300,
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    ensure_columns("qd_strategies_trading", {
        "market_category": "TEXT DEFAULT 'Crypto'",
        "execution_mode": "TEXT DEFAULT 'signal'",
        "notification_config": "TEXT DEFAULT ''"
    })

    # 2. 持仓表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_strategy_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER,
        symbol TEXT,
        side TEXT, -- long/short
        size REAL,
        entry_price REAL,
        current_price REAL,
        highest_price REAL DEFAULT 0,
        lowest_price REAL DEFAULT 0,
        unrealized_pnl REAL DEFAULT 0,
        pnl_percent REAL DEFAULT 0,
        equity REAL DEFAULT 0,
        updated_at INTEGER,
        UNIQUE(strategy_id, symbol, side)
    )
    """)

    ensure_columns("qd_strategy_positions", {
        "highest_price": "REAL DEFAULT 0",
        "lowest_price": "REAL DEFAULT 0",
    })

    # 3. 交易记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_strategy_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER,
        symbol TEXT,
        type TEXT, -- open_long, close_short, etc.
        price REAL,
        amount REAL,
        value REAL,
        commission REAL DEFAULT 0,
        commission_ccy TEXT DEFAULT '',
        profit REAL DEFAULT 0,
        created_at INTEGER
    )
    """)

    ensure_columns("qd_strategy_trades", {
        "commission_ccy": "TEXT DEFAULT ''",
    })

    # NOTE:
    # We intentionally do not persist runtime logs in DB for local deployments.
    # Use console logs / stdout prints instead.

    # 3.1 Pending orders queue (signal dispatch / live execution)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER,
        symbol TEXT NOT NULL,
        signal_type TEXT NOT NULL, -- open_long/close_long/open_short/close_short/add_long/add_short
        signal_ts INTEGER, -- candle timestamp (seconds). used for strict de-dup per candle
        market_type TEXT DEFAULT 'swap',
        order_type TEXT DEFAULT 'market',
        amount REAL DEFAULT 0, -- base amount (or stake amount depending on execution)
        price REAL DEFAULT 0,  -- reference price at enqueue time
        execution_mode TEXT DEFAULT 'signal', -- signal/live
        status TEXT DEFAULT 'pending', -- pending/processing/sent/failed/deferred
        priority INTEGER DEFAULT 0,
        attempts INTEGER DEFAULT 0,
        max_attempts INTEGER DEFAULT 10,
        last_error TEXT DEFAULT '',
        payload_json TEXT DEFAULT '', -- JSON string for dispatcher
        -- Live execution result fields (best-effort)
        dispatch_note TEXT DEFAULT '',
        exchange_id TEXT DEFAULT '',
        exchange_order_id TEXT DEFAULT '',
        exchange_response_json TEXT DEFAULT '',
        filled REAL DEFAULT 0,
        avg_price REAL DEFAULT 0,
        executed_at INTEGER,
        created_at INTEGER,
        updated_at INTEGER,
        processed_at INTEGER,
        sent_at INTEGER
    )
    """)

    ensure_columns("pending_orders", {
        "signal_ts": "INTEGER",
        "market_type": "TEXT DEFAULT 'swap'",
        "order_type": "TEXT DEFAULT 'market'",
        "price": "REAL DEFAULT 0",
        "execution_mode": "TEXT DEFAULT 'signal'",
        "status": "TEXT DEFAULT 'pending'",
        "priority": "INTEGER DEFAULT 0",
        "attempts": "INTEGER DEFAULT 0",
        "max_attempts": "INTEGER DEFAULT 10",
        "last_error": "TEXT DEFAULT ''",
        "payload_json": "TEXT DEFAULT ''",
        "dispatch_note": "TEXT DEFAULT ''",
        "exchange_id": "TEXT DEFAULT ''",
        "exchange_order_id": "TEXT DEFAULT ''",
        "exchange_response_json": "TEXT DEFAULT ''",
        "filled": "REAL DEFAULT 0",
        "avg_price": "REAL DEFAULT 0",
        "executed_at": "INTEGER",
        "created_at": "INTEGER",
        "updated_at": "INTEGER",
        "processed_at": "INTEGER",
        "sent_at": "INTEGER",
    })

    # 3.2 Strategy notifications (browser polling / audit trail)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_strategy_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER,
        symbol TEXT DEFAULT '',
        signal_type TEXT DEFAULT '',
        channels TEXT DEFAULT '',
        title TEXT DEFAULT '',
        message TEXT DEFAULT '',
        payload_json TEXT DEFAULT '',
        created_at INTEGER
    )
    """)

    ensure_columns("qd_strategy_notifications", {
        "strategy_id": "INTEGER",
        "symbol": "TEXT DEFAULT ''",
        "signal_type": "TEXT DEFAULT ''",
        "channels": "TEXT DEFAULT ''",
        "title": "TEXT DEFAULT ''",
        "message": "TEXT DEFAULT ''",
        "payload_json": "TEXT DEFAULT ''",
        "created_at": "INTEGER",
    })

    # 4. 指标代码表（参考 MySQL: qd_indicator_codes）
    # 说明：
    # - 本地化后统一使用 SQLite，但字段保持与 MySQL 结构接近，便于前端/业务复用。
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_indicator_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        is_buy INTEGER NOT NULL DEFAULT 0,
        end_time INTEGER NOT NULL DEFAULT 1,
        name TEXT NOT NULL DEFAULT '',
        code TEXT,
        description TEXT DEFAULT '',
        publish_to_community INTEGER NOT NULL DEFAULT 0,
        pricing_type TEXT NOT NULL DEFAULT 'free',
        price REAL NOT NULL DEFAULT 0,
        is_encrypted INTEGER NOT NULL DEFAULT 0,
        preview_image TEXT DEFAULT '',
        createtime INTEGER,
        updatetime INTEGER,
        -- legacy local columns (kept for backward compatibility)
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    # Migrate older local DBs (missing columns) to the new schema shape.
    ensure_columns("qd_indicator_codes", {
        "user_id": "INTEGER NOT NULL DEFAULT 1",
        "is_buy": "INTEGER NOT NULL DEFAULT 0",
        "end_time": "INTEGER NOT NULL DEFAULT 1",
        "publish_to_community": "INTEGER NOT NULL DEFAULT 0",
        "pricing_type": "TEXT NOT NULL DEFAULT 'free'",
        "price": "REAL NOT NULL DEFAULT 0",
        "is_encrypted": "INTEGER NOT NULL DEFAULT 0",
        "preview_image": "TEXT DEFAULT ''",
        "createtime": "INTEGER",
        "updatetime": "INTEGER"
    })

    # 4.1 策略代码表（indicator-analysis 本地策略；与交易执行器的 qd_strategies_trading 区分）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_strategy_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        name TEXT NOT NULL DEFAULT '',
        code TEXT,
        description TEXT DEFAULT '',
        createtime INTEGER,
        updatetime INTEGER
    )
    """)

    ensure_columns("qd_strategy_codes", {
        "user_id": "INTEGER NOT NULL DEFAULT 1",
        "name": "TEXT NOT NULL DEFAULT ''",
        "code": "TEXT",
        "description": "TEXT DEFAULT ''",
        "createtime": "INTEGER",
        "updatetime": "INTEGER"
    })
    
    # 5. AI决策记录表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_ai_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER,
        decision_data TEXT, -- JSON
        context_data TEXT,  -- JSON
        created_at INTEGER
    )
    """)

    # 6. 插件/系统配置表（原来由 MySQL 提供，这里用 SQLite 本地化）
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_addon_config (
        config_key TEXT PRIMARY KEY,
        config_value TEXT,
        type TEXT DEFAULT 'string'
    )
    """)

    # 7. Watchlist (local-only, single-user by default)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER DEFAULT 1,
        market TEXT NOT NULL,
        symbol TEXT NOT NULL,
        name TEXT DEFAULT '',
        created_at INTEGER,
        updated_at INTEGER,
        UNIQUE(user_id, market, symbol)
    )
    """)

    # 8. Analysis tasks / history (local-only)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_analysis_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER DEFAULT 1,
        market TEXT NOT NULL,
        symbol TEXT NOT NULL,
        model TEXT DEFAULT '',
        language TEXT DEFAULT 'en-US',
        status TEXT DEFAULT 'completed', -- completed/failed/processing/pending
        result_json TEXT DEFAULT '',
        error_message TEXT DEFAULT '',
        created_at INTEGER,
        completed_at INTEGER
    )
    """)

    # 9. Backtest runs (for AI optimization / history)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_backtest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        indicator_id INTEGER,
        market TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        start_date TEXT NOT NULL, -- YYYY-MM-DD
        end_date TEXT NOT NULL,   -- YYYY-MM-DD
        initial_capital REAL DEFAULT 10000,
        commission REAL DEFAULT 0.001,
        slippage REAL DEFAULT 0,
        leverage INTEGER DEFAULT 1,
        trade_direction TEXT DEFAULT 'long',
        strategy_config TEXT DEFAULT '', -- JSON string
        status TEXT DEFAULT 'success',   -- success/failed
        error_message TEXT DEFAULT '',
        result_json TEXT DEFAULT '',     -- JSON string
        created_at INTEGER
    )
    """)

    ensure_columns("qd_backtest_runs", {
        "user_id": "INTEGER NOT NULL DEFAULT 1",
        "indicator_id": "INTEGER",
        "market": "TEXT NOT NULL DEFAULT ''",
        "symbol": "TEXT NOT NULL DEFAULT ''",
        "timeframe": "TEXT NOT NULL DEFAULT ''",
        "start_date": "TEXT NOT NULL DEFAULT ''",
        "end_date": "TEXT NOT NULL DEFAULT ''",
        "initial_capital": "REAL DEFAULT 10000",
        "commission": "REAL DEFAULT 0.001",
        "slippage": "REAL DEFAULT 0",
        "leverage": "INTEGER DEFAULT 1",
        "trade_direction": "TEXT DEFAULT 'long'",
        "strategy_config": "TEXT DEFAULT ''",
        "status": "TEXT DEFAULT 'success'",
        "error_message": "TEXT DEFAULT ''",
        "result_json": "TEXT DEFAULT ''",
        "created_at": "INTEGER"
    })

    # 10. Exchange credentials vault (local-only)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qd_exchange_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL DEFAULT 1,
        name TEXT DEFAULT '',
        exchange_id TEXT NOT NULL,
        api_key_hint TEXT DEFAULT '',
        encrypted_config TEXT NOT NULL, -- encrypted JSON string
        created_at INTEGER,
        updated_at INTEGER
    )
    """)

    ensure_columns("qd_exchange_credentials", {
        "user_id": "INTEGER NOT NULL DEFAULT 1",
        "name": "TEXT DEFAULT ''",
        "exchange_id": "TEXT NOT NULL DEFAULT ''",
        "api_key_hint": "TEXT DEFAULT ''",
        "encrypted_config": "TEXT NOT NULL DEFAULT ''",
        "created_at": "INTEGER",
        "updated_at": "INTEGER"
    })

    conn.commit()
    logger.info("Database schema initialized (SQLite)")

# 初始化一次（按 db_file 维度）
_has_initialized = False
_initialized_db_file = None

class SQLiteCursor:
    """模拟 pymysql DictCursor"""
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query: str, args: Any = None):
        # 适配 MySQL -> SQLite 语法
        # 1. 替换占位符: %s -> ?
        query = query.replace('%s', '?')
        # 2. 替换 INSERT IGNORE -> INSERT OR IGNORE
        query = query.replace('INSERT IGNORE', 'INSERT OR IGNORE')
        # 3. 替换 ON DUPLICATE KEY UPDATE -> 简化为 UPSERT (SQLite 3.24+) 
        # 注意：复杂的 ON DUPLICATE KEY UPDATE 很难自动转换，建议业务代码改写
        # 这里做一个简单的替换尝试，如果失败则需要人工介入代码
        if 'ON DUPLICATE KEY UPDATE' in query:
            # 简单的正则替换很难完美，这里记录日志提醒
            logger.warning(f"Complex SQL may require manual SQLite adaptation: {query}")
            # 尝试转换为 SQLite 的 ON CONFLICT (id) DO UPDATE SET ...
            # 但由于不知道主键冲突列，很难自动转换。
            # 临时方案：如果遇到这种 SQL，可能报错。我们假设主要业务逻辑已经重构。
            pass

        if args:
            return self._cursor.execute(query, args)
        return self._cursor.execute(query)

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        # Convert sqlite3.Row to dict
        return dict(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self._cursor.close()
    
    @property
    def lastrowid(self):
        return self._cursor.lastrowid

class SQLiteConnection:
    """数据库连接包装类"""
    def __init__(self, db_path):
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        # 设置 Row factory 以支持字段名访问
        self._conn.row_factory = sqlite3.Row
    
    def cursor(self):
        return SQLiteCursor(self._conn.cursor())
    
    def commit(self):
        self._conn.commit()
    
    def rollback(self):
        self._conn.rollback()
    
    def close(self):
        self._conn.close()

@contextmanager
def get_db_connection():
    """
    获取数据库连接 (Context Manager)
    """
    global _has_initialized, _initialized_db_file
    
    # 简单的连接创建，不使用连接池（SQLite 文件锁机制决定了连接池意义不大）
    # 使用线程锁防止写冲突（虽然 SQLite 有 WAL 模式，但稳妥起见）
    # 注意：这里加锁粒度较大，如果是高并发场景可能会慢，但对于个人量化系统足够。
    
    # 初始化表结构（确保每个 db_file 都被初始化过）
    db_file = _get_db_file()
    if (not _has_initialized) or (_initialized_db_file != db_file):
        try:
            conn_init = sqlite3.connect(db_file)
            _init_db_schema(conn_init)
            conn_init.close()
            _has_initialized = True
            _initialized_db_file = db_file
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    conn = SQLiteConnection(db_file)
    try:
        # with _db_lock: # SQLite 内部有锁，这里如果不跨线程共享连接其实不用强加锁
        yield conn
    except Exception as e:
        logger.error(f"Database operation error: {e}")
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_db_connection_sync():
    """兼容旧接口"""
    global _has_initialized, _initialized_db_file
    db_file = _get_db_file()
    if (not _has_initialized) or (_initialized_db_file != db_file):
        try:
            conn_init = sqlite3.connect(db_file)
            _init_db_schema(conn_init)
            conn_init.close()
            _has_initialized = True
            _initialized_db_file = db_file
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            
    return SQLiteConnection(db_file)

def close_db_connection():
    pass
