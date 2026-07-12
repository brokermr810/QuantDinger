"""Local symbol master synchronization.

The app searches `qd_market_symbols` first. This module keeps that table useful
without requiring users to remember ticker codes.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import requests

from app.data_sources.tencent import normalize_hk_code
from app.services.symbol_name import normalize_crypto_symbol
from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SymbolMasterRow:
    market: str
    symbol: str
    name: str
    exchange: str = ""
    currency: str = ""
    market_type: str = "spot"
    instrument_id: str = ""
    settle_currency: str = ""
    asset_class: str = ""


STATIC_MARKET_ROWS = [
    SymbolMasterRow("Crypto", "BTC/USDT", "Bitcoin", "binance", "USDT"),
    SymbolMasterRow("Crypto", "ETH/USDT", "Ethereum", "binance", "USDT"),
    SymbolMasterRow("Crypto", "BNB/USDT", "BNB", "binance", "USDT"),
    SymbolMasterRow("Crypto", "SOL/USDT", "Solana", "binance", "USDT"),
    SymbolMasterRow("Crypto", "XRP/USDT", "XRP", "binance", "USDT"),
    SymbolMasterRow("Crypto", "DOGE/USDT", "Dogecoin", "binance", "USDT"),
    SymbolMasterRow("Crypto", "ADA/USDT", "Cardano", "binance", "USDT"),
    SymbolMasterRow("Crypto", "AVAX/USDT", "Avalanche", "binance", "USDT"),
    SymbolMasterRow("Crypto", "LINK/USDT", "Chainlink", "binance", "USDT"),
    SymbolMasterRow("Crypto", "DOT/USDT", "Polkadot", "binance", "USDT"),
    SymbolMasterRow("Crypto", "TRX/USDT", "TRON", "binance", "USDT"),
    SymbolMasterRow("Crypto", "TON/USDT", "Toncoin", "binance", "USDT"),
    SymbolMasterRow("Crypto", "LTC/USDT", "Litecoin", "binance", "USDT"),
    SymbolMasterRow("Crypto", "BCH/USDT", "Bitcoin Cash", "binance", "USDT"),
    SymbolMasterRow("Crypto", "UNI/USDT", "Uniswap", "binance", "USDT"),
    SymbolMasterRow("Crypto", "AAVE/USDT", "Aave", "binance", "USDT"),
    SymbolMasterRow("Crypto", "MATIC/USDT", "Polygon", "binance", "USDT"),
    SymbolMasterRow("Crypto", "NEAR/USDT", "NEAR Protocol", "binance", "USDT"),
    SymbolMasterRow("Crypto", "APT/USDT", "Aptos", "binance", "USDT"),
    SymbolMasterRow("Crypto", "ARB/USDT", "Arbitrum", "binance", "USDT"),
    SymbolMasterRow("Crypto", "OP/USDT", "Optimism", "binance", "USDT"),
    SymbolMasterRow("Crypto", "FIL/USDT", "Filecoin", "binance", "USDT"),
    SymbolMasterRow("Crypto", "ETC/USDT", "Ethereum Classic", "binance", "USDT"),
    SymbolMasterRow("Crypto", "ATOM/USDT", "Cosmos", "binance", "USDT"),
    SymbolMasterRow("Crypto", "INJ/USDT", "Injective", "binance", "USDT"),
    SymbolMasterRow("Crypto", "SUI/USDT", "Sui", "binance", "USDT"),
    SymbolMasterRow("Crypto", "SEI/USDT", "Sei", "binance", "USDT"),
    SymbolMasterRow("Crypto", "PEPE/USDT", "Pepe", "binance", "USDT"),
    SymbolMasterRow("Crypto", "SHIB/USDT", "Shiba Inu", "binance", "USDT"),
    SymbolMasterRow("Crypto", "WLD/USDT", "Worldcoin", "binance", "USDT"),
    SymbolMasterRow("Forex", "XAUUSD", "Gold Spot", "TwelveData", "USD"),
    SymbolMasterRow("Forex", "XAGUSD", "Silver Spot", "TwelveData", "USD"),
    SymbolMasterRow("Forex", "EURUSD", "Euro / US Dollar", "TwelveData", "USD"),
    SymbolMasterRow("Forex", "GBPUSD", "British Pound / US Dollar", "TwelveData", "USD"),
    SymbolMasterRow("Forex", "USDJPY", "US Dollar / Japanese Yen", "TwelveData", "JPY"),
    SymbolMasterRow("Forex", "AUDUSD", "Australian Dollar / US Dollar", "TwelveData", "USD"),
    SymbolMasterRow("Forex", "USDCAD", "US Dollar / Canadian Dollar", "TwelveData", "CAD"),
    SymbolMasterRow("Forex", "USDCHF", "US Dollar / Swiss Franc", "TwelveData", "CHF"),
    SymbolMasterRow("Forex", "NZDUSD", "New Zealand Dollar / US Dollar", "TwelveData", "USD"),
    SymbolMasterRow("Forex", "GBPJPY", "British Pound / Japanese Yen", "TwelveData", "JPY"),
    SymbolMasterRow("Forex", "EURJPY", "Euro / Japanese Yen", "TwelveData", "JPY"),
    SymbolMasterRow("Forex", "EURGBP", "Euro / British Pound", "TwelveData", "GBP"),
    SymbolMasterRow("Forex", "AUDNZD", "Australian Dollar / New Zealand Dollar", "TwelveData", "NZD"),
    SymbolMasterRow("Forex", "USDCNH", "US Dollar / Offshore Chinese Yuan", "TwelveData", "CNH"),
    SymbolMasterRow("Futures", "GC", "Gold Futures", "CME", "USD"),
    SymbolMasterRow("Futures", "SI", "Silver Futures", "CME", "USD"),
    SymbolMasterRow("Futures", "CL", "Crude Oil WTI Futures", "NYMEX", "USD"),
    SymbolMasterRow("Futures", "NG", "Natural Gas Futures", "NYMEX", "USD"),
    SymbolMasterRow("Futures", "HG", "Copper Futures", "COMEX", "USD"),
    SymbolMasterRow("Futures", "PL", "Platinum Futures", "NYMEX", "USD"),
    SymbolMasterRow("Futures", "ES", "E-mini S&P 500 Futures", "CME", "USD"),
    SymbolMasterRow("Futures", "NQ", "E-mini Nasdaq 100 Futures", "CME", "USD"),
    SymbolMasterRow("Futures", "YM", "E-mini Dow Futures", "CBOT", "USD"),
    SymbolMasterRow("Futures", "RTY", "E-mini Russell 2000 Futures", "CME", "USD"),
    SymbolMasterRow("Futures", "ZC", "Corn Futures", "CBOT", "USD"),
    SymbolMasterRow("Futures", "ZS", "Soybean Futures", "CBOT", "USD"),
    SymbolMasterRow("Futures", "ZW", "Wheat Futures", "CBOT", "USD"),
    SymbolMasterRow("MOEX", "SBER", "Sberbank", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "GAZP", "Gazprom", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "LKOH", "Lukoil", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "ROSN", "Rosneft", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "GMKN", "Norilsk Nickel", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "NVTK", "Novatek", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "TATN", "Tatneft", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "YDEX", "Yandex", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "VTBR", "VTB Bank", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "MGNT", "Magnit", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "SNGS", "Surgutneftegas", "MOEX", "RUB"),
    SymbolMasterRow("MOEX", "PLZL", "Polyus", "MOEX", "RUB"),
]


def _clean_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    suspicious = any(ch in text for ch in ("\u9a9e", "\u95be", "\u934f", "\u6d93", "\u6df1", "\u7eee", "\u60f0"))
    if not suspicious:
        return text
    for enc in ("gbk", "cp936", "latin1"):
        try:
            fixed = text.encode(enc).decode("utf-8")
            if fixed and fixed != text:
                return fixed
        except Exception:
            pass
    return text


def _clean_symbol(value: object) -> str:
    return _clean_text(value).upper()


def _unique_rows(rows: Iterable[SymbolMasterRow]) -> List[SymbolMasterRow]:
    out: List[SymbolMasterRow] = []
    seen = set()
    for row in rows:
        key = (row.market, row.symbol, row.exchange, row.market_type, row.instrument_id)
        if not row.market or not row.symbol or not row.name or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _static_rows(market: str) -> List[SymbolMasterRow]:
    return [row for row in STATIC_MARKET_ROWS if row.market == market]


def _df_records(df) -> list:
    if df is None:
        return []
    try:
        return df.to_dict("records")
    except Exception:
        return []


def fetch_cn_stock_symbols() -> List[SymbolMasterRow]:
    """Fetch A-share code/name rows from AkShare."""
    import akshare as ak  # type: ignore

    rows = []
    for item in _df_records(ak.stock_info_a_code_name()):
        symbol = _clean_symbol(item.get("code") or item.get("代码"))
        name = _clean_text(item.get("name") or item.get("名称"))
        if re.fullmatch(r"\d{6}", symbol) and name:
            rows.append(SymbolMasterRow("CNStock", symbol, name, "CN", "CNY"))
    return _unique_rows(rows)


def fetch_hk_stock_symbols() -> List[SymbolMasterRow]:
    """Fetch Hong Kong stock code/name rows from HKEX, with AkShare fallback."""
    rows = fetch_hk_stock_symbols_hkex()
    if rows:
        return rows
    return fetch_hk_stock_symbols_akshare()


def fetch_hk_stock_symbols_hkex() -> List[SymbolMasterRow]:
    import pandas as pd

    resp = requests.get(
        "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx",
        timeout=25,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content), sheet_name=0, header=2)
    rows = []
    for item in _df_records(df):
        raw_symbol = item.get("Stock Code")
        name = _clean_text(item.get("Name of Securities"))
        category = _clean_text(item.get("Category"))
        currency = _clean_text(item.get("Trading Currency")) or "HKD"
        symbol = re.sub(r"[^0-9]", "", _clean_text(raw_symbol)).zfill(5)
        if symbol and name and category in {"Equity", "Exchange Traded Products"}:
            asset_class = "etf" if category == "Exchange Traded Products" else "equity"
            rows.append(SymbolMasterRow("HKStock", symbol, name, "HKEX", currency, asset_class=asset_class))
    return _unique_rows(rows)


def fetch_hk_stock_symbols_akshare() -> List[SymbolMasterRow]:
    import akshare as ak  # type: ignore

    rows = []
    for item in _df_records(ak.stock_hk_spot_em()):
        raw_symbol = _clean_symbol(item.get("代码") or item.get("code") or item.get("symbol"))
        name = _clean_text(item.get("名称") or item.get("name"))
        digits = re.sub(r"[^0-9]", "", raw_symbol)
        if digits and name:
            symbol = normalize_hk_code(digits).replace("HK", "")
            rows.append(SymbolMasterRow("HKStock", symbol, name, "HKEX", "HKD"))
    return _unique_rows(rows)


def _fetch_nasdaq_trader_file(url: str) -> List[Dict[str, str]]:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    text = resp.text
    lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
    return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|"))


def fetch_us_stock_symbols() -> List[SymbolMasterRow]:
    """Fetch US listed equities and ETFs from Nasdaq Trader symbol directories."""
    rows: List[SymbolMasterRow] = []

    nasdaq_rows = _fetch_nasdaq_trader_file("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt")
    for item in nasdaq_rows:
        symbol = _clean_symbol(item.get("Symbol"))
        name = _clean_text(item.get("Security Name"))
        test_issue = _clean_symbol(item.get("Test Issue"))
        etf = _clean_symbol(item.get("ETF"))
        if symbol and name and test_issue != "Y":
            rows.append(SymbolMasterRow(
                "USStock", symbol, name, "NASDAQ", "USD",
                asset_class="etf" if etf == "Y" else "equity",
            ))

    other_rows = _fetch_nasdaq_trader_file("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt")
    exchange_map = {
        "A": "NYSE American",
        "N": "NYSE",
        "P": "NYSE Arca",
        "Z": "Cboe BZX",
        "V": "IEX",
    }
    for item in other_rows:
        symbol = _clean_symbol(item.get("ACT Symbol"))
        name = _clean_text(item.get("Security Name"))
        exchange = exchange_map.get(_clean_symbol(item.get("Exchange")), _clean_symbol(item.get("Exchange")))
        test_issue = _clean_symbol(item.get("Test Issue"))
        etf = _clean_symbol(item.get("ETF"))
        if symbol and name and test_issue != "Y":
            rows.append(SymbolMasterRow(
                "USStock", symbol, name, exchange, "USD",
                asset_class="etf" if etf == "Y" else "equity",
            ))

    return _unique_rows(rows)


def fetch_crypto_symbols_with_diagnostics():
    """Fetch active USDT instruments and return per-context diagnostics."""
    import ccxt  # type: ignore
    from app.config.data_sources import CCXTConfig
    from app.data_sources.crypto import PUBLIC_KLINE_EXCHANGE_IDS, resolve_ccxt_for_live_trading
    from app.services.market.symbol_search import _classify_asset

    rows: List[SymbolMasterRow] = []
    contexts = []
    for exchange_id in PUBLIC_KLINE_EXCHANGE_IDS:
        for market_type in ("spot", "swap"):
            context_rows: List[SymbolMasterRow] = []
            try:
                ccxt_id, options = resolve_ccxt_for_live_trading(exchange_id, market_type)
                config = {"enableRateLimit": True, "timeout": CCXTConfig.TIMEOUT}
                if options:
                    config["options"] = options
                exchange = getattr(ccxt, ccxt_id)(config)
                exchange.load_markets()
                for symbol, info in exchange.markets.items():
                    is_target = bool(info.get("spot")) if market_type == "spot" else bool(info.get("swap"))
                    quote = _clean_symbol(info.get("quote"))
                    base = _clean_symbol(info.get("base"))
                    if not info.get("active") or not is_target or quote != "USDT" or not base:
                        continue
                    context_rows.append(SymbolMasterRow(
                        "Crypto",
                        normalize_crypto_symbol(symbol),
                        _clean_text(info.get("displayName") or info.get("name") or base),
                        exchange_id,
                        "USDT",
                        market_type,
                        _clean_text(info.get("id") or symbol),
                        _clean_symbol(info.get("settle") or quote),
                        _classify_asset(info),
                    ))
                rows.extend(context_rows)
                contexts.append({
                    "exchange": exchange_id,
                    "market_type": market_type,
                    "ok": True,
                    "rows": len(context_rows),
                })
            except Exception as e:
                logger.warning("crypto catalog unavailable exchange=%s type=%s: %s", exchange_id, market_type, e)
                contexts.append({
                    "exchange": exchange_id,
                    "market_type": market_type,
                    "ok": False,
                    "rows": 0,
                    "error": str(e),
                })
    return _unique_rows(rows), contexts


def fetch_crypto_symbols() -> List[SymbolMasterRow]:
    """Fetch all active USDT spot and swap instruments from six venues."""
    rows, _ = fetch_crypto_symbols_with_diagnostics()
    return rows


def fetch_forex_symbols() -> List[SymbolMasterRow]:
    """Return supported forex and metals symbols."""
    return _unique_rows(_static_rows("Forex"))


def fetch_futures_symbols() -> List[SymbolMasterRow]:
    """Return supported traditional futures symbols."""
    return _unique_rows(_static_rows("Futures"))


def fetch_moex_symbols() -> List[SymbolMasterRow]:
    """Fetch MOEX TQBR shares, with a static blue-chip fallback."""
    rows = _static_rows("MOEX")
    try:
        resp = requests.get(
            "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json",
            params={"iss.meta": "off"},
            timeout=20,
            headers={"User-Agent": "QuantDinger/1.0"},
        )
        resp.raise_for_status()
        data = resp.json().get("securities", {})
        columns = data.get("columns") or []
        for values in data.get("data") or []:
            item = dict(zip(columns, values))
            symbol = _clean_symbol(item.get("SECID"))
            name = _clean_text(item.get("SECNAME") or item.get("SHORTNAME"))
            if symbol and name:
                rows.append(SymbolMasterRow("MOEX", symbol, name, "MOEX", "RUB"))
    except Exception as e:
        logger.warning("moex symbol source unavailable, using static fallback: %s", e)
    return _unique_rows(rows)


FETCHERS = {
    "CNStock": fetch_cn_stock_symbols,
    "HKStock": fetch_hk_stock_symbols,
    "USStock": fetch_us_stock_symbols,
    "Crypto": fetch_crypto_symbols,
    "Forex": fetch_forex_symbols,
    "Futures": fetch_futures_symbols,
    "MOEX": fetch_moex_symbols,
}


def upsert_symbol_master(rows: Sequence[SymbolMasterRow]) -> int:
    """Upsert rows while preserving curated hot flags and sort order."""
    if not rows:
        return 0
    with get_db_connection() as db:
        cur = db.cursor()
        count = 0
        crypto_contexts = {
            (row.exchange, row.market_type)
            for row in rows
            if row.market == "Crypto" and row.exchange
        }
        for exchange_id, market_type in crypto_contexts:
            cur.execute(
                "UPDATE qd_market_symbols SET is_active = 0 WHERE market = 'Crypto' AND exchange = ? AND market_type = ?",
                (exchange_id, market_type),
            )
        for row in rows:
            asset_class = row.asset_class or _default_asset_class(row.market)
            cur.execute(
                """
                INSERT INTO qd_market_symbols
                    (market, symbol, name, exchange, currency, market_type, instrument_id, settle_currency, asset_class,
                     is_active, is_hot, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0)
                ON CONFLICT (market, symbol, exchange, market_type, instrument_id) DO UPDATE
                  SET name = EXCLUDED.name,
                      exchange = COALESCE(NULLIF(EXCLUDED.exchange, ''), qd_market_symbols.exchange),
                      currency = COALESCE(NULLIF(EXCLUDED.currency, ''), qd_market_symbols.currency),
                      settle_currency = COALESCE(NULLIF(EXCLUDED.settle_currency, ''), qd_market_symbols.settle_currency),
                      asset_class = EXCLUDED.asset_class,
                      is_active = 1
                """,
                (
                    row.market, row.symbol, row.name, row.exchange, row.currency,
                    row.market_type, row.instrument_id, row.settle_currency, asset_class,
                ),
            )
            count += 1
        db.commit()
        cur.close()
        return count


def _default_asset_class(market: str) -> str:
    return {
        "Crypto": "crypto",
        "Forex": "forex",
        "Futures": "futures",
    }.get(str(market or ""), "equity")


def sync_symbol_master(markets: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, object]]:
    """Fetch and upsert local symbol master data for the requested markets."""
    selected = list(markets or FETCHERS.keys())
    stats: Dict[str, Dict[str, object]] = {}
    for market in selected:
        fetcher = FETCHERS.get(market)
        if not fetcher:
            stats[market] = {"ok": False, "error": "unsupported market", "rows": 0}
            continue
        try:
            rows = fetcher()
            written = upsert_symbol_master(rows)
            stats[market] = {"ok": True, "rows": len(rows), "upserted": written}
        except Exception as e:
            logger.warning("symbol master sync failed market=%s: %s", market, e)
            stats[market] = {"ok": False, "error": str(e), "rows": 0}
    return stats
