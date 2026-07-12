from app.services.live_trading.symbols import (
    to_binance_futures_symbol,
    to_bitget_um_symbol,
    to_bybit_symbol,
    to_gate_currency_pair,
    to_htx_contract_code,
    to_okx_swap_inst_id,
)


def test_equity_perpetual_native_instrument_ids_for_six_exchanges():
    symbol = "AAPL/USDT"

    assert to_binance_futures_symbol(symbol) == "AAPLUSDT"
    assert to_bitget_um_symbol(symbol) == "AAPLUSDT"
    assert to_bybit_symbol(symbol) == "AAPLUSDT"
    assert to_okx_swap_inst_id(symbol) == "AAPL-USDT-SWAP"
    assert to_gate_currency_pair(symbol) == "AAPL_USDT"
    assert to_htx_contract_code(symbol) == "AAPL-USDT"
