ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) NOT NULL DEFAULT 'spot';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS instrument_id VARCHAR(120) NOT NULL DEFAULT '';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS settle_currency VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE qd_market_symbols ADD COLUMN IF NOT EXISTS asset_class VARCHAR(20) NOT NULL DEFAULT 'crypto';

CREATE UNIQUE INDEX IF NOT EXISTS uq_market_symbols_venue_instrument
  ON qd_market_symbols(market, symbol, exchange, market_type, instrument_id);

UPDATE qd_market_symbols
SET is_active = 0
WHERE market = 'Crypto'
  AND exchange <> ''
  AND exchange NOT IN ('binance', 'bitget', 'bybit', 'okx', 'gate', 'htx');
