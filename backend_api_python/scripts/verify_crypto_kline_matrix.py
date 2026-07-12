"""Verify public OHLCV access for every supported crypto venue and product."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_sources.crypto import (
    PUBLIC_KLINE_EXCHANGE_IDS,
    CryptoDataSource,
    resolve_ccxt_for_live_trading,
)


def verify(
    exchange_id: str,
    market_type: str,
    *,
    symbol: str,
    timeframe: str,
    limit: int,
    timeout_ms: int,
) -> dict[str, Any]:
    started_at = time.monotonic()
    ccxt_id, options = resolve_ccxt_for_live_trading(exchange_id, market_type)
    source = CryptoDataSource.for_exchange(exchange_id, market_type)
    source.exchange.timeout = max(1000, timeout_ms)
    bars = source.get_kline(symbol, timeframe, limit)
    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    latest = bars[-1] if bars else {}
    return {
        "exchange_id": exchange_id,
        "market_type": market_type,
        "ccxt_id": ccxt_id,
        "options": options,
        "ok": len(bars) > 0,
        "bar_count": len(bars),
        "latest_time": latest.get("time"),
        "latest_close": latest.get("close"),
        "elapsed_ms": elapsed_ms,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", choices=["all", *PUBLIC_KLINE_EXCHANGE_IDS], default="all")
    parser.add_argument("--market-type", choices=["both", "spot", "swap"], default="both")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1H")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exchanges = PUBLIC_KLINE_EXCHANGE_IDS if args.exchange == "all" else (args.exchange,)
    market_types = ("spot", "swap") if args.market_type == "both" else (args.market_type,)
    results = [
        verify(
            exchange_id,
            market_type,
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=max(1, args.limit),
            timeout_ms=args.timeout_ms,
        )
        for exchange_id in exchanges
        for market_type in market_types
    ]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
