from __future__ import annotations

import pandas as pd

from app.services.backtest_engine import BacktestConfig, ScriptStrategyBacktestRunner
from app.services.indicator_params import StrategyConfigParser
from app.services.strategy_contract import resolve_script_strategy_contract
from app.services.strategy_warmup import (
    live_warmup_status,
    required_live_history_limit,
    resolve_startup_candle_count,
    warmup_start_date,
)


def test_declared_startup_candle_count_is_shared_contract():
    code = """
# startup_candle_count: 275
def on_bar(ctx, bar):
    pass
"""

    assert StrategyConfigParser.parse_contract_headers(code)["startup_candle_count"] == 275
    assert StrategyConfigParser.build_nested_cfg_from_code(code)["startupCandleCount"] == 275
    assert resolve_startup_candle_count(code) == 275


def test_strategy_contract_merges_parameters_once_for_backtest_and_live():
    contract = resolve_script_strategy_contract(
        "# startup_candle_count: 40\ndef on_bar(ctx, bar):\n    pass\n",
        {
            "script_template_params": {"length": 20, "threshold": 1.0},
            "paramOverrides": {"threshold": 2.0},
            "bot_params": {"layers": 3},
        },
    )

    assert contract["startupCandleCount"] == 40
    assert contract["parameters"] == {"length": 20, "threshold": 2.0, "layers": 3}


def test_recursive_indicator_inference_preserves_legacy_strategy_warmup():
    code = """
def on_init(ctx):
    ctx.fast_ema = ctx.param("fast_ema", 21)
    ctx.slow_ema = ctx.param("slow_ema", 55)
    ctx.pivot_lookback = ctx.param("pivot_lookback", 20)

def on_bar(ctx, bar):
    pass
"""

    assert resolve_startup_candle_count(code) == 275


def test_stock_warmup_fetch_start_accounts_for_trading_sessions():
    requested_start = pd.Timestamp("2026-07-01").to_pydatetime()

    crypto_start = warmup_start_date(requested_start, "1D", 275, "Crypto")
    stock_start = warmup_start_date(requested_start, "1D", 275, "USStock")

    assert (requested_start - crypto_start).days == 275
    assert (requested_start - stock_start).days > 400


def test_live_warmup_requires_completed_history_before_ready():
    assert required_live_history_limit(100, 275) == 276
    assert live_warmup_status(275, 275) == {
        "required": 275,
        "completed": 274,
        "missing": 1,
        "ready": False,
    }
    assert live_warmup_status(276, 275)["ready"] is True


def test_backtest_processes_warmup_bars_but_blocks_warmup_orders():
    idx = pd.date_range("2026-01-01", periods=7, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0] * len(idx),
            "high": [101.0] * len(idx),
            "low": [99.0] * len(idx),
            "close": [100.0] * len(idx),
            "volume": [1000.0] * len(idx),
        },
        index=idx,
    )
    code = """
# startup_candle_count: 3
def on_bar(ctx, bar):
    if ctx.position.is_flat():
        ctx.order_value(100, side="long", reason="entry")
"""
    cfg = BacktestConfig(
        initial_capital=1000,
        commission=0,
        slippage=0,
        leverage=1,
        trade_direction="long",
        timeframe="1D",
        signal_timing="next_bar_open",
        market_type="swap",
    )
    result = ScriptStrategyBacktestRunner(
        config=cfg,
        code=code,
        runtime={
            "symbol": "BTC/USDT",
            "trading_start": idx[3].to_pydatetime(),
            "startup_candle_count": 3,
        },
    ).run(df=df, start_date=idx[3].to_pydatetime(), end_date=idx[-1].to_pydatetime())

    assert result["engine"]["warmupBarsProcessed"] == 3
    entries = [order for order in result["orders"] if order["scriptIntent"] == "open_long"]
    assert len(entries) == 1
    assert entries[0]["submittedBar"] == 4
    assert pd.Timestamp(result["equityCurve"][0]["time"]) == idx[3]
