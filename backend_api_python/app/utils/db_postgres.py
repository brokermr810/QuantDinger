"""
PostgreSQL Database Connection Utility

Supports multi-user mode with connection pooling.
Provides placeholder conversion for backward compatibility with legacy code.

Pool tuning (all via env, safe defaults):
    DB_POOL_MIN               minconn                       default 5
    DB_POOL_MAX               maxconn                       default 50
    DB_POOL_ACQUIRE_TIMEOUT   seconds to wait on exhaustion default 10
    DB_POOL_HEALTH_CHECK      "true" / "false"              default "true"
"""
import os
import time
import threading
from typing import Optional, Any, List, Dict
from contextlib import contextmanager
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Try to import psycopg2
try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2 import OperationalError, InterfaceError
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    logger.warning("psycopg2 not installed. PostgreSQL support disabled.")

# Connection pool (global singleton)
_connection_pool: Optional[Any] = None
_pool_lock = threading.Lock()


def _env_int(key: str, default: int) -> int:
    try:
        v = int(os.getenv(key, str(default)))
        return v if v > 0 else default
    except Exception:
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


DB_POOL_MIN = _env_int("DB_POOL_MIN", 5)
DB_POOL_MAX = _env_int("DB_POOL_MAX", 50)
DB_POOL_ACQUIRE_TIMEOUT = _env_int("DB_POOL_ACQUIRE_TIMEOUT", 10)
DB_POOL_HEALTH_CHECK = _env_bool("DB_POOL_HEALTH_CHECK", True)


def _get_database_url() -> str:
    """Get database connection URL from environment"""
    return os.getenv('DATABASE_URL', '').strip()


def _parse_database_url(url: str) -> Dict[str, Any]:
    """
    Parse DATABASE_URL format: postgresql://user:password@host:port/dbname
    """
    if not url:
        return {}
    
    # Remove protocol prefix
    if url.startswith('postgresql://'):
        url = url[13:]
    elif url.startswith('postgres://'):
        url = url[11:]
    else:
        return {}
    
    result = {}
    
    # Split user:password@host:port/dbname
    if '@' in url:
        auth, hostpart = url.rsplit('@', 1)
        if ':' in auth:
            result['user'], result['password'] = auth.split(':', 1)
        else:
            result['user'] = auth
    else:
        hostpart = url
    
    # Split host:port/dbname
    if '/' in hostpart:
        hostport, result['dbname'] = hostpart.split('/', 1)
    else:
        hostport = hostpart
    
    if ':' in hostport:
        result['host'], port_str = hostport.split(':', 1)
        result['port'] = int(port_str)
    else:
        result['host'] = hostport
        result['port'] = 5432
    
    return result


def _get_connection_pool():
    """Get or create connection pool"""
    global _connection_pool
    
    if _connection_pool is not None:
        return _connection_pool
    
    with _pool_lock:
        if _connection_pool is not None:
            return _connection_pool
        
        if not HAS_PSYCOPG2:
            raise RuntimeError("psycopg2 is not installed. Cannot use PostgreSQL.")
        
        db_url = _get_database_url()
        if not db_url:
            raise RuntimeError("DATABASE_URL environment variable is not set.")
        
        params = _parse_database_url(db_url)
        if not params:
            raise RuntimeError(f"Invalid DATABASE_URL format: {db_url}")
        
        try:
            _connection_pool = pool.ThreadedConnectionPool(
                minconn=DB_POOL_MIN,
                maxconn=DB_POOL_MAX,
                host=params.get('host', 'localhost'),
                port=params.get('port', 5432),
                user=params.get('user', 'quantdinger'),
                password=params.get('password', ''),
                dbname=params.get('dbname', 'quantdinger'),
                connect_timeout=10,
                # Apply timezone at connection establishment so we don't need
                # per-checkout SET TIME ZONE (which left connections in an
                # "idle in transaction" state when no explicit commit/rollback
                # followed).  keepalives keep dead sockets from lingering in
                # the pool when the PG side or a NAT drops them.
                options="-c timezone=UTC",
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
            )
            logger.info(
                f"PostgreSQL connection pool created: "
                f"{params.get('host')}:{params.get('port')}/{params.get('dbname')} "
                f"(min={DB_POOL_MIN}, max={DB_POOL_MAX}, "
                f"acquire_timeout={DB_POOL_ACQUIRE_TIMEOUT}s, "
                f"health_check={DB_POOL_HEALTH_CHECK})"
            )
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {e}")
            raise
        
        return _connection_pool


def _is_connection_healthy(conn) -> bool:
    """Quick health check: make sure the connection is not closed and can
    actually round-trip a trivial query.  Used only when DB_POOL_HEALTH_CHECK
    is on, since SELECT 1 adds a small latency.
    """
    if conn is None:
        return False
    # psycopg2 sets .closed to nonzero when the connection is closed.
    if getattr(conn, "closed", 0):
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        return True
    except Exception:
        return False


def _acquire_conn_with_wait(pg_pool):
    """Wrapper around pg_pool.getconn() that waits up to
    DB_POOL_ACQUIRE_TIMEOUT seconds instead of failing immediately when the
    pool is exhausted (psycopg2's default behaviour).  Also performs a
    lightweight health check on the returned connection and discards dead
    connections back to the pool to let PG reopen fresh ones.
    """
    if not HAS_PSYCOPG2:
        raise RuntimeError("psycopg2 is not installed. Cannot use PostgreSQL.")

    deadline = time.monotonic() + max(1, DB_POOL_ACQUIRE_TIMEOUT)
    backoff = 0.05  # start at 50ms
    last_err: Optional[Exception] = None
    warned = False
    while True:
        try:
            conn = pg_pool.getconn()
        except pool.PoolError as e:
            last_err = e
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(
                    f"PostgreSQL pool exhausted: all {DB_POOL_MAX} connections are in use "
                    f"and waiting {DB_POOL_ACQUIRE_TIMEOUT}s did not free any. "
                    f"Consider raising DB_POOL_MAX or investigating long-running queries."
                )
                raise
            if not warned:
                logger.warning(
                    f"PostgreSQL pool exhausted ({DB_POOL_MAX} in use); "
                    f"waiting up to {DB_POOL_ACQUIRE_TIMEOUT}s for a slot..."
                )
                warned = True
            time.sleep(min(backoff, max(0.0, remaining)))
            backoff = min(backoff * 2, 0.5)
            continue

        if DB_POOL_HEALTH_CHECK and not _is_connection_healthy(conn):
            # Drop the dead connection and let the pool create a new one on
            # next attempt.  putconn(close=True) asks the pool to discard it.
            try:
                pg_pool.putconn(conn, close=True)
            except Exception:
                pass
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise last_err or RuntimeError("DB pool returned only dead connections")
            time.sleep(min(backoff, max(0.0, remaining)))
            continue

        return conn


class PostgresCursor:
    """PostgreSQL cursor wrapper with placeholder conversion for backward compatibility"""
    
    def __init__(self, cursor):
        self._cursor = cursor
        self._last_insert_id = None
        # INSERT ... RETURNING: execute() peeks the first row for lastrowid; callers
        # that also cur.fetchone() must see the same row (not a second fetch from PG).
        self._buffered_row: Optional[Dict[str, Any]] = None
    
    def _convert_placeholders(self, query: str) -> str:
        """
        Convert ? placeholders to PostgreSQL %s for backward compatibility.
        Also handle some SQL syntax differences.
        """
        # Replace ? -> %s
        query = query.replace('?', '%s')
        
        # INSERT OR IGNORE -> PostgreSQL: INSERT ... ON CONFLICT DO NOTHING
        query = query.replace('INSERT OR IGNORE', 'INSERT')
        
        return query
    
    def execute(self, query: str, args: Any = None):
        """Execute SQL statement.

        For INSERT statements without an explicit RETURNING clause, we try to
        append ``RETURNING id`` so legacy callers can read ``cursor.lastrowid``.
        But not every table has an ``id`` column (e.g. ``qd_oauth_states``
        uses ``state`` as PK).  In that case psycopg2 raises
        ``UndefinedColumn`` and aborts the whole transaction, which can
        cascade into "column \"id\" does not exist" errors across the app.

        To stay safe, wrap the RETURNING-id variant in a SAVEPOINT.  If it
        fails with UndefinedColumn, roll back to the savepoint and retry the
        plain INSERT without RETURNING.  The outer transaction is preserved.
        """
        query = self._convert_placeholders(query)
        if args is not None and not isinstance(args, (tuple, list)):
            args = (args,)

        self._buffered_row = None

        is_insert = query.strip().upper().startswith('INSERT')
        has_returning = 'RETURNING' in query.upper()

        if is_insert and not has_returning:
            q_with_id = query.rstrip(';').rstrip() + ' RETURNING id'
            savepoint = '_pg_ins_ret_id'
            try:
                self._cursor.execute(f"SAVEPOINT {savepoint}")
            except Exception:
                savepoint = None

            try:
                if args:
                    result = self._cursor.execute(q_with_id, args)
                else:
                    result = self._cursor.execute(q_with_id)
                try:
                    row = self._cursor.fetchone()
                    if row and 'id' in row:
                        self._last_insert_id = row['id']
                except Exception:
                    pass
                if savepoint:
                    try:
                        self._cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
                    except Exception:
                        pass
                return result
            except Exception as e:
                # If the error is about missing id column, fall back.  Other
                # errors (unique violation, NOT NULL, FK, ...) must propagate.
                msg = str(e).lower()
                is_missing_id = (
                    'column "id" does not exist' in msg
                    or 'undefinedcolumn' in e.__class__.__name__.lower()
                    and '"id"' in msg
                )
                if not is_missing_id:
                    raise
                if savepoint:
                    try:
                        self._cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    except Exception:
                        pass
                # Retry without RETURNING id.  Leaves _last_insert_id as None.
                if args:
                    return self._cursor.execute(query, args)
                return self._cursor.execute(query)

        # Non-INSERT, or INSERT with caller-supplied RETURNING
        if args:
            result = self._cursor.execute(query, args)
        else:
            result = self._cursor.execute(query)

        if is_insert and has_returning:
            try:
                row = self._cursor.fetchone()
                if row is not None:
                    self._buffered_row = row if isinstance(row, dict) else dict(row)
                    if "id" in self._buffered_row:
                        self._last_insert_id = self._buffered_row["id"]
            except Exception:
                self._buffered_row = None
                pass

        return result
    
    def fetchone(self) -> Optional[Dict[str, Any]]:
        """Fetch single row"""
        if self._buffered_row is not None:
            row = self._buffered_row
            self._buffered_row = None
            return row
        row = self._cursor.fetchone()
        if row is None:
            return None
        # RealDictCursor already returns a dict, so return as-is
        return row if isinstance(row, dict) else dict(row) if row else None
    
    def fetchall(self) -> List[Dict[str, Any]]:
        """Fetch all rows"""
        rows = self._cursor.fetchall()
        if not rows:
            return []
        # RealDictCursor already returns dicts, so return as-is
        return [row if isinstance(row, dict) else dict(row) for row in rows]
    
    def close(self):
        """Close cursor"""
        self._cursor.close()
    
    @property
    def lastrowid(self) -> Optional[int]:
        """Get last inserted row ID"""
        return self._last_insert_id
    
    @property
    def rowcount(self) -> int:
        """Get affected row count"""
        return self._cursor.rowcount


class PostgresConnection:
    """PostgreSQL connection wrapper"""
    
    def __init__(self, conn):
        self._conn = conn
        self._pool = _get_connection_pool()
    
    def cursor(self) -> PostgresCursor:
        """Create cursor"""
        return PostgresCursor(self._conn.cursor(cursor_factory=RealDictCursor))
    
    def commit(self):
        """Commit transaction"""
        self._conn.commit()
    
    def rollback(self):
        """Rollback transaction"""
        self._conn.rollback()
    
    def close(self):
        """Return connection to pool.  Broken connections are discarded so
        we don't poison the pool with closed sockets.
        """
        if self._pool and self._conn:
            try:
                broken = bool(getattr(self._conn, "closed", 0))
                self._pool.putconn(self._conn, close=broken)
            except Exception as e:
                logger.warning(f"Failed to return connection to pool: {e}")


@contextmanager
def get_pg_connection():
    """
    Get PostgreSQL database connection (Context Manager).

    Uses _acquire_conn_with_wait so a momentary pool exhaustion does not
    immediately fail the request; we wait up to DB_POOL_ACQUIRE_TIMEOUT
    seconds for a connection to be released.
    """
    pg_pool = _get_connection_pool()
    conn = None
    broken = False
    try:
        conn = _acquire_conn_with_wait(pg_pool)
        pg_conn = PostgresConnection(conn)
        yield pg_conn
    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            # If the connection itself died mid-request, discard it instead
            # of returning it to the pool.
            if isinstance(e, (OperationalError, InterfaceError)) or getattr(conn, "closed", 0):
                broken = True
        error_msg = str(e) if e else repr(e)
        error_type = type(e).__name__
        logger.error(f"PostgreSQL operation error ({error_type}): {error_msg}", exc_info=True)
        raise
    finally:
        if conn is not None:
            try:
                pg_pool.putconn(conn, close=broken)
            except Exception:
                pass


def get_pg_connection_sync() -> PostgresConnection:
    """
    Get connection synchronously (caller must close).

    NOTE: this function leaks its connection if the caller forgets to call
    `.close()`.  Prefer `get_pg_connection()` (context manager) whenever
    possible.
    """
    pg_pool = _get_connection_pool()
    conn = _acquire_conn_with_wait(pg_pool)
    return PostgresConnection(conn)


def execute_sql(sql: str, params: tuple = None) -> List[Dict[str, Any]]:
    """
    Execute SQL and return results (convenience function)
    """
    with get_pg_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        if sql.strip().upper().startswith('SELECT'):
            return cursor.fetchall()
        conn.commit()
        return []


def is_postgres_available() -> bool:
    """Check if PostgreSQL is available"""
    if not HAS_PSYCOPG2:
        return False
    
    db_url = _get_database_url()
    if not db_url:
        return False
    
    try:
        with get_pg_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            return True
    except Exception as e:
        logger.debug(f"PostgreSQL not available: {e}")
        return False


def close_pool():
    """Close connection pool (call on app shutdown)"""
    global _connection_pool
    if _connection_pool:
        try:
            _connection_pool.closeall()
            _connection_pool = None
            logger.info("PostgreSQL connection pool closed")
        except Exception as e:
            logger.warning(f"Error closing connection pool: {e}")
