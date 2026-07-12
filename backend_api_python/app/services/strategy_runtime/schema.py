"""Idempotent schema helpers for the stateful strategy runtime."""

from __future__ import annotations

from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)


RUNTIME_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS strategy_runs (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL DEFAULT 1,
        strategy_id INTEGER NOT NULL,
        source_version_id VARCHAR(64) NOT NULL DEFAULT '',
        code_hash VARCHAR(128) NOT NULL DEFAULT '',
        parameter_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        account_id VARCHAR(64) NOT NULL DEFAULT '',
        exchange_id VARCHAR(50) NOT NULL DEFAULT '',
        credential_id INTEGER NOT NULL DEFAULT 0,
        symbol VARCHAR(80) NOT NULL DEFAULT '',
        market_type VARCHAR(20) NOT NULL DEFAULT 'swap',
        position_mode VARCHAR(20) NOT NULL DEFAULT '',
        runtime_status VARCHAR(32) NOT NULL DEFAULT 'running',
        runtime_epoch BIGINT NOT NULL DEFAULT 1,
        started_at TIMESTAMP NOT NULL DEFAULT NOW(),
        stopped_at TIMESTAMP,
        stop_reason TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_runs_strategy ON strategy_runs(strategy_id, runtime_status)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_runs_started ON strategy_runs(started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS strategy_runtime_state (
        id SERIAL PRIMARY KEY,
        strategy_run_id INTEGER NOT NULL DEFAULT 0,
        strategy_id INTEGER NOT NULL,
        state_key VARCHAR(128) NOT NULL,
        state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        version BIGINT NOT NULL DEFAULT 1,
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(strategy_run_id, strategy_id, state_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_runtime_state_strategy ON strategy_runtime_state(strategy_id)",
    """
    CREATE TABLE IF NOT EXISTS strategy_baskets (
        id SERIAL PRIMARY KEY,
        basket_id VARCHAR(96) NOT NULL,
        strategy_run_id INTEGER NOT NULL DEFAULT 0,
        strategy_id INTEGER NOT NULL,
        symbol VARCHAR(80) NOT NULL DEFAULT '',
        side VARCHAR(10) NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'idle',
        current_layer INTEGER NOT NULL DEFAULT 0,
        current_order_in_layer INTEGER NOT NULL DEFAULT 0,
        total_qty DECIMAL(28, 12) NOT NULL DEFAULT 0,
        total_notional DECIMAL(28, 12) NOT NULL DEFAULT 0,
        avg_entry_price DECIMAL(28, 12) NOT NULL DEFAULT 0,
        next_entry_trigger DECIMAL(28, 12) NOT NULL DEFAULT 0,
        take_profit_price DECIMAL(28, 12) NOT NULL DEFAULT 0,
        max_layer INTEGER NOT NULL DEFAULT 0,
        max_orders_per_layer INTEGER NOT NULL DEFAULT 0,
        risk_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(strategy_run_id, strategy_id, basket_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_baskets_strategy ON strategy_baskets(strategy_id, status)",
    """
    CREATE TABLE IF NOT EXISTS strategy_basket_orders (
        id SERIAL PRIMARY KEY,
        basket_order_id VARCHAR(128) NOT NULL DEFAULT '',
        basket_id VARCHAR(96) NOT NULL,
        strategy_run_id INTEGER NOT NULL DEFAULT 0,
        strategy_id INTEGER NOT NULL,
        symbol VARCHAR(80) NOT NULL DEFAULT '',
        side VARCHAR(10) NOT NULL,
        layer_index INTEGER NOT NULL DEFAULT 0,
        order_index INTEGER NOT NULL DEFAULT 0,
        action VARCHAR(24) NOT NULL DEFAULT 'open',
        planned_price DECIMAL(28, 12) NOT NULL DEFAULT 0,
        planned_qty DECIMAL(28, 12) NOT NULL DEFAULT 0,
        planned_notional DECIMAL(28, 12) NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'planned',
        order_intent_id INTEGER NOT NULL DEFAULT 0,
        exchange_order_id VARCHAR(100) NOT NULL DEFAULT '',
        client_order_id VARCHAR(100) NOT NULL DEFAULT '',
        filled_qty DECIMAL(28, 12) NOT NULL DEFAULT 0,
        avg_fill_price DECIMAL(28, 12) NOT NULL DEFAULT 0,
        fee DECIMAL(28, 12) NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        extra_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(strategy_run_id, basket_id, side, layer_index, order_index, action)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_basket_orders_basket ON strategy_basket_orders(strategy_run_id, basket_id, status)",
    """
    CREATE TABLE IF NOT EXISTS strategy_order_intents (
        id SERIAL PRIMARY KEY,
        strategy_run_id INTEGER NOT NULL DEFAULT 0,
        strategy_id INTEGER NOT NULL,
        basket_id VARCHAR(96) NOT NULL DEFAULT '',
        basket_order_id INTEGER NOT NULL DEFAULT 0,
        idempotency_key VARCHAR(180) NOT NULL,
        symbol VARCHAR(80) NOT NULL,
        market_type VARCHAR(20) NOT NULL DEFAULT 'swap',
        side VARCHAR(10) NOT NULL,
        position_side VARCHAR(10) NOT NULL DEFAULT '',
        reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
        order_type VARCHAR(24) NOT NULL DEFAULT 'market',
        quantity DECIMAL(28, 12) NOT NULL DEFAULT 0,
        notional DECIMAL(28, 12) NOT NULL DEFAULT 0,
        limit_price DECIMAL(28, 12) NOT NULL DEFAULT 0,
        execution_algo VARCHAR(32) NOT NULL DEFAULT 'market',
        portfolio_id VARCHAR(96) NOT NULL DEFAULT '',
        universe_id VARCHAR(96) NOT NULL DEFAULT '',
        rebalance_group_id VARCHAR(128) NOT NULL DEFAULT '',
        target_weight DECIMAL(18, 10),
        target_notional DECIMAL(28, 12),
        target_position_qty DECIMAL(28, 12),
        status VARCHAR(32) NOT NULL DEFAULT 'intent_created',
        client_order_id VARCHAR(100) NOT NULL DEFAULT '',
        exchange_order_id VARCHAR(100) NOT NULL DEFAULT '',
        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(strategy_run_id, idempotency_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_order_intents_strategy ON strategy_order_intents(strategy_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_order_intents_basket ON strategy_order_intents(strategy_run_id, basket_id)",
    """
    CREATE TABLE IF NOT EXISTS strategy_order_fills (
        id SERIAL PRIMARY KEY,
        order_intent_id INTEGER NOT NULL DEFAULT 0,
        strategy_run_id INTEGER NOT NULL DEFAULT 0,
        strategy_id INTEGER NOT NULL DEFAULT 0,
        basket_id VARCHAR(96) NOT NULL DEFAULT '',
        exchange_id VARCHAR(50) NOT NULL DEFAULT '',
        exchange_order_id VARCHAR(100) NOT NULL DEFAULT '',
        exchange_fill_id VARCHAR(128) NOT NULL DEFAULT '',
        side VARCHAR(10) NOT NULL DEFAULT '',
        position_side VARCHAR(10) NOT NULL DEFAULT '',
        price DECIMAL(28, 12) NOT NULL DEFAULT 0,
        quantity DECIMAL(28, 12) NOT NULL DEFAULT 0,
        notional DECIMAL(28, 12) NOT NULL DEFAULT 0,
        fee DECIMAL(28, 12) NOT NULL DEFAULT 0,
        fee_ccy VARCHAR(20) NOT NULL DEFAULT '',
        filled_at TIMESTAMP NOT NULL DEFAULT NOW(),
        raw_json JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_order_fills_intent ON strategy_order_fills(order_intent_id)",
    "CREATE INDEX IF NOT EXISTS idx_strategy_order_fills_strategy ON strategy_order_fills(strategy_id, filled_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS strategy_runtime_events (
        id SERIAL PRIMARY KEY,
        strategy_run_id INTEGER NOT NULL DEFAULT 0,
        strategy_id INTEGER NOT NULL DEFAULT 0,
        event_type VARCHAR(64) NOT NULL,
        severity VARCHAR(16) NOT NULL DEFAULT 'info',
        message TEXT NOT NULL DEFAULT '',
        payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_strategy_runtime_events_run ON strategy_runtime_events(strategy_run_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS strategy_runtime_locks (
        lock_key VARCHAR(180) PRIMARY KEY,
        strategy_run_id INTEGER NOT NULL DEFAULT 0,
        runtime_epoch BIGINT NOT NULL DEFAULT 1,
        owner VARCHAR(100) NOT NULL DEFAULT '',
        expires_at TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    "ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS strategy_run_id INTEGER DEFAULT 0",
    "ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS order_intent_id INTEGER DEFAULT 0",
    "ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(180) DEFAULT ''",
    "ALTER TABLE strategy_order_intents ADD COLUMN IF NOT EXISTS portfolio_id VARCHAR(96) NOT NULL DEFAULT ''",
    "ALTER TABLE strategy_order_intents ADD COLUMN IF NOT EXISTS universe_id VARCHAR(96) NOT NULL DEFAULT ''",
    "ALTER TABLE strategy_order_intents ADD COLUMN IF NOT EXISTS rebalance_group_id VARCHAR(128) NOT NULL DEFAULT ''",
    "ALTER TABLE strategy_order_intents ADD COLUMN IF NOT EXISTS target_weight DECIMAL(18, 10)",
    "ALTER TABLE strategy_order_intents ADD COLUMN IF NOT EXISTS target_notional DECIMAL(28, 12)",
    "ALTER TABLE strategy_order_intents ADD COLUMN IF NOT EXISTS target_position_qty DECIMAL(28, 12)",
    "ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS strategy_run_id INTEGER DEFAULT 0",
    "ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS order_intent_id INTEGER DEFAULT 0",
    "ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS strategy_run_id INTEGER DEFAULT 0",
)


def ensure_strategy_runtime_schema() -> None:
    """Create/upgrade runtime tables. Safe to call repeatedly."""
    for sql in RUNTIME_SCHEMA_STATEMENTS:
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(sql)
                db.commit()
                cur.close()
        except Exception as exc:
            logger.warning("strategy runtime schema statement failed: %s", exc)
