"""OKX order size precision inference from lotSz."""

import time

from app.services.live_trading.okx import OkxClient


def _client_with_instrument(inst_id: str, inst_type: str, lot_sz: str, min_sz: str) -> OkxClient:
    c = OkxClient(api_key="k", secret_key="s", passphrase="p")
    c._inst_cache[f"{inst_type}:{inst_id}"] = (
        time.time(),
        {"instId": inst_id, "lotSz": lot_sz, "minSz": min_sz},
    )
    return c


def test_spot_small_lot_sz_keeps_fractional_size():
    c = _client_with_instrument("BTC-USDT", "SPOT", "0.00000001", "0.00001")
    sz, precision = c._normalize_order_size(
        inst_id="BTC-USDT", market_type="spot", size=0.00081471
    )
    assert precision == 8
    assert c._dec_str(sz, strict_precision=precision) == "0.00081471"


def test_spot_regular_lot_sz_precision():
    c = _client_with_instrument("ETH-USDT", "SPOT", "0.000001", "0.001")
    sz, precision = c._normalize_order_size(
        inst_id="ETH-USDT", market_type="spot", size=0.0234567891
    )
    assert precision == 6
    assert c._dec_str(sz, strict_precision=precision) == "0.023456"


def test_swap_integer_lot_sz_precision_zero():
    c = _client_with_instrument("BTC-USDT-SWAP", "SWAP", "1", "1")
    c._inst_cache["SWAP:BTC-USDT-SWAP"][1]["ctVal"] = "0.01"
    sz, precision = c._normalize_order_size(
        inst_id="BTC-USDT-SWAP", market_type="swap", size=0.05
    )
    assert precision == 0
    assert c._dec_str(sz, strict_precision=precision) == "5"


def test_positive_exponent_lot_sz_clamps_to_zero_precision():
    c = _client_with_instrument("X-USDT", "SPOT", "10", "10")
    sz, precision = c._normalize_order_size(
        inst_id="X-USDT", market_type="spot", size=25.0
    )
    assert precision == 0
    assert c._dec_str(sz, strict_precision=precision) == "20"
