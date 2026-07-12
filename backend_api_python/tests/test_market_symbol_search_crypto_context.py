from app.services.market import symbol_search


def test_crypto_search_uses_matching_cached_catalog_without_live_lookup(monkeypatch):
    monkeypatch.setattr(
        symbol_search,
        "_search_crypto_exchange",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live lookup must not run")),
    )
    monkeypatch.setattr(
        symbol_search,
        "_search_cached_crypto_symbols",
        lambda keyword, limit, exchange_id, market_type: [
            {
                "market": "Crypto",
                "symbol": "AAPL/USDT",
                "name": "Apple",
                "exchange_id": exchange_id,
                "market_type": market_type,
                "instrument_id": "AAPL-USDT-SWAP",
                "settle_currency": "USDT",
                "asset_class": "equity",
            }
        ],
    )

    rows = symbol_search.search_market_symbols(
        "Crypto",
        "AAPL",
        exchange_id="okx",
        market_type="swap",
    )

    assert rows == [
        {
            "market": "Crypto",
            "symbol": "AAPL/USDT",
            "name": "Apple",
            "exchange_id": "okx",
            "market_type": "swap",
            "instrument_id": "AAPL-USDT-SWAP",
            "settle_currency": "USDT",
            "asset_class": "equity",
        }
    ]


def test_crypto_search_rejects_removed_exchange():
    assert symbol_search.search_market_symbols(
        "Crypto",
        "BTC",
        exchange_id="kraken",
        market_type="spot",
    ) == []
