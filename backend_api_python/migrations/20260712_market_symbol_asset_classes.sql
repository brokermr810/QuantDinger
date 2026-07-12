UPDATE qd_market_symbols SET asset_class = 'equity'
WHERE market IN ('CNStock', 'HKStock', 'USStock', 'MOEX') AND asset_class = 'crypto';

UPDATE qd_market_symbols SET asset_class = 'forex'
WHERE market = 'Forex' AND asset_class = 'crypto';

UPDATE qd_market_symbols SET asset_class = 'futures'
WHERE market = 'Futures' AND asset_class = 'crypto';

INSERT INTO qd_universes
  (code, name_i18n_key, market, universe_type, source, source_ref, is_system, status)
VALUES
  ('hk_core', 'universe.catalog.hkCore', 'HKStock', 'market', 'symbol_master', 'HKStock:hot:equity', TRUE, 'active'),
  ('hk_etf', 'universe.catalog.hkEtf', 'HKStock', 'etf', 'symbol_master', 'HKStock:hot:etf', TRUE, 'active'),
  ('us_etf', 'universe.catalog.usEtf', 'USStock', 'etf', 'symbol_master', 'USStock:hot:etf', TRUE, 'active')
ON CONFLICT DO NOTHING;

UPDATE qd_universes SET source_ref = 'USStock:hot:etf', updated_at = NOW()
WHERE code = 'us_etf' AND is_system = TRUE;

UPDATE qd_universes SET source_ref = 'HKStock:hot:etf', updated_at = NOW()
WHERE code = 'hk_etf' AND is_system = TRUE;

UPDATE qd_universes SET status = 'deprecated', updated_at = NOW()
WHERE code IN ('etf_pool', 'hk_equities') AND is_system = TRUE;

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
