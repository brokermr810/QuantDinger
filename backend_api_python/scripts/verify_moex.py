#!/usr/bin/env python3
"""Live verification script for the MOEX data source.

Hits the public MOEX ISS API. Run from the backend_api_python directory:

    python scripts/verify_moex.py
    python scripts/verify_moex.py SBER 1D 30
    python scripts/verify_moex.py GAZP 1H 50

Prints a summary of fetched candles and the latest ticker. Useful for smoke-
testing connectivity in environments where pytest can run only offline tests.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

# Make `app` importable when the script is run directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Minimal env so app.config doesn't blow up
os.environ.setdefault("SECRET_KEY", "verify-moex-script")
os.environ.setdefault("ADMIN_USER", "verify")
os.environ.setdefault("ADMIN_PASSWORD", "verifypass")

from app.data_sources.factory import DataSourceFactory  # noqa: E402


def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "SBER"
    timeframe = sys.argv[2] if len(sys.argv) > 2 else "1D"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    print(f"== MOEX verification ==  symbol={symbol} timeframe={timeframe} limit={limit}")
    src = DataSourceFactory.get_source("MOEX")
    print(f"data source: {src.name}")

    klines = src.get_kline(symbol, timeframe, limit)
    print(f"candles returned: {len(klines)}")
    for k in klines[-5:]:
        utc = datetime.fromtimestamp(k['time'], tz=timezone.utc).isoformat()
        print(f"  {utc}  O={k['open']:>8} H={k['high']:>8} L={k['low']:>8} C={k['close']:>8} V={k['volume']}")

    print()
    ticker = src.get_ticker(symbol)
    print(f"ticker: {ticker}")

    if not klines:
        print("WARNING: no candles returned (network blocked? bad symbol? non-trading window?)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
