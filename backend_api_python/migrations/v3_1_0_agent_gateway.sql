-- QuantDinger V3.1.0 — Agent Gateway (idempotent; safe to re-run)
-- Source: docs/CHANGELOG.md — mirrors init.sql agent section + extra indexes

-- 1. Agent tokens
CREATE TABLE IF NOT EXISTS qd_agent_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    token_prefix VARCHAR(24) NOT NULL,
    token_hash VARCHAR(128) NOT NULL,
    scopes TEXT NOT NULL DEFAULT 'R',
    markets TEXT NOT NULL DEFAULT '*',
    instruments TEXT NOT NULL DEFAULT '*',
    paper_only BOOLEAN NOT NULL DEFAULT TRUE,
    rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tokens_hash   ON qd_agent_tokens(token_hash);
CREATE INDEX        IF NOT EXISTS idx_agent_tokens_user   ON qd_agent_tokens(user_id);
CREATE INDEX        IF NOT EXISTS idx_agent_tokens_status ON qd_agent_tokens(status);

-- 2. Agent async jobs
CREATE TABLE IF NOT EXISTS qd_agent_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(40) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    agent_token_id INTEGER REFERENCES qd_agent_tokens(id) ON DELETE SET NULL,
    kind VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    progress JSONB,
    idempotency_key VARCHAR(120),
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
ALTER TABLE qd_agent_jobs ADD COLUMN IF NOT EXISTS progress JSONB;

CREATE INDEX        IF NOT EXISTS idx_agent_jobs_user   ON qd_agent_jobs(user_id);
CREATE INDEX        IF NOT EXISTS idx_agent_jobs_status ON qd_agent_jobs(status);
CREATE INDEX        IF NOT EXISTS idx_agent_jobs_kind   ON qd_agent_jobs(kind);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_jobs_idem
    ON qd_agent_jobs(agent_token_id, kind, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- 3. Audit log
CREATE TABLE IF NOT EXISTS qd_agent_audit (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    agent_token_id INTEGER,
    agent_name VARCHAR(80),
    route VARCHAR(160) NOT NULL,
    method VARCHAR(8) NOT NULL,
    scope_class VARCHAR(4) NOT NULL,
    status_code INTEGER NOT NULL,
    idempotency_key VARCHAR(120),
    request_summary JSONB,
    response_summary JSONB,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_audit_user  ON qd_agent_audit(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_token ON qd_agent_audit(agent_token_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_audit_class ON qd_agent_audit(scope_class);

-- 4. Paper orders ledger
CREATE TABLE IF NOT EXISTS qd_agent_paper_orders (
    id BIGSERIAL PRIMARY KEY,
    order_uid VARCHAR(40) NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES qd_users(id) ON DELETE CASCADE,
    agent_token_id INTEGER REFERENCES qd_agent_tokens(id) ON DELETE SET NULL,
    market VARCHAR(40) NOT NULL,
    symbol VARCHAR(60) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(16) NOT NULL DEFAULT 'market',
    qty DECIMAL(28,10) NOT NULL,
    limit_price DECIMAL(28,10),
    fill_price DECIMAL(28,10),
    fill_value DECIMAL(28,10),
    status VARCHAR(16) NOT NULL DEFAULT 'filled',
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_paper_orders_user  ON qd_agent_paper_orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_paper_orders_token ON qd_agent_paper_orders(agent_token_id);

DO $$ BEGIN RAISE NOTICE 'QuantDinger V3.1.0 agent gateway schema migration completed.'; END $$;
