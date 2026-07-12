"""Canonical market-data identity shared by research, backtest, and live flows."""

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.config.data_sources import CCXTConfig


CRYPTO_MARKET_TYPES = frozenset({"spot", "swap"})
SUPPORTED_CRYPTO_EXCHANGE_IDS = frozenset({"binance", "bitget", "bybit", "okx", "gate", "htx"})


def normalize_exchange_id(value: Any) -> str:
    exchange_id = str(value or "").strip().lower()
    aliases = {
        "okex": "okx",
        "gateio": "gate",
        "huobi": "htx",
        "binanceusdm": "binance",
    }
    return aliases.get(exchange_id, exchange_id)


def default_crypto_exchange_id() -> str:
    exchange_id = normalize_exchange_id(CCXTConfig.DEFAULT_EXCHANGE or "binance") or "binance"
    return exchange_id if exchange_id in SUPPORTED_CRYPTO_EXCHANGE_IDS else "binance"


def normalize_market_type(value: Any, *, market: str = "") -> str:
    market_type = str(value or "").strip().lower()
    if market_type in {"future", "futures", "perp", "perpetual"}:
        market_type = "swap"
    if str(market or "").strip() != "Crypto":
        return "spot"
    return market_type if market_type in CRYPTO_MARKET_TYPES else "spot"


def canonical_crypto_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":", 1)[0]
    return symbol


@dataclass(frozen=True)
class MarketContext:
    market: str
    symbol: str
    exchange_id: str = ""
    market_type: str = "spot"
    instrument_id: str = ""
    settle_currency: str = ""
    timeframe: str = ""

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        apply_crypto_defaults: bool = True,
    ) -> "MarketContext":
        data = payload or {}
        market = str(
            data.get("market")
            or data.get("market_category")
            or data.get("marketCategory")
            or ""
        ).strip()
        symbol = canonical_crypto_symbol(data.get("symbol")) if market == "Crypto" else str(data.get("symbol") or "").strip().upper()
        exchange_id = normalize_exchange_id(
            data.get("exchange_id")
            or data.get("exchangeId")
            or data.get("exchange")
        )
        market_type = normalize_market_type(
            data.get("market_type") or data.get("marketType"),
            market=market,
        )
        if market == "Crypto" and apply_crypto_defaults and not exchange_id:
            exchange_id = default_crypto_exchange_id()
        if market != "Crypto":
            exchange_id = ""
        return cls(
            market=market,
            symbol=symbol,
            exchange_id=exchange_id,
            market_type=market_type,
            instrument_id=str(data.get("instrument_id") or data.get("instrumentId") or "").strip(),
            settle_currency=str(data.get("settle_currency") or data.get("settleCurrency") or "").strip().upper(),
            timeframe=str(data.get("timeframe") or "").strip(),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def identity_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.market,
            self.symbol,
            self.exchange_id,
            self.market_type,
            self.instrument_id,
        )
