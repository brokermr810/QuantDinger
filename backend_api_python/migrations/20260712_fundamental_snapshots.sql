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
