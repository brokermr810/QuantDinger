INSERT INTO qd_universes
  (code, name, name_i18n_key, market, universe_type, source, source_ref, is_system, status)
VALUES
  ('hk_hsi_core50', 'Hang Seng Index Core 50', 'universe.catalog.hkHsiCore50', 'HKStock', 'index', 'public_snapshot', 'HSI_CORE50', TRUE, 'data_required'),
  ('hk_tech30', 'Hang Seng TECH 30', 'universe.catalog.hkTech30', 'HKStock', 'index', 'public_snapshot', 'HSTECH', TRUE, 'data_required'),
  ('hk_china_enterprises50', 'Hang Seng China Enterprises 50', 'universe.catalog.hkChinaEnterprises50', 'HKStock', 'index', 'public_snapshot', 'HSCEI', TRUE, 'data_required'),
  ('hk_high_dividend50', 'Hang Seng High Dividend Yield 50', 'universe.catalog.hkHighDividend50', 'HKStock', 'index', 'public_snapshot', 'HSHDYI', TRUE, 'data_required')
ON CONFLICT DO NOTHING;

UPDATE qd_universes SET status = 'deprecated', updated_at = NOW()
WHERE code = 'hk_core' AND is_system = TRUE;
