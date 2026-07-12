"""Watchlist business logic."""

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Optional

from app.data.market_symbols_seed import get_symbol_name as seed_get_symbol_name
from app.services.market.symbol_search import find_available_crypto_symbol, find_market_symbol
from app.services.symbol_name import normalize_crypto_symbol, persist_seed_name, resolve_symbol_name
from app.services.market_context import MarketContext, SUPPORTED_CRYPTO_EXCHANGE_IDS
from app.utils.db import get_db_connection
from app.utils.logger import get_logger

logger = get_logger(__name__)

VALID_MARKETS = frozenset({
    "Crypto", "USStock", "CNStock", "HKStock", "Forex", "Futures", "MOEX",
})
CN_A_SHARE_PATTERN = re.compile(r"^\d{6}$")

_name_resolve_executor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="watchlist-name-resolve",
)


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper()


def validate_watchlist_pair(market: str, symbol: str) -> Optional[str]:
    """Validate a market/symbol pair before persisting it."""
    if market not in VALID_MARKETS:
        return f"Unsupported market '{market}'. Must be one of: {', '.join(sorted(VALID_MARKETS))}"
    if not symbol:
        return "Empty symbol"
    if CN_A_SHARE_PATTERN.match(symbol) and market != "CNStock":
        return f"Symbol '{symbol}' looks like a Chinese A-share code; market must be CNStock, not {market}"
    if symbol.endswith(".HK") and market != "HKStock":
        return f"Symbol '{symbol}' looks like a Hong Kong stock; market must be HKStock, not {market}"
    if market == "Crypto" and "/" not in symbol:
        return f"Crypto symbol '{symbol}' must be a BASE/QUOTE pair (e.g. BTC/USDT)."
    return None


def list_watchlist(user_id: int) -> list:
    """Return one asset-level row per market/symbol pair."""
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT id, market, symbol, name, exchange_id, market_type,
                   instrument_id, settle_currency
            FROM qd_watchlist
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        )
        stored_rows = cur.fetchall() or []
        rows = []
        seen = set()
        for row in stored_rows:
            asset_key = (row.get("market"), row.get("symbol"))
            if asset_key in seen:
                continue
            seen.add(asset_key)
            row.update({
                "exchange_id": "",
                "market_type": "",
                "instrument_id": "",
            })
            _backfill_row_name(cur, user_id, row)
            rows.append(row)
        db.commit()
        cur.close()
    return rows


def add_watchlist_item(
    user_id: int,
    market: str,
    raw_symbol: str,
    name_in: str = "",
    *,
    exchange_id: str = "",
    market_type: str = "",
    instrument_id: str = "",
    settle_currency: str = "",
) -> tuple[bool, str]:
    """Validate and persist a watchlist item."""
    market = (market or "").strip()
    symbol = normalize_symbol(raw_symbol)
    if not market or not symbol:
        return False, "Missing market or symbol"

    if market == "Crypto":
        symbol = normalize_crypto_symbol(symbol)
    context = MarketContext.from_mapping({
        "market": market,
        "symbol": symbol,
        "exchange_id": exchange_id,
        "market_type": market_type,
        "instrument_id": instrument_id,
        "settle_currency": settle_currency,
    })
    if market == "Crypto" and context.exchange_id not in SUPPORTED_CRYPTO_EXCHANGE_IDS:
        return False, f"Unsupported crypto exchange: {context.exchange_id}"

    validation_err = validate_watchlist_pair(market, symbol)
    if validation_err:
        logger.info("Rejecting watchlist add for user %s: %s", user_id, validation_err)
        return False, validation_err

    if market == "Crypto":
        matched = find_available_crypto_symbol(
            symbol,
            preferred_exchange_id=context.exchange_id,
            preferred_market_type=context.market_type,
        )
    else:
        matched = find_market_symbol(
            market,
            symbol,
            exchange_id=context.exchange_id,
            market_type=context.market_type,
        )
    if not matched:
        err = (
            f"Symbol '{symbol}' not found on {market}. "
            "Please verify the ticker and market, or pick from search results."
        )
        logger.info("Rejecting watchlist add for user %s: %s", user_id, err)
        return False, err

    resolved = (
        (matched.get("name") or "").strip()
        or resolve_symbol_name_bounded(market, symbol)
        or seed_get_symbol_name(market, symbol)
    )
    name = (name_in or "").strip() or resolved or symbol
    persist_seed_name(market, symbol, name)
    settle_currency = str((matched or {}).get("settle_currency") or context.settle_currency or "").strip().upper()

    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            "DELETE FROM qd_watchlist WHERE user_id = ? AND market = ? AND symbol = ?",
            (user_id, market, symbol),
        )
        cur.execute(
            """
            INSERT INTO qd_watchlist (
                user_id, market, symbol, name, exchange_id, market_type,
                instrument_id, settle_currency, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())
            ON CONFLICT(user_id, market, symbol, exchange_id, market_type, instrument_id) DO UPDATE SET
                name = excluded.name,
                settle_currency = excluded.settle_currency,
                updated_at = NOW()
            """,
            (
                user_id,
                market,
                symbol,
                name,
                "",
                "spot",
                "",
                settle_currency,
            ),
        )
        db.commit()
        cur.close()
    return True, "success"


def remove_watchlist_item(
    user_id: int,
    market: str,
    raw_symbol: str,
    *,
    exchange_id: str = "",
    market_type: str = "",
    instrument_id: str = "",
) -> bool:
    """Remove an asset-level watchlist item."""
    market = (market or "").strip()
    raw_symbol = normalize_symbol(raw_symbol)
    canonical_symbol = normalize_crypto_symbol(raw_symbol) if market == "Crypto" else raw_symbol

    with get_db_connection() as db:
        cur = db.cursor()
        if market:
            cur.execute(
                "DELETE FROM qd_watchlist WHERE user_id = ? AND market = ? AND symbol = ?",
                (user_id, market, canonical_symbol),
            )
            deleted = cur.rowcount or 0
            if deleted == 0 and canonical_symbol != raw_symbol:
                cur.execute(
                    "DELETE FROM qd_watchlist WHERE user_id = ? AND market = ? AND symbol = ?",
                    (user_id, market, raw_symbol),
                )
        else:
            logger.info(
                "remove_watchlist called without market (user=%s, symbol=%s); using legacy symbol-only delete",
                user_id,
                raw_symbol,
            )
            cur.execute(
                "DELETE FROM qd_watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, raw_symbol),
            )
        db.commit()
        cur.close()
    return True


def get_user_watchlist_pairs(user_id: int) -> list:
    """Return market/symbol rows for quote fetching."""
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            SELECT market, symbol, exchange_id, market_type,
                   instrument_id, settle_currency
            FROM qd_watchlist
            WHERE user_id = ?
            """,
            (user_id,),
        )
        rows = cur.fetchall() or []
        cur.close()
    out = []
    seen = set()
    for row in rows:
        asset_key = (row.get("market"), row.get("symbol"))
        if asset_key in seen:
            continue
        seen.add(asset_key)
        out.append({
            "market": row.get("market") or "",
            "symbol": row.get("symbol") or "",
            "exchange_id": "",
            "market_type": "",
            "instrument_id": "",
            "settle_currency": row.get("settle_currency") or "",
        })
    return out


def resolve_symbol_name_bounded(market: str, symbol: str, timeout_sec: float = 4.0) -> Optional[str]:
    """Resolve a display name with a hard wall-clock cap."""
    try:
        future = _name_resolve_executor.submit(resolve_symbol_name, market, symbol)
        return future.result(timeout=timeout_sec)
    except FuturesTimeoutError:
        logger.info(
            "Symbol name resolve timed out after %.1fs for %s:%s",
            timeout_sec,
            market,
            symbol,
        )
        return None
    except Exception as exc:
        logger.debug("Symbol name resolve raised for %s:%s: %s", market, symbol, exc)
        return None


def _backfill_row_name(cur, user_id: int, row: dict) -> None:
    try:
        market = row.get("market")
        symbol = row.get("symbol")
        current_name = (row.get("name") or "").strip()
        if not market or not symbol or (current_name and current_name != symbol):
            return
        resolved = resolve_symbol_name(market, symbol) or seed_get_symbol_name(market, symbol)
        if resolved and resolved != current_name:
            row["name"] = resolved
            cur.execute(
                "UPDATE qd_watchlist SET name = ?, updated_at = NOW() WHERE user_id = ? AND market = ? AND symbol = ?",
                (resolved, user_id, market, symbol),
            )
    except Exception:
        return

