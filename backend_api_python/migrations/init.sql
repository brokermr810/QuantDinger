-- QuantDinger PostgreSQL Schema Initialization
-- This script runs automatically when PostgreSQL container starts for the first time.

-- =============================================================================
-- 1. Users & Authentication
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(100) UNIQUE,
    nickname VARCHAR(50),
    avatar VARCHAR(255) DEFAULT '/avatar2.jpg',
    status VARCHAR(20) DEFAULT 'active',  -- active/disabled/pending
    role VARCHAR(20) DEFAULT 'user',       -- admin/manager/user/viewer
    credits DECIMAL(20,2) DEFAULT 0,       -- 绉垎浣欓
    vip_expires_at TIMESTAMP,              -- VIP杩囨湡鏃堕棿
    vip_plan VARCHAR(20) DEFAULT '',       -- VIP濂楅锛歮onthly/yearly/lifetime
    vip_is_lifetime BOOLEAN DEFAULT FALSE, -- 鏄惁姘镐箙浼氬憳
    vip_monthly_credits_last_grant TIMESTAMP, -- 姘镐箙浼氬憳涓婃鍙戞斁鏈堝害绉垎鏃堕棿
    email_verified BOOLEAN DEFAULT FALSE,  -- 閭鏄惁宸查獙璇?
    referred_by INTEGER,                   -- 閭€璇蜂汉ID
    notification_settings TEXT DEFAULT '', -- 鐢ㄦ埛閫氱煡閰嶇疆 JSON (telegram_chat_id, default_channels绛?
    chart_templates TEXT DEFAULT '',      -- 鐢ㄦ埛鍥捐〃妯℃澘 JSON锛堟寚鏍囧竷灞€/鏍峰紡锛?
    timezone VARCHAR(64) DEFAULT '',       -- IANA 鏃跺尯鏍囪瘑锛岀┖琛ㄧず璺熼殢瀹㈡埛绔?娴忚鍣?
    token_version INTEGER DEFAULT 1,       -- Token鐗堟湰鍙凤紝鐢ㄤ簬鍗曚竴瀹㈡埛绔櫥褰曟帶鍒?
    password_changed_at TIMESTAMP,           -- NULL only prompts when bootstrap password is still 123456
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_referred_by ON qd_users(referred_by);

-- Note: Admin user is created automatically by the application on startup
-- using ADMIN_USER and ADMIN_PASSWORD from environment variables

-- =============================================================================
-- 1.5. Credits Log (绉垎鍙樺姩鏃ュ織)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_credits_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,            -- recharge/consume/refund/admin_adjust/vip_grant
    amount DECIMAL(20,2) NOT NULL,          -- 鍙樺姩閲戦锛堟鏁板鍔狅紝璐熸暟鍑忓皯锛?
    balance_after DECIMAL(20,2) NOT NULL,   -- 鍙樺姩鍚庝綑棰?
    feature VARCHAR(50) DEFAULT '',          -- 娑堣垂鐨勫姛鑳斤細ai_analysis/strategy_run/backtest 绛?
    reference_id VARCHAR(100) DEFAULT '',    -- 鍏宠仈ID锛堝璁㈠崟鍙枫€佸垎鏋愪换鍔D绛夛級
    remark TEXT DEFAULT '',                  -- 澶囨敞
    operator_id INTEGER,                     -- 鎿嶄綔浜篒D锛堢鐞嗗憳璋冩暣鏃惰褰曪級
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credits_log_user_id ON qd_credits_log(user_id);
CREATE INDEX IF NOT EXISTS idx_credits_log_action ON qd_credits_log(action);
CREATE INDEX IF NOT EXISTS idx_credits_log_created_at ON qd_credits_log(created_at);

-- =============================================================================
-- 1.55. Membership Orders (浼氬憳璁㈠崟 - Mock鏀粯)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_membership_orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    plan VARCHAR(20) NOT NULL,             -- monthly/yearly/lifetime
    price_usd DECIMAL(10,2) DEFAULT 0,     -- 璁㈠崟閲戦锛圲SD锛?
    status VARCHAR(20) DEFAULT 'paid',     -- paid/pending/failed/refunded (mock 榛樿 paid)
    created_at TIMESTAMP DEFAULT NOW(),
    paid_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_membership_orders_user_id ON qd_membership_orders(user_id);

-- =============================================================================
-- 1.56. USDT Orders (multi-chain single-receiving-address + amount-suffix model)
-- =============================================================================
--
-- v3.0.6 reset: replaced xpub-derived per-order addresses with a single fixed
-- receiving address per chain. Orders are identified on-chain by a unique
-- amount suffix in the low decimals (e.g. 19.991234 -> suffix 0.001234).
-- This eliminates the consolidation step (funds land directly in the main
-- wallet) and removes per-sweep TRX/gas costs.
--
-- Supported chains: TRC20 (TRON), BEP20 (BSC), ERC20 (Ethereum), SOL (Solana SPL).
-- Each chain's address is configured via USDT_{CHAIN}_ADDRESS env var.

CREATE TABLE IF NOT EXISTS qd_usdt_orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    plan VARCHAR(20) NOT NULL,                                  -- monthly/yearly/lifetime
    chain VARCHAR(20) NOT NULL DEFAULT 'TRC20',                 -- TRC20/BEP20/ERC20/SOL
    currency VARCHAR(10) NOT NULL DEFAULT 'USDT',
    amount_usdt DECIMAL(20,8) NOT NULL DEFAULT 0,               -- final amount = base + suffix (6 dp typical)
    amount_suffix DECIMAL(20,8) NOT NULL DEFAULT 0,             -- the unique suffix portion used for matching
    address VARCHAR(120) NOT NULL DEFAULT '',                   -- fixed receiving address (per chain)
    payment_uri TEXT NOT NULL DEFAULT '',                       -- full deep link (EIP-681 / Solana Pay / tron URI)
    matched_via VARCHAR(20) NOT NULL DEFAULT 'amount_suffix',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',              -- pending/paid/confirmed/expired/cancelled/failed
    tx_hash VARCHAR(120) DEFAULT '',
    paid_at TIMESTAMP,
    confirmed_at TIMESTAMP,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usdt_orders_user_id ON qd_usdt_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_usdt_orders_status ON qd_usdt_orders(status);
-- v3.0.6 cleanup: drop the legacy unique index on (chain, address) that
-- was used by the per-order xpub-derived address scheme. In the current
-- "single fixed receiving address per chain + amount-suffix matching"
-- model, every active order on the same chain shares the same address,
-- so this old index would falsely reject every second pending order
-- (UniqueViolation on idx_usdt_orders_address_unique). Safe & idempotent.
DROP INDEX IF EXISTS idx_usdt_orders_address_unique;
-- Prevent two active orders on the same chain from claiming the same amount,
-- which is the foundation of the amount-suffix matching scheme.
CREATE UNIQUE INDEX IF NOT EXISTS idx_usdt_orders_amount_active
  ON qd_usdt_orders(chain, amount_usdt)
  WHERE status IN ('pending', 'paid');

-- One-shot cleanup for installs that pre-date v3.0.6. address_index is no
-- longer used; we keep the column where it already exists to avoid breaking
-- old rows, but new installs do not need it. The DO block is idempotent and
-- safe to re-run.
DO $$
BEGIN
    -- amount_suffix
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='qd_usdt_orders' AND column_name='amount_suffix'
    ) THEN
        ALTER TABLE qd_usdt_orders ADD COLUMN amount_suffix DECIMAL(20,8) NOT NULL DEFAULT 0;
    END IF;
    -- payment_uri
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='qd_usdt_orders' AND column_name='payment_uri'
    ) THEN
        ALTER TABLE qd_usdt_orders ADD COLUMN payment_uri TEXT NOT NULL DEFAULT '';
    END IF;
    -- currency
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='qd_usdt_orders' AND column_name='currency'
    ) THEN
        ALTER TABLE qd_usdt_orders ADD COLUMN currency VARCHAR(10) NOT NULL DEFAULT 'USDT';
    END IF;
    -- matched_via
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='qd_usdt_orders' AND column_name='matched_via'
    ) THEN
        ALTER TABLE qd_usdt_orders ADD COLUMN matched_via VARCHAR(20) NOT NULL DEFAULT 'amount_suffix';
    END IF;
    -- widen amount_usdt to (20,8) so suffix at 6+ decimals fits exactly
    BEGIN
        ALTER TABLE qd_usdt_orders ALTER COLUMN amount_usdt TYPE DECIMAL(20,8);
    EXCEPTION WHEN others THEN NULL;
    END;
    -- widen address (TRC20 base58 ~34, Solana ~44; old col was 80)
    BEGIN
        ALTER TABLE qd_usdt_orders ALTER COLUMN address TYPE VARCHAR(120);
    EXCEPTION WHEN others THEN NULL;
    END;
END
$$;

-- =============================================================================
-- 1.59. OAuth CSRF State (澶?worker / 澶氬疄渚嬪叡浜紝閬垮厤 Invalid state)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_oauth_states (
    state VARCHAR(128) PRIMARY KEY,
    provider VARCHAR(20) NOT NULL,
    redirect TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON qd_oauth_states(expires_at);

-- =============================================================================
-- 1.6. Verification Codes (閭楠岃瘉鐮?
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_verification_codes (
    id SERIAL PRIMARY KEY,
    email VARCHAR(100) NOT NULL,
    code VARCHAR(10) NOT NULL,
    type VARCHAR(20) NOT NULL,              -- register/login/reset_password/change_email/change_password
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    ip_address VARCHAR(45),
    attempts INTEGER DEFAULT 0,             -- Failed verification attempts (anti-brute-force)
    last_attempt_at TIMESTAMP,              -- Last attempt time
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_verification_codes_email ON qd_verification_codes(email);
CREATE INDEX IF NOT EXISTS idx_verification_codes_type ON qd_verification_codes(type);
CREATE INDEX IF NOT EXISTS idx_verification_codes_expires ON qd_verification_codes(expires_at);

-- =============================================================================
-- 1.7. Login Attempts (鐧诲綍灏濊瘯璁板綍 - 闃茬垎鐮?
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_login_attempts (
    id SERIAL PRIMARY KEY,
    identifier VARCHAR(100) NOT NULL,       -- IP address or username
    identifier_type VARCHAR(10) NOT NULL,   -- 'ip' or 'account'
    attempt_time TIMESTAMP DEFAULT NOW(),
    success BOOLEAN DEFAULT FALSE,
    ip_address VARCHAR(45),
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_identifier ON qd_login_attempts(identifier, identifier_type);
CREATE INDEX IF NOT EXISTS idx_login_attempts_time ON qd_login_attempts(attempt_time);

-- =============================================================================
-- 1.8. OAuth Links (绗笁鏂硅处鍙峰叧鑱?
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_oauth_links (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES qd_users(id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL,          -- 'google' or 'github'
    provider_user_id VARCHAR(100) NOT NULL,
    provider_email VARCHAR(100),
    provider_name VARCHAR(100),
    provider_avatar VARCHAR(255),
    access_token TEXT,
    refresh_token TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(provider, provider_user_id)
);

CREATE INDEX IF NOT EXISTS idx_oauth_links_user_id ON qd_oauth_links(user_id);
CREATE INDEX IF NOT EXISTS idx_oauth_links_provider ON qd_oauth_links(provider);

-- =============================================================================
-- 1.9. Security Audit Log (瀹夊叏瀹¤鏃ュ織)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_security_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    action VARCHAR(50) NOT NULL,            -- login/logout/register/reset_password/oauth_login/etc
    ip_address VARCHAR(45),
    user_agent TEXT,
    details TEXT,                           -- JSON with additional info
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_logs_user_id ON qd_security_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_security_logs_action ON qd_security_logs(action);
CREATE INDEX IF NOT EXISTS idx_security_logs_created_at ON qd_security_logs(created_at);

-- =============================================================================
-- 1.10. User MFA (TOTP / Authenticator App)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_user_mfa (
    user_id INTEGER PRIMARY KEY REFERENCES qd_users(id) ON DELETE CASCADE,
    enabled BOOLEAN DEFAULT FALSE,
    secret_encrypted TEXT NOT NULL,
    recovery_codes_hash TEXT DEFAULT '',
    last_used_counter BIGINT DEFAULT 0,
    confirmed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qd_mfa_challenges (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    challenge_hash VARCHAR(128) UNIQUE NOT NULL,
    reason VARCHAR(50) DEFAULT 'risk_login',
    ip_address VARCHAR(45),
    user_agent TEXT,
    attempts INTEGER DEFAULT 0,
    expires_at TIMESTAMP NOT NULL,
    consumed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mfa_challenges_user_id ON qd_mfa_challenges(user_id);
CREATE INDEX IF NOT EXISTS idx_mfa_challenges_expires ON qd_mfa_challenges(expires_at);

-- =============================================================================
-- 2. Trading Strategies
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_strategies_trading (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_name VARCHAR(255) NOT NULL,
    strategy_type VARCHAR(50) DEFAULT 'ScriptStrategy',
    market_category VARCHAR(50) DEFAULT 'Crypto',
    execution_mode VARCHAR(20) DEFAULT 'script',
    notification_config TEXT DEFAULT '',
    status VARCHAR(20) DEFAULT 'stopped',
    symbol VARCHAR(50),
    timeframe VARCHAR(10),
    initial_capital DECIMAL(20,8) DEFAULT 1000,
    leverage INTEGER DEFAULT 1,
    market_type VARCHAR(20) DEFAULT 'swap',
    exchange_config TEXT,
    indicator_config TEXT,
    trading_config TEXT,
    ai_model_config TEXT,
    decide_interval INTEGER DEFAULT 300,
    strategy_group_id VARCHAR(100) DEFAULT '',
    group_base_name VARCHAR(255) DEFAULT '',
    strategy_mode VARCHAR(20) DEFAULT 'script',
    strategy_code TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategies_user_id ON qd_strategies_trading(user_id);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON qd_strategies_trading(status);
CREATE INDEX IF NOT EXISTS idx_strategies_group_id ON qd_strategies_trading(strategy_group_id);

-- Script source library: reusable code assets separated from live/runtime strategy rows.
CREATE TABLE IF NOT EXISTS qd_script_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    code TEXT NOT NULL DEFAULT '',
    asset_type VARCHAR(32) NOT NULL DEFAULT 'script',
    template_key VARCHAR(80) DEFAULT '',
    param_schema JSONB DEFAULT '{}'::jsonb,
    source_marketplace_indicator_id INTEGER,
    source_script_source_id INTEGER,
    visibility VARCHAR(32) DEFAULT 'private',
    status VARCHAR(32) DEFAULT 'draft',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_script_sources_user_id ON qd_script_sources(user_id);
CREATE INDEX IF NOT EXISTS idx_script_sources_marketplace ON qd_script_sources(source_marketplace_indicator_id);
ALTER TABLE qd_script_sources ADD COLUMN IF NOT EXISTS asset_type VARCHAR(32) NOT NULL DEFAULT 'script';
CREATE INDEX IF NOT EXISTS idx_script_sources_asset_type ON qd_script_sources(user_id, asset_type);

-- Add strategy_mode and strategy_code columns (script strategy support)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'qd_strategies_trading' AND column_name = 'strategy_mode'
    ) THEN
        ALTER TABLE qd_strategies_trading ADD COLUMN strategy_mode VARCHAR(20) DEFAULT 'signal';
        RAISE NOTICE 'Added strategy_mode column to qd_strategies_trading';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'qd_strategies_trading' AND column_name = 'strategy_code'
    ) THEN
        ALTER TABLE qd_strategies_trading ADD COLUMN strategy_code TEXT DEFAULT '';
        RAISE NOTICE 'Added strategy_code column to qd_strategies_trading';
    END IF;
END$$;

DO $$
BEGIN
    ALTER TABLE qd_strategies_trading DROP COLUMN IF EXISTS last_rebalance_at;
    RAISE NOTICE 'Dropped obsolete last_rebalance_at column from qd_strategies_trading';
END$$;

-- =============================================================================
-- 3. Strategy Positions
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_strategy_positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    symbol VARCHAR(50),
    symbol_canonical VARCHAR(50) DEFAULT '',
    side VARCHAR(10),  -- long/short
    size DECIMAL(20,8),
    entry_price DECIMAL(20,8),
    current_price DECIMAL(20,8),
    highest_price DECIMAL(20,8) DEFAULT 0,
    lowest_price DECIMAL(20,8) DEFAULT 0,
    unrealized_pnl DECIMAL(20,8) DEFAULT 0,
    pnl_percent DECIMAL(10,4) DEFAULT 0,
    equity DECIMAL(20,8) DEFAULT 0,
    market_type VARCHAR(20) DEFAULT 'swap',
    credential_id INTEGER DEFAULT 0,
    inst_id VARCHAR(80) DEFAULT '',
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(strategy_id, symbol, side)
);

CREATE INDEX IF NOT EXISTS idx_positions_user_id ON qd_strategy_positions(user_id);
CREATE INDEX IF NOT EXISTS idx_positions_strategy_id ON qd_strategy_positions(strategy_id);

-- =============================================================================
-- 4. Strategy Trades
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_strategy_trades (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    symbol VARCHAR(50),
    symbol_canonical VARCHAR(50) DEFAULT '',
    type VARCHAR(30),  -- open_long, close_short, etc.
    price DECIMAL(20,8),
    amount DECIMAL(20,8),
    value DECIMAL(20,8),
    commission DECIMAL(20,8) DEFAULT 0,
    commission_ccy VARCHAR(20) DEFAULT '',
    profit DECIMAL(20,8) DEFAULT 0,
    close_reason VARCHAR(64) DEFAULT '',
    matched_entry_price DECIMAL(20,8) DEFAULT 0,
    grid_matched_profit DECIMAL(20,8) DEFAULT 0,
    market_type VARCHAR(20) DEFAULT 'swap',
    credential_id INTEGER DEFAULT 0,
    inst_id VARCHAR(80) DEFAULT '',
    fill_source VARCHAR(32) DEFAULT '',
    pending_order_id INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_user_id ON qd_strategy_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_id ON qd_strategy_trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON qd_strategy_trades(created_at);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_symbol_canon ON qd_strategy_trades (strategy_id, market_type, symbol_canonical);
CREATE INDEX IF NOT EXISTS idx_positions_strategy_leg ON qd_strategy_positions (strategy_id, market_type, symbol_canonical, side);

-- Strategy AI review report history.
CREATE TABLE IF NOT EXISTS qd_strategy_review_reports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    lookback_days INTEGER NOT NULL DEFAULT 30,
    language VARCHAR(20) DEFAULT 'zh-CN',
    include_ai BOOLEAN DEFAULT TRUE,
    ai_status VARCHAR(32) DEFAULT '',
    summary TEXT DEFAULT '',
    total_net_pnl DECIMAL(20,8) DEFAULT 0,
    total_return_pct DECIMAL(20,8) DEFAULT 0,
    win_rate DECIMAL(20,8) DEFAULT 0,
    profit_factor DECIMAL(20,8) DEFAULT 0,
    max_drawdown_pct DECIMAL(20,8) DEFAULT 0,
    report_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_strategy_review_reports_strategy
    ON qd_strategy_review_reports(strategy_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_review_reports_user
    ON qd_strategy_review_reports(user_id, created_at DESC);

-- L1 account position mirror (exchange truth per credential + inst_id + side)
CREATE TABLE IF NOT EXISTS qd_account_positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    credential_id INTEGER NOT NULL DEFAULT 0,
    exchange_id VARCHAR(40) NOT NULL DEFAULT '',
    market_type VARCHAR(20) NOT NULL DEFAULT 'swap',
    inst_id VARCHAR(80) NOT NULL DEFAULT '',
    symbol VARCHAR(50) NOT NULL DEFAULT '',
    side VARCHAR(10) NOT NULL DEFAULT '',
    size DECIMAL(24, 8) NOT NULL DEFAULT 0,
    entry_price DECIMAL(24, 8) DEFAULT 0,
    mark_price DECIMAL(24, 8) DEFAULT 0,
    unrealized_pnl DECIMAL(24, 8) DEFAULT 0,
    raw_json JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (credential_id, market_type, inst_id, side)
);
CREATE INDEX IF NOT EXISTS idx_account_pos_user ON qd_account_positions(user_id);
CREATE INDEX IF NOT EXISTS idx_account_pos_cred ON qd_account_positions(credential_id, market_type);

-- Grid cell ladder state (P2). Pre-placed limit orders / user-stream driven
-- fills will land here; today only the scaffolding lives in code (see
-- app.services.live_trading.grid_cells).
CREATE TABLE IF NOT EXISTS qd_grid_cells (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    symbol VARCHAR(50) NOT NULL,
    cell_index INTEGER NOT NULL,
    lower_price DECIMAL(20,8) NOT NULL,
    upper_price DECIMAL(20,8) NOT NULL,
    state VARCHAR(24) NOT NULL DEFAULT 'idle',
    leg_size DECIMAL(20,8) DEFAULT 0,
    leg_entry_price DECIMAL(20,8) DEFAULT 0,
    working_order_id VARCHAR(64) DEFAULT '',
    last_event_ts TIMESTAMP DEFAULT NOW(),
    extra JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT uniq_grid_cell UNIQUE(strategy_id, symbol, cell_index)
);
CREATE INDEX IF NOT EXISTS idx_grid_cells_strategy ON qd_grid_cells(strategy_id);
CREATE INDEX IF NOT EXISTS idx_grid_cells_state ON qd_grid_cells(strategy_id, state);

CREATE TABLE IF NOT EXISTS qd_grid_resting_orders (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    symbol VARCHAR(50) NOT NULL,
    cell_index INTEGER NOT NULL DEFAULT 0,
    purpose VARCHAR(24) NOT NULL,
    side VARCHAR(8) NOT NULL,
    pos_side VARCHAR(8) NOT NULL DEFAULT '',
    reduce_only BOOLEAN NOT NULL DEFAULT FALSE,
    price DECIMAL(24, 8) NOT NULL,
    quantity DECIMAL(24, 8) NOT NULL DEFAULT 0,
    quote_amount DECIMAL(24, 8) NOT NULL DEFAULT 0,
    client_order_id VARCHAR(64) NOT NULL DEFAULT '',
    exchange_order_id VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    filled_quantity DECIMAL(24, 8) NOT NULL DEFAULT 0,
    avg_fill_price DECIMAL(24, 8) NOT NULL DEFAULT 0,
    processed_fill_qty DECIMAL(24, 8) NOT NULL DEFAULT 0,
    extra JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_grid_resting_strategy ON qd_grid_resting_orders(strategy_id, status);

-- =============================================================================
-- 5. Pending Orders Queue
-- =============================================================================

CREATE TABLE IF NOT EXISTS pending_orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE SET NULL,
    symbol VARCHAR(50) NOT NULL,
    signal_type VARCHAR(30) NOT NULL,
    signal_ts BIGINT,
    market_type VARCHAR(20) DEFAULT 'swap',
    order_type VARCHAR(20) DEFAULT 'market',
    amount DECIMAL(20,8) DEFAULT 0,
    price DECIMAL(20,8) DEFAULT 0,
    execution_mode VARCHAR(20) DEFAULT 'signal',
    status VARCHAR(20) DEFAULT 'pending',
    priority INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 10,
    last_error TEXT DEFAULT '',
    payload_json TEXT DEFAULT '',
    dispatch_note TEXT DEFAULT '',
    exchange_id VARCHAR(50) DEFAULT '',
    exchange_order_id VARCHAR(100) DEFAULT '',
    exchange_response_json TEXT DEFAULT '',
    filled DECIMAL(20,8) DEFAULT 0,
    avg_price DECIMAL(20,8) DEFAULT 0,
    executed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    sent_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pending_orders_user_id ON pending_orders(user_id);
CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(status);
CREATE INDEX IF NOT EXISTS idx_pending_orders_strategy_id ON pending_orders(strategy_id);

-- =============================================================================
-- 6. Strategy Notifications
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_strategy_notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    symbol VARCHAR(50) DEFAULT '',
    signal_type VARCHAR(30) DEFAULT '',
    channels VARCHAR(255) DEFAULT '',
    title VARCHAR(255) DEFAULT '',
    message TEXT DEFAULT '',
    payload_json TEXT DEFAULT '',
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON qd_strategy_notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_strategy_id ON qd_strategy_notifications(strategy_id);
CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON qd_strategy_notifications(is_read);

-- =============================================================================
-- 6a. Indicator Signal Alerts
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_indicator_signal_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    indicator_id INTEGER NOT NULL,
    indicator_name VARCHAR(160) DEFAULT '',
    market VARCHAR(32) NOT NULL,
    symbol VARCHAR(64) NOT NULL,
    symbol_name VARCHAR(128) DEFAULT '',
    timeframe VARCHAR(16) NOT NULL DEFAULT '1D',
    signal_keys TEXT DEFAULT '[]',
    channels TEXT DEFAULT '["browser"]',
    target_json TEXT DEFAULT '{}',
    param_json TEXT DEFAULT '{}',
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    last_bar_time VARCHAR(64) DEFAULT '',
    last_fingerprint VARCHAR(255) DEFAULT '',
    last_signal_payload TEXT DEFAULT '{}',
    last_error TEXT DEFAULT '',
    check_count INTEGER NOT NULL DEFAULT 0,
    trigger_count INTEGER NOT NULL DEFAULT 0,
    next_check_at TIMESTAMP DEFAULT NOW(),
    last_checked_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_indicator_signal_alerts_user_id ON qd_indicator_signal_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_indicator_signal_alerts_status_next ON qd_indicator_signal_alerts(status, next_check_at);
CREATE INDEX IF NOT EXISTS idx_indicator_signal_alerts_indicator_id ON qd_indicator_signal_alerts(indicator_id);

-- =============================================================================
-- 6b. Strategy runtime logs (dashboard / API)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_strategy_logs (
    id SERIAL PRIMARY KEY,
    strategy_id INTEGER NOT NULL REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    level VARCHAR(20) DEFAULT 'info',
    message TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_logs_strategy_id ON qd_strategy_logs(strategy_id);
CREATE INDEX IF NOT EXISTS idx_strategy_logs_timestamp ON qd_strategy_logs(timestamp);

-- =============================================================================
-- 7. Indicator Codes
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_indicator_codes (
   id serial4 NOT NULL,
   user_id int4 DEFAULT 1 NOT NULL,
   is_buy int4 DEFAULT 0 NOT NULL,
   end_time int8 DEFAULT 1 NOT NULL,
   name varchar(255) DEFAULT ''::character varying NOT NULL,
   code text NULL,
   description text DEFAULT ''::text NULL,
   publish_to_community int4 DEFAULT 0 NOT NULL,
   pricing_type varchar(20) DEFAULT 'free'::character varying NOT NULL,
   price numeric(10, 2) DEFAULT 0 NOT NULL,
   is_encrypted int4 DEFAULT 0 NOT NULL,
   preview_image varchar(500) DEFAULT ''::character varying NULL,
   vip_free boolean DEFAULT false, -- VIP鍏嶈垂鎸囨爣锛歏IP鍙厤鎵ｇН鍒嗕娇鐢?
   createtime int8 NULL,
   updatetime int8 NULL,
   created_at timestamp DEFAULT now(),
   updated_at timestamp DEFAULT now(),
   purchase_count int4 DEFAULT 0 NULL,
   avg_rating numeric(3, 2) DEFAULT 0 NULL,
   rating_count int4 DEFAULT 0 NULL,
   view_count int4 DEFAULT 0 NULL,
   review_status varchar(20) DEFAULT 'approved'::character varying NULL,
   review_note text DEFAULT ''::text NULL,
   reviewed_at timestamp NULL,
   reviewed_by int4 NULL,
   asset_type varchar(32) DEFAULT 'indicator'::character varying NULL,
    -- 瀵瑰凡璐敤鎴疯€岃█锛屾湰鍦板壇鏈€氳繃姝ゅ瓧娈靛叧鑱斿埌甯傚満涓婄殑鍘熷鎸囨爣锛?
    -- 鐢ㄤ簬鍚庣画"鍚屾浠ｇ爜"鍔熻兘鎷夊彇鍙戝竷鑰呯殑鏈€鏂扮増鏈?
    source_indicator_id int4 NULL,
    source_script_source_id int4 NULL,
    source_strategy_id int4 NULL,
    -- 澶氳瑷€鏀寔锛氱敤鎴蜂笂浼犵殑 name / description 鐢?source_language 鏍囪瘑鍘熷璇█
    -- (zh-CN / en-US / ja-JP 绛?锛沶ame_i18n / description_i18n 鏄?LLM 缈昏瘧鐢熸垚鐨?
    -- JSONB锛岀粨鏋勫舰濡?{"en-US": "...", "zh-CN": "...", ...}銆?
    -- 甯傚満/璇︽儏鎺ュ彛鎸?Accept-Language 鍛戒腑锛氬厛鏌?i18n 瀵瑰簲閿紝鏈懡涓啀鍥為€€鍒板師濮?name銆?
    -- 瑙?app/services/indicator_translator.py 涓?community_service.py:_localize_indicator銆?
    source_language varchar(16) DEFAULT NULL,
    name_i18n        jsonb       DEFAULT NULL,
    description_i18n jsonb       DEFAULT NULL,
    CONSTRAINT qd_indicator_codes_pkey PRIMARY KEY (id),
   CONSTRAINT qd_indicator_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES qd_users(id) ON DELETE CASCADE

);

CREATE INDEX IF NOT EXISTS idx_indicator_codes_user_id ON qd_indicator_codes USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_indicator_review_status ON qd_indicator_codes USING btree (review_status);
CREATE INDEX IF NOT EXISTS idx_indicator_codes_source ON qd_indicator_codes USING btree (source_indicator_id);
CREATE INDEX IF NOT EXISTS idx_indicator_codes_source_script ON qd_indicator_codes USING btree (source_script_source_id);
CREATE INDEX IF NOT EXISTS idx_indicator_codes_source_strategy ON qd_indicator_codes USING btree (source_strategy_id);

CREATE TABLE IF NOT EXISTS qd_indicator_code_versions (
   id serial4 NOT NULL,
   indicator_id int4 NOT NULL,
   user_id int4 NOT NULL,
   version_no int4 NOT NULL,
   name varchar(255) DEFAULT ''::character varying NOT NULL,
   description text DEFAULT ''::text NULL,
   code text NOT NULL,
   created_at timestamp DEFAULT now(),
   CONSTRAINT qd_indicator_code_versions_pkey PRIMARY KEY (id),
   CONSTRAINT qd_indicator_code_versions_indicator_fkey FOREIGN KEY (indicator_id) REFERENCES qd_indicator_codes(id) ON DELETE CASCADE,
   CONSTRAINT qd_indicator_code_versions_user_fkey FOREIGN KEY (user_id) REFERENCES qd_users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_indicator_code_versions_indicator ON qd_indicator_code_versions USING btree (indicator_id, version_no DESC);
CREATE INDEX IF NOT EXISTS idx_indicator_code_versions_user ON qd_indicator_code_versions USING btree (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_indicator_code_versions_no ON qd_indicator_code_versions USING btree (indicator_id, version_no);

-- =============================================================================
-- 10. Watchlist
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_watchlist (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    exchange_id VARCHAR(50) NOT NULL DEFAULT '',
    market_type VARCHAR(20) NOT NULL DEFAULT 'spot',
    instrument_id VARCHAR(120) NOT NULL DEFAULT '',
    settle_currency VARCHAR(20) NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_watchlist_asset UNIQUE(user_id, market, symbol)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user_id ON qd_watchlist(user_id);

ALTER TABLE qd_watchlist ADD COLUMN IF NOT EXISTS exchange_id VARCHAR(50) NOT NULL DEFAULT '';
ALTER TABLE qd_watchlist ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) NOT NULL DEFAULT 'spot';
ALTER TABLE qd_watchlist ADD COLUMN IF NOT EXISTS instrument_id VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE qd_watchlist ADD COLUMN IF NOT EXISTS settle_currency VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE qd_watchlist DROP CONSTRAINT IF EXISTS qd_watchlist_user_id_market_symbol_key;
DELETE FROM qd_watchlist newer
USING qd_watchlist older
WHERE newer.user_id = older.user_id
  AND newer.market = older.market
  AND newer.symbol = older.symbol
  AND newer.id < older.id;
UPDATE qd_watchlist
SET exchange_id = '', market_type = 'spot', instrument_id = ''
WHERE exchange_id <> '' OR market_type <> 'spot' OR instrument_id <> '';
DROP INDEX IF EXISTS uq_watchlist_market_context;
CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_asset
  ON qd_watchlist(user_id, market, symbol);

-- =============================================================================
-- 10A. Strategy universes and point-in-time membership
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_universes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES qd_users(id) ON DELETE CASCADE,
    code VARCHAR(80) NOT NULL,
    name VARCHAR(160) NOT NULL DEFAULT '',
    name_i18n_key VARCHAR(160) NOT NULL DEFAULT '',
    market VARCHAR(50) NOT NULL DEFAULT '',
    universe_type VARCHAR(32) NOT NULL,
    source VARCHAR(50) NOT NULL DEFAULT 'manual',
    source_ref VARCHAR(160) NOT NULL DEFAULT '',
    is_system BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_universes_system_code
  ON qd_universes(code) WHERE is_system = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_universes_user_code
  ON qd_universes(user_id, code) WHERE is_system = FALSE;
CREATE INDEX IF NOT EXISTS idx_universes_user
  ON qd_universes(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS qd_universe_members (
    id BIGSERIAL PRIMARY KEY,
    universe_id INTEGER NOT NULL REFERENCES qd_universes(id) ON DELETE CASCADE,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(80) NOT NULL,
    name VARCHAR(160) NOT NULL DEFAULT '',
    exchange_id VARCHAR(50) NOT NULL DEFAULT '',
    market_type VARCHAR(20) NOT NULL DEFAULT 'spot',
    instrument_id VARCHAR(120) NOT NULL DEFAULT '',
    settle_currency VARCHAR(20) NOT NULL DEFAULT '',
    valid_from DATE NOT NULL DEFAULT DATE '1900-01-01',
    valid_to DATE,
    member_weight DOUBLE PRECISION,
    member_rank INTEGER,
    source_version VARCHAR(120) NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_universe_member_valid_range
      CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_universe_member_interval
  ON qd_universe_members(
    universe_id, market, symbol, exchange_id, market_type, instrument_id, valid_from
  );
CREATE INDEX IF NOT EXISTS idx_universe_members_asof
  ON qd_universe_members(universe_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_universe_members_symbol
  ON qd_universe_members(market, symbol);

CREATE TABLE IF NOT EXISTS qd_universe_snapshots (
    snapshot_id VARCHAR(36) PRIMARY KEY,
    universe_id INTEGER NOT NULL REFERENCES qd_universes(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    as_of_date DATE NOT NULL,
    source_version VARCHAR(120) NOT NULL DEFAULT '',
    content_hash VARCHAR(64) NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    members_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_universe_snapshot_content
  ON qd_universe_snapshots(universe_id, user_id, as_of_date, content_hash);
CREATE INDEX IF NOT EXISTS idx_universe_snapshots_lookup
  ON qd_universe_snapshots(user_id, universe_id, as_of_date DESC);

CREATE TABLE IF NOT EXISTS qd_fundamental_snapshots (
    id BIGSERIAL PRIMARY KEY,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(80) NOT NULL,
    period_end DATE NOT NULL,
    available_at DATE NOT NULL,
    frequency VARCHAR(20) NOT NULL DEFAULT 'quarterly',
    currency VARCHAR(20) NOT NULL DEFAULT '',
    revenue DOUBLE PRECISION,
    net_income DOUBLE PRECISION,
    book_value DOUBLE PRECISION,
    shareholder_equity DOUBLE PRECISION,
    total_debt DOUBLE PRECISION,
    free_cash_flow DOUBLE PRECISION,
    shares_outstanding DOUBLE PRECISION,
    market_cap DOUBLE PRECISION,
    source VARCHAR(80) NOT NULL DEFAULT 'manual',
    source_version VARCHAR(120) NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (market, symbol, period_end, available_at, source)
);

CREATE INDEX IF NOT EXISTS idx_fundamental_snapshots_pit
  ON qd_fundamental_snapshots (market, symbol, available_at, period_end);

CREATE TABLE IF NOT EXISTS qd_portfolio_rebalance_plans (
    plan_id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE SET NULL,
    portfolio_id VARCHAR(96) NOT NULL DEFAULT '',
    universe_id INTEGER REFERENCES qd_universes(id) ON DELETE SET NULL,
    universe_snapshot_id VARCHAR(36) NOT NULL DEFAULT '',
    rebalance_group_id VARCHAR(128) NOT NULL,
    execution_mode VARCHAR(24) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    signal_time TIMESTAMP NOT NULL,
    scheduled_execution_time TIMESTAMP,
    equity DOUBLE PRECISION NOT NULL DEFAULT 0,
    cash DOUBLE PRECISION NOT NULL DEFAULT 0,
    target_weights_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_weights_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    diagnostics_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    notification_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_portfolio_execution_mode
      CHECK (execution_mode IN ('live', 'notify_only'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_rebalance_group
  ON qd_portfolio_rebalance_plans(user_id, strategy_id, rebalance_group_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_rebalance_plans_user
  ON qd_portfolio_rebalance_plans(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS qd_portfolio_rebalance_orders (
    id BIGSERIAL PRIMARY KEY,
    plan_id VARCHAR(36) NOT NULL REFERENCES qd_portfolio_rebalance_plans(plan_id) ON DELETE CASCADE,
    idempotency_key VARCHAR(180) NOT NULL,
    market VARCHAR(50) NOT NULL DEFAULT '',
    symbol VARCHAR(80) NOT NULL,
    exchange_id VARCHAR(50) NOT NULL DEFAULT '',
    market_type VARCHAR(20) NOT NULL DEFAULT 'spot',
    side VARCHAR(10) NOT NULL,
    action VARCHAR(24) NOT NULL,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    reference_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    estimated_notional DOUBLE PRECISION NOT NULL DEFAULT 0,
    estimated_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
    current_weight DOUBLE PRECISION NOT NULL DEFAULT 0,
    target_weight DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    order_intent_id INTEGER NOT NULL DEFAULT 0,
    pending_order_id BIGINT NOT NULL DEFAULT 0,
    error_code VARCHAR(120) NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_rebalance_order_key
  ON qd_portfolio_rebalance_orders(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_portfolio_rebalance_orders_plan
  ON qd_portfolio_rebalance_orders(plan_id, status);

ALTER TABLE qd_portfolio_rebalance_orders
  ADD COLUMN IF NOT EXISTS pending_order_id BIGINT NOT NULL DEFAULT 0;
ALTER TABLE qd_portfolio_rebalance_orders
  ADD COLUMN IF NOT EXISTS actual_quantity DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE qd_portfolio_rebalance_orders
  ADD COLUMN IF NOT EXISTS actual_price DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE qd_portfolio_rebalance_orders
  ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMP NULL;

CREATE TABLE IF NOT EXISTS qd_portfolio_deployments (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER NOT NULL REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES qd_script_sources(id) ON DELETE RESTRICT,
    universe_id BIGINT NOT NULL REFERENCES qd_universes(id) ON DELETE RESTRICT,
    name VARCHAR(255) NOT NULL,
    execution_mode VARCHAR(20) NOT NULL DEFAULT 'notify_only',
    credential_id INTEGER NOT NULL DEFAULT 0,
    rebalance_frequency VARCHAR(16) NOT NULL DEFAULT 'weekly',
    status VARCHAR(20) NOT NULL DEFAULT 'stopped',
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_run_at TIMESTAMP NULL,
    next_run_at TIMESTAMP NULL,
    last_error VARCHAR(500) NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_portfolio_deployment_mode CHECK (execution_mode IN ('live', 'notify_only')),
    CONSTRAINT ck_portfolio_deployment_frequency CHECK (rebalance_frequency IN ('daily', 'weekly', 'monthly')),
    CONSTRAINT ck_portfolio_deployment_status CHECK (status IN ('stopped', 'running', 'error'))
);

CREATE INDEX IF NOT EXISTS idx_portfolio_deployments_due
  ON qd_portfolio_deployments(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_portfolio_deployments_user
  ON qd_portfolio_deployments(user_id, updated_at DESC);

ALTER TABLE qd_portfolio_deployments
  ADD COLUMN IF NOT EXISTS cash_balance DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS qd_portfolio_deployment_positions (
    deployment_id BIGINT NOT NULL REFERENCES qd_portfolio_deployments(id) ON DELETE CASCADE,
    symbol VARCHAR(80) NOT NULL,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
    average_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (deployment_id, symbol)
);

INSERT INTO qd_universes
  (code, name_i18n_key, market, universe_type, source, source_ref, is_system, status)
VALUES
  ('watchlist', 'universe.catalog.watchlist', 'Mixed', 'watchlist', 'watchlist', 'current_user', TRUE, 'active'),
  ('csi300', 'universe.catalog.csi300', 'CNStock', 'index', 'provider', '000300.SH', TRUE, 'data_required'),
  ('csi500', 'universe.catalog.csi500', 'CNStock', 'index', 'provider', '000905.SH', TRUE, 'data_required'),
  ('sp500', 'universe.catalog.sp500', 'USStock', 'index', 'provider', 'SPX', TRUE, 'data_required'),
  ('nasdaq100', 'universe.catalog.nasdaq100', 'USStock', 'index', 'provider', 'NDX', TRUE, 'data_required'),
  ('etf_pool', 'universe.catalog.etfPool', 'Mixed', 'etf', 'provider', 'etf_pool', TRUE, 'data_required'),
  ('crypto_top100', 'universe.catalog.cryptoTop100', 'Crypto', 'market_cap', 'provider', 'top100', TRUE, 'data_required'),
  ('hk_equities', 'universe.catalog.hkEquities', 'HKStock', 'market', 'provider', 'hk_equities', TRUE, 'data_required')
ON CONFLICT DO NOTHING;

INSERT INTO qd_universes
  (code, name_i18n_key, market, universe_type, source, source_ref, is_system, status)
VALUES
  ('hk_core', 'universe.catalog.hkCore', 'HKStock', 'market', 'symbol_master', 'HKStock:hot:equity', TRUE, 'active'),
  ('hk_etf', 'universe.catalog.hkEtf', 'HKStock', 'etf', 'symbol_master', 'HKStock:hot:etf', TRUE, 'active'),
  ('us_etf', 'universe.catalog.usEtf', 'USStock', 'etf', 'symbol_master', 'USStock:hot:etf', TRUE, 'active')
ON CONFLICT DO NOTHING;

INSERT INTO qd_universes
  (code, name, name_i18n_key, market, universe_type, source, source_ref, is_system, status)
VALUES
  ('hk_hsi_core50', 'Hang Seng Index Core 50', 'universe.catalog.hkHsiCore50', 'HKStock', 'index', 'public_snapshot', 'HSI_CORE50', TRUE, 'data_required'),
  ('hk_tech30', 'Hang Seng TECH 30', 'universe.catalog.hkTech30', 'HKStock', 'index', 'public_snapshot', 'HSTECH', TRUE, 'data_required'),
  ('hk_china_enterprises50', 'Hang Seng China Enterprises 50', 'universe.catalog.hkChinaEnterprises50', 'HKStock', 'index', 'public_snapshot', 'HSCEI', TRUE, 'data_required'),
  ('hk_high_dividend50', 'Hang Seng High Dividend Yield 50', 'universe.catalog.hkHighDividend50', 'HKStock', 'index', 'public_snapshot', 'HSHDYI', TRUE, 'data_required')
ON CONFLICT DO NOTHING;

UPDATE qd_universes SET source_ref = 'USStock:hot:etf', updated_at = NOW()
WHERE code = 'us_etf' AND is_system = TRUE;

UPDATE qd_universes SET source_ref = 'HKStock:hot:etf', updated_at = NOW()
WHERE code = 'hk_etf' AND is_system = TRUE;

UPDATE qd_universes SET status = 'deprecated', updated_at = NOW()
WHERE code IN ('etf_pool', 'hk_equities', 'hk_core') AND is_system = TRUE;

UPDATE qd_market_symbols SET is_hot = 1, sort_order = GREATEST(sort_order, 80)
WHERE market = 'HKStock' AND asset_class = 'etf' AND symbol IN (
  '02800','02801','02823','02828','02840','02846','03032','03033','03037',
  '03040','03067','03075','03088','03110','03188','03191','03416','03437'
);

UPDATE qd_market_symbols SET is_hot = 1, sort_order = GREATEST(sort_order, 80)
WHERE market = 'USStock' AND asset_class = 'etf' AND symbol IN (
  'SPY','QQQ','IWM','DIA','VTI','VOO','IVV','EFA','EEM','AGG','BND','TLT','IEF',
  'GLD','SLV','USO','XLF','XLK','XLE','XLV','XLI','XLY','XLP','XLU','VNQ','ARKK',
  'HYG','LQD','SCHD','VUG','VTV'
);

-- =============================================================================
-- 11. Analysis Tasks
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_analysis_tasks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    model VARCHAR(100) DEFAULT '',
    language VARCHAR(20) DEFAULT 'en-US',
    status VARCHAR(20) DEFAULT 'completed',
    result_json TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_tasks_user_id ON qd_analysis_tasks(user_id);

CREATE TABLE IF NOT EXISTS qd_ai_strategy_decisions (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    strategy_run_id INTEGER NOT NULL DEFAULT 0,
    decision_key VARCHAR(64) NOT NULL,
    profile_name VARCHAR(80) NOT NULL DEFAULT '',
    model_id VARCHAR(160) NOT NULL DEFAULT '',
    prompt_version VARCHAR(80) NOT NULL DEFAULT '',
    prompt_hash VARCHAR(64) NOT NULL,
    input_hash VARCHAR(64) NOT NULL,
    symbol VARCHAR(80) NOT NULL DEFAULT '',
    as_of_time VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(24) NOT NULL,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(120) NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_strategy_decision_key
  ON qd_ai_strategy_decisions(user_id, strategy_id, decision_key);
CREATE INDEX IF NOT EXISTS idx_ai_strategy_decisions_lookup
  ON qd_ai_strategy_decisions(user_id, strategy_id, symbol, created_at DESC);

-- =============================================================================
-- 12. Backtest Runs
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_backtest_runs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER,
    strategy_name VARCHAR(255) DEFAULT '',
    asset_type VARCHAR(50) DEFAULT '',
    asset_id INTEGER,
    run_type VARCHAR(50) DEFAULT 'indicator',
    market VARCHAR(50) NOT NULL DEFAULT '',
    symbol VARCHAR(50) NOT NULL DEFAULT '',
    exchange_id VARCHAR(50) NOT NULL DEFAULT '',
    market_type VARCHAR(20) NOT NULL DEFAULT 'spot',
    instrument_id VARCHAR(120) NOT NULL DEFAULT '',
    timeframe VARCHAR(10) NOT NULL DEFAULT '',
    start_date VARCHAR(20) NOT NULL DEFAULT '',
    end_date VARCHAR(20) NOT NULL DEFAULT '',
    initial_capital DECIMAL(20,8) DEFAULT 10000,
    commission DECIMAL(10,6) DEFAULT 0.001,
    slippage DECIMAL(10,6) DEFAULT 0,
    leverage INTEGER DEFAULT 1,
    trade_direction VARCHAR(20) DEFAULT 'long',
    strategy_config TEXT DEFAULT '',
    config_snapshot TEXT DEFAULT '',
    engine_version VARCHAR(50) DEFAULT '',
    code_hash VARCHAR(128) DEFAULT '',
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT DEFAULT '',
    result_json TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_user_id ON qd_backtest_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_id ON qd_backtest_runs(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_run_type ON qd_backtest_runs(run_type);
ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS exchange_id VARCHAR(50) NOT NULL DEFAULT '';
ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) NOT NULL DEFAULT 'spot';
ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS instrument_id VARCHAR(120) NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS qd_backtest_trades (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER,
    trade_index INTEGER DEFAULT 0,
    trade_time VARCHAR(64) DEFAULT '',
    trade_type VARCHAR(64) DEFAULT '',
    side VARCHAR(32) DEFAULT '',
    price DOUBLE PRECISION DEFAULT 0,
    amount DOUBLE PRECISION DEFAULT 0,
    profit DOUBLE PRECISION DEFAULT 0,
    balance DOUBLE PRECISION DEFAULT 0,
    reason VARCHAR(64) DEFAULT '',
    payload_json TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_id ON qd_backtest_trades(run_id);

CREATE TABLE IF NOT EXISTS qd_backtest_equity_points (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL,
    point_index INTEGER DEFAULT 0,
    point_time VARCHAR(64) DEFAULT '',
    point_value DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_equity_points_run_id ON qd_backtest_equity_points(run_id);

-- =============================================================================
-- 13. Exchange Credentials
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_exchange_credentials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    name VARCHAR(100) DEFAULT '',
    exchange_id VARCHAR(50) NOT NULL,
    api_key_hint VARCHAR(50) DEFAULT '',
    encrypted_config TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exchange_credentials_user_id ON qd_exchange_credentials(user_id);

-- =============================================================================
-- 14. Manual Positions
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_manual_positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    side VARCHAR(10) DEFAULT 'long',
    quantity DECIMAL(20,8) NOT NULL DEFAULT 0,
    entry_price DECIMAL(20,8) NOT NULL DEFAULT 0,
    entry_time BIGINT,
    notes TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    group_name VARCHAR(100) DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, market, symbol, side, group_name)
);

CREATE INDEX IF NOT EXISTS idx_manual_positions_user_id ON qd_manual_positions(user_id);

-- =============================================================================
-- 15. Position Alerts
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_position_alerts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    position_id INTEGER,
    market VARCHAR(50) DEFAULT '',
    symbol VARCHAR(50) DEFAULT '',
    alert_type VARCHAR(30) NOT NULL,
    threshold DECIMAL(20,8) NOT NULL DEFAULT 0,
    notification_config TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    is_triggered INTEGER DEFAULT 0,
    last_triggered_at TIMESTAMP,
    trigger_count INTEGER DEFAULT 0,
    repeat_interval INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_position_alerts_user_id ON qd_position_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_position_alerts_position_id ON qd_position_alerts(position_id);

-- =============================================================================
-- 16. Position Monitors
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_position_monitors (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    name VARCHAR(100) DEFAULT '',
    position_ids TEXT DEFAULT '',
    monitor_type VARCHAR(20) DEFAULT 'ai',
    config TEXT DEFAULT '',
    notification_config TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    last_result TEXT DEFAULT '',
    run_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_position_monitors_user_id ON qd_position_monitors(user_id);

-- =============================================================================
-- 17. Market Symbols (Seed Data)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_market_symbols (
    id SERIAL PRIMARY KEY,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    name VARCHAR(255) DEFAULT '',
    exchange VARCHAR(50) DEFAULT '',
    market_type VARCHAR(20) NOT NULL DEFAULT 'spot',
    instrument_id VARCHAR(120) NOT NULL DEFAULT '',
    settle_currency VARCHAR(20) NOT NULL DEFAULT '',
    asset_class VARCHAR(20) NOT NULL DEFAULT 'crypto',
    currency VARCHAR(10) DEFAULT '',
    is_active INTEGER DEFAULT 1,
    is_hot INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(market, symbol, exchange, market_type, instrument_id)
);

CREATE INDEX IF NOT EXISTS idx_market_symbols_market ON qd_market_symbols(market);
CREATE INDEX IF NOT EXISTS idx_market_symbols_is_hot ON qd_market_symbols(market, is_hot);
CREATE INDEX IF NOT EXISTS idx_market_symbols_market_upper_symbol
  ON qd_market_symbols(market, UPPER(symbol));

CREATE TABLE IF NOT EXISTS qd_market_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    trigger_type VARCHAR(20) NOT NULL DEFAULT 'manual',
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    result JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_market_sync_runs_running
  ON qd_market_sync_runs ((status)) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_market_sync_runs_started
  ON qd_market_sync_runs(started_at DESC);

ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) NOT NULL DEFAULT 'spot';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS instrument_id VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS settle_currency VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS asset_class VARCHAR(20) NOT NULL DEFAULT 'crypto';
UPDATE qd_market_symbols SET asset_class = 'equity'
WHERE market IN ('CNStock', 'HKStock', 'USStock', 'MOEX') AND asset_class = 'crypto';
UPDATE qd_market_symbols SET asset_class = 'forex'
WHERE market = 'Forex' AND asset_class = 'crypto';
UPDATE qd_market_symbols SET asset_class = 'futures'
WHERE market = 'Futures' AND asset_class = 'crypto';
ALTER TABLE qd_market_symbols DROP CONSTRAINT IF EXISTS qd_market_symbols_market_symbol_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_symbols_venue_instrument
  ON qd_market_symbols(market, symbol, exchange, market_type, instrument_id);

UPDATE qd_market_symbols
SET is_active = 0
WHERE market = 'Crypto'
  AND exchange <> ''
  AND exchange NOT IN ('binance', 'bitget', 'bybit', 'okx', 'gate', 'htx');

CREATE TABLE IF NOT EXISTS qd_market_symbol_aliases (
    id SERIAL PRIMARY KEY,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    alias VARCHAR(255) NOT NULL,
    is_active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(market, symbol, alias)
);

CREATE INDEX IF NOT EXISTS idx_market_symbol_aliases_lookup
  ON qd_market_symbol_aliases(market, alias);
CREATE INDEX IF NOT EXISTS idx_market_symbol_aliases_upper_lookup
  ON qd_market_symbol_aliases(market, UPPER(alias));

-- Seed data: Hot symbols for each market
INSERT INTO qd_market_symbols (market, symbol, name, exchange, currency, is_active, is_hot, sort_order) VALUES
-- USStock (US Stocks)
('USStock', 'AAPL', 'Apple Inc.', 'NASDAQ', 'USD', 1, 1, 100),
('USStock', 'MSFT', 'Microsoft Corporation', 'NASDAQ', 'USD', 1, 1, 99),
('USStock', 'GOOGL', 'Alphabet Inc.', 'NASDAQ', 'USD', 1, 1, 98),
('USStock', 'AMZN', 'Amazon.com Inc.', 'NASDAQ', 'USD', 1, 1, 97),
('USStock', 'TSLA', 'Tesla, Inc.', 'NASDAQ', 'USD', 1, 1, 96),
('USStock', 'META', 'Meta Platforms Inc.', 'NASDAQ', 'USD', 1, 1, 95),
('USStock', 'NVDA', 'NVIDIA Corporation', 'NASDAQ', 'USD', 1, 1, 94),
('USStock', 'JPM', 'JPMorgan Chase & Co.', 'NYSE', 'USD', 1, 1, 93),
('USStock', 'V', 'Visa Inc.', 'NYSE', 'USD', 1, 1, 92),
('USStock', 'JNJ', 'Johnson & Johnson', 'NYSE', 'USD', 1, 1, 91),
-- Crypto (major + popular altcoins)
('Crypto', 'BTC/USDT', 'Bitcoin', 'Binance', 'USDT', 1, 1, 100),
('Crypto', 'ETH/USDT', 'Ethereum', 'Binance', 'USDT', 1, 1, 99),
('Crypto', 'BNB/USDT', 'BNB', 'Binance', 'USDT', 1, 1, 98),
('Crypto', 'SOL/USDT', 'Solana', 'Binance', 'USDT', 1, 1, 97),
('Crypto', 'XRP/USDT', 'Ripple', 'Binance', 'USDT', 1, 1, 96),
('Crypto', 'ADA/USDT', 'Cardano', 'Binance', 'USDT', 1, 1, 95),
('Crypto', 'DOGE/USDT', 'Dogecoin', 'Binance', 'USDT', 1, 1, 94),
('Crypto', 'DOT/USDT', 'Polkadot', 'Binance', 'USDT', 1, 1, 93),
('Crypto', 'POL/USDT', 'Polygon', 'Binance', 'USDT', 1, 1, 92),
('Crypto', 'AVAX/USDT', 'Avalanche', 'Binance', 'USDT', 1, 1, 91),
-- Layer 1 / Layer 2
('Crypto', 'LINK/USDT', 'Chainlink', 'Binance', 'USDT', 1, 1, 90),
('Crypto', 'UNI/USDT', 'Uniswap', 'Binance', 'USDT', 1, 1, 89),
('Crypto', 'ATOM/USDT', 'Cosmos', 'Binance', 'USDT', 1, 1, 88),
('Crypto', 'LTC/USDT', 'Litecoin', 'Binance', 'USDT', 1, 1, 87),
('Crypto', 'FIL/USDT', 'Filecoin', 'Binance', 'USDT', 1, 1, 86),
('Crypto', 'NEAR/USDT', 'NEAR Protocol', 'Binance', 'USDT', 1, 1, 85),
('Crypto', 'APT/USDT', 'Aptos', 'Binance', 'USDT', 1, 1, 84),
('Crypto', 'SUI/USDT', 'Sui', 'Binance', 'USDT', 1, 1, 83),
('Crypto', 'ARB/USDT', 'Arbitrum', 'Binance', 'USDT', 1, 1, 82),
('Crypto', 'OP/USDT', 'Optimism', 'Binance', 'USDT', 1, 1, 81),
('Crypto', 'SEI/USDT', 'Sei', 'Binance', 'USDT', 1, 1, 80),
('Crypto', 'TIA/USDT', 'Celestia', 'Binance', 'USDT', 1, 1, 79),
('Crypto', 'INJ/USDT', 'Injective', 'Binance', 'USDT', 1, 1, 78),
('Crypto', 'FTM/USDT', 'Fantom', 'Binance', 'USDT', 1, 1, 77),
('Crypto', 'ALGO/USDT', 'Algorand', 'Binance', 'USDT', 1, 1, 76),
('Crypto', 'HBAR/USDT', 'Hedera', 'Binance', 'USDT', 1, 1, 75),
('Crypto', 'ICP/USDT', 'Internet Computer', 'Binance', 'USDT', 1, 1, 74),
('Crypto', 'VET/USDT', 'VeChain', 'Binance', 'USDT', 1, 1, 73),
('Crypto', 'SAND/USDT', 'The Sandbox', 'Binance', 'USDT', 1, 1, 72),
('Crypto', 'MANA/USDT', 'Decentraland', 'Binance', 'USDT', 1, 1, 71),
-- DeFi
('Crypto', 'AAVE/USDT', 'Aave', 'Binance', 'USDT', 1, 1, 70),
('Crypto', 'MKR/USDT', 'Maker', 'Binance', 'USDT', 1, 1, 69),
('Crypto', 'CRV/USDT', 'Curve DAO', 'Binance', 'USDT', 1, 1, 68),
('Crypto', 'COMP/USDT', 'Compound', 'Binance', 'USDT', 1, 1, 67),
('Crypto', 'SNX/USDT', 'Synthetix', 'Binance', 'USDT', 1, 1, 66),
('Crypto', 'SUSHI/USDT', 'SushiSwap', 'Binance', 'USDT', 1, 1, 65),
('Crypto', 'DYDX/USDT', 'dYdX', 'Binance', 'USDT', 1, 1, 64),
('Crypto', 'LDO/USDT', 'Lido DAO', 'Binance', 'USDT', 1, 1, 63),
('Crypto', 'PENDLE/USDT', 'Pendle', 'Binance', 'USDT', 1, 1, 62),
('Crypto', 'JUP/USDT', 'Jupiter', 'Binance', 'USDT', 1, 1, 61),
-- Meme coins
('Crypto', 'SHIB/USDT', 'Shiba Inu', 'Binance', 'USDT', 1, 1, 60),
('Crypto', 'PEPE/USDT', 'Pepe', 'Binance', 'USDT', 1, 1, 59),
('Crypto', 'WIF/USDT', 'dogwifhat', 'Binance', 'USDT', 1, 1, 58),
('Crypto', 'FLOKI/USDT', 'Floki', 'Binance', 'USDT', 1, 1, 57),
('Crypto', 'BONK/USDT', 'Bonk', 'Binance', 'USDT', 1, 1, 56),
('Crypto', 'MEME/USDT', 'Memecoin', 'Binance', 'USDT', 1, 1, 55),
('Crypto', 'TURBO/USDT', 'Turbo', 'Binance', 'USDT', 1, 1, 54),
('Crypto', 'NEIRO/USDT', 'Neiro', 'Binance', 'USDT', 1, 1, 53),
-- AI / Infra
('Crypto', 'RENDER/USDT', 'Render', 'Binance', 'USDT', 1, 1, 52),
('Crypto', 'FET/USDT', 'Fetch.ai', 'Binance', 'USDT', 1, 1, 51),
('Crypto', 'RNDR/USDT', 'Render Network', 'Binance', 'USDT', 1, 1, 50),
('Crypto', 'TAO/USDT', 'Bittensor', 'Binance', 'USDT', 1, 1, 49),
('Crypto', 'WLD/USDT', 'Worldcoin', 'Binance', 'USDT', 1, 1, 48),
('Crypto', 'AR/USDT', 'Arweave', 'Binance', 'USDT', 1, 1, 47),
('Crypto', 'STX/USDT', 'Stacks', 'Binance', 'USDT', 1, 1, 46),
('Crypto', 'ORDI/USDT', 'ORDI', 'Binance', 'USDT', 1, 1, 45),
-- Others
('Crypto', 'TRX/USDT', 'Tron', 'Binance', 'USDT', 1, 1, 44),
('Crypto', 'ETC/USDT', 'Ethereum Classic', 'Binance', 'USDT', 1, 1, 43),
('Crypto', 'THETA/USDT', 'Theta Network', 'Binance', 'USDT', 1, 1, 42),
('Crypto', 'EOS/USDT', 'EOS', 'Binance', 'USDT', 1, 1, 41),
('Crypto', 'XLM/USDT', 'Stellar', 'Binance', 'USDT', 1, 1, 40),
('Crypto', 'GALA/USDT', 'Gala', 'Binance', 'USDT', 1, 1, 39),
('Crypto', 'IMX/USDT', 'Immutable X', 'Binance', 'USDT', 1, 1, 38),
('Crypto', 'CFX/USDT', 'Conflux', 'Binance', 'USDT', 1, 1, 37),
('Crypto', 'JASMY/USDT', 'JasmyCoin', 'Binance', 'USDT', 1, 1, 36),
('Crypto', 'CHZ/USDT', 'Chiliz', 'Binance', 'USDT', 1, 1, 35),
('Crypto', 'GMT/USDT', 'STEPN', 'Binance', 'USDT', 1, 1, 34),
('Crypto', 'CAKE/USDT', 'PancakeSwap', 'Binance', 'USDT', 1, 1, 33),
('Crypto', '1INCH/USDT', '1inch', 'Binance', 'USDT', 1, 1, 32),
('Crypto', 'ENS/USDT', 'Ethereum Name Service', 'Binance', 'USDT', 1, 1, 31),
('Crypto', 'BLUR/USDT', 'Blur', 'Binance', 'USDT', 1, 1, 30),
-- Forex
('Forex', 'XAUUSD', 'Gold/USD', 'Forex', 'USD', 1, 1, 100),
('Forex', 'XAGUSD', 'Silver/USD', 'Forex', 'USD', 1, 1, 99),
('Forex', 'EURUSD', 'Euro/US Dollar', 'Forex', 'USD', 1, 1, 98),
('Forex', 'GBPUSD', 'British Pound/US Dollar', 'Forex', 'USD', 1, 1, 97),
('Forex', 'USDJPY', 'US Dollar/Japanese Yen', 'Forex', 'USD', 1, 1, 96),
('Forex', 'AUDUSD', 'Australian Dollar/US Dollar', 'Forex', 'USD', 1, 1, 95),
('Forex', 'USDCAD', 'US Dollar/Canadian Dollar', 'Forex', 'USD', 1, 1, 94),
('Forex', 'NZDUSD', 'New Zealand Dollar/US Dollar', 'Forex', 'USD', 1, 1, 93),
('Forex', 'USDCHF', 'US Dollar/Swiss Franc', 'Forex', 'EUR', 1, 1, 92),
('Forex', 'EURJPY', 'Euro/Japanese Yen', 'Forex', 'EUR', 1, 1, 91),
-- Futures
('Futures', 'CL', 'WTI Crude Oil', 'NYMEX', 'USD', 1, 1, 100),
('Futures', 'GC', 'Gold', 'COMEX', 'USD', 1, 1, 99),
('Futures', 'SI', 'Silver', 'COMEX', 'USD', 1, 1, 98),
('Futures', 'NG', 'Natural Gas', 'NYMEX', 'USD', 1, 1, 97),
('Futures', 'HG', 'Copper', 'COMEX', 'USD', 1, 1, 96),
('Futures', 'ZC', 'Corn', 'CBOT', 'USD', 1, 1, 95),
('Futures', 'ZS', 'Soybeans', 'CBOT', 'USD', 1, 1, 94),
('Futures', 'ZW', 'Wheat', 'CBOT', 'USD', 1, 1, 93),
('Futures', 'ES', 'S&P 500 E-mini', 'CME', 'USD', 1, 1, 92),
('Futures', 'NQ', 'NASDAQ 100 E-mini', 'CME', 'USD', 1, 1, 91),
-- A-share hot symbols use the canonical exchange identifier from the symbol master.
('CNStock', '600519', '贵州茅台', 'CN', 'CNY', 1, 1, 100),
('CNStock', '600036', '招商银行', 'CN', 'CNY', 1, 1, 99),
('CNStock', '601318', '中国平安', 'CN', 'CNY', 1, 1, 98),
('CNStock', '600900', '长江电力', 'CN', 'CNY', 1, 1, 97),
('CNStock', '601899', '紫金矿业', 'CN', 'CNY', 1, 1, 96),
('CNStock', '000858', '五粮液', 'CN', 'CNY', 1, 1, 95),
('CNStock', '000333', '美的集团', 'CN', 'CNY', 1, 1, 94),
('CNStock', '002594', '比亚迪', 'CN', 'CNY', 1, 1, 93),
('CNStock', '300750', '宁德时代', 'CN', 'CNY', 1, 1, 92),
('CNStock', '000001', '平安银行', 'CN', 'CNY', 1, 1, 91),
-- Hong Kong hot symbols.
('HKStock', '00700', '腾讯控股', 'HKEX', 'HKD', 1, 1, 100),
('HKStock', '09988', '阿里巴巴-W', 'HKEX', 'HKD', 1, 1, 99),
('HKStock', '03690', '美团-W', 'HKEX', 'HKD', 1, 1, 98),
('HKStock', '01810', '小米集团-W', 'HKEX', 'HKD', 1, 1, 97),
('HKStock', '00939', '建设银行', 'HKEX', 'HKD', 1, 1, 96),
('HKStock', '01299', '友邦保险', 'HKEX', 'HKD', 1, 1, 95),
('HKStock', '02318', '中国平安', 'HKEX', 'HKD', 1, 1, 94),
('HKStock', '00388', '香港交易所', 'HKEX', 'HKD', 1, 1, 93),
('HKStock', '00883', '中国海洋石油', 'HKEX', 'HKD', 1, 1, 92),
('HKStock', '01398', '工商银行', 'HKEX', 'HKD', 1, 1, 91),
-- MOEX (Moscow Exchange) blue chips
-- Tickers are the MOEX ISS instrument codes; resolve_symbol_name() upgrades
-- the display name from MOEX ISS securities/<sym>.json on first lookup.
('MOEX', 'SBER',  'Sberbank',          'MOEX', 'RUB', 1, 1, 100),
('MOEX', 'GAZP',  'Gazprom',           'MOEX', 'RUB', 1, 1, 99),
('MOEX', 'LKOH',  'Lukoil',            'MOEX', 'RUB', 1, 1, 98),
('MOEX', 'ROSN',  'Rosneft',           'MOEX', 'RUB', 1, 1, 97),
('MOEX', 'GMKN',  'Nornickel',         'MOEX', 'RUB', 1, 1, 96),
('MOEX', 'NVTK',  'Novatek',           'MOEX', 'RUB', 1, 1, 95),
('MOEX', 'TATN',  'Tatneft',           'MOEX', 'RUB', 1, 1, 94),
('MOEX', 'VTBR',  'VTB Bank',          'MOEX', 'RUB', 1, 1, 93),
('MOEX', 'MGNT',  'Magnit',            'MOEX', 'RUB', 1, 1, 92),
('MOEX', 'YNDX',  'Yandex',            'MOEX', 'RUB', 1, 1, 91),
('MOEX', 'SBERP', 'Sberbank Preferred','MOEX', 'RUB', 1, 1, 90),
('MOEX', 'PLZL',  'Polyus',            'MOEX', 'RUB', 1, 1, 89),
('MOEX', 'CHMF',  'Severstal',         'MOEX', 'RUB', 1, 1, 88),
('MOEX', 'ALRS',  'Alrosa',            'MOEX', 'RUB', 1, 1, 87),
('MOEX', 'MOEX',  'Moscow Exchange',   'MOEX', 'RUB', 1, 1, 86)
ON CONFLICT (market, symbol, exchange, market_type, instrument_id) DO NOTHING;

-- Remove legacy A-share rows that used venue-specific exchange identifiers.
-- Canonical symbol-master rows use exchange = 'CN'; the old identifiers caused
-- duplicate search results because exchange is part of the uniqueness key.
UPDATE qd_market_symbols canonical
SET is_hot = GREATEST(canonical.is_hot, legacy.is_hot),
    sort_order = GREATEST(canonical.sort_order, legacy.sort_order)
FROM qd_market_symbols legacy
WHERE canonical.market = 'CNStock'
  AND canonical.exchange = 'CN'
  AND legacy.market = canonical.market
  AND legacy.symbol = canonical.symbol
  AND legacy.exchange IN ('SSE', 'SZSE')
  AND legacy.market_type = canonical.market_type
  AND legacy.instrument_id = canonical.instrument_id;

DELETE FROM qd_market_symbols legacy
USING qd_market_symbols canonical
WHERE legacy.market = 'CNStock'
  AND legacy.exchange IN ('SSE', 'SZSE')
  AND canonical.market = legacy.market
  AND canonical.symbol = legacy.symbol
  AND canonical.exchange = 'CN'
  AND canonical.market_type = legacy.market_type
  AND canonical.instrument_id = legacy.instrument_id;

-- =============================================================================
-- 19.5. Analysis Memory (Fast AI Analysis Memory System)
-- =============================================================================
-- Stores AI analysis results for history, feedback, and learning.

CREATE TABLE IF NOT EXISTS qd_analysis_memory (
    id SERIAL PRIMARY KEY,
    user_id INT,                                -- User who created this analysis (for filtering)
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    decision VARCHAR(10) NOT NULL,
    confidence INT DEFAULT 50,
    price_at_analysis DECIMAL(24, 8),
    summary TEXT,
    reasons JSONB,
    scores JSONB,
    indicators_snapshot JSONB,
    raw_result JSONB,                           -- Full analysis result for history replay
    consensus_score DECIMAL(24, 8),
    consensus_abs DECIMAL(24, 8),
    agreement_ratio DECIMAL(10, 6),
    quality_multiplier DECIMAL(10, 6),
    created_at TIMESTAMP DEFAULT NOW(),
    validated_at TIMESTAMP,
    actual_outcome VARCHAR(20),
    actual_return_pct DECIMAL(10, 4),
    was_correct BOOLEAN,
    user_feedback VARCHAR(20),                  -- helpful/not_helpful
    feedback_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_memory_symbol ON qd_analysis_memory(market, symbol);
CREATE INDEX IF NOT EXISTS idx_analysis_memory_created ON qd_analysis_memory(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_memory_validated ON qd_analysis_memory(validated_at) WHERE validated_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_analysis_memory_user ON qd_analysis_memory(user_id);

-- Migration: Add user_id column to existing qd_analysis_memory table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'qd_analysis_memory' AND column_name = 'user_id'
    ) THEN
        ALTER TABLE qd_analysis_memory ADD COLUMN user_id INT;
        CREATE INDEX IF NOT EXISTS idx_analysis_memory_user ON qd_analysis_memory(user_id);
        RAISE NOTICE 'Added user_id column to qd_analysis_memory';
    END IF;
END $$;

-- =============================================================================
-- 20. Migration: Add token_version for single-client login
-- =============================================================================
-- This migration adds token_version column for enforcing single-client login.
-- When a user logs in from a new device, the token_version is incremented,
-- invalidating all previous tokens and forcing other sessions to logout.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'qd_users' AND column_name = 'token_version'
    ) THEN
        ALTER TABLE qd_users ADD COLUMN token_version INTEGER DEFAULT 1;
        RAISE NOTICE 'Added token_version column to qd_users table';
    END IF;
END $$;

-- =============================================================================
-- 20b. Migration: user profile timezone (IANA)
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'qd_users' AND column_name = 'timezone'
    ) THEN
        ALTER TABLE qd_users ADD COLUMN timezone VARCHAR(64) DEFAULT '';
        RAISE NOTICE 'Added timezone column to qd_users table';
    END IF;
END $$;

-- =============================================================================
-- 20c. Migration: password_changed_at (initial password reminder)
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'qd_users' AND column_name = 'password_changed_at'
    ) THEN
        ALTER TABLE qd_users ADD COLUMN password_changed_at TIMESTAMP NULL;
        -- One-time backfill when upgrading old DBs (skip on fresh installs after bootstrap user exists)
        UPDATE qd_users
        SET password_changed_at = COALESCE(updated_at, created_at, NOW())
        WHERE password_changed_at IS NULL;
        RAISE NOTICE 'Added password_changed_at column to qd_users table (existing users backfilled)';
    END IF;
END $$;

-- =============================================================================
-- 20d. Migration: strategy trade close reason & grid matched PnL (old DBs)
-- =============================================================================

ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS close_reason VARCHAR(64) DEFAULT '';
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS matched_entry_price DECIMAL(20,8) DEFAULT 0;
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS grid_matched_profit DECIMAL(20,8) DEFAULT 0;
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) DEFAULT 'swap';
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS credential_id INTEGER DEFAULT 0;
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS inst_id VARCHAR(80) DEFAULT '';
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS symbol_canonical VARCHAR(50) DEFAULT '';
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS fill_source VARCHAR(32) DEFAULT '';
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS pending_order_id INTEGER DEFAULT 0;
ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) DEFAULT 'swap';
ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS credential_id INTEGER DEFAULT 0;
ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS inst_id VARCHAR(80) DEFAULT '';
ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS symbol_canonical VARCHAR(50) DEFAULT '';
ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS credential_id INTEGER DEFAULT 0;
ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS inst_id VARCHAR(80) DEFAULT '';
ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS strategy_run_id INTEGER DEFAULT 0;
ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS order_intent_id INTEGER DEFAULT 0;
ALTER TABLE pending_orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(180) DEFAULT '';
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS strategy_run_id INTEGER DEFAULT 0;
ALTER TABLE qd_strategy_trades ADD COLUMN IF NOT EXISTS order_intent_id INTEGER DEFAULT 0;
ALTER TABLE qd_strategy_positions ADD COLUMN IF NOT EXISTS strategy_run_id INTEGER DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_trades_strategy_symbol_canon ON qd_strategy_trades (strategy_id, market_type, symbol_canonical);
CREATE INDEX IF NOT EXISTS idx_positions_strategy_leg ON qd_strategy_positions (strategy_id, market_type, symbol_canonical, side);

-- =============================================================================
-- 20e. Stateful ScriptStrategy runtime / basket / order intent infrastructure
-- =============================================================================

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
);
CREATE INDEX IF NOT EXISTS idx_strategy_runs_strategy ON strategy_runs(strategy_id, runtime_status);
CREATE INDEX IF NOT EXISTS idx_strategy_runs_started ON strategy_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS strategy_runtime_state (
    id SERIAL PRIMARY KEY,
    strategy_run_id INTEGER NOT NULL DEFAULT 0,
    strategy_id INTEGER NOT NULL,
    state_key VARCHAR(128) NOT NULL,
    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    version BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(strategy_run_id, strategy_id, state_key)
);
CREATE INDEX IF NOT EXISTS idx_strategy_runtime_state_strategy ON strategy_runtime_state(strategy_id);

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
);
CREATE INDEX IF NOT EXISTS idx_strategy_baskets_strategy ON strategy_baskets(strategy_id, status);

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
);
CREATE INDEX IF NOT EXISTS idx_strategy_basket_orders_basket ON strategy_basket_orders(strategy_run_id, basket_id, status);

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
    status VARCHAR(32) NOT NULL DEFAULT 'intent_created',
    client_order_id VARCHAR(100) NOT NULL DEFAULT '',
    exchange_order_id VARCHAR(100) NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(strategy_run_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_strategy_order_intents_strategy ON strategy_order_intents(strategy_id, status);
CREATE INDEX IF NOT EXISTS idx_strategy_order_intents_basket ON strategy_order_intents(strategy_run_id, basket_id);

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
);
CREATE INDEX IF NOT EXISTS idx_strategy_order_fills_intent ON strategy_order_fills(order_intent_id);
CREATE INDEX IF NOT EXISTS idx_strategy_order_fills_strategy ON strategy_order_fills(strategy_id, filled_at DESC);

CREATE TABLE IF NOT EXISTS strategy_runtime_events (
    id SERIAL PRIMARY KEY,
    strategy_run_id INTEGER NOT NULL DEFAULT 0,
    strategy_id INTEGER NOT NULL DEFAULT 0,
    event_type VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'info',
    message TEXT NOT NULL DEFAULT '',
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_strategy_runtime_events_run ON strategy_runtime_events(strategy_run_id, created_at DESC);

CREATE TABLE IF NOT EXISTS strategy_runtime_locks (
    lock_key VARCHAR(180) PRIMARY KEY,
    strategy_run_id INTEGER NOT NULL DEFAULT 0,
    runtime_epoch BIGINT NOT NULL DEFAULT 1,
    owner VARCHAR(100) NOT NULL DEFAULT '',
    expires_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS qd_account_positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    credential_id INTEGER NOT NULL DEFAULT 0,
    exchange_id VARCHAR(40) NOT NULL DEFAULT '',
    market_type VARCHAR(20) NOT NULL DEFAULT 'swap',
    inst_id VARCHAR(80) NOT NULL DEFAULT '',
    symbol VARCHAR(50) NOT NULL DEFAULT '',
    side VARCHAR(10) NOT NULL DEFAULT '',
    size DECIMAL(24, 8) NOT NULL DEFAULT 0,
    entry_price DECIMAL(24, 8) DEFAULT 0,
    mark_price DECIMAL(24, 8) DEFAULT 0,
    unrealized_pnl DECIMAL(24, 8) DEFAULT 0,
    raw_json JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (credential_id, market_type, inst_id, side)
);
CREATE INDEX IF NOT EXISTS idx_account_pos_user ON qd_account_positions(user_id);
CREATE INDEX IF NOT EXISTS idx_account_pos_cred ON qd_account_positions(credential_id, market_type);

-- =============================================================================
-- 21. Indicator Community Tables
-- =============================================================================

-- Indicator Purchases (璐拱璁板綍)
CREATE TABLE IF NOT EXISTS qd_indicator_purchases (
    id SERIAL PRIMARY KEY,
    indicator_id INTEGER NOT NULL REFERENCES qd_indicator_codes(id) ON DELETE CASCADE,
    buyer_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    seller_id INTEGER NOT NULL REFERENCES qd_users(id),
    price DECIMAL(10,2) NOT NULL DEFAULT 0,
    gross_price DECIMAL(10,2),
    platform_fee DECIMAL(10,2) DEFAULT 0,
    seller_amount DECIMAL(10,2),
    fee_rate DECIMAL(10,6) DEFAULT 0,
    asset_name_snapshot VARCHAR(255),
    asset_description_snapshot TEXT,
    asset_code_snapshot TEXT,
    asset_type_snapshot VARCHAR(32),
    asset_preview_image_snapshot VARCHAR(500),
    asset_is_encrypted_snapshot INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(indicator_id, buyer_id)
);

ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS gross_price DECIMAL(10,2);
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS platform_fee DECIMAL(10,2) DEFAULT 0;
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS seller_amount DECIMAL(10,2);
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS fee_rate DECIMAL(10,6) DEFAULT 0;
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS asset_name_snapshot VARCHAR(255);
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS asset_description_snapshot TEXT;
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS asset_code_snapshot TEXT;
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS asset_type_snapshot VARCHAR(32);
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS asset_preview_image_snapshot VARCHAR(500);
ALTER TABLE qd_indicator_purchases ADD COLUMN IF NOT EXISTS asset_is_encrypted_snapshot INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_purchases_indicator ON qd_indicator_purchases(indicator_id);
CREATE INDEX IF NOT EXISTS idx_purchases_buyer ON qd_indicator_purchases(buyer_id);
CREATE INDEX IF NOT EXISTS idx_purchases_seller ON qd_indicator_purchases(seller_id);

-- Indicator Comments (璇勮)
CREATE TABLE IF NOT EXISTS qd_indicator_comments (
    id SERIAL PRIMARY KEY,
    indicator_id INTEGER NOT NULL REFERENCES qd_indicator_codes(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    rating INTEGER DEFAULT 5 CHECK (rating >= 1 AND rating <= 5),
    content TEXT DEFAULT '',
    parent_id INTEGER REFERENCES qd_indicator_comments(id) ON DELETE CASCADE,
    is_deleted INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comments_indicator ON qd_indicator_comments(indicator_id);
CREATE INDEX IF NOT EXISTS idx_comments_user ON qd_indicator_comments(user_id);

-- Add community stats columns to qd_indicator_codes
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'qd_indicator_codes' AND column_name = 'purchase_count'
    ) THEN
        ALTER TABLE qd_indicator_codes ADD COLUMN purchase_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added purchase_count column to qd_indicator_codes';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'qd_indicator_codes' AND column_name = 'avg_rating'
    ) THEN
        ALTER TABLE qd_indicator_codes ADD COLUMN avg_rating DECIMAL(3,2) DEFAULT 0;
        RAISE NOTICE 'Added avg_rating column to qd_indicator_codes';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'qd_indicator_codes' AND column_name = 'rating_count'
    ) THEN
        ALTER TABLE qd_indicator_codes ADD COLUMN rating_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added rating_count column to qd_indicator_codes';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'qd_indicator_codes' AND column_name = 'view_count'
    ) THEN
        ALTER TABLE qd_indicator_codes ADD COLUMN view_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added view_count column to qd_indicator_codes';
    END IF;
END $$;

-- =============================================================================
-- Quick Trades (manual / discretionary orders from Quick Trade Panel)
-- =============================================================================
CREATE TABLE IF NOT EXISTS qd_quick_trades (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    credential_id   INTEGER DEFAULT 0,
    exchange_id     VARCHAR(40) NOT NULL DEFAULT '',
    symbol          VARCHAR(60) NOT NULL DEFAULT '',
    side            VARCHAR(10) NOT NULL DEFAULT '',       -- buy / sell
    order_type      VARCHAR(20) NOT NULL DEFAULT 'market', -- market / limit
    amount          DECIMAL(24, 8) DEFAULT 0,
    price           DECIMAL(24, 8) DEFAULT 0,
    leverage        INTEGER DEFAULT 1,
    market_type     VARCHAR(20) DEFAULT 'swap',            -- swap / spot
    tp_price        DECIMAL(24, 8) DEFAULT 0,
    sl_price        DECIMAL(24, 8) DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'submitted',       -- submitted / filled / failed / cancelled
    exchange_order_id VARCHAR(120) DEFAULT '',
    filled_amount   DECIMAL(24, 8) DEFAULT 0,
    avg_fill_price  DECIMAL(24, 8) DEFAULT 0,
    commission      DECIMAL(24, 8) DEFAULT 0,              -- realised trading fee for this fill (best-effort)
    commission_ccy  VARCHAR(16) DEFAULT '',                -- e.g. 'USDT' / 'BNB'; empty when unknown
    error_msg       TEXT DEFAULT '',
    source          VARCHAR(40) DEFAULT 'manual',          -- ai_radar / ai_analysis / indicator / manual
    raw_result      JSONB,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quick_trades_user    ON qd_quick_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_quick_trades_created ON qd_quick_trades(created_at DESC);

-- Migration: Add commission tracking columns to existing qd_quick_trades.
-- (Introduced in v3.0.8. Pre-existing rows default to 0 / '' which is the
-- accurate value 鈥?those orders were never enriched with exchange fee data.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'qd_quick_trades' AND column_name = 'commission'
    ) THEN
        ALTER TABLE qd_quick_trades ADD COLUMN commission DECIMAL(24, 8) DEFAULT 0;
        ALTER TABLE qd_quick_trades ADD COLUMN commission_ccy VARCHAR(16) DEFAULT '';
        RAISE NOTICE 'Added commission / commission_ccy columns to qd_quick_trades';
    END IF;
END $$;

-- =============================================================================
-- Polymarket (宸茬Щ闄?/ removed in v3.0.7)
-- =============================================================================
-- 棰勬祴甯傚満鐩稿叧鍔熻兘宸蹭笅绾匡紝鐩稿叧鍚庡彴 LLM worker銆丄PI銆佹暟鎹簮鍏ㄩ儴鍒犻櫎銆?
-- 鑰佸簱涓€娆℃€ф竻鐞嗗搴?3 寮犺〃涓庣储寮曪紱鑻ユ槸鍏ㄦ柊閮ㄧ讲锛屼笅闈?DROP 鏄?no-op銆?
DROP TABLE IF EXISTS qd_polymarket_asset_opportunities CASCADE;
DROP TABLE IF EXISTS qd_polymarket_ai_analysis CASCADE;
DROP TABLE IF EXISTS qd_polymarket_markets CASCADE;

-- =============================================================================
-- 30. Agent Gateway (/api/agent/v1) 鈥?tokens, async jobs, audit, idempotency
-- =============================================================================
-- These tables back the multi-agent runtime (see docs/agent/AI_INTEGRATION_DESIGN.md).
-- They are tenant-scoped via user_id and stay isolated from human JWT sessions.

CREATE TABLE IF NOT EXISTS qd_agent_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    token_prefix VARCHAR(24) NOT NULL,           -- e.g. "qd_agent_AbCdEf12" (shown to humans/audit only)
    token_hash VARCHAR(128) NOT NULL,            -- sha256(token) hex
    scopes TEXT NOT NULL DEFAULT 'R',            -- comma-separated subset of R,W,B,N,C,T
    markets TEXT NOT NULL DEFAULT '*',           -- comma-separated allowlist or '*'
    instruments TEXT NOT NULL DEFAULT '*',       -- comma-separated allowlist or '*'
    paper_only BOOLEAN NOT NULL DEFAULT TRUE,    -- T-class always starts paper-only
    rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
    status VARCHAR(20) NOT NULL DEFAULT 'active',-- active/revoked/expired
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tokens_hash ON qd_agent_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_user ON qd_agent_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_status ON qd_agent_tokens(status);

CREATE TABLE IF NOT EXISTS qd_agent_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(40) NOT NULL UNIQUE,          -- public id (uuid4 hex)
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    agent_token_id INTEGER REFERENCES qd_agent_tokens(id) ON DELETE SET NULL,
    kind VARCHAR(40) NOT NULL,                   -- backtest / experiment_pipeline / ai_optimize / ...
    status VARCHAR(20) NOT NULL DEFAULT 'queued',-- queued/running/succeeded/failed/cancelled
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    progress JSONB,
    idempotency_key VARCHAR(120),
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_user ON qd_agent_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_status ON qd_agent_jobs(status);
CREATE INDEX IF NOT EXISTS idx_agent_jobs_kind ON qd_agent_jobs(kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_jobs_idem
    ON qd_agent_jobs(agent_token_id, kind, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS qd_agent_audit (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    agent_token_id INTEGER,
    agent_name VARCHAR(80),
    route VARCHAR(160) NOT NULL,
    method VARCHAR(8) NOT NULL,
    scope_class VARCHAR(4) NOT NULL,             -- R / W / B / N / C / T
    status_code INTEGER NOT NULL,
    idempotency_key VARCHAR(120),
    request_summary JSONB,                       -- redacted (no secrets)
    response_summary JSONB,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_user ON qd_agent_audit(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_token ON qd_agent_audit(agent_token_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_class ON qd_agent_audit(scope_class);

-- Paper-only ledger so trading-class tokens can simulate without ever touching
-- live exchange credentials.  Real-money execution stays gated by paper_only=false
-- AND the existing TradingExecutor code path.
CREATE TABLE IF NOT EXISTS qd_agent_paper_orders (
    id BIGSERIAL PRIMARY KEY,
    order_uid VARCHAR(40) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    agent_token_id INTEGER REFERENCES qd_agent_tokens(id) ON DELETE SET NULL,
    market VARCHAR(40) NOT NULL,
    symbol VARCHAR(60) NOT NULL,
    side VARCHAR(8) NOT NULL,                    -- buy / sell
    order_type VARCHAR(16) NOT NULL DEFAULT 'market',
    qty DECIMAL(28,10) NOT NULL,
    limit_price DECIMAL(28,10),
    fill_price DECIMAL(28,10),
    fill_value DECIMAL(28,10),
    status VARCHAR(16) NOT NULL DEFAULT 'filled',-- filled / cancelled / rejected
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_paper_orders_user ON qd_agent_paper_orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_paper_orders_token ON qd_agent_paper_orders(agent_token_id);

-- Jobs created before progress JSONB existed (Agent Gateway v3.1)
ALTER TABLE qd_agent_jobs ADD COLUMN IF NOT EXISTS progress JSONB;

-- ===== Script strategy templates seed =====
CREATE TABLE IF NOT EXISTS qd_script_templates (
    id SERIAL PRIMARY KEY,
    template_key VARCHAR(80) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    code TEXT NOT NULL DEFAULT '',
    param_schema JSONB DEFAULT '{}'::jsonb,
    tags JSONB DEFAULT '[]'::jsonb,
    icon VARCHAR(64) DEFAULT 'appstore',
    accent VARCHAR(32) DEFAULT 'blue',
    sort_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_script_templates_active ON qd_script_templates(is_active, sort_order);

DELETE FROM qd_script_templates
WHERE template_key IN ('ema_atr_trend_risk', 'breakout_retest_guard');


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('classic_ema_atr_trend', 'Classic EMA ATR Trend', 'EMA trend-following strategy with ATR stop, trailing stop, and cooldown.', $qdtpl1$"""
Classic EMA ATR Trend
EMA trend-following strategy with ATR stop, trailing stop, and cooldown.
"""

# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.fast_ema = ctx.param("fast_ema", 12)
    ctx.slow_ema = ctx.param("slow_ema", 48)
    ctx.atr_period = ctx.param("atr_period", 14)
    ctx.risk_pct = ctx.param("risk_pct", 0.35)
    ctx.stop_atr = ctx.param("stop_atr", 2.2)
    ctx.trail_atr = ctx.param("trail_atr", 2.8)
    ctx.cooldown_bars = ctx.param("cooldown_bars", 8)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        v = float(ctx.investment_amount or 0.0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    try:
        return float(ctx.equity or 0.0)
    except Exception:
        return 0.0

def _qty(ctx, pct, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(_budget(ctx) * float(pct), 10.0) * lev / price

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)


def _ema(values, period):
    if not values:
        return 0.0
    k = 2.0 / (float(period) + 1.0)
    out = float(values[0])
    for v in values[1:]:
        out = float(v) * k + out * (1.0 - k)
    return out


def _atr(bars, period):
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(len(bars) - period, len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.slow_ema), int(ctx.atr_period)) + 3
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars]
    atr = _atr(bars, int(ctx.atr_period))
    if atr <= 0:
        return
    fast = _ema(closes[-int(ctx.fast_ema):], int(ctx.fast_ema))
    slow = _ema(closes[-int(ctx.slow_ema):], int(ctx.slow_ema))
    key = "ema_atr_" + side
    if _has_pos(ctx, side):
        best = float(ctx.state.get(key + "_best", price) or price)
        stop = float(ctx.state.get(key + "_stop", 0.0) or 0.0)
        if side == "long":
            best = max(best, price)
            stop = max(stop, best - atr * float(ctx.trail_atr)) if stop > 0 else price - atr * float(ctx.stop_atr)
            hit = price <= stop
        else:
            best = min(best, price)
            stop = min(stop, best + atr * float(ctx.trail_atr)) if stop > 0 else price + atr * float(ctx.stop_atr)
            hit = price >= stop
        ctx.state.set(key + "_best", best)
        ctx.state.set(key + "_stop", stop)
        if hit:
            _close(ctx, side, "ema_atr_stop")
            ctx.state.set(key + "_cooldown", _bar_no(ctx) + int(ctx.cooldown_bars))
        return
    if _bar_no(ctx) < int(ctx.state.get(key + "_cooldown", -1) or -1):
        return
    signal = fast > slow if side == "long" else fast < slow
    if signal:
        qty = _qty(ctx, ctx.risk_pct, price)
        _open(ctx, side, qty, price, "ema_atr_entry")
        ctx.state.set(key + "_best", price)
        ctx.state.set(key + "_stop", price - atr * float(ctx.stop_atr) if side == "long" else price + atr * float(ctx.stop_atr))
$qdtpl1$,
 '{"params":[{"name":"fast_ema","type":"integer","default":12,"min":2,"max":200,"step":1},{"name":"slow_ema","type":"integer","default":48,"min":5,"max":400,"step":1},{"name":"atr_period","type":"integer","default":14,"min":3,"max":120,"step":1},{"name":"risk_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01},{"name":"stop_atr","type":"number","default":2.2,"min":0.5,"max":12,"step":0.1},{"name":"trail_atr","type":"number","default":2.8,"min":0.5,"max":12,"step":0.1},{"name":"cooldown_bars","type":"integer","default":8,"min":0,"max":300,"step":1}]}'::jsonb, '["trend", "atr"]'::jsonb, 'line-chart', 'green',
 10, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('donchian_breakout_pyramid', 'Donchian Breakout Pyramid', 'Channel breakout strategy with pyramiding, hard stop, and exit channel.', $qdtpl2$"""
Donchian Breakout Pyramid
Channel breakout strategy with pyramiding, hard stop, and exit channel.
"""

# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.entry_lookback = ctx.param("entry_lookback", 55)
    ctx.exit_lookback = ctx.param("exit_lookback", 20)
    ctx.max_layers = ctx.param("max_layers", 4)
    ctx.step_pct = ctx.param("step_pct", 0.012)
    ctx.hard_stop_price_pct = ctx.param("hard_stop_price_pct", 0.06)
    ctx.cooldown_bars = ctx.param("cooldown_bars", 8)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        v = float(ctx.investment_amount or 0.0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    try:
        return float(ctx.equity or 0.0)
    except Exception:
        return 0.0

def _qty(ctx, pct, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(_budget(ctx) * float(pct), 10.0) * lev / price

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)

def _key(side, name):
    return "donchian_" + side + "_" + name

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.entry_lookback), int(ctx.exit_lookback)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    entry_window = bars[-int(ctx.entry_lookback)-1:-1]
    exit_window = bars[-int(ctx.exit_lookback)-1:-1]
    high = max([float(b["high"]) for b in entry_window])
    low = min([float(b["low"]) for b in entry_window])
    exit_high = max([float(b["high"]) for b in exit_window])
    exit_low = min([float(b["low"]) for b in exit_window])
    if _has_pos(ctx, side):
        entry = _entry(ctx, side, price)
        channel_exit = price <= exit_low if side == "long" else price >= exit_high
        if channel_exit or _pnl(side, entry, price) <= -float(ctx.hard_stop_price_pct):
            _close(ctx, side, "donchian_exit")
            ctx.state.set(_key(side, "layer"), 0)
            ctx.state.set(_key(side, "cooldown"), _bar_no(ctx) + int(ctx.cooldown_bars))
            return
        layer = int(ctx.state.get(_key(side, "layer"), 1) or 1)
        next_add = float(ctx.state.get(_key(side, "next_add"), 0.0) or 0.0)
        add_hit = price >= next_add if side == "long" else price <= next_add
        if layer < int(ctx.max_layers) and next_add > 0 and add_hit:
            qty = _qty(ctx, 1.0 / max(1, int(ctx.max_layers)), price)
            _add(ctx, side, qty, price, "donchian_pyramid")
            ctx.state.set(_key(side, "layer"), layer + 1)
            ctx.state.set(_key(side, "next_add"), price * (1.0 + float(ctx.step_pct)) if side == "long" else price * (1.0 - float(ctx.step_pct)))
        return
    if _bar_no(ctx) < int(ctx.state.get(_key(side, "cooldown"), -1) or -1):
        return
    breakout = price > high if side == "long" else price < low
    if breakout:
        qty = _qty(ctx, 1.0 / max(1, int(ctx.max_layers)), price)
        _open(ctx, side, qty, price, "donchian_breakout")
        ctx.state.set(_key(side, "layer"), 1)
        ctx.state.set(_key(side, "next_add"), price * (1.0 + float(ctx.step_pct)) if side == "long" else price * (1.0 - float(ctx.step_pct)))
$qdtpl2$,
 '{"params":[{"name":"entry_lookback","type":"integer","default":55,"min":10,"max":300,"step":1},{"name":"exit_lookback","type":"integer","default":20,"min":5,"max":200,"step":1},{"name":"max_layers","type":"integer","default":4,"min":1,"max":8,"step":1},{"name":"step_pct","type":"percent","default":0.012,"min":0.001,"max":0.2,"step":0.001},{"name":"hard_stop_price_pct","type":"percent","default":0.06,"min":0.005,"max":0.8,"step":0.005},{"name":"cooldown_bars","type":"integer","default":8,"min":0,"max":300,"step":1}]}'::jsonb, '["breakout", "pyramid"]'::jsonb, 'rise', 'cyan',
 20, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('bollinger_reversion_basket', 'Bollinger Reversion Basket', 'Bollinger mean-reversion basket with controlled add layers and average-cost exit.', $qdtpl3$"""
Bollinger Reversion Basket
Bollinger mean-reversion basket with controlled add layers and average-cost exit.
"""

# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.period = ctx.param("period", 20)
    ctx.std_mult = ctx.param("std_mult", 2.0)
    ctx.max_layers = ctx.param("max_layers", 4)
    ctx.layer_step_pct = ctx.param("layer_step_pct", 0.012)
    ctx.layer_multiplier = ctx.param("layer_multiplier", 1.25)
    ctx.take_profit_price_pct = ctx.param("take_profit_price_pct", 0.008)
    ctx.hard_stop_price_pct = ctx.param("hard_stop_price_pct", 0.08)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        v = float(ctx.investment_amount or 0.0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    try:
        return float(ctx.equity or 0.0)
    except Exception:
        return 0.0

def _qty(ctx, pct, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(_budget(ctx) * float(pct), 10.0) * lev / price

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)

def _mean(values):
    return sum(values) / len(values) if values else 0.0

def _std(values):
    m = _mean(values)
    return (sum([(v - m) * (v - m) for v in values]) / len(values)) ** 0.5 if values else 0.0

def _key(side, name):
    return "boll_" + side + "_" + name

def on_bar(ctx, bar):
    side = _side(ctx)
    bars = ctx.bars(int(ctx.period) + 2)
    if len(bars) < int(ctx.period) + 2:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars[-int(ctx.period)-1:-1]]
    mid = _mean(closes)
    dev = _std(closes)
    upper = mid + dev * float(ctx.std_mult)
    lower = mid - dev * float(ctx.std_mult)
    if _has_pos(ctx, side):
        entry = _entry(ctx, side, price)
        if _pnl(side, entry, price) >= float(ctx.take_profit_price_pct) or _pnl(side, entry, price) <= -float(ctx.hard_stop_price_pct):
            _close(ctx, side, "bollinger_exit")
            ctx.state.set(_key(side, "layer"), 0)
            return
        layer = int(ctx.state.get(_key(side, "layer"), 1) or 1)
        anchor = float(ctx.state.get(_key(side, "anchor"), price) or price)
        trigger = anchor * (1.0 - float(ctx.layer_step_pct) * layer) if side == "long" else anchor * (1.0 + float(ctx.layer_step_pct) * layer)
        add_hit = price <= trigger if side == "long" else price >= trigger
        if layer < int(ctx.max_layers) and add_hit:
            pct = (1.0 / max(1, int(ctx.max_layers))) * (float(ctx.layer_multiplier) ** max(0, layer))
            _add(ctx, side, _qty(ctx, pct, price), price, "bollinger_add")
            ctx.state.set(_key(side, "layer"), layer + 1)
        return
    entry_signal = price <= lower if side == "long" else price >= upper
    if entry_signal:
        _open(ctx, side, _qty(ctx, 1.0 / max(1, int(ctx.max_layers)), price), price, "bollinger_entry")
        ctx.state.set(_key(side, "layer"), 1)
        ctx.state.set(_key(side, "anchor"), price)
$qdtpl3$,
 '{"params":[{"name":"period","type":"integer","default":20,"min":5,"max":240,"step":1},{"name":"std_mult","type":"number","default":2,"min":0.5,"max":5,"step":0.1},{"name":"max_layers","type":"integer","default":4,"min":1,"max":10,"step":1},{"name":"layer_step_pct","type":"percent","default":0.012,"min":0.001,"max":0.3,"step":0.001},{"name":"layer_multiplier","type":"number","default":1.25,"min":1,"max":5,"step":0.05},{"name":"take_profit_price_pct","type":"percent","default":0.008,"min":0.0005,"max":0.2,"step":0.0005},{"name":"hard_stop_price_pct","type":"percent","default":0.08,"min":0.005,"max":0.8,"step":0.005}]}'::jsonb, '["reversion", "bollinger"]'::jsonb, 'stock', 'teal',
 30, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('range_grid_basket', 'Range Grid Basket', 'Bar-close range grid simulation using recent high/low as adaptive boundaries. It does not pre-place exchange resting limit orders; use the Grid Bot engine for live long/short/neutral grids.', $qdtpl4$"""
Range Grid Basket
Bar-close range grid simulation using recent high/low as adaptive boundaries.

This script is a lightweight strategy-code example. It reacts on completed bars
and sends open/add/close intents. It is NOT the exchange-style Grid Bot that
pre-places resting limit orders on every grid line. For live long/short/neutral
grid trading with pre-hung orders, use the Grid Bot template strategy.
"""

# timeframe: 15m
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.lookback = ctx.param("lookback", 120)
    ctx.grid_levels = ctx.param("grid_levels", 8)
    ctx.order_pct = ctx.param("order_pct", 0.08)
    ctx.take_profit_price_pct = ctx.param("take_profit_price_pct", 0.006)
    ctx.range_buffer_pct = ctx.param("range_buffer_pct", 0.01)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        v = float(ctx.investment_amount or 0.0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    try:
        return float(ctx.equity or 0.0)
    except Exception:
        return 0.0

def _qty(ctx, pct, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(_budget(ctx) * float(pct), 10.0) * lev / price

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)

def on_bar(ctx, bar):
    side = _side(ctx)
    bars = ctx.bars(int(ctx.lookback) + 2)
    if len(bars) < int(ctx.lookback) + 2:
        return
    price = float(bar["close"])
    top = max([float(b["high"]) for b in bars[-int(ctx.lookback)-1:-1]])
    bottom = min([float(b["low"]) for b in bars[-int(ctx.lookback)-1:-1]])
    width = top - bottom
    if width <= 0:
        return
    if _has_pos(ctx, side):
        entry = _entry(ctx, side, price)
        out_range = price < bottom * (1.0 - float(ctx.range_buffer_pct)) or price > top * (1.0 + float(ctx.range_buffer_pct))
        if _pnl(side, entry, price) >= float(ctx.take_profit_price_pct) or out_range:
            _close(ctx, side, "grid_exit")
        return
    level = int((price - bottom) / (width / max(2, int(ctx.grid_levels))))
    low_zone = level <= int(ctx.grid_levels) // 3
    high_zone = level >= int(ctx.grid_levels) * 2 // 3
    if (side == "long" and low_zone) or (side == "short" and high_zone):
        _open(ctx, side, _qty(ctx, ctx.order_pct, price), price, "grid_entry")
$qdtpl4$,
 '{"params":[{"name":"lookback","type":"integer","default":120,"min":20,"max":500,"step":1},{"name":"grid_levels","type":"integer","default":8,"min":3,"max":40,"step":1},{"name":"order_pct","type":"percent","default":0.08,"min":0.01,"max":0.5,"step":0.01},{"name":"take_profit_price_pct","type":"percent","default":0.006,"min":0.0005,"max":0.1,"step":0.0005},{"name":"range_buffer_pct","type":"percent","default":0.01,"min":0,"max":0.2,"step":0.001}]}'::jsonb, '["grid", "range"]'::jsonb, 'table', 'gold',
 40, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('dca_accumulator', 'DCA Accumulator', 'Periodic DCA accumulator with dip multiplier and portfolio-level exit controls.', $qdtpl5$"""
DCA Accumulator
Periodic DCA accumulator with dip multiplier and portfolio-level exit controls.
"""

# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.interval_bars = ctx.param("interval_bars", 24)
    ctx.order_pct = ctx.param("order_pct", 0.08)
    ctx.dip_pct = ctx.param("dip_pct", 0.05)
    ctx.dip_multiplier = ctx.param("dip_multiplier", 2.0)
    ctx.max_orders = ctx.param("max_orders", 20)
    ctx.take_profit_price_pct = ctx.param("take_profit_price_pct", 0.25)
    ctx.hard_stop_price_pct = ctx.param("hard_stop_price_pct", 0.35)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        v = float(ctx.investment_amount or 0.0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    try:
        return float(ctx.equity or 0.0)
    except Exception:
        return 0.0

def _qty(ctx, pct, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(_budget(ctx) * float(pct), 10.0) * lev / price

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)

def on_bar(ctx, bar):
    side = "long"
    price = float(bar["close"])
    orders = int(ctx.state.get("dca_orders", 0) or 0)
    last_buy = float(ctx.state.get("dca_last_buy", 0.0) or 0.0)
    if _has_pos(ctx, side):
        entry = _entry(ctx, side, price)
        if _pnl(side, entry, price) >= float(ctx.take_profit_price_pct) or _pnl(side, entry, price) <= -float(ctx.hard_stop_price_pct):
            _close(ctx, side, "dca_exit")
            ctx.state.set("dca_orders", 0)
            ctx.state.set("dca_last_buy", 0.0)
            return
    if orders >= int(ctx.max_orders):
        return
    periodic = int(ctx.interval_bars) > 0 and _bar_no(ctx) % int(ctx.interval_bars) == 0
    dip = last_buy > 0 and price <= last_buy * (1.0 - float(ctx.dip_pct))
    if periodic or dip:
        pct = float(ctx.order_pct) * (float(ctx.dip_multiplier) if dip else 1.0)
        if _has_pos(ctx, side):
            _add(ctx, side, _qty(ctx, pct, price), price, "dca_add")
        else:
            _open(ctx, side, _qty(ctx, pct, price), price, "dca_open")
        ctx.state.set("dca_orders", orders + 1)
        ctx.state.set("dca_last_buy", price)
$qdtpl5$,
 '{"params":[{"name":"interval_bars","type":"integer","default":24,"min":1,"max":2000,"step":1},{"name":"order_pct","type":"percent","default":0.08,"min":0.01,"max":0.5,"step":0.01},{"name":"dip_pct","type":"percent","default":0.05,"min":0.001,"max":0.5,"step":0.001},{"name":"dip_multiplier","type":"number","default":2,"min":1,"max":10,"step":0.1},{"name":"max_orders","type":"integer","default":20,"min":1,"max":200,"step":1},{"name":"take_profit_price_pct","type":"percent","default":0.25,"min":0.01,"max":3,"step":0.01},{"name":"hard_stop_price_pct","type":"percent","default":0.35,"min":0.01,"max":0.9,"step":0.01}]}'::jsonb, '["dca"]'::jsonb, 'dollar', 'blue',
 50, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('sequential_martingale', 'Sequential Martingale', 'Budget-capped sequential martingale with explicit total budget, first-order sizing, adverse-price adds, average-cost take-profit, and hard stop.', $qdtpl6$"""
Sequential Martingale
Budget-capped sequential martingale with explicit total budget, first-order
sizing, adverse-price adds, average-cost take-profit, and hard stop.

Sizing rules:
- total_budget_usdt > 0 overrides the panel investment amount.
- otherwise total_budget_pct controls how much of the panel investment amount
  this martingale sequence may consume.
- initial_order_usdt > 0 overrides first_order_pct.
- otherwise first_order_pct controls the first order as a share of total budget.
- add orders follow first_order * multiplier^n but are clipped by remaining
  sequence budget, so the whole sequence cannot exceed total budget.
"""

# timeframe: 5m
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.max_orders = ctx.param("max_orders", 8)
    ctx.total_budget_usdt = ctx.param("total_budget_usdt", 0.0)
    ctx.total_budget_pct = ctx.param("total_budget_pct", 1.0)
    ctx.initial_order_usdt = ctx.param("initial_order_usdt", 0.0)
    ctx.first_order_pct = ctx.param("first_order_pct", 0.05)
    ctx.multiplier = ctx.param("multiplier", 1.7)
    ctx.spacing_pct = ctx.param("spacing_pct", 0.008)
    ctx.take_profit_price_pct = ctx.param("take_profit_price_pct", 0.006)
    ctx.hard_stop_price_pct = ctx.param("hard_stop_price_pct", 0.22)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        explicit = float(ctx.total_budget_usdt or 0.0)
    except Exception:
        explicit = 0.0
    if explicit > 0:
        return explicit
    try:
        base = float(ctx.investment_amount or 0.0)
    except Exception:
        base = 0.0
    if base <= 0:
        try:
            base = float(ctx.equity or 0.0)
        except Exception:
            base = 0.0
    try:
        pct = max(0.0, min(1.0, float(ctx.total_budget_pct)))
    except Exception:
        pct = 1.0
    return max(base * pct, 0.0)

def _first_quote(ctx):
    budget = _budget(ctx)
    if budget <= 0:
        return 0.0
    try:
        explicit = float(ctx.initial_order_usdt or 0.0)
    except Exception:
        explicit = 0.0
    if explicit > 0:
        return min(explicit, budget)
    try:
        pct = max(0.0, min(1.0, float(ctx.first_order_pct)))
    except Exception:
        pct = 0.05
    return min(max(budget * pct, 10.0), budget)

def _planned_quote(ctx, order_index):
    first = _first_quote(ctx)
    if first <= 0:
        return 0.0
    try:
        mult = max(1.0, float(ctx.multiplier))
    except Exception:
        mult = 1.0
    return first * (mult ** max(0, int(order_index)))

def _quote_to_qty(ctx, quote, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(float(quote or 0.0), 0.0) * lev / price

def _budget_left(ctx, spent):
    return max(_budget(ctx) - max(0.0, float(spent or 0.0)), 0.0)

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)

def _next(side, price, pct):
    return price * (1.0 - pct) if side == "long" else price * (1.0 + pct)

def _hit(side, price, trigger):
    return price <= trigger if side == "long" else price >= trigger

def on_bar(ctx, bar):
    side = _side(ctx)
    price = float(bar["close"])
    count_key = "mart_count_" + side
    next_key = "mart_next_" + side
    spent_key = "mart_spent_" + side
    count = int(ctx.state.get(count_key, 0) or 0)
    spent = float(ctx.state.get(spent_key, 0.0) or 0.0)
    if _has_pos(ctx, side):
        entry = _entry(ctx, side, price)
        if _pnl(side, entry, price) >= float(ctx.take_profit_price_pct) or _pnl(side, entry, price) <= -float(ctx.hard_stop_price_pct):
            _close(ctx, side, "martingale_exit")
            ctx.state.set(count_key, 0)
            ctx.state.set(spent_key, 0.0)
            return
        trigger = float(ctx.state.get(next_key, 0.0) or 0.0)
        if count < int(ctx.max_orders) and trigger > 0 and _hit(side, price, trigger):
            quote = min(_planned_quote(ctx, count), _budget_left(ctx, spent))
            if quote >= 10.0:
                _add(ctx, side, _quote_to_qty(ctx, quote, price), price, "martingale_add")
                ctx.state.set(count_key, count + 1)
                ctx.state.set(spent_key, spent + quote)
                ctx.state.set(next_key, _next(side, price, float(ctx.spacing_pct)))
        return
    quote = _first_quote(ctx)
    if quote < 10.0:
        return
    _open(ctx, side, _quote_to_qty(ctx, quote, price), price, "martingale_open")
    ctx.state.set(count_key, 1)
    ctx.state.set(spent_key, quote)
    ctx.state.set(next_key, _next(side, price, float(ctx.spacing_pct)))
$qdtpl6$,
 '{"params":[{"name":"max_orders","type":"integer","default":8,"min":1,"max":30,"step":1},{"name":"total_budget_usdt","type":"number","default":0,"min":0,"max":100000000,"step":10},{"name":"total_budget_pct","type":"percent","default":1,"min":0.01,"max":1,"step":0.01},{"name":"initial_order_usdt","type":"number","default":0,"min":0,"max":100000000,"step":10},{"name":"first_order_pct","type":"percent","default":0.05,"min":0.001,"max":1,"step":0.001},{"name":"multiplier","type":"number","default":1.7,"min":1,"max":5,"step":0.05},{"name":"spacing_pct","type":"percent","default":0.008,"min":0.0005,"max":0.5,"step":0.0005},{"name":"take_profit_price_pct","type":"percent","default":0.006,"min":0.0005,"max":0.5,"step":0.0005},{"name":"hard_stop_price_pct","type":"percent","default":0.22,"min":0.01,"max":0.9,"step":0.01}]}'::jsonb, '["martingale"]'::jsonb, 'branches', 'red',
 60, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('layered_martingale_basket', 'Layered Martingale Basket', 'Split-position martingale with several child entries inside each layer.', $qdtpl7$"""
Layered Martingale Basket
Split-position martingale with several child entries inside each layer.
"""

# timeframe: 5m
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.max_layers = ctx.param("max_layers", 4)
    ctx.splits_per_layer = ctx.param("splits_per_layer", 4)
    ctx.layer_multiplier = ctx.param("layer_multiplier", 1.6)
    ctx.split_spacing_pct = ctx.param("split_spacing_pct", 0.004)
    ctx.layer_spacing_pct = ctx.param("layer_spacing_pct", 0.018)
    ctx.take_profit_price_pct = ctx.param("take_profit_price_pct", 0.007)
    ctx.hard_stop_price_pct = ctx.param("hard_stop_price_pct", 0.24)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        v = float(ctx.investment_amount or 0.0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    try:
        return float(ctx.equity or 0.0)
    except Exception:
        return 0.0

def _qty(ctx, pct, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(_budget(ctx) * float(pct), 10.0) * lev / price

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)

def _key(side, name):
    return "layer_mart_" + side + "_" + name

def _trigger(side, price, pct):
    return price * (1.0 - pct) if side == "long" else price * (1.0 + pct)

def _hit(side, price, trigger):
    return price <= trigger if side == "long" else price >= trigger

def on_bar(ctx, bar):
    side = _side(ctx)
    price = float(bar["close"])
    layer = int(ctx.state.get(_key(side, "layer"), 0) or 0)
    split = int(ctx.state.get(_key(side, "split"), 0) or 0)
    if _has_pos(ctx, side):
        entry = _entry(ctx, side, price)
        if _pnl(side, entry, price) >= float(ctx.take_profit_price_pct) or _pnl(side, entry, price) <= -float(ctx.hard_stop_price_pct):
            _close(ctx, side, "layered_martingale_exit")
            ctx.state.set(_key(side, "layer"), 0)
            return
        trigger = float(ctx.state.get(_key(side, "next"), 0.0) or 0.0)
        if trigger <= 0 or not _hit(side, price, trigger):
            return
        next_split = split + 1
        next_layer = layer
        if next_split > int(ctx.splits_per_layer):
            next_split = 1
            next_layer = layer + 1
        if next_layer > int(ctx.max_layers):
            return
        pct = (1.0 / max(1, int(ctx.max_layers) * int(ctx.splits_per_layer))) * (float(ctx.layer_multiplier) ** max(0, next_layer - 1))
        _add(ctx, side, _qty(ctx, pct, price), price, "layered_martingale_add")
        spacing = float(ctx.split_spacing_pct) if next_split < int(ctx.splits_per_layer) else float(ctx.layer_spacing_pct)
        ctx.state.set(_key(side, "layer"), next_layer)
        ctx.state.set(_key(side, "split"), next_split)
        ctx.state.set(_key(side, "next"), _trigger(side, price, spacing))
        return
    pct = 1.0 / max(1, int(ctx.max_layers) * int(ctx.splits_per_layer))
    _open(ctx, side, _qty(ctx, pct, price), price, "layered_martingale_open")
    ctx.state.set(_key(side, "layer"), 1)
    ctx.state.set(_key(side, "split"), 1)
    ctx.state.set(_key(side, "next"), _trigger(side, price, float(ctx.split_spacing_pct)))
$qdtpl7$,
 '{"params":[{"name":"max_layers","type":"integer","default":4,"min":1,"max":10,"step":1},{"name":"splits_per_layer","type":"integer","default":4,"min":1,"max":10,"step":1},{"name":"layer_multiplier","type":"number","default":1.6,"min":1,"max":5,"step":0.05},{"name":"split_spacing_pct","type":"percent","default":0.004,"min":0.0005,"max":0.2,"step":0.0005},{"name":"layer_spacing_pct","type":"percent","default":0.018,"min":0.0005,"max":0.5,"step":0.0005},{"name":"take_profit_price_pct","type":"percent","default":0.007,"min":0.0005,"max":0.5,"step":0.0005},{"name":"hard_stop_price_pct","type":"percent","default":0.24,"min":0.01,"max":0.9,"step":0.01}]}'::jsonb, '["martingale", "split"]'::jsonb, 'branches', 'purple',
 70, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();


INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('keltner_retest_breakout', 'Keltner Retest Breakout', 'Keltner channel breakout that waits for retest confirmation and exits with ATR trail.', $qdtpl8$"""
Keltner Retest Breakout
Keltner channel breakout that waits for retest confirmation and exits with ATR trail.
"""

# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: indicator

def on_init(ctx):
    ctx.ema_period = ctx.param("ema_period", 40)
    ctx.atr_period = ctx.param("atr_period", 14)
    ctx.channel_mult = ctx.param("channel_mult", 2.0)
    ctx.retest_buffer_pct = ctx.param("retest_buffer_pct", 0.004)
    ctx.risk_pct = ctx.param("risk_pct", 0.30)
    ctx.trail_atr = ctx.param("trail_atr", 2.5)

def _side(ctx):
    d = str(ctx.direction or "long").lower()
    return "short" if d == "short" else "long"

def _budget(ctx):
    try:
        v = float(ctx.investment_amount or 0.0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    try:
        return float(ctx.equity or 0.0)
    except Exception:
        return 0.0

def _qty(ctx, pct, price):
    if price <= 0:
        return 0.0
    lev = 1.0
    if str(ctx.market_type or "swap").lower() != "spot":
        try:
            lev = max(1.0, float(ctx.leverage or 1.0))
        except Exception:
            lev = 1.0
    return max(_budget(ctx) * float(pct), 10.0) * lev / price

def _bar_no(ctx):
    try:
        return int(ctx.current_index)
    except Exception:
        return 0

def _has_pos(ctx, side):
    if not ctx.position:
        return False
    if side == "short":
        return float(ctx.position.get("short_size", 0.0) or 0.0) > 0
    return float(ctx.position.get("long_size", ctx.position.get("size", 0.0)) or 0.0) > 0

def _entry(ctx, side, fallback):
    if not ctx.position:
        return fallback
    if side == "short":
        return float(ctx.position.get("short_entry", fallback) or fallback or 0.0)
    return float(ctx.position.get("long_entry", ctx.position.get("entry_price", fallback)) or fallback or 0.0)

def _pnl(side, entry, price):
    if entry <= 0:
        return 0.0
    return (entry - price) / entry if side == "short" else (price - entry) / entry

def _open(ctx, side, qty, price, reason):
    if side == "short":
        ctx.open_short(amount=qty, price=price, reason=reason)
    else:
        ctx.open_long(amount=qty, price=price, reason=reason)

def _add(ctx, side, qty, price, reason):
    if side == "short":
        ctx.add_short(amount=qty, price=price, reason=reason)
    else:
        ctx.add_long(amount=qty, price=price, reason=reason)

def _close(ctx, side, reason):
    if side == "short":
        ctx.close_short(reason=reason)
    else:
        ctx.close_long(reason=reason)


def _ema(values, period):
    if not values:
        return 0.0
    k = 2.0 / (float(period) + 1.0)
    out = float(values[0])
    for v in values[1:]:
        out = float(v) * k + out * (1.0 - k)
    return out


def _atr(bars, period):
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(len(bars) - period, len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.ema_period), int(ctx.atr_period)) + 3
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars]
    ema = _ema(closes[-int(ctx.ema_period):], int(ctx.ema_period))
    atr = _atr(bars, int(ctx.atr_period))
    if atr <= 0:
        return
    upper = ema + atr * float(ctx.channel_mult)
    lower = ema - atr * float(ctx.channel_mult)
    key = "keltner_" + side
    if _has_pos(ctx, side):
        stop = float(ctx.state.get(key + "_stop", 0.0) or 0.0)
        if side == "long":
            stop = max(stop, price - atr * float(ctx.trail_atr)) if stop > 0 else price - atr * float(ctx.trail_atr)
            hit = price <= stop
        else:
            stop = min(stop, price + atr * float(ctx.trail_atr)) if stop > 0 else price + atr * float(ctx.trail_atr)
            hit = price >= stop
        ctx.state.set(key + "_stop", stop)
        if hit:
            _close(ctx, side, "keltner_trail_exit")
        return
    pending = float(ctx.state.get(key + "_pending", 0.0) or 0.0)
    breakout = price > upper if side == "long" else price < lower
    if pending <= 0 and breakout:
        ctx.state.set(key + "_pending", upper if side == "long" else lower)
        return
    retest = pending > 0 and (price <= pending * (1.0 + float(ctx.retest_buffer_pct)) if side == "long" else price >= pending * (1.0 - float(ctx.retest_buffer_pct)))
    if retest:
        _open(ctx, side, _qty(ctx, ctx.risk_pct, price), price, "keltner_retest")
        ctx.state.set(key + "_stop", price - atr * float(ctx.trail_atr) if side == "long" else price + atr * float(ctx.trail_atr))
        ctx.state.set(key + "_pending", 0.0)
$qdtpl8$,
 '{"params":[{"name":"ema_period","type":"integer","default":40,"min":5,"max":300,"step":1},{"name":"atr_period","type":"integer","default":14,"min":3,"max":120,"step":1},{"name":"channel_mult","type":"number","default":2,"min":0.5,"max":8,"step":0.1},{"name":"retest_buffer_pct","type":"percent","default":0.004,"min":0,"max":0.1,"step":0.0005},{"name":"risk_pct","type":"percent","default":0.3,"min":0.01,"max":1,"step":0.01},{"name":"trail_atr","type":"number","default":2.5,"min":0.5,"max":12,"step":0.1}]}'::jsonb, '["keltner", "breakout"]'::jsonb, 'area-chart', 'orange',
 80, TRUE, '{"source": "system_seed", "version": 1}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

-- ===== End script strategy templates seed =====

UPDATE qd_script_templates
SET is_active = FALSE, updated_at = NOW()
WHERE template_key IN (
    'classic_ema_atr_trend',
    'donchian_breakout_pyramid',
    'bollinger_reversion_basket',
    'range_grid_basket',
    'dca_accumulator',
    'sequential_martingale',
    'layered_martingale_basket',
    'keltner_retest_breakout'
);

INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('ema_trend_pullback', 'EMA Trend Pullback', 'EMA trend filter with pullback entry and trend-exit discipline.', $qdtpl9$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.04
# @strategy takeProfitPct 0.08

def on_init(ctx):
    ctx.fast = ctx.param("fast_ema", 20)
    ctx.slow = ctx.param("slow_ema", 80)
    ctx.pullback_pct = ctx.param("pullback_pct", 0.015)
    ctx.target_pct = ctx.param("target_pct", 0.35)

def _ema(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = values[0]
    for value in values[1:]:
        out = value * k + out * (1.0 - k)
    return out

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def on_bar(ctx, bar):
    side = _side(ctx)
    bars = ctx.bars(int(ctx.slow) + 5)
    if len(bars) < int(ctx.slow) + 5:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars]
    fast = _ema(closes[-int(ctx.fast):], int(ctx.fast))
    slow = _ema(closes[-int(ctx.slow):], int(ctx.slow))
    trend = fast > slow if side == "long" else fast < slow
    pullback = price <= fast * (1.0 - float(ctx.pullback_pct)) if side == "long" else price >= fast * (1.0 + float(ctx.pullback_pct))
    if _has_pos(ctx, side):
        if not trend:
            ctx.order_target(0, side=side, reason="ema_trend_exit")
        return
    if trend and pullback:
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="ema_pullback_entry")
$qdtpl9$, '{"params":[{"name":"fast_ema","type":"integer","default":20,"min":2,"max":200,"step":1},{"name":"slow_ema","type":"integer","default":80,"min":5,"max":400,"step":1},{"name":"pullback_pct","type":"percent","default":0.015,"min":0.001,"max":0.2,"step":0.001},{"name":"target_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["trend","ema","pullback"]'::jsonb, 'line-chart', 'green', 10, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW()),

('donchian_breakout', 'Donchian Breakout', 'Donchian channel breakout with opposite-channel exit.', $qdtpl10$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.06

def on_init(ctx):
    ctx.entry_lookback = ctx.param("entry_lookback", 55)
    ctx.exit_lookback = ctx.param("exit_lookback", 20)
    ctx.target_pct = ctx.param("target_pct", 0.4)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.entry_lookback), int(ctx.exit_lookback)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    entry_window = bars[-int(ctx.entry_lookback)-1:-1]
    exit_window = bars[-int(ctx.exit_lookback)-1:-1]
    high = max([float(b["high"]) for b in entry_window])
    low = min([float(b["low"]) for b in entry_window])
    exit_high = max([float(b["high"]) for b in exit_window])
    exit_low = min([float(b["low"]) for b in exit_window])
    if _has_pos(ctx, side):
        if (side == "long" and price < exit_low) or (side == "short" and price > exit_high):
            ctx.order_target(0, side=side, reason="donchian_exit")
        return
    if (side == "long" and price > high) or (side == "short" and price < low):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="donchian_breakout")
$qdtpl10$, '{"params":[{"name":"entry_lookback","type":"integer","default":55,"min":10,"max":300,"step":1},{"name":"exit_lookback","type":"integer","default":20,"min":5,"max":200,"step":1},{"name":"target_pct","type":"percent","default":0.4,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["breakout","channel"]'::jsonb, 'rise', 'cyan', 20, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW()),

('atr_channel_breakout', 'ATR Channel Breakout', 'ATR envelope breakout around a moving average with channel re-entry exit.', $qdtpl11$# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.05

def on_init(ctx):
    ctx.ma_period = ctx.param("ma_period", 40)
    ctx.atr_period = ctx.param("atr_period", 14)
    ctx.atr_mult = ctx.param("atr_mult", 2.0)
    ctx.target_pct = ctx.param("target_pct", 0.35)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, max(h - pc, pc - h), max(pc - l, l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.ma_period), int(ctx.atr_period)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars[-int(ctx.ma_period):]]
    mid = sum(closes) / len(closes)
    atr = _atr(bars, int(ctx.atr_period))
    upper = mid + atr * float(ctx.atr_mult)
    lower = mid - atr * float(ctx.atr_mult)
    if _has_pos(ctx, side):
        if (side == "long" and price < mid) or (side == "short" and price > mid):
            ctx.order_target(0, side=side, reason="atr_channel_exit")
        return
    if (side == "long" and price > upper) or (side == "short" and price < lower):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="atr_channel_breakout")
$qdtpl11$, '{"params":[{"name":"ma_period","type":"integer","default":40,"min":5,"max":300,"step":1},{"name":"atr_period","type":"integer","default":14,"min":3,"max":120,"step":1},{"name":"atr_mult","type":"number","default":2,"min":0.5,"max":8,"step":0.1},{"name":"target_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["atr","breakout"]'::jsonb, 'area-chart', 'orange', 30, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW()),

('rsi_mean_reversion', 'RSI Mean Reversion', 'RSI exhaustion entry with midline recovery exit.', $qdtpl12$# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.05

def on_init(ctx):
    ctx.period = ctx.param("period", 14)
    ctx.oversold = ctx.param("oversold", 30)
    ctx.overbought = ctx.param("overbought", 70)
    ctx.exit_level = ctx.param("exit_level", 50)
    ctx.target_pct = ctx.param("target_pct", 0.25)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _rsi(values, period):
    gains = []
    losses = []
    for i in range(len(values) - int(period), len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)

def on_bar(ctx, bar):
    side = _side(ctx)
    bars = ctx.bars(int(ctx.period) + 2)
    if len(bars) < int(ctx.period) + 2:
        return
    closes = [float(b["close"]) for b in bars]
    rsi = _rsi(closes, int(ctx.period))
    if _has_pos(ctx, side):
        if (side == "long" and rsi >= float(ctx.exit_level)) or (side == "short" and rsi <= float(ctx.exit_level)):
            ctx.order_target(0, side=side, reason="rsi_reversion_exit")
        return
    if (side == "long" and rsi <= float(ctx.oversold)) or (side == "short" and rsi >= float(ctx.overbought)):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="rsi_reversion_entry")
$qdtpl12$, '{"params":[{"name":"period","type":"integer","default":14,"min":3,"max":80,"step":1},{"name":"oversold","type":"number","default":30,"min":5,"max":50,"step":1},{"name":"overbought","type":"number","default":70,"min":50,"max":95,"step":1},{"name":"exit_level","type":"number","default":50,"min":20,"max":80,"step":1},{"name":"target_pct","type":"percent","default":0.25,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["rsi","reversion"]'::jsonb, 'refresh', 'blue', 40, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW()),

('macd_momentum', 'MACD Momentum', 'MACD line and signal-line momentum strategy.', $qdtpl13$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.04

def on_init(ctx):
    ctx.fast = ctx.param("fast", 12)
    ctx.slow = ctx.param("slow", 26)
    ctx.signal = ctx.param("signal", 9)
    ctx.target_pct = ctx.param("target_pct", 0.35)

def _ema_series(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = []
    ema = values[0]
    for value in values:
        ema = value * k + ema * (1.0 - k)
        out.append(ema)
    return out

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = int(ctx.slow) + int(ctx.signal) + 10
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    closes = [float(b["close"]) for b in bars]
    fast = _ema_series(closes, int(ctx.fast))
    slow = _ema_series(closes, int(ctx.slow))
    macd = [fast[i] - slow[i] for i in range(len(closes))]
    signal = _ema_series(macd, int(ctx.signal))
    bullish = macd[-1] > signal[-1]
    if _has_pos(ctx, side):
        if (side == "long" and not bullish) or (side == "short" and bullish):
            ctx.order_target(0, side=side, reason="macd_momentum_exit")
        return
    if (side == "long" and bullish) or (side == "short" and not bullish):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="macd_momentum_entry")
$qdtpl13$, '{"params":[{"name":"fast","type":"integer","default":12,"min":2,"max":80,"step":1},{"name":"slow","type":"integer","default":26,"min":5,"max":160,"step":1},{"name":"signal","type":"integer","default":9,"min":2,"max":80,"step":1},{"name":"target_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["macd","momentum"]'::jsonb, 'exchange', 'purple', 50, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW()),

('bollinger_reversion', 'Bollinger Reversion', 'Bollinger band mean reversion with middle-band exit.', $qdtpl14$# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.06

def on_init(ctx):
    ctx.period = ctx.param("period", 20)
    ctx.std_mult = ctx.param("std_mult", 2.0)
    ctx.target_pct = ctx.param("target_pct", 0.25)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _mean(values):
    return sum(values) / len(values) if values else 0.0

def _std(values):
    mean = _mean(values)
    return (sum([(v - mean) * (v - mean) for v in values]) / len(values)) ** 0.5 if values else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    bars = ctx.bars(int(ctx.period) + 1)
    if len(bars) < int(ctx.period) + 1:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars[-int(ctx.period)-1:-1]]
    mid = _mean(closes)
    dev = _std(closes)
    upper = mid + dev * float(ctx.std_mult)
    lower = mid - dev * float(ctx.std_mult)
    if _has_pos(ctx, side):
        if (side == "long" and price >= mid) or (side == "short" and price <= mid):
            ctx.order_target(0, side=side, reason="bollinger_mid_exit")
        return
    if (side == "long" and price <= lower) or (side == "short" and price >= upper):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="bollinger_reversion_entry")
$qdtpl14$, '{"params":[{"name":"period","type":"integer","default":20,"min":5,"max":240,"step":1},{"name":"std_mult","type":"number","default":2,"min":0.5,"max":5,"step":0.1},{"name":"target_pct","type":"percent","default":0.25,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["bollinger","reversion"]'::jsonb, 'stock', 'teal', 60, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW()),

('turtle_breakout_lite', 'Turtle Breakout Lite', 'Compact Turtle-style breakout using entry/exit channels and ATR risk guard.', $qdtpl15$# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.08

def on_init(ctx):
    ctx.entry_lookback = ctx.param("entry_lookback", 20)
    ctx.exit_lookback = ctx.param("exit_lookback", 10)
    ctx.atr_period = ctx.param("atr_period", 20)
    ctx.atr_stop = ctx.param("atr_stop", 2.0)
    ctx.target_pct = ctx.param("target_pct", 0.35)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _entry(ctx, side, fallback):
    return float(ctx.positions[side]["entry_price"] or fallback)

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, max(h - pc, pc - h), max(pc - l, l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.entry_lookback), int(ctx.exit_lookback), int(ctx.atr_period)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    atr = _atr(bars, int(ctx.atr_period))
    entry_window = bars[-int(ctx.entry_lookback)-1:-1]
    exit_window = bars[-int(ctx.exit_lookback)-1:-1]
    high = max([float(b["high"]) for b in entry_window])
    low = min([float(b["low"]) for b in entry_window])
    exit_high = max([float(b["high"]) for b in exit_window])
    exit_low = min([float(b["low"]) for b in exit_window])
    if _has_pos(ctx, side):
        entry = _entry(ctx, side, price)
        stop = price <= entry - atr * float(ctx.atr_stop) if side == "long" else price >= entry + atr * float(ctx.atr_stop)
        channel_exit = price < exit_low if side == "long" else price > exit_high
        if stop or channel_exit:
            ctx.order_target(0, side=side, reason="turtle_exit")
        return
    if (side == "long" and price > high) or (side == "short" and price < low):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="turtle_breakout")
$qdtpl15$, '{"params":[{"name":"entry_lookback","type":"integer","default":20,"min":5,"max":120,"step":1},{"name":"exit_lookback","type":"integer","default":10,"min":3,"max":80,"step":1},{"name":"atr_period","type":"integer","default":20,"min":3,"max":120,"step":1},{"name":"atr_stop","type":"number","default":2,"min":0.5,"max":8,"step":0.1},{"name":"target_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["turtle","breakout"]'::jsonb, 'flag', 'red', 70, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW()),

('volatility_stop_trend', 'Volatility Stop Trend', 'Trend-following entry with ATR volatility stop that ratchets with price.', $qdtpl16$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: strategy
# @strategy stopLossPct 0.05

def on_init(ctx):
    ctx.ema_period = ctx.param("ema_period", 50)
    ctx.atr_period = ctx.param("atr_period", 14)
    ctx.stop_atr = ctx.param("stop_atr", 2.5)
    ctx.target_pct = ctx.param("target_pct", 0.35)

def _ema(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = values[0]
    for value in values[1:]:
        out = value * k + out * (1.0 - k)
    return out

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, max(h - pc, pc - h), max(pc - l, l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.ema_period), int(ctx.atr_period)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars]
    ema = _ema(closes[-int(ctx.ema_period):], int(ctx.ema_period))
    atr = _atr(bars, int(ctx.atr_period))
    key = "vol_stop_" + side
    trend = price > ema if side == "long" else price < ema
    if _has_pos(ctx, side):
        old_stop = float(ctx.state.get(key, 0.0) or 0.0)
        new_stop = price - atr * float(ctx.stop_atr) if side == "long" else price + atr * float(ctx.stop_atr)
        stop = max(old_stop, new_stop) if side == "long" and old_stop > 0 else new_stop
        stop = min(old_stop, new_stop) if side == "short" and old_stop > 0 else stop
        ctx.state.set(key, stop)
        if (side == "long" and price <= stop) or (side == "short" and price >= stop):
            ctx.order_target(0, side=side, reason="volatility_stop_exit")
        return
    if trend:
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="volatility_trend_entry")
        ctx.state.set(key, price - atr * float(ctx.stop_atr) if side == "long" else price + atr * float(ctx.stop_atr))
$qdtpl16$, '{"params":[{"name":"ema_period","type":"integer","default":50,"min":5,"max":300,"step":1},{"name":"atr_period","type":"integer","default":14,"min":3,"max":120,"step":1},{"name":"stop_atr","type":"number","default":2.5,"min":0.5,"max":12,"step":0.1},{"name":"target_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["trend","volatility","atr"]'::jsonb, 'shield-o', 'green', 80, TRUE, '{"source":"system_seed","version":2}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

-- ===== Script strategy templates v3 seed =====
UPDATE qd_script_templates
SET is_active = FALSE, updated_at = NOW()
WHERE template_key IN (
    'classic_ema_atr_trend',
    'donchian_breakout_pyramid',
    'bollinger_reversion_basket',
    'range_grid_basket',
    'dca_accumulator',
    'sequential_martingale',
    'layered_martingale_basket',
    'keltner_retest_breakout'
);

INSERT INTO qd_script_templates
(template_key, title, description, code, param_schema, tags, icon, accent, sort_order, is_active, metadata, updated_at)
VALUES
('ema_trend_pullback', 'EMA Trend Pullback', 'EMA swing trend filter with pullback recovery entry, EMA failure exit, and engine trailing risk.', $qdtplv3_1$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: engine
# @strategy stopLossPct 0.025
# @strategy takeProfitPct 0.045
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.012
# @strategy trailingActivationPct 0.018
# @strategy maxHoldingBars 36

def on_init(ctx):
    ctx.fast_ema = ctx.param("fast_ema", 8)
    ctx.slow_ema = ctx.param("slow_ema", 21)
    ctx.atr_period = ctx.param("atr_period", 10)
    ctx.pullback_pct = ctx.param("pullback_pct", 0.002)
    ctx.min_atr_pct = ctx.param("min_atr_pct", 0.0)
    ctx.exit_buffer_pct = ctx.param("exit_buffer_pct", 0.002)
    ctx.cooldown_bars = ctx.param("cooldown_bars", 1)
    ctx.target_pct = ctx.param("target_pct", 0.35)

def _requested_sides(ctx):
    direction = str(ctx.direction).lower()
    if direction == "both":
        return ("long", "short")
    return ("short",) if direction == "short" else ("long",)

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _bar_no(ctx):
    return int(ctx.current_index)

def _ema(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = values[0]
    for value in values[1:]:
        out = value * k + out * (1.0 - k)
    return out

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def _signals(ctx, side, price, fast, slow, prev_close, prev_fast, liquid):
    trend = fast > slow if side == "long" else fast < slow
    if side == "long":
        recovered = prev_close <= prev_fast * (1.0 - float(ctx.pullback_pct)) and price > fast
        rejoined = prev_close <= slow and price > fast and price > prev_close
        failed = price < fast * (1.0 - float(ctx.exit_buffer_pct)) or fast < slow
    else:
        recovered = prev_close >= prev_fast * (1.0 + float(ctx.pullback_pct)) and price < fast
        rejoined = prev_close >= slow and price < fast and price < prev_close
        failed = price > fast * (1.0 + float(ctx.exit_buffer_pct)) or fast > slow
    return trend and liquid and (recovered or rejoined), failed

def on_bar(ctx, bar):
    need = max(int(ctx.slow_ema), int(ctx.atr_period)) + 5
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    closes = [float(b["close"]) for b in bars]
    price = float(bar["close"])
    fast = _ema(closes[-int(ctx.fast_ema):], int(ctx.fast_ema))
    slow = _ema(closes[-int(ctx.slow_ema):], int(ctx.slow_ema))
    prev_fast = _ema(closes[-int(ctx.fast_ema)-1:-1], int(ctx.fast_ema))
    prev_close = closes[-2]
    atr = _atr(bars, int(ctx.atr_period))
    liquid = atr / price >= float(ctx.min_atr_pct) if price > 0 else False
    sides = _requested_sides(ctx)
    signals = {}
    closing = set()
    for side in sides:
        entry, failed = _signals(ctx, side, price, fast, slow, prev_close, prev_fast, liquid)
        signals[side] = entry
        if _has_pos(ctx, side) and failed:
            closing.add(side)
            ctx.state.set(side + "_cooldown_until", _bar_no(ctx) + int(ctx.cooldown_bars))
            ctx.order_target(0, side=side, reason="ema_pullback_exit")
    for side in sides:
        if _has_pos(ctx, side):
            continue
        opposite = "short" if side == "long" else "long"
        if _has_pos(ctx, opposite) and opposite not in closing:
            continue
        cooldown_until = int(ctx.state.get(side + "_cooldown_until", -1) or -1)
        if _bar_no(ctx) < cooldown_until:
            continue
        if signals.get(side):
            ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="ema_pullback_recovery")
$qdtplv3_1$, '{"params":[{"name":"fast_ema","type":"integer","default":8,"min":2,"max":200,"step":1},{"name":"slow_ema","type":"integer","default":21,"min":5,"max":400,"step":1},{"name":"atr_period","type":"integer","default":10,"min":3,"max":120,"step":1},{"name":"pullback_pct","type":"percent","default":0.002,"min":0,"max":0.2,"step":0.001},{"name":"min_atr_pct","type":"percent","default":0,"min":0,"max":0.1,"step":0.001},{"name":"exit_buffer_pct","type":"percent","default":0.002,"min":0,"max":0.1,"step":0.001},{"name":"cooldown_bars","type":"integer","default":1,"min":0,"max":100,"step":1},{"name":"target_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["trend","ema","pullback","trailing"]'::jsonb, 'line-chart', 'green', 10, TRUE, '{"source":"system_seed","version":4}'::jsonb, NOW()),

('donchian_breakout', 'Donchian Breakout', 'Classic channel breakout with ATR volatility gate, channel exit, and max-hold safety.', $qdtplv3_2$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: engine
# @strategy stopLossPct 0.055
# @strategy takeProfitPct 0.12
# @strategy maxHoldingBars 120

def on_init(ctx):
    ctx.entry_lookback = ctx.param("entry_lookback", 55)
    ctx.exit_lookback = ctx.param("exit_lookback", 20)
    ctx.atr_period = ctx.param("atr_period", 20)
    ctx.min_range_atr = ctx.param("min_range_atr", 2.0)
    ctx.target_pct = ctx.param("target_pct", 0.4)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.entry_lookback), int(ctx.exit_lookback), int(ctx.atr_period)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    entry_window = bars[-int(ctx.entry_lookback)-1:-1]
    exit_window = bars[-int(ctx.exit_lookback)-1:-1]
    high = max(float(b["high"]) for b in entry_window)
    low = min(float(b["low"]) for b in entry_window)
    exit_high = max(float(b["high"]) for b in exit_window)
    exit_low = min(float(b["low"]) for b in exit_window)
    atr = _atr(bars, int(ctx.atr_period))
    wide_enough = (high - low) >= atr * float(ctx.min_range_atr)
    if _has_pos(ctx, side):
        if (side == "long" and price < exit_low) or (side == "short" and price > exit_high):
            ctx.order_target(0, side=side, reason="donchian_channel_exit")
        return
    if wide_enough and ((side == "long" and price > high) or (side == "short" and price < low)):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="donchian_breakout")
$qdtplv3_2$, '{"params":[{"name":"entry_lookback","type":"integer","default":55,"min":10,"max":300,"step":1},{"name":"exit_lookback","type":"integer","default":20,"min":5,"max":200,"step":1},{"name":"atr_period","type":"integer","default":20,"min":3,"max":120,"step":1},{"name":"min_range_atr","type":"number","default":2,"min":0,"max":10,"step":0.1},{"name":"target_pct","type":"percent","default":0.4,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["breakout","channel","trend"]'::jsonb, 'rise', 'cyan', 20, TRUE, '{"source":"system_seed","version":3}'::jsonb, NOW()),

('atr_channel_breakout', 'ATR Channel Breakout', 'ATR envelope breakout around an EMA baseline with trend-strength and midline exits.', $qdtplv3_3$# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: engine
# @strategy stopLossPct 0.045
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.02
# @strategy trailingActivationPct 0.04

def on_init(ctx):
    ctx.ema_period = ctx.param("ema_period", 48)
    ctx.atr_period = ctx.param("atr_period", 14)
    ctx.atr_mult = ctx.param("atr_mult", 2.2)
    ctx.slope_lookback = ctx.param("slope_lookback", 6)
    ctx.target_pct = ctx.param("target_pct", 0.32)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _ema(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = values[0]
    for value in values[1:]:
        out = value * k + out * (1.0 - k)
    return out

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.ema_period), int(ctx.atr_period)) + int(ctx.slope_lookback) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars]
    ema = _ema(closes[-int(ctx.ema_period):], int(ctx.ema_period))
    ema_prev = _ema(closes[-int(ctx.ema_period)-int(ctx.slope_lookback):-int(ctx.slope_lookback)], int(ctx.ema_period))
    atr = _atr(bars, int(ctx.atr_period))
    upper = ema + atr * float(ctx.atr_mult)
    lower = ema - atr * float(ctx.atr_mult)
    slope_ok = ema > ema_prev if side == "long" else ema < ema_prev
    if _has_pos(ctx, side):
        if (side == "long" and price < ema) or (side == "short" and price > ema):
            ctx.order_target(0, side=side, reason="atr_channel_mid_exit")
        return
    if slope_ok and ((side == "long" and price > upper) or (side == "short" and price < lower)):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="atr_channel_breakout")
$qdtplv3_3$, '{"params":[{"name":"ema_period","type":"integer","default":48,"min":5,"max":300,"step":1},{"name":"atr_period","type":"integer","default":14,"min":3,"max":120,"step":1},{"name":"atr_mult","type":"number","default":2.2,"min":0.5,"max":8,"step":0.1},{"name":"slope_lookback","type":"integer","default":6,"min":1,"max":50,"step":1},{"name":"target_pct","type":"percent","default":0.32,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["atr","breakout","trailing"]'::jsonb, 'area-chart', 'orange', 30, TRUE, '{"source":"system_seed","version":3}'::jsonb, NOW()),

('rsi_mean_reversion', 'RSI Mean Reversion', 'RSI exhaustion strategy with regime filter, confirmation candle, fixed target, and time stop.', $qdtplv3_4$# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: engine
# @strategy stopLossPct 0.035
# @strategy takeProfitPct 0.055
# @strategy maxHoldingBars 36

def on_init(ctx):
    ctx.rsi_period = ctx.param("rsi_period", 14)
    ctx.regime_period = ctx.param("regime_period", 120)
    ctx.oversold = ctx.param("oversold", 32)
    ctx.overbought = ctx.param("overbought", 68)
    ctx.exit_level = ctx.param("exit_level", 50)
    ctx.target_pct = ctx.param("target_pct", 0.24)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _sma(values):
    return sum(values) / len(values) if values else 0.0

def _rsi(values, period):
    gains = []
    losses = []
    for i in range(len(values) - int(period), len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = _sma(gains)
    avg_loss = _sma(losses)
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.rsi_period) + 3, int(ctx.regime_period) + 1)
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    closes = [float(b["close"]) for b in bars]
    price = closes[-1]
    prev = closes[-2]
    regime = _sma(closes[-int(ctx.regime_period):])
    rsi = _rsi(closes, int(ctx.rsi_period))
    regime_ok = price >= regime if side == "long" else price <= regime
    confirm = price > prev if side == "long" else price < prev
    if _has_pos(ctx, side):
        if (side == "long" and rsi >= float(ctx.exit_level)) or (side == "short" and rsi <= float(ctx.exit_level)):
            ctx.order_target(0, side=side, reason="rsi_midline_exit")
        return
    if regime_ok and confirm and ((side == "long" and rsi <= float(ctx.oversold)) or (side == "short" and rsi >= float(ctx.overbought))):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="rsi_confirmed_reversion")
$qdtplv3_4$, '{"params":[{"name":"rsi_period","type":"integer","default":14,"min":3,"max":80,"step":1},{"name":"regime_period","type":"integer","default":120,"min":20,"max":400,"step":1},{"name":"oversold","type":"number","default":32,"min":5,"max":50,"step":1},{"name":"overbought","type":"number","default":68,"min":50,"max":95,"step":1},{"name":"exit_level","type":"number","default":50,"min":20,"max":80,"step":1},{"name":"target_pct","type":"percent","default":0.24,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["rsi","reversion","mean-reversion"]'::jsonb, 'sync', 'blue', 40, TRUE, '{"source":"system_seed","version":3}'::jsonb, NOW()),

('macd_momentum', 'MACD Momentum', 'MACD histogram expansion with EMA regime filter, signal crossover entry, and momentum decay exit.', $qdtplv3_5$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: engine
# @strategy stopLossPct 0.04
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.022
# @strategy trailingActivationPct 0.045

def on_init(ctx):
    ctx.fast = ctx.param("fast", 12)
    ctx.slow = ctx.param("slow", 26)
    ctx.signal = ctx.param("signal", 9)
    ctx.regime_ema = ctx.param("regime_ema", 100)
    ctx.target_pct = ctx.param("target_pct", 0.34)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _ema_series(values, period):
    k = 2.0 / (float(period) + 1.0)
    ema = values[0]
    out = []
    for value in values:
        ema = value * k + ema * (1.0 - k)
        out.append(ema)
    return out

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.regime_ema), int(ctx.slow) + int(ctx.signal) + 10)
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    closes = [float(b["close"]) for b in bars]
    fast = _ema_series(closes, int(ctx.fast))
    slow = _ema_series(closes, int(ctx.slow))
    macd = [fast[i] - slow[i] for i in range(len(closes))]
    sig = _ema_series(macd, int(ctx.signal))
    hist = [macd[i] - sig[i] for i in range(len(macd))]
    regime = _ema_series(closes, int(ctx.regime_ema))[-1]
    long_signal = hist[-1] > 0 and hist[-1] > hist[-2]
    short_signal = hist[-1] < 0 and hist[-1] < hist[-2]
    long_decay = hist[-1] < hist[-2]
    short_decay = hist[-1] > hist[-2]
    regime_ok = closes[-1] > regime if side == "long" else closes[-1] < regime
    if _has_pos(ctx, side):
        if (side == "long" and long_decay) or (side == "short" and short_decay):
            ctx.order_target(0, side=side, reason="macd_histogram_exit")
        return
    if regime_ok and ((side == "long" and long_signal) or (side == "short" and short_signal)):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="macd_momentum_cross")
$qdtplv3_5$, '{"params":[{"name":"fast","type":"integer","default":12,"min":2,"max":80,"step":1},{"name":"slow","type":"integer","default":26,"min":5,"max":160,"step":1},{"name":"signal","type":"integer","default":9,"min":2,"max":80,"step":1},{"name":"regime_ema","type":"integer","default":100,"min":20,"max":400,"step":1},{"name":"target_pct","type":"percent","default":0.34,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["macd","momentum","trailing"]'::jsonb, 'swap', 'purple', 50, TRUE, '{"source":"system_seed","version":3}'::jsonb, NOW()),

('bollinger_reversion', 'Bollinger Reversion', 'Bollinger z-score reversion with bandwidth filter, mid-band exit, and fixed engine target.', $qdtplv3_6$# timeframe: 1H
# signal_timing: next_bar_open
# exit_owner: engine
# @strategy stopLossPct 0.045
# @strategy takeProfitPct 0.065
# @strategy maxHoldingBars 48

def on_init(ctx):
    ctx.period = ctx.param("period", 20)
    ctx.std_mult = ctx.param("std_mult", 2.1)
    ctx.min_bandwidth = ctx.param("min_bandwidth", 0.015)
    ctx.exit_z = ctx.param("exit_z", 0.15)
    ctx.target_pct = ctx.param("target_pct", 0.25)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _mean(values):
    return sum(values) / len(values) if values else 0.0

def _std(values):
    mean = _mean(values)
    return (sum((v - mean) * (v - mean) for v in values) / len(values)) ** 0.5 if values else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    bars = ctx.bars(int(ctx.period) + 2)
    if len(bars) < int(ctx.period) + 2:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars[-int(ctx.period)-1:-1]]
    mid = _mean(closes)
    dev = _std(closes)
    if dev <= 0 or mid <= 0:
        return
    upper = mid + dev * float(ctx.std_mult)
    lower = mid - dev * float(ctx.std_mult)
    bandwidth = (upper - lower) / mid
    z = (price - mid) / dev
    if _has_pos(ctx, side):
        if abs(z) <= float(ctx.exit_z):
            ctx.order_target(0, side=side, reason="bollinger_z_exit")
        return
    if bandwidth >= float(ctx.min_bandwidth) and ((side == "long" and price <= lower) or (side == "short" and price >= upper)):
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="bollinger_band_reversion")
$qdtplv3_6$, '{"params":[{"name":"period","type":"integer","default":20,"min":5,"max":240,"step":1},{"name":"std_mult","type":"number","default":2.1,"min":0.5,"max":5,"step":0.1},{"name":"min_bandwidth","type":"percent","default":0.015,"min":0,"max":0.2,"step":0.001},{"name":"exit_z","type":"number","default":0.15,"min":0,"max":2,"step":0.05},{"name":"target_pct","type":"percent","default":0.25,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["bollinger","reversion","zscore"]'::jsonb, 'stock', 'teal', 60, TRUE, '{"source":"system_seed","version":3}'::jsonb, NOW()),

('turtle_breakout_lite', 'Turtle Breakout Lite', 'Turtle-style channel breakout with ATR unit sizing, one add-on unit, and channel exits.', $qdtplv3_7$# timeframe: 1D
# signal_timing: next_bar_open
# exit_owner: engine
# @strategy stopLossPct 0.08
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.04
# @strategy trailingActivationPct 0.08

def on_init(ctx):
    ctx.entry_lookback = ctx.param("entry_lookback", 20)
    ctx.exit_lookback = ctx.param("exit_lookback", 10)
    ctx.atr_period = ctx.param("atr_period", 20)
    ctx.risk_pct = ctx.param("risk_pct", 0.01)
    ctx.add_atr = ctx.param("add_atr", 0.5)
    ctx.max_target_pct = ctx.param("max_target_pct", 0.5)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.entry_lookback), int(ctx.exit_lookback), int(ctx.atr_period)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    atr = _atr(bars, int(ctx.atr_period))
    if price <= 0 or atr <= 0:
        return
    entry_window = bars[-int(ctx.entry_lookback)-1:-1]
    exit_window = bars[-int(ctx.exit_lookback)-1:-1]
    high = max(float(b["high"]) for b in entry_window)
    low = min(float(b["low"]) for b in entry_window)
    exit_high = max(float(b["high"]) for b in exit_window)
    exit_low = min(float(b["low"]) for b in exit_window)
    unit_value = min(float(ctx.equity) * float(ctx.max_target_pct) * 0.5, float(ctx.equity) * float(ctx.risk_pct) * price / atr)
    if _has_pos(ctx, side):
        entry = float(ctx.positions[side]["entry_price"] or price)
        added_key = "turtle_added_" + side
        add_trigger = price >= entry + atr * float(ctx.add_atr) if side == "long" else price <= entry - atr * float(ctx.add_atr)
        if add_trigger and not bool(ctx.state.get(added_key, False)):
            ctx.order_value(unit_value, side=side, reason="turtle_add_unit")
            ctx.state.set(added_key, True)
        if (side == "long" and price < exit_low) or (side == "short" and price > exit_high):
            ctx.order_target(0, side=side, reason="turtle_channel_exit")
            ctx.state.set(added_key, False)
        return
    if (side == "long" and price > high) or (side == "short" and price < low):
        ctx.order_value(unit_value, side=side, reason="turtle_breakout")
$qdtplv3_7$, '{"params":[{"name":"entry_lookback","type":"integer","default":20,"min":5,"max":120,"step":1},{"name":"exit_lookback","type":"integer","default":10,"min":3,"max":80,"step":1},{"name":"atr_period","type":"integer","default":20,"min":3,"max":120,"step":1},{"name":"risk_pct","type":"percent","default":0.01,"min":0.001,"max":0.1,"step":0.001},{"name":"add_atr","type":"number","default":0.5,"min":0.1,"max":4,"step":0.1},{"name":"max_target_pct","type":"percent","default":0.5,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["turtle","breakout","atr","trailing"]'::jsonb, 'flag', 'red', 70, TRUE, '{"source":"system_seed","version":3}'::jsonb, NOW()),

('volatility_stop_trend', 'Volatility Stop Trend', 'Trend-following EMA entry with an ATR volatility stop maintained in script state.', $qdtplv3_8$# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: strategy

def on_init(ctx):
    ctx.ema_period = ctx.param("ema_period", 55)
    ctx.atr_period = ctx.param("atr_period", 14)
    ctx.stop_atr = ctx.param("stop_atr", 2.8)
    ctx.breakout_lookback = ctx.param("breakout_lookback", 12)
    ctx.target_pct = ctx.param("target_pct", 0.35)

def _side(ctx):
    return "short" if str(ctx.direction).lower() == "short" else "long"

def _has_pos(ctx, side):
    return float(ctx.positions[side]["size"] or 0.0) > 0

def _ema(values, period):
    k = 2.0 / (float(period) + 1.0)
    out = values[0]
    for value in values[1:]:
        out = value * k + out * (1.0 - k)
    return out

def _atr(bars, period):
    trs = []
    for i in range(len(bars) - int(period), len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0

def on_bar(ctx, bar):
    side = _side(ctx)
    need = max(int(ctx.ema_period), int(ctx.atr_period), int(ctx.breakout_lookback)) + 2
    bars = ctx.bars(need)
    if len(bars) < need:
        return
    price = float(bar["close"])
    closes = [float(b["close"]) for b in bars]
    ema = _ema(closes[-int(ctx.ema_period):], int(ctx.ema_period))
    atr = _atr(bars, int(ctx.atr_period))
    high = max(float(b["high"]) for b in bars[-int(ctx.breakout_lookback)-1:-1])
    low = min(float(b["low"]) for b in bars[-int(ctx.breakout_lookback)-1:-1])
    key = "vol_stop_" + side
    if _has_pos(ctx, side):
        old_stop = float(ctx.state.get(key, 0.0) or 0.0)
        candidate = price - atr * float(ctx.stop_atr) if side == "long" else price + atr * float(ctx.stop_atr)
        stop = max(old_stop, candidate) if side == "long" and old_stop > 0 else candidate
        stop = min(old_stop, candidate) if side == "short" and old_stop > 0 else stop
        ctx.state.set(key, stop)
        if (side == "long" and price <= stop) or (side == "short" and price >= stop):
            ctx.order_target(0, side=side, reason="volatility_stop_exit")
        return
    trend = price > ema and price > high if side == "long" else price < ema and price < low
    if trend:
        ctx.order_value(float(ctx.equity) * float(ctx.target_pct), side=side, reason="volatility_trend_entry")
        ctx.state.set(key, price - atr * float(ctx.stop_atr) if side == "long" else price + atr * float(ctx.stop_atr))
$qdtplv3_8$, '{"params":[{"name":"ema_period","type":"integer","default":55,"min":5,"max":300,"step":1},{"name":"atr_period","type":"integer","default":14,"min":3,"max":120,"step":1},{"name":"stop_atr","type":"number","default":2.8,"min":0.5,"max":12,"step":0.1},{"name":"breakout_lookback","type":"integer","default":12,"min":3,"max":100,"step":1},{"name":"target_pct","type":"percent","default":0.35,"min":0.01,"max":1,"step":0.01}]}'::jsonb, '["trend","volatility","atr","stateful-stop"]'::jsonb, 'safety', 'green', 80, TRUE, '{"source":"system_seed","version":3}'::jsonb, NOW())
ON CONFLICT (template_key) DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    code = EXCLUDED.code,
    param_schema = EXCLUDED.param_schema,
    tags = EXCLUDED.tags,
    icon = EXCLUDED.icon,
    accent = EXCLUDED.accent,
    sort_order = EXCLUDED.sort_order,
    is_active = TRUE,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

-- =============================================================================
-- Completion Notice
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE 'QuantDinger PostgreSQL schema initialized successfully!';
END $$;
