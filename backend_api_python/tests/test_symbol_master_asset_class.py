from app.services.symbol_master_sync import SymbolMasterRow, _default_asset_class


def test_symbol_master_asset_class_defaults_follow_market_type():
    assert _default_asset_class("USStock") == "equity"
    assert _default_asset_class("HKStock") == "equity"
    assert _default_asset_class("CNStock") == "equity"
    assert _default_asset_class("Crypto") == "crypto"
    assert _default_asset_class("Forex") == "forex"
    assert _default_asset_class("Futures") == "futures"


def test_explicit_etf_classification_is_preserved():
    row = SymbolMasterRow("HKStock", "02800", "Tracker Fund", "HKEX", "HKD", asset_class="etf")
    assert row.asset_class == "etf"
