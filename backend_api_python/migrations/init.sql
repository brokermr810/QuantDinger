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
    credits DECIMAL(20,2) DEFAULT 0,       -- 积分余额
    vip_expires_at TIMESTAMP,              -- VIP过期时间
    email_verified BOOLEAN DEFAULT FALSE,  -- 邮箱是否已验证
    referred_by INTEGER,                   -- 邀请人ID
    notification_settings TEXT DEFAULT '', -- 用户通知配置 JSON (telegram_chat_id, default_channels等)
    token_version INTEGER DEFAULT 1,       -- Token版本号，用于单一客户端登录控制
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_referred_by ON qd_users(referred_by);

-- Note: Admin user is created automatically by the application on startup
-- using ADMIN_USER and ADMIN_PASSWORD from environment variables

-- =============================================================================
-- 1.5. Credits Log (积分变动日志)
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_credits_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,            -- recharge/consume/refund/admin_adjust/vip_grant
    amount DECIMAL(20,2) NOT NULL,          -- 变动金额（正数增加，负数减少）
    balance_after DECIMAL(20,2) NOT NULL,   -- 变动后余额
    feature VARCHAR(50) DEFAULT '',          -- 消费的功能：ai_analysis/strategy_run/backtest 等
    reference_id VARCHAR(100) DEFAULT '',    -- 关联ID（如订单号、分析任务ID等）
    remark TEXT DEFAULT '',                  -- 备注
    operator_id INTEGER,                     -- 操作人ID（管理员调整时记录）
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credits_log_user_id ON qd_credits_log(user_id);
CREATE INDEX IF NOT EXISTS idx_credits_log_action ON qd_credits_log(action);
CREATE INDEX IF NOT EXISTS idx_credits_log_created_at ON qd_credits_log(created_at);

-- =============================================================================
-- 1.6. Verification Codes (邮箱验证码)
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
-- 1.7. Login Attempts (登录尝试记录 - 防爆破)
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
-- 1.8. OAuth Links (第三方账号关联)
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
-- 1.9. Security Audit Log (安全审计日志)
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
-- 2. Trading Strategies
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_strategies_trading (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_name VARCHAR(255) NOT NULL,
    strategy_type VARCHAR(50) DEFAULT 'IndicatorStrategy',
    market_category VARCHAR(50) DEFAULT 'Crypto',
    execution_mode VARCHAR(20) DEFAULT 'signal',
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
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategies_user_id ON qd_strategies_trading(user_id);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON qd_strategies_trading(status);
CREATE INDEX IF NOT EXISTS idx_strategies_group_id ON qd_strategies_trading(strategy_group_id);

-- =============================================================================
-- 3. Strategy Positions
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_strategy_positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    symbol VARCHAR(50),
    side VARCHAR(10),  -- long/short
    size DECIMAL(20,8),
    entry_price DECIMAL(20,8),
    current_price DECIMAL(20,8),
    highest_price DECIMAL(20,8) DEFAULT 0,
    lowest_price DECIMAL(20,8) DEFAULT 0,
    unrealized_pnl DECIMAL(20,8) DEFAULT 0,
    pnl_percent DECIMAL(10,4) DEFAULT 0,
    equity DECIMAL(20,8) DEFAULT 0,
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
    type VARCHAR(30),  -- open_long, close_short, etc.
    price DECIMAL(20,8),
    amount DECIMAL(20,8),
    value DECIMAL(20,8),
    commission DECIMAL(20,8) DEFAULT 0,
    commission_ccy VARCHAR(20) DEFAULT '',
    profit DECIMAL(20,8) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_user_id ON qd_strategy_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy_id ON qd_strategy_trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON qd_strategy_trades(created_at);

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
   CONSTRAINT qd_indicator_codes_pkey PRIMARY KEY (id),
   CONSTRAINT qd_indicator_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES qd_users(id) ON DELETE CASCADE

);

CREATE INDEX IF NOT EXISTS idx_indicator_codes_user_id ON qd_indicator_codes USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_indicator_review_status ON qd_indicator_codes USING btree (review_status);

-- =============================================================================
-- 8. AI Decisions
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_ai_decisions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    strategy_id INTEGER REFERENCES qd_strategies_trading(id) ON DELETE CASCADE,
    decision_data TEXT,
    context_data TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_decisions_user_id ON qd_ai_decisions(user_id);

-- =============================================================================
-- 9. Addon Config
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_addon_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value TEXT,
    type VARCHAR(20) DEFAULT 'string'
);

-- =============================================================================
-- 10. Watchlist
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_watchlist (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    name VARCHAR(100) DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, market, symbol)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user_id ON qd_watchlist(user_id);

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

-- =============================================================================
-- 12. Backtest Runs
-- =============================================================================

CREATE TABLE IF NOT EXISTS qd_backtest_runs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL DEFAULT 1 REFERENCES qd_users(id) ON DELETE CASCADE,
    indicator_id INTEGER,
    market VARCHAR(50) NOT NULL DEFAULT '',
    symbol VARCHAR(50) NOT NULL DEFAULT '',
    timeframe VARCHAR(10) NOT NULL DEFAULT '',
    start_date VARCHAR(20) NOT NULL DEFAULT '',
    end_date VARCHAR(20) NOT NULL DEFAULT '',
    initial_capital DECIMAL(20,8) DEFAULT 10000,
    commission DECIMAL(10,6) DEFAULT 0.001,
    slippage DECIMAL(10,6) DEFAULT 0,
    leverage INTEGER DEFAULT 1,
    trade_direction VARCHAR(20) DEFAULT 'long',
    strategy_config TEXT DEFAULT '',
    status VARCHAR(20) DEFAULT 'success',
    error_message TEXT DEFAULT '',
    result_json TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_user_id ON qd_backtest_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_indicator_id ON qd_backtest_runs(indicator_id);

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
    currency VARCHAR(10) DEFAULT '',
    is_active INTEGER DEFAULT 1,
    is_hot INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(market, symbol)
);

CREATE INDEX IF NOT EXISTS idx_market_symbols_market ON qd_market_symbols(market);
CREATE INDEX IF NOT EXISTS idx_market_symbols_is_hot ON qd_market_symbols(market, is_hot);

-- Seed data: Hot symbols for each market
INSERT INTO qd_market_symbols (market, symbol, name, exchange, currency, is_active, is_hot, sort_order) VALUES
-- AShare (China A-Shares)
('AShare', '000001', '平安银行', 'SZSE', 'CNY', 1, 1, 100),
('AShare', '000002', '万科A', 'SZSE', 'CNY', 1, 1, 99),
('AShare', '600000', '浦发银行', 'SSE', 'CNY', 1, 1, 98),
('AShare', '600036', '招商银行', 'SSE', 'CNY', 1, 1, 97),
('AShare', '600519', '贵州茅台', 'SSE', 'CNY', 1, 1, 96),
('AShare', '000858', '五粮液', 'SZSE', 'CNY', 1, 1, 95),
('AShare', '002415', '海康威视', 'SZSE', 'CNY', 1, 1, 94),
('AShare', '300059', '东方财富', 'SZSE', 'CNY', 1, 1, 93),
('AShare', '000725', '京东方A', 'SZSE', 'CNY', 1, 1, 92),
('AShare', '002594', '比亚迪', 'SZSE', 'CNY', 1, 1, 91),
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
-- HShare (Hong Kong Stocks)
('HShare', '00700', 'Tencent Holdings', 'HKEX', 'HKD', 1, 1, 100),
('HShare', '09988', 'Alibaba Group', 'HKEX', 'HKD', 1, 1, 99),
('HShare', '03690', 'Meituan', 'HKEX', 'HKD', 1, 1, 98),
('HShare', '01810', 'Xiaomi Corporation', 'HKEX', 'HKD', 1, 1, 97),
('HShare', '02318', 'Ping An Insurance', 'HKEX', 'HKD', 1, 1, 96),
('HShare', '01398', 'ICBC', 'HKEX', 'HKD', 1, 1, 95),
('HShare', '00939', 'CCB', 'HKEX', 'HKD', 1, 1, 94),
('HShare', '01299', 'AIA Group', 'HKEX', 'HKD', 1, 1, 93),
('HShare', '02020', 'Anta Sports', 'HKEX', 'HKD', 1, 1, 92),
('HShare', '01024', 'Kuaishou Technology', 'HKEX', 'HKD', 1, 1, 91),
-- Crypto
('Crypto', 'BTC/USDT', 'Bitcoin', 'Binance', 'USDT', 1, 1, 100),
('Crypto', 'ETH/USDT', 'Ethereum', 'Binance', 'USDT', 1, 1, 99),
('Crypto', 'BNB/USDT', 'BNB', 'Binance', 'USDT', 1, 1, 98),
('Crypto', 'SOL/USDT', 'Solana', 'Binance', 'USDT', 1, 1, 97),
('Crypto', 'XRP/USDT', 'Ripple', 'Binance', 'USDT', 1, 1, 96),
('Crypto', 'ADA/USDT', 'Cardano', 'Binance', 'USDT', 1, 1, 95),
('Crypto', 'DOGE/USDT', 'Dogecoin', 'Binance', 'USDT', 1, 1, 94),
('Crypto', 'DOT/USDT', 'Polkadot', 'Binance', 'USDT', 1, 1, 93),
('Crypto', 'MATIC/USDT', 'Polygon', 'Binance', 'USDT', 1, 1, 92),
('Crypto', 'AVAX/USDT', 'Avalanche', 'Binance', 'USDT', 1, 1, 91),
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
('Futures', 'NQ', 'NASDAQ 100 E-mini', 'CME', 'USD', 1, 1, 91)
ON CONFLICT (market, symbol) DO NOTHING;

-- =============================================================================
-- 18. Agent Memories (AI Learning System)
-- =============================================================================
-- Stores agent decision experiences for RAG-style retrieval during analysis.
-- Each agent (trader, risk_analyst, etc.) shares this table but is identified by agent_name.

CREATE TABLE IF NOT EXISTS qd_agent_memories (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL,
    situation TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    result TEXT,
    returns REAL,
    market VARCHAR(50),
    symbol VARCHAR(50),
    timeframe VARCHAR(20),
    features_json TEXT,
    embedding BYTEA,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_agent ON qd_agent_memories(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_memories_created ON qd_agent_memories(agent_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_memories_market ON qd_agent_memories(agent_name, market, symbol);

-- =============================================================================
-- 19. Reflection Records (AI Auto-Verification System)
-- =============================================================================
-- Records analysis predictions for future auto-verification and closed-loop learning.

CREATE TABLE IF NOT EXISTS qd_reflection_records (
    id SERIAL PRIMARY KEY,
    market VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    initial_price REAL,
    decision VARCHAR(20),
    confidence INTEGER,
    reasoning TEXT,
    analysis_date TIMESTAMP DEFAULT NOW(),
    target_check_date TIMESTAMP,
    status VARCHAR(20) DEFAULT 'PENDING',
    final_price REAL,
    actual_return REAL,
    check_result TEXT
);

CREATE INDEX IF NOT EXISTS idx_reflection_status ON qd_reflection_records(status, target_check_date);
CREATE INDEX IF NOT EXISTS idx_reflection_market ON qd_reflection_records(market, symbol);

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
    entry_price DECIMAL(24, 8),
    stop_loss DECIMAL(24, 8),
    take_profit DECIMAL(24, 8),
    summary TEXT,
    reasons JSONB,
    risks JSONB,
    scores JSONB,
    indicators_snapshot JSONB,
    raw_result JSONB,                           -- Full analysis result for history replay
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
-- 21. Indicator Community Tables
-- =============================================================================

-- Indicator Purchases (购买记录)
CREATE TABLE IF NOT EXISTS qd_indicator_purchases (
    id SERIAL PRIMARY KEY,
    indicator_id INTEGER NOT NULL REFERENCES qd_indicator_codes(id) ON DELETE CASCADE,
    buyer_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    seller_id INTEGER NOT NULL REFERENCES qd_users(id),
    price DECIMAL(10,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(indicator_id, buyer_id)
);

CREATE INDEX IF NOT EXISTS idx_purchases_indicator ON qd_indicator_purchases(indicator_id);
CREATE INDEX IF NOT EXISTS idx_purchases_buyer ON qd_indicator_purchases(buyer_id);
CREATE INDEX IF NOT EXISTS idx_purchases_seller ON qd_indicator_purchases(seller_id);

-- Indicator Comments (评论)
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
-- Completion Notice
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE 'QuantDinger PostgreSQL schema initialized successfully!';
END $$;
