import ccxt

from app.data_sources import crypto
from app.services.symbol_master_sync import fetch_crypto_symbols, fetch_crypto_symbols_with_diagnostics
from app.services.market.symbol_search import _classify_asset


class FakeExchange:
    def __init__(self, config):
        market_type = (config.get("options") or {}).get("defaultType") or "spot"
        is_swap = market_type in {"swap", "linear"}
        self.markets = {
            "AAPL/USDT:USDT" if is_swap else "AAPL/USDT": {
                "active": True,
                "spot": not is_swap,
                "swap": is_swap,
                "base": "AAPL",
                "quote": "USDT",
                "settle": "USDT" if is_swap else None,
                "id": "AAPLUSDT",
                "displayName": "Apple",
            }
        }

    def load_markets(self):
        return self.markets


def test_full_catalog_keeps_same_equity_separate_by_venue_and_product(monkeypatch):
    monkeypatch.setattr(
        crypto,
        "resolve_ccxt_for_live_trading",
        lambda exchange_id, market_type: (
            exchange_id,
            {"defaultType": market_type},
        ),
    )
    for exchange_id in crypto.PUBLIC_KLINE_EXCHANGE_IDS:
        monkeypatch.setattr(ccxt, exchange_id, FakeExchange)

    rows = fetch_crypto_symbols()

    assert len(rows) == 12
    assert {
        (row.exchange, row.market_type)
        for row in rows
    } == {
        (exchange_id, market_type)
        for exchange_id in crypto.PUBLIC_KLINE_EXCHANGE_IDS
        for market_type in ("spot", "swap")
    }


def test_equity_metadata_is_classified_without_ticker_hardcoding():
    assert _classify_asset({"info": {"instCategory": "3"}}) == "equity"
    assert _classify_asset({"info": {"symbolType": "xstocks"}}) == "equity"
    assert _classify_asset({"info": {"symbolType": "stock"}}) == "equity"
    assert _classify_asset({"info": {"isRwa": "YES"}}) == "rwa"
    assert _classify_asset({"info": {}}) == "crypto"


def test_catalog_diagnostics_report_every_venue_product(monkeypatch):
    monkeypatch.setattr(
        crypto,
        "resolve_ccxt_for_live_trading",
        lambda exchange_id, market_type: (exchange_id, {"defaultType": market_type}),
    )
    for exchange_id in crypto.PUBLIC_KLINE_EXCHANGE_IDS:
        monkeypatch.setattr(ccxt, exchange_id, FakeExchange)

    rows, contexts = fetch_crypto_symbols_with_diagnostics()

    assert len(rows) == 12
    assert len(contexts) == 12
    assert all(context["ok"] and context["rows"] == 1 for context in contexts)
