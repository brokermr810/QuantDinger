"""Quick trade symbol and exchange helpers."""

from __future__ import annotations


CRYPTO_EXCHANGES = {
    "binance",
    "okx",
    "bitget",
    "bybit",
    "gate",
    "htx",
}


def is_supported_crypto_exchange(exchange_id: str) -> bool:
    """Return whether Quick Trade supports this exchange id."""
    return (exchange_id or "").strip().lower() in CRYPTO_EXCHANGES


def symbols_match(user_symbol: str, position_symbol: str) -> bool:
    """Match UI symbols with exchange-native ids."""

    def normalize(value: str) -> str:
        return (value or "").strip().upper().replace("/", "").replace("-", "").replace("_", "")

    user_value = normalize(user_symbol)
    position_value = normalize(position_symbol)
    if not user_value or not position_value:
        return False
    if user_value == position_value:
        return True

    for suffix in ("SWAP", "PERPETUAL", "PERP"):
        if position_value.endswith(suffix) and user_value == position_value[: -len(suffix)]:
            return True
        if user_value.endswith(suffix) and position_value == user_value[: -len(suffix)]:
            return True

    # Some exchanges use less standard ids. Require length >= 6 to avoid false
    # positives such as ETH vs ETHW.
    return (
        len(user_value) >= 6 and user_value in position_value
    ) or (
        len(position_value) >= 6 and position_value in user_value
    )
