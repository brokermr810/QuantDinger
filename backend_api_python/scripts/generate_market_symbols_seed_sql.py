#!/usr/bin/env python3
"""Generate an idempotent SQL seed file for qd_market_symbols."""

from __future__ import annotations

import argparse
import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple


Row = Tuple[str, str, str, str, str]


STATIC_MARKET_ROWS: List[Row] = [
    ("HKStock", "00763", "\u4e2d\u5174\u901a\u8baf", "HKEX", "HKD"),
    ("CNStock", "000063", "\u4e2d\u5174\u901a\u8baf", "CN", "CNY"),
    ("HKStock", "01810", "\u5c0f\u7c73\u96c6\u56e2-W", "HKEX", "HKD"),
    ("HKStock", "00700", "\u817e\u8baf\u63a7\u80a1", "HKEX", "HKD"),
    ("HKStock", "09988", "\u963f\u91cc\u5df4\u5df4-W", "HKEX", "HKD"),
    ("USStock", "MSFT", "Microsoft Corporation", "NASDAQ", "USD"),
    ("USStock", "GOOGL", "Alphabet Inc.", "NASDAQ", "USD"),
    ("USStock", "AAPL", "Apple Inc.", "NASDAQ", "USD"),
    ("USStock", "TSLA", "Tesla Inc.", "NASDAQ", "USD"),
    ("USStock", "NVDA", "NVIDIA Corporation", "NASDAQ", "USD"),
    ("Crypto", "BTC/USDT", "Bitcoin", "binance", "USDT"),
    ("Crypto", "ETH/USDT", "Ethereum", "binance", "USDT"),
    ("Crypto", "BNB/USDT", "BNB", "binance", "USDT"),
    ("Crypto", "SOL/USDT", "Solana", "binance", "USDT"),
    ("Crypto", "XRP/USDT", "XRP", "binance", "USDT"),
    ("Crypto", "DOGE/USDT", "Dogecoin", "binance", "USDT"),
    ("Crypto", "ADA/USDT", "Cardano", "binance", "USDT"),
    ("Crypto", "AVAX/USDT", "Avalanche", "binance", "USDT"),
    ("Crypto", "LINK/USDT", "Chainlink", "binance", "USDT"),
    ("Crypto", "DOT/USDT", "Polkadot", "binance", "USDT"),
    ("Crypto", "TRX/USDT", "TRON", "binance", "USDT"),
    ("Crypto", "TON/USDT", "Toncoin", "binance", "USDT"),
    ("Crypto", "LTC/USDT", "Litecoin", "binance", "USDT"),
    ("Crypto", "BCH/USDT", "Bitcoin Cash", "binance", "USDT"),
    ("Crypto", "UNI/USDT", "Uniswap", "binance", "USDT"),
    ("Crypto", "AAVE/USDT", "Aave", "binance", "USDT"),
    ("Crypto", "MATIC/USDT", "Polygon", "binance", "USDT"),
    ("Crypto", "NEAR/USDT", "NEAR Protocol", "binance", "USDT"),
    ("Crypto", "APT/USDT", "Aptos", "binance", "USDT"),
    ("Crypto", "ARB/USDT", "Arbitrum", "binance", "USDT"),
    ("Crypto", "OP/USDT", "Optimism", "binance", "USDT"),
    ("Crypto", "FIL/USDT", "Filecoin", "binance", "USDT"),
    ("Crypto", "ETC/USDT", "Ethereum Classic", "binance", "USDT"),
    ("Crypto", "ATOM/USDT", "Cosmos", "binance", "USDT"),
    ("Crypto", "INJ/USDT", "Injective", "binance", "USDT"),
    ("Crypto", "SUI/USDT", "Sui", "binance", "USDT"),
    ("Crypto", "SEI/USDT", "Sei", "binance", "USDT"),
    ("Crypto", "PEPE/USDT", "Pepe", "binance", "USDT"),
    ("Crypto", "SHIB/USDT", "Shiba Inu", "binance", "USDT"),
    ("Crypto", "WLD/USDT", "Worldcoin", "binance", "USDT"),
    ("Forex", "XAUUSD", "Gold Spot", "TwelveData", "USD"),
    ("Forex", "XAGUSD", "Silver Spot", "TwelveData", "USD"),
    ("Forex", "EURUSD", "Euro / US Dollar", "TwelveData", "USD"),
    ("Forex", "GBPUSD", "British Pound / US Dollar", "TwelveData", "USD"),
    ("Forex", "USDJPY", "US Dollar / Japanese Yen", "TwelveData", "JPY"),
    ("Forex", "AUDUSD", "Australian Dollar / US Dollar", "TwelveData", "USD"),
    ("Forex", "USDCAD", "US Dollar / Canadian Dollar", "TwelveData", "CAD"),
    ("Forex", "USDCHF", "US Dollar / Swiss Franc", "TwelveData", "CHF"),
    ("Forex", "NZDUSD", "New Zealand Dollar / US Dollar", "TwelveData", "USD"),
    ("Forex", "GBPJPY", "British Pound / Japanese Yen", "TwelveData", "JPY"),
    ("Forex", "EURJPY", "Euro / Japanese Yen", "TwelveData", "JPY"),
    ("Forex", "EURGBP", "Euro / British Pound", "TwelveData", "GBP"),
    ("Forex", "AUDNZD", "Australian Dollar / New Zealand Dollar", "TwelveData", "NZD"),
    ("Forex", "USDCNH", "US Dollar / Offshore Chinese Yuan", "TwelveData", "CNH"),
    ("Futures", "GC", "Gold Futures", "CME", "USD"),
    ("Futures", "SI", "Silver Futures", "CME", "USD"),
    ("Futures", "CL", "Crude Oil WTI Futures", "NYMEX", "USD"),
    ("Futures", "NG", "Natural Gas Futures", "NYMEX", "USD"),
    ("Futures", "HG", "Copper Futures", "COMEX", "USD"),
    ("Futures", "PL", "Platinum Futures", "NYMEX", "USD"),
    ("Futures", "ES", "E-mini S&P 500 Futures", "CME", "USD"),
    ("Futures", "NQ", "E-mini Nasdaq 100 Futures", "CME", "USD"),
    ("Futures", "YM", "E-mini Dow Futures", "CBOT", "USD"),
    ("Futures", "RTY", "E-mini Russell 2000 Futures", "CME", "USD"),
    ("Futures", "ZC", "Corn Futures", "CBOT", "USD"),
    ("Futures", "ZS", "Soybean Futures", "CBOT", "USD"),
    ("Futures", "ZW", "Wheat Futures", "CBOT", "USD"),
    ("MOEX", "SBER", "Sberbank", "MOEX", "RUB"),
    ("MOEX", "GAZP", "Gazprom", "MOEX", "RUB"),
    ("MOEX", "LKOH", "Lukoil", "MOEX", "RUB"),
    ("MOEX", "ROSN", "Rosneft", "MOEX", "RUB"),
    ("MOEX", "GMKN", "Norilsk Nickel", "MOEX", "RUB"),
    ("MOEX", "NVTK", "Novatek", "MOEX", "RUB"),
    ("MOEX", "TATN", "Tatneft", "MOEX", "RUB"),
    ("MOEX", "YDEX", "Yandex", "MOEX", "RUB"),
    ("MOEX", "VTBR", "VTB Bank", "MOEX", "RUB"),
    ("MOEX", "MGNT", "Magnit", "MOEX", "RUB"),
    ("MOEX", "SNGS", "Surgutneftegas", "MOEX", "RUB"),
    ("MOEX", "PLZL", "Polyus", "MOEX", "RUB"),
]


def clean(value: object) -> str:
    return str(value or "").strip()


def repair_mojibake(value: object) -> str:
    text = clean(value)
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


def normalize_hk_symbol(value: object) -> str:
    digits = re.sub(r"[^0-9]", "", clean(value).upper())
    return digits.zfill(5) if digits else ""


def normalize_crypto_symbol(symbol: str) -> str:
    sym = clean(symbol).upper()
    if ":" in sym:
        sym = sym.split(":", 1)[0]
    if "/" in sym:
        base, quote = sym.split("/", 1)
        return f"{base}/{quote}" if base and quote else sym
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if sym.endswith(quote) and len(sym) > len(quote):
            return f"{sym[:-len(quote)]}/{quote}"
    return f"{sym}/USDT" if sym else ""


class Collector:
    def __init__(self) -> None:
        self.rows: List[Row] = []
        self.seen = set()

    def add(self, market: str, symbol: object, name: object, exchange: str = "", currency: str = "") -> None:
        sym = clean(symbol).upper()
        nm = repair_mojibake(name)
        if not market or not sym or not nm:
            return
        key = (market, sym)
        if key in self.seen:
            return
        self.seen.add(key)
        self.rows.append((market, sym, nm, clean(exchange), clean(currency)))


def df_records(df) -> list:
    if df is None:
        return []
    try:
        return df.to_dict("records")
    except Exception:
        return []


def add_static_rows(col: Collector, market: str | None = None) -> None:
    for row in STATIC_MARKET_ROWS:
        if market is None or row[0] == market:
            col.add(*row)


def add_cn_rows(col: Collector) -> None:
    import akshare as ak  # type: ignore

    df = ak.stock_info_a_code_name()
    for rec in df_records(df):
        symbol = clean(rec.get("code") or rec.get("\u4ee3\u7801")).upper()
        name = rec.get("name") or rec.get("\u540d\u79f0")
        if re.fullmatch(r"\d{6}", symbol):
            col.add("CNStock", symbol, name, "CN", "CNY")


def add_hk_rows(col: Collector) -> None:
    if add_hk_rows_hkex(col):
        return
    add_hk_rows_akshare(col)


def add_hk_rows_hkex(col: Collector) -> bool:
    import pandas as pd
    import requests

    resp = requests.get(
        "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx",
        timeout=25,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content), sheet_name=0, header=2)
    before = len(col.rows)
    for rec in df_records(df):
        symbol = normalize_hk_symbol(rec.get("Stock Code"))
        name = rec.get("Name of Securities")
        category = clean(rec.get("Category"))
        currency = clean(rec.get("Trading Currency")) or "HKD"
        if symbol and name and category in {"Equity", "Exchange Traded Products"}:
            col.add("HKStock", symbol, name, "HKEX", currency)
    return len(col.rows) > before


def add_hk_rows_akshare(col: Collector) -> None:
    import akshare as ak  # type: ignore

    df = ak.stock_hk_spot_em()
    for rec in df_records(df):
        symbol = normalize_hk_symbol(rec.get("\u4ee3\u7801") or rec.get("code") or rec.get("symbol"))
        name = rec.get("\u540d\u79f0") or rec.get("name")
        if symbol:
            col.add("HKStock", symbol, name, "HKEX", "HKD")


def read_nasdaq_file(url: str) -> Iterable[dict]:
    import requests

    resp = requests.get(url, timeout=25)
    resp.raise_for_status()
    lines = [line for line in resp.text.splitlines() if line and not line.startswith("File Creation Time")]
    return csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|")


def add_us_rows(col: Collector) -> None:
    for rec in read_nasdaq_file("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"):
        if clean(rec.get("Test Issue")).upper() == "Y":
            continue
        col.add("USStock", rec.get("Symbol"), rec.get("Security Name"), "NASDAQ", "USD")

    exchange_map = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
    for rec in read_nasdaq_file("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"):
        if clean(rec.get("Test Issue")).upper() == "Y":
            continue
        code = clean(rec.get("Exchange")).upper()
        col.add("USStock", rec.get("ACT Symbol"), rec.get("Security Name"), exchange_map.get(code, code), "USD")


def add_crypto_rows(col: Collector) -> None:
    add_static_rows(col, "Crypto")
    import ccxt  # type: ignore

    exchange = ccxt.binance()
    exchange.load_markets()
    for symbol, info in exchange.markets.items():
        if not info.get("active"):
            continue
        base = clean(info.get("base")).upper()
        quote = clean(info.get("quote")).upper()
        if base and quote == "USDT":
            col.add("Crypto", normalize_crypto_symbol(symbol), base, "binance", "USDT")


def add_forex_rows(col: Collector) -> None:
    add_static_rows(col, "Forex")


def add_futures_rows(col: Collector) -> None:
    add_static_rows(col, "Futures")


def add_moex_rows(col: Collector) -> None:
    add_static_rows(col, "MOEX")
    import requests

    resp = requests.get(
        "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json",
        params={"iss.meta": "off"},
        timeout=25,
        headers={"User-Agent": "QuantDinger/1.0"},
    )
    resp.raise_for_status()
    data = resp.json().get("securities", {})
    columns = data.get("columns") or []
    for values in data.get("data") or []:
        rec = dict(zip(columns, values))
        symbol = clean(rec.get("SECID")).upper()
        name = rec.get("SECNAME") or rec.get("SHORTNAME")
        if symbol and name:
            col.add("MOEX", symbol, name, "MOEX", "RUB")


def sql_quote(value: object) -> str:
    return "'" + clean(value).replace("'", "''") + "'"


def build_sql(rows: List[Row], notes: List[str]) -> str:
    rows = sorted(rows, key=lambda r: (r[0], r[1]))
    out = [
        "-- Auto-generated local symbol master seed.",
        f"-- Generated at {datetime.now(timezone.utc).isoformat()}",
        "-- Refresh with: python scripts/generate_market_symbols_seed_sql.py --output migrations/market_symbols_master.sql",
    ]
    for note in notes:
        out.append(f"-- {note}")
    out.extend(["", "INSERT INTO qd_market_symbols (market, symbol, name, exchange, currency, market_type, instrument_id, is_active, is_hot, sort_order) VALUES"])
    values = [
        "  (" + ", ".join([sql_quote(a), sql_quote(b), sql_quote(c), sql_quote(d), sql_quote(e), "'spot'", "''", "1", "0", "0"]) + ")"
        for a, b, c, d, e in rows
    ]
    out.append(",\n".join(values))
    out.extend([
        "ON CONFLICT (market, symbol, exchange, market_type, instrument_id) DO UPDATE",
        "  SET name = EXCLUDED.name,",
        "      exchange = COALESCE(NULLIF(EXCLUDED.exchange, ''), qd_market_symbols.exchange),",
        "      currency = COALESCE(NULLIF(EXCLUDED.currency, ''), qd_market_symbols.currency),",
        "      is_active = 1;",
        "",
    ])
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate market symbol seed SQL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--markets",
        nargs="*",
        default=["CNStock", "HKStock", "USStock", "Crypto", "Forex", "Futures", "MOEX"],
    )
    args = parser.parse_args()

    col = Collector()
    notes: List[str] = []
    for market in ("CNStock", "HKStock", "USStock"):
        add_static_rows(col, market)
    fetchers = {
        "CNStock": add_cn_rows,
        "HKStock": add_hk_rows,
        "USStock": add_us_rows,
        "Crypto": add_crypto_rows,
        "Forex": add_forex_rows,
        "Futures": add_futures_rows,
        "MOEX": add_moex_rows,
    }
    for market in args.markets:
        fetcher = fetchers.get(market)
        if not fetcher:
            notes.append(f"{market}: unsupported")
            continue
        before = len(col.rows)
        try:
            fetcher(col)
            notes.append(f"{market}: {len(col.rows) - before} rows fetched")
        except Exception as exc:
            notes.append(f"{market}: failed ({exc})")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_sql(col.rows, notes), encoding="utf-8")
    print(f"Wrote {len(col.rows)} rows to {args.output}")
    for note in notes:
        print(note)


if __name__ == "__main__":
    main()
