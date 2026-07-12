"""Refresh versioned current-universe snapshots from public sources."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.symbol_master_sync import SymbolMasterRow, upsert_symbol_master
from app.utils.db import get_db_connection


SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
NASDAQ100_URL = "https://raw.githubusercontent.com/Gary-Strauss/NASDAQ100_Constituents/master/data/nasdaq100_constituents.csv"
COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
HSI_FACTSHEET_BASE = "https://www.hsi.com.hk/static/uploads/contents/en/dl_centre/factsheets"

HK_FACTSHEETS = {
    "hk_hsi_core50": ("hsie", 50),
    "hk_tech30": ("hsteche", 30),
    "hk_china_enterprises50": ("hsceie", 50),
    "hk_high_dividend50": ("hshdyie", 50),
}

HK_INDUSTRIES = (
    "Properties & Construction",
    "Consumer Discretionary",
    "Information Technology",
    "Consumer Staples",
    "Telecommunications",
    "Conglomerates",
    "Healthcare",
    "Financials",
    "Industrials",
    "Materials",
    "Utilities",
    "Energy",
)


def _csv_rows(url: str) -> list[dict]:
    response = requests.get(url, timeout=30, headers={"User-Agent": "QuantDinger/4.0"})
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text)))


def hk_factsheet(factsheet_code: str) -> list[dict]:
    url = f"{HSI_FACTSHEET_BASE}/{factsheet_code}.pdf"
    response = requests.get(url, timeout=45, headers={"User-Agent": "QuantDinger/4.0"})
    response.raise_for_status()
    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _parse_hk_factsheet_text(text, factsheet_code)


def _parse_hk_factsheet_text(text: str, factsheet_code: str) -> list[dict]:
    section = text.split("CONSTITUENTS", 1)[-1].split("Total 100.00", 1)[0]
    rows = []
    pattern = re.compile(r"^(\d{4})\s+([A-Z0-9]{12})\s+(.+?)\s+(\d+\.\d+)\s*$")
    for line in section.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        symbol, isin, body, raw_weight = match.groups()
        symbol = symbol.zfill(5)
        industry = next((value for value in HK_INDUSTRIES if f" {value} " in f" {body} "), "")
        if not industry:
            continue
        name, share_type = body.split(industry, 1)
        rows.append({
            "market": "HKStock",
            "symbol": symbol,
            "name": name.strip(),
            "rank": len(rows) + 1,
            "weight": float(raw_weight) / 100.0,
            "metadata": {
                "isin": isin,
                "industry": industry,
                "share_type": share_type.strip(),
                "factsheet_code": factsheet_code,
            },
        })
    return rows


def sp500() -> list[dict]:
    return [
        {
            "market": "USStock",
            "symbol": str(row.get("Symbol") or "").strip().upper(),
            "name": str(row.get("Security") or "").strip(),
            "rank": index,
            "metadata": {
                "sector": row.get("GICS Sector") or "",
                "sub_industry": row.get("GICS Sub-Industry") or "",
                "headquarters": row.get("Headquarters Location") or "",
                "date_added": row.get("Date added") or "",
                "cik": row.get("CIK") or "",
            },
        }
        for index, row in enumerate(_csv_rows(SP500_URL), start=1)
        if row.get("Symbol")
    ]


def nasdaq100() -> list[dict]:
    return [
        {
            "market": "USStock",
            "symbol": str(row.get("Ticker") or "").strip().upper(),
            "name": str(row.get("Company") or "").strip(),
            "rank": index,
            "metadata": {
                "sector": row.get("GICS_Sector") or "",
                "sub_industry": row.get("GICS_Sub_Industry") or "",
            },
        }
        for index, row in enumerate(_csv_rows(NASDAQ100_URL), start=1)
        if row.get("Ticker")
    ]


def csi(index_code: str) -> list[dict]:
    import akshare as ak  # type: ignore

    frame = ak.index_stock_cons_weight_csindex(symbol=index_code)
    rows = []
    for index, item in enumerate(frame.to_dict("records"), start=1):
        symbol = str(item.get("品种代码") or item.get("成分券代码") or item.get("代码") or "").strip().zfill(6)
        name = str(item.get("品种名称") or item.get("成分券名称") or item.get("名称") or "").strip()
        if symbol.isdigit() and len(symbol) == 6:
            raw_weight = item.get("权重")
            weight = float(raw_weight) / 100.0 if raw_weight not in (None, "") else None
            rows.append({
                "market": "CNStock",
                "symbol": symbol,
                "name": name,
                "rank": index,
                "weight": weight,
                "metadata": {"exchange": item.get("交易所") or ""},
            })
    return rows


def crypto_top100() -> list[dict]:
    response = requests.get(
        COINGECKO_URL,
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 100,
            "page": 1,
            "sparkline": "false",
        },
        timeout=30,
        headers={"User-Agent": "QuantDinger/4.0"},
    )
    response.raise_for_status()
    rows = []
    seen = set()
    for item in response.json():
        symbol = f"{str(item.get('symbol') or '').upper()}/USDT"
        if symbol in seen or symbol == "/USDT":
            continue
        seen.add(symbol)
        rows.append({
            "market": "Crypto",
            "symbol": symbol,
            "name": str(item.get("name") or ""),
            "rank": int(item.get("market_cap_rank") or len(rows) + 1),
            "metadata": {
                "coingecko_id": item.get("id") or "",
                "market_cap_usd": item.get("market_cap"),
                "circulating_supply": item.get("circulating_supply"),
                "total_volume_usd": item.get("total_volume"),
            },
        })
    return rows


def symbol_master_etfs(market: str) -> list[dict]:
    """Build an ETF snapshot from the synchronized symbol master."""
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT market, symbol, name
            FROM qd_market_symbols
            WHERE market = ? AND is_active = 1 AND is_hot = 1 AND asset_class = 'etf'
            ORDER BY sort_order DESC, symbol
            """,
            (market,),
        )
        rows = cur.fetchall() or []
        cur.close()
    return [
        {
            "market": str(row.get("market") or market),
            "symbol": str(row.get("symbol") or "").strip().upper(),
            "name": str(row.get("name") or "").strip(),
            "rank": index,
            "metadata": {"source": "symbol_master", "asset_class": "etf"},
        }
        for index, row in enumerate(rows, start=1)
        if row.get("symbol")
    ]


LOADERS = {
    "sp500": sp500,
    "nasdaq100": nasdaq100,
    "csi300": lambda: csi("000300"),
    "csi500": lambda: csi("000905"),
    "crypto_top100": crypto_top100,
    "hk_etf": lambda: symbol_master_etfs("HKStock"),
    "us_etf": lambda: symbol_master_etfs("USStock"),
    **{
        code: (lambda factsheet_code=factsheet_code: hk_factsheet(factsheet_code))
        for code, (factsheet_code, _count) in HK_FACTSHEETS.items()
    },
}

SOURCE_METADATA = {
    "sp500": {"url": SP500_URL, "license": "ODC-PDDL", "snapshot_only": True},
    "nasdaq100": {"url": NASDAQ100_URL, "license": "MIT scraper; source data CC BY-SA", "snapshot_only": True},
    "csi300": {"url": "https://www.csindex.com.cn/", "adapter": "AKShare index_stock_cons_weight_csindex", "snapshot_only": True},
    "csi500": {"url": "https://www.csindex.com.cn/", "adapter": "AKShare index_stock_cons_weight_csindex", "snapshot_only": True},
    "crypto_top100": {"url": COINGECKO_URL, "snapshot_only": True},
    "hk_etf": {"adapter": "symbol_master", "market": "HKStock", "asset_class": "etf", "snapshot_only": True},
    "us_etf": {"adapter": "symbol_master", "market": "USStock", "asset_class": "etf", "snapshot_only": True},
    **{
        code: {
            "url": f"{HSI_FACTSHEET_BASE}/{factsheet_code}.pdf",
            "publisher": "Hang Seng Indexes Company Limited",
            "snapshot_only": True,
        }
        for code, (factsheet_code, _count) in HK_FACTSHEETS.items()
    },
}


def apply_snapshot(code: str, members: list[dict], as_of: date, *, dry_run: bool = False) -> dict:
    clean = {item["symbol"]: item for item in members if item.get("symbol")}
    if dry_run:
        return {"code": code, "members": len(clean), "dry_run": True}
    hk_rows = [
        SymbolMasterRow(
            "HKStock", item["symbol"], item.get("name") or "", "HKEX", "HKD",
            asset_class="equity",
        )
        for item in clean.values()
        if item.get("market") == "HKStock"
    ]
    if hk_rows:
        upsert_symbol_master(hk_rows)
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute("SELECT id FROM qd_universes WHERE code = ? AND is_system = TRUE", (code,))
        universe = cur.fetchone() or {}
        universe_id = int(universe.get("id") or 0)
        if not universe_id:
            raise RuntimeError(f"unknown system universe: {code}")
        cur.execute(
            "SELECT symbol, valid_from FROM qd_universe_members WHERE universe_id = ? AND valid_to IS NULL",
            (universe_id,),
        )
        active_rows = cur.fetchall() or []
        active = {str(row.get("symbol") or "") for row in active_rows}
        active_from = {str(row.get("symbol") or ""): row.get("valid_from") for row in active_rows}
        removed = active - set(clean)
        if removed:
            same_day = [symbol for symbol in removed if active_from.get(symbol) and active_from[symbol] >= as_of]
            historical = sorted(removed - set(same_day))
            if same_day:
                cur.execute(
                    "DELETE FROM qd_universe_members WHERE universe_id = ? AND valid_to IS NULL AND symbol = ANY(?)",
                    (universe_id, sorted(same_day)),
                )
            if historical:
                cur.execute(
                    "UPDATE qd_universe_members SET valid_to = ? WHERE universe_id = ? AND valid_to IS NULL AND symbol = ANY(?)",
                    (as_of, universe_id, historical),
                )
        for symbol, item in clean.items():
            metadata = json.dumps(item.get("metadata") or {}, ensure_ascii=False)
            if symbol in active:
                cur.execute(
                    """
                    UPDATE qd_universe_members
                    SET name = ?, member_weight = ?, member_rank = ?, metadata_json = ?, source_version = ?
                    WHERE universe_id = ? AND symbol = ? AND valid_to IS NULL
                    """,
                    (item.get("name") or "", item.get("weight"), item.get("rank"), metadata, as_of.isoformat(), universe_id, symbol),
                )
                continue
            cur.execute(
                """
                INSERT INTO qd_universe_members
                  (universe_id, market, symbol, name, market_type, valid_from,
                   member_weight, member_rank, source_version, metadata_json)
                VALUES (?, ?, ?, ?, 'spot', ?, ?, ?, ?, ?)
                """,
                (
                    universe_id, item.get("market") or "", symbol, item.get("name") or "",
                    as_of, item.get("weight"), item.get("rank"), as_of.isoformat(), metadata,
                ),
            )
        universe_metadata = json.dumps(
            {**SOURCE_METADATA.get(code, {}), "snapshot_as_of": as_of.isoformat()},
            ensure_ascii=False,
        )
        cur.execute(
            """
            UPDATE qd_universes
            SET status = 'active', source = 'public_snapshot', metadata_json = ?, updated_at = NOW()
            WHERE id = ?
            """,
            (universe_metadata, universe_id),
        )
        db.commit()
        cur.close()
    return {"code": code, "members": len(clean), "added": len(set(clean) - active), "removed": len(removed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universes", default=",".join(LOADERS))
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    as_of = date.fromisoformat(args.as_of)
    results = []
    for code in [item.strip() for item in args.universes.split(",") if item.strip()]:
        loader = LOADERS.get(code)
        if loader is None:
            raise RuntimeError(f"unsupported universe: {code}")
        members = loader()
        expected = {
            "csi300": (300, 300), "csi500": (500, 500), "sp500": (500, 510),
            "nasdaq100": (100, 102), "crypto_top100": (95, 100),
            "hk_etf": (1, 1000), "us_etf": (1, 1000),
            **{code: (count, count) for code, (_factsheet, count) in HK_FACTSHEETS.items()},
        }
        minimum, maximum = expected[code]
        if not minimum <= len({item.get("symbol") for item in members}) <= maximum:
            raise RuntimeError(f"{code} member count failed validation: {len(members)}")
        results.append(apply_snapshot(code, members, as_of, dry_run=args.dry_run))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
