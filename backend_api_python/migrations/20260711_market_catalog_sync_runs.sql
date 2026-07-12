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
