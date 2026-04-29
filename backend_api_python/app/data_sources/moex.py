"""
MOEX (Moscow Exchange) equities data source.

Read-only data source for analysis and backtesting that uses the MOEX ISS public
HTTP API (https://iss.moex.com/iss/reference/). Supports Russian equities listed
on the TQBR board (e.g. SBER, GAZP, LKOH).

Live order placement is intentionally NOT implemented — this source only exposes
historical candles and last-trade ticker data.

ISS candle intervals (minutes):
    1, 10, 60, 24 (=day), 7 (=week), 31 (=month)

QuantDinger timeframes are mapped to the closest ISS interval.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from app.data_sources.base import BaseDataSource, TIMEFRAME_SECONDS
from app.utils.logger import get_logger

logger = get_logger(__name__)


# QuantDinger timeframe -> MOEX ISS candle interval (minutes; 24=day, 7=week, 31=month)
# 5m / 15m / 30m / 4H are not natively offered by ISS; we resample from the
# nearest finer interval (1m for sub-hour, 60m for 4H).
INTERVAL_MAP: Dict[str, int] = {
    '1m': 1,
    '5m': 1,
    '15m': 1,
    '30m': 1,
    '1H': 60,
    '4H': 60,
    '1D': 24,
    '1W': 7,
}

# Native ISS interval set per timeframe -- used to decide whether resampling is needed.
_NATIVE_ISS = {'1m': 1, '1H': 60, '1D': 24, '1W': 7}

ISS_BASE = "https://iss.moex.com/iss"
DEFAULT_BOARD = "TQBR"  # main equities board (T+ settlement)
DEFAULT_ENGINE = "stock"
DEFAULT_MARKET = "shares"
HTTP_TIMEOUT = 15


class MOEXDataSource(BaseDataSource):
    """Moscow Exchange (MOEX) equities — analysis & backtest only."""

    name = "MOEX/iss"

    def __init__(self, board: str = DEFAULT_BOARD):
        self.board = board
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "QuantDinger/MOEX-DataSource"})

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Strip exchange suffixes / whitespace and uppercase. e.g. 'sber.me' -> 'SBER'."""
        if not symbol:
            return ""
        s = str(symbol).strip().upper()
        for suffix in (".ME", ".MOEX", ":MOEX", "@MOEX"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break
        return s

    def _candle_url(self, symbol: str) -> str:
        return (
            f"{ISS_BASE}/engines/{DEFAULT_ENGINE}/markets/{DEFAULT_MARKET}"
            f"/boards/{self.board}/securities/{symbol}/candles.json"
        )

    def _securities_url(self, symbol: str) -> str:
        return (
            f"{ISS_BASE}/engines/{DEFAULT_ENGINE}/markets/{DEFAULT_MARKET}"
            f"/boards/{self.board}/securities/{symbol}.json"
        )

    def _http_get(self, url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            resp = self._session.get(url, params=params, timeout=HTTP_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(f"MOEX ISS HTTP {resp.status_code} for {url}")
                return None
            return resp.json()
        except Exception as e:
            logger.warning(f"MOEX ISS request failed ({url}): {e}")
            return None

    @staticmethod
    def _moex_dt_to_unix(dt_str: str) -> Optional[int]:
        """ISS returns naive Moscow-time timestamps like '2025-01-10 10:00:00'.
        Treat them as Europe/Moscow (UTC+3, no DST since 2014) and convert to Unix UTC seconds.
        """
        if not dt_str:
            return None
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d")
            except ValueError:
                return None
        msk = timezone(timedelta(hours=3))
        return int(dt.replace(tzinfo=msk).timestamp())

    @staticmethod
    def _resample(klines: List[Dict[str, Any]], target_seconds: int) -> List[Dict[str, Any]]:
        """Aggregate a sorted list of finer-interval candles into target_seconds buckets."""
        if not klines or target_seconds <= 0:
            return klines
        out: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        bucket_start = -1
        for k in klines:
            ts = int(k['time'])
            b = ts - (ts % target_seconds)
            if current is None or b != bucket_start:
                if current is not None:
                    out.append(current)
                current = {
                    'time': b,
                    'open': k['open'],
                    'high': k['high'],
                    'low': k['low'],
                    'close': k['close'],
                    'volume': k['volume'],
                }
                bucket_start = b
            else:
                current['high'] = max(current['high'], k['high'])
                current['low'] = min(current['low'], k['low'])
                current['close'] = k['close']
                current['volume'] = round(current['volume'] + k['volume'], 2)
        if current is not None:
            out.append(current)
        return out

    # ------------------------------------------------------------------ public
    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        sym = self._normalize_symbol(symbol)
        if not sym:
            return []

        iss_interval = INTERVAL_MAP.get(timeframe)
        if iss_interval is None:
            logger.warning(f"MOEX: unsupported timeframe {timeframe}, defaulting to 1D")
            iss_interval = 24
            timeframe = '1D'
        target_seconds = TIMEFRAME_SECONDS.get(timeframe, 86400)

        # Date range: enough history to cover `limit` candles with weekend/holiday buffer.
        end_dt = datetime.fromtimestamp(before_time, tz=timezone.utc) if before_time else datetime.now(tz=timezone.utc)
        # ISS uses local (Moscow) date strings; using UTC date is acceptable for from/till bounds.
        # For minute data, ISS returns at most 500 rows per page — we paginate via `start`.
        if timeframe in ('1m', '5m', '15m', '30m'):
            # ~7h trading day -> ~420 1m bars; assume ≤390 bars/day, add safety
            days = max(2, int(limit / 300) + 2)
        elif timeframe == '1H':
            days = max(5, int(limit / 7) + 3)
        elif timeframe == '4H':
            days = max(15, int(limit / 2) + 5)
        elif timeframe == '1W':
            days = max(60, limit * 7 + 14)
        else:  # 1D
            days = max(7, int(limit * 1.6) + 5)
        start_dt = end_dt - timedelta(days=days)
        if after_time is not None:
            start_dt = min(start_dt, datetime.fromtimestamp(after_time, tz=timezone.utc))

        url = self._candle_url(sym)
        all_rows: List[List[Any]] = []
        col_idx: Dict[str, int] = {}
        start = 0
        page_size = 500  # ISS default cap for candles
        max_pages = 50  # hard safety cap (25k rows)

        for _ in range(max_pages):
            params = {
                'from': start_dt.strftime('%Y-%m-%d'),
                'till': end_dt.strftime('%Y-%m-%d'),
                'interval': iss_interval,
                'start': start,
            }
            payload = self._http_get(url, params)
            if not payload:
                break
            block = payload.get('candles') or {}
            data = block.get('data') or []
            if not col_idx:
                cols = block.get('columns') or []
                col_idx = {c: i for i, c in enumerate(cols)}
            all_rows.extend(data)
            if len(data) < page_size:
                break
            start += len(data)

        if not col_idx:
            logger.info(f"MOEX: empty candles response for {sym} ({timeframe})")
            return []

        i_open = col_idx.get('open')
        i_close = col_idx.get('close')
        i_high = col_idx.get('high')
        i_low = col_idx.get('low')
        i_vol = col_idx.get('volume')
        i_begin = col_idx.get('begin')
        if None in (i_open, i_close, i_high, i_low, i_vol, i_begin):
            logger.warning(f"MOEX: unexpected candle columns for {sym}: {col_idx}")
            return []

        klines: List[Dict[str, Any]] = []
        for row in all_rows:
            try:
                ts = self._moex_dt_to_unix(row[i_begin])
                if ts is None:
                    continue
                klines.append(self.format_kline(
                    timestamp=ts,
                    open_price=row[i_open] or 0,
                    high=row[i_high] or 0,
                    low=row[i_low] or 0,
                    close=row[i_close] or 0,
                    volume=row[i_vol] or 0,
                ))
            except Exception as e:
                logger.debug(f"MOEX: failed to parse candle row {row}: {e}")
                continue

        # Resample for non-native intervals (5/15/30m, 4H)
        if timeframe not in _NATIVE_ISS:
            klines.sort(key=lambda x: x['time'])
            klines = self._resample(klines, target_seconds)

        klines = self.filter_and_limit(
            klines,
            limit,
            before_time,
            after_time,
            truncate=(after_time is None),
        )
        self.log_result(sym, klines, timeframe)
        return klines

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Latest quote via ISS securities snapshot. Returns dict with 'last', 'change', etc."""
        sym = self._normalize_symbol(symbol)
        if not sym:
            return {'last': 0, 'symbol': symbol}
        payload = self._http_get(self._securities_url(sym), {'iss.meta': 'off'})
        if not payload:
            return {'last': 0, 'symbol': sym}

        marketdata = payload.get('marketdata') or {}
        md_cols = marketdata.get('columns') or []
        md_data = marketdata.get('data') or []
        if not md_data:
            return {'last': 0, 'symbol': sym}
        idx = {c: i for i, c in enumerate(md_cols)}
        row = md_data[0]

        def _pick(*names) -> float:
            for n in names:
                i = idx.get(n)
                if i is not None and row[i] is not None:
                    try:
                        return float(row[i])
                    except (TypeError, ValueError):
                        continue
            return 0.0

        last = _pick('LAST', 'LCURRENTPRICE', 'MARKETPRICE', 'LCLOSEPRICE')
        prev_close = _pick('LCLOSEPRICE', 'PREVPRICE', 'PREVADMITTEDQUOTE')
        high = _pick('HIGH')
        low = _pick('LOW')
        open_p = _pick('OPEN')
        change = round(last - prev_close, 4) if (last and prev_close) else 0.0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
        return {
            'last': last,
            'change': change,
            'changePercent': change_pct,
            'high': high,
            'low': low,
            'open': open_p,
            'previousClose': prev_close,
            'symbol': sym,
        }
