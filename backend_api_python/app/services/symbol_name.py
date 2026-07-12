"""
Symbol/company name resolver for local-only mode.

Goal:
- When a symbol is not present in our seed list, try to resolve a human-readable name
  from public data sources, then persist it into watchlist records.

Notes:
- For US stocks we use Finnhub (if configured) or yfinance.
- For Crypto/Forex/Futures we provide best-effort fallbacks.
"""

from __future__ import annotations

from typing import Optional

import re
import os

import requests

from app.utils.logger import get_logger
from app.utils.db import get_db_connection
from app.data.market_symbols_seed import get_symbol_name as seed_get_symbol_name
from app.data_sources.tencent import normalize_cn_code, normalize_hk_code

logger = get_logger(__name__)


# Markets allowed in the seed cache. Mirrors VALID_MARKETS in routes/market.py.
# Kept here as a local constant to avoid importing a routes module from a
# service module (circular-import hazard).
_CACHEABLE_MARKETS = frozenset({
    'Crypto', 'USStock', 'CNStock', 'HKStock', 'Forex', 'Futures', 'MOEX',
})


def persist_seed_name(market: str, symbol: str, name: str) -> None:
    """Self-learning seed: upsert a resolved (market, symbol, name) tuple into
    ``qd_market_symbols`` so the next lookup for the same symbol can short-
    circuit through the local DB instead of hitting yfinance / Finnhub /
    Tencent quote / MOEX ISS / etc.

    This is invoked by :func:`resolve_symbol_name` after a successful external
    resolution. It is intentionally best-effort:

    - Skips when ``name`` is empty or simply echoes ``symbol`` (Crypto/Forex/
      Futures resolvers commonly fall back to returning the ticker, which is
      useless to cache).
    - Skips when ``market`` is outside the canonical set (legacy 'AShare',
      typos, etc.).
    - Swallows any DB error so a flaky write can never poison a successful
      resolve.

    Existing rows whose ``name`` is already a real string are left untouched;
    we only fill in placeholders so we don't overwrite curated seed data.
    """
    if market not in _CACHEABLE_MARKETS:
        return
    sym = (symbol or '').strip().upper()
    nm = (name or '').strip()
    if not sym or not nm or nm.upper() == sym:
        return
    try:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_market_symbols (
                    market, symbol, name, exchange, market_type, instrument_id,
                    is_active, is_hot, sort_order
                )
                VALUES (?, ?, ?, '', 'spot', '', 1, 0, 0)
                ON CONFLICT (market, symbol, exchange, market_type, instrument_id) DO UPDATE
                  SET name = EXCLUDED.name
                  WHERE qd_market_symbols.name IS NULL
                     OR qd_market_symbols.name = ''
                     OR qd_market_symbols.name = qd_market_symbols.symbol
                """,
                (market, sym, nm),
            )
            db.commit()
            cur.close()
    except Exception as e:
        logger.debug("symbol-name seed persist failed for %s:%s: %s", market, symbol, e)


# Common crypto quote currencies, ordered by how aggressively we want to detect
# them when a user types a fused ticker like "BTCUSDT". USDT first because it
# is by far the most common quote on the exchanges we integrate against.
_COMMON_CRYPTO_QUOTES = (
    'USDT', 'USDC', 'BUSD', 'USD', 'EUR', 'GBP', 'BTC', 'ETH', 'BNB',
)


def normalize_crypto_symbol(symbol: str) -> str:
    """Canonicalise a crypto symbol to ``BASE/QUOTE`` form, defaulting to
    ``BASE/USDT`` when no quote is supplied.

    This is the single source of truth for the rule "in QuantDinger, a Crypto
    symbol is always stored as ``BASE/QUOTE``". We deliberately keep it pure
    (no ccxt / network calls) so it can be invoked from any layer — route
    handlers, services, migrations — without dragging in heavy dependencies.

    Inputs handled (all case-insensitive):

    - ``BTC/USDT``       → ``BTC/USDT`` (already canonical)
    - ``BTC/USDT:USDT``  → ``BTC/USDT`` (CCXT swap suffix stripped)
    - ``btc/usdt``       → ``BTC/USDT`` (upper-cased)
    - ``BTC``            → ``BTC/USDT`` (defaulted)
    - ``BTCUSDT``        → ``BTC/USDT`` (fused → split on known quote)
    - ``BTCUSD``         → ``BTC/USD``  (fused → split on known quote)
    - ``""`` / ``None``  → ``""``

    The downstream :class:`CryptoDataSource` has its own runtime normaliser
    that does broadly the same thing; calling this at write-time means the
    DB always holds the canonical form so UI, search, dedupe and joins all
    see the same string regardless of how the user typed it.
    """
    if not symbol:
        return ''
    sym = symbol.strip()
    if not sym:
        return ''

    # CCXT swap symbols look like ``BTC/USDT:USDT``. The trailing ``:QUOTE``
    # marks settlement currency; for storage we collapse to the spot pair.
    if ':' in sym:
        sym = sym.split(':', 1)[0]

    sym = sym.upper()

    if '/' in sym:
        parts = sym.split('/', 1)
        base = parts[0].strip()
        quote = parts[1].strip() if len(parts) > 1 else ''
        if base and quote:
            return f"{base}/{quote}"
        if base:
            return f"{base}/USDT"
        return sym  # malformed (e.g. ``/USDT``); let downstream reject it

    # Fused tickers like ``BTCUSDT``: try to peel off a known quote suffix.
    for quote in _COMMON_CRYPTO_QUOTES:
        if sym.endswith(quote) and len(sym) > len(quote):
            base = sym[:-len(quote)]
            if base:
                return f"{base}/{quote}"

    # Bare base ticker (``BTC``, ``ETH``, ``PI``...) — default to USDT pair.
    return f"{sym}/USDT"


def _normalize_symbol_for_market(market: str, symbol: str) -> str:
    m = (market or '').strip()
    s = (symbol or '').strip().upper()
    if m == 'CNStock':
        return normalize_cn_code(s)
    if m == 'HKStock':
        return normalize_hk_code(s)
    if m == 'Crypto':
        return normalize_crypto_symbol(s)
    return s


def _resolve_name_from_yfinance(symbol: str) -> Optional[str]:
    """
    Best-effort company name via yfinance.
    """
    def _try_one(sym: str) -> Optional[str]:
        import yfinance as yf
        t = yf.Ticker(sym)
        info = getattr(t, "info", None)
        if not isinstance(info, dict) or not info:
            return None
        name = (info.get('longName') or info.get('shortName') or '').strip()
        return name if name else None
    try:
        # yfinance uses '-' for some tickers (e.g. BRK-B) while users may input 'BRK.B'
        out = _try_one(symbol)
        if out:
            return out
        if '.' in symbol:
            out = _try_one(symbol.replace('.', '-'))
            if out:
                return out
        return None
    except Exception as e:
        logger.debug(f"yfinance name resolve failed: {symbol}: {e}")
        return None


def _resolve_name_from_finnhub(symbol: str) -> Optional[str]:
    """
    Finnhub company profile (requires FINNHUB_API_KEY).
    https://finnhub.io/docs/api/company-profile2
    """
    try:
        api_key = (os.getenv('FINNHUB_API_KEY') or '').strip()
        if not api_key:
            return None
        url = "https://finnhub.io/api/v1/stock/profile2"
        resp = requests.get(url, params={"symbol": symbol, "token": api_key}, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json() if resp.text else {}
        if not isinstance(data, dict) or not data:
            return None
        name = (data.get("name") or data.get("ticker") or '').strip()
        return name if name else None
    except Exception as e:
        logger.debug(f"Finnhub name resolve failed: {symbol}: {e}")
        return None


def resolve_symbol_name(market: str, symbol: str) -> Optional[str]:
    """
    Resolve a display name for a symbol.
    Priority:
    1) Seed mapping (fast, offline)
    2) Market-specific public sources
    3) Reasonable fallback (None)
    """
    m = (market or '').strip()
    s = _normalize_symbol_for_market(m, symbol)
    if not m or not s:
        return None

    # 1) Seed (already in our DB — nothing to learn, just return).
    seed = seed_get_symbol_name(m, s)
    if seed:
        return seed

    # 2) Market-specific external resolution. Every successful external hit is
    # written back to the seed table so the next request for the same symbol
    # can short-circuit through step 1 instead of paying for the network call
    # again. Writes are best-effort (failures swallowed inside persist_seed_name).
    if m == 'USStock':
        ext = _resolve_name_from_finnhub(s) or _resolve_name_from_yfinance(s)
        if ext:
            persist_seed_name(m, s, ext)
        return ext

    if m in ('CNStock', 'HKStock'):
        try:
            from app.data_sources.tencent import fetch_quote
            parts = fetch_quote(s)
            if parts and len(parts) > 1 and parts[1]:
                ext = str(parts[1]).strip()
                if ext:
                    persist_seed_name(m, s, ext)
                    return ext
        except Exception:
            pass
        ext = _resolve_name_from_yfinance(s)
        if ext:
            persist_seed_name(m, s, ext)
        return ext

    # MOEX (Russian equities): try MOEX ISS securities description for a name.
    if m == 'MOEX':
        try:
            from app.data_sources.moex import MOEXDataSource, ISS_BASE
            sym = MOEXDataSource._normalize_symbol(s)
            url = f"{ISS_BASE}/securities/{sym}.json"
            resp = requests.get(url, params={"iss.meta": "off"}, timeout=8)
            if resp.status_code == 200:
                payload = resp.json() or {}
                desc = (payload.get('description') or {})
                cols = desc.get('columns') or []
                data = desc.get('data') or []
                if cols and data:
                    name_idx = cols.index('name') if 'name' in cols else None
                    val_idx = cols.index('value') if 'value' in cols else None
                    if name_idx is not None and val_idx is not None:
                        for row in data:
                            if row[name_idx] in ('SHORTNAME', 'SECNAME'):
                                v = (row[val_idx] or '').strip()
                                if v:
                                    persist_seed_name(m, s, v)
                                    return v
        except Exception as e:
            logger.debug(f"MOEX name resolve failed: {symbol}: {e}")
        return s

    # Crypto/Forex/Futures: fall back to returning the symbol itself. We
    # intentionally do NOT cache these — persist_seed_name skips name==symbol
    # anyway, but being explicit here documents that there's nothing to learn.
    if m == 'Crypto':
        if '/' in s:
            base = s.split('/')[0].strip()
            return base if base else None
        return s

    if m == 'Forex':
        return s

    if m == 'Futures':
        return s

    return None
