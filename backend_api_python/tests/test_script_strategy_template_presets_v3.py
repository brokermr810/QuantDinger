from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner
from app.services.script_source import ScriptSourceService
from app.services.strategy_script_runtime import compile_strategy_script_handlers


EXPECTED_V3_KEYS = {
    "ema_trend_pullback",
    "donchian_breakout",
    "atr_channel_breakout",
    "rsi_mean_reversion",
    "macd_momentum",
    "bollinger_reversion",
    "turtle_breakout_lite",
    "volatility_stop_trend",
}

BANNED_LEGACY_KEYS = {
    "range_grid_basket",
    "dca_accumulator",
    "sequential_martingale",
    "layered_martingale_basket",
}


def _seed_templates() -> dict[str, dict]:
    path = Path(__file__).resolve().parents[1] / "migrations" / "init.sql"
    sql = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\('(?P<key>[^']+)',\s*'(?P<title>[^']+)',\s*'(?P<desc>(?:[^']|'')*)',\s*"
        r"\$(?P<tag>qdtplv3_\d+)\$(?P<code>.*?)\$(?P=tag)\$,\s*"
        r"'(?P<schema>\{.*?\})'::jsonb",
        re.DOTALL,
    )
    out: dict[str, dict] = {}
    for match in pattern.finditer(sql):
        key = match.group("key")
        out[key] = {
            "title": match.group("title"),
            "code": match.group("code"),
            "schema": json.loads(match.group("schema")),
        }
    return out


def _frame(closes: list[float], freq: str = "h") -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(closes), freq=freq)
    return pd.DataFrame(
        {
            "open": [float(v) for v in closes],
            "high": [float(v) * 1.015 for v in closes],
            "low": [float(v) * 0.985 for v in closes],
            "close": [float(v) for v in closes],
            "volume": [10_000.0] * len(closes),
        },
        index=idx,
    )


def _mixed_frame() -> pd.DataFrame:
    closes: list[float] = []
    for i in range(40):
        closes.append(100 + math.sin(i / 3) * 1.0)
    for i in range(25):
        closes.append(100 - i * 0.8)
    for i in range(20):
        closes.append(80 + i * 1.2)
    for i in range(50):
        closes.append(104 + i * 0.9)
    for i in range(20):
        closes.append(149 - i * 1.8)
    for i in range(45):
        closes.append(113 + math.sin(i / 2) * 8.0)
    return _frame(closes)


def _run_template(code: str, df: pd.DataFrame, params: dict, direction: str = "long") -> dict:
    config = BacktestConfig(
        initial_capital=10_000,
        commission=0.0,
        slippage=0.0,
        leverage=1.0,
        trade_direction=direction,
        timeframe="1H",
        signal_timing="next_bar_open",
        market_type="swap",
    )
    return ScriptBacktestRunner(
        config=config,
        code=code,
        params=params,
        runtime={"symbol": "BTC/USDT"},
    ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())


def test_v3_seed_contains_exactly_eight_current_script_strategy_templates():
    templates = _seed_templates()

    assert set(templates) == EXPECTED_V3_KEYS
    assert not (set(templates) & BANNED_LEGACY_KEYS)
    for key, template in templates.items():
        assert template["schema"].get("params"), key
        assert '"version":4' in re.sub(r"\s+", "", Path(__file__).resolve().parents[1].joinpath("migrations", "init.sql").read_text(encoding="utf-8"))


def test_script_source_service_syncs_from_v3_seed_block_only():
    seed_sql = ScriptSourceService()._current_template_seed_sql()

    assert "Script strategy templates v3 seed" in seed_sql
    assert "market_symbols" not in seed_sql.lower()
    for key in EXPECTED_V3_KEYS:
        assert key in seed_sql
    for key in BANNED_LEGACY_KEYS:
        assert key in seed_sql
    assert '"version":4' in re.sub(r"\s+", "", seed_sql)


def test_v3_templates_compile_and_smoke_backtest_on_script_runner():
    templates = _seed_templates()
    df = _mixed_frame()
    overrides = {
        "ema_trend_pullback": {"fast_ema": 4, "slow_ema": 12, "atr_period": 4, "pullback_pct": 0.005, "min_atr_pct": 0, "exit_buffer_pct": 0.004, "cooldown_bars": 0, "target_pct": 0.2},
        "donchian_breakout": {"entry_lookback": 8, "exit_lookback": 4, "atr_period": 4, "min_range_atr": 0, "target_pct": 0.2},
        "atr_channel_breakout": {"ema_period": 12, "atr_period": 4, "atr_mult": 0.8, "slope_lookback": 3, "target_pct": 0.2},
        "rsi_mean_reversion": {"rsi_period": 3, "regime_period": 3, "oversold": 50, "overbought": 50, "exit_level": 55, "target_pct": 0.2},
        "macd_momentum": {"fast": 2, "slow": 5, "signal": 2, "regime_ema": 2, "target_pct": 0.2},
        "bollinger_reversion": {"period": 10, "std_mult": 1.2, "min_bandwidth": 0, "exit_z": 0.2, "target_pct": 0.2},
        "turtle_breakout_lite": {"entry_lookback": 8, "exit_lookback": 4, "atr_period": 4, "risk_pct": 0.02, "add_atr": 0.2, "max_target_pct": 0.3},
        "volatility_stop_trend": {"ema_period": 12, "atr_period": 4, "stop_atr": 1.2, "breakout_lookback": 4, "target_pct": 0.2},
    }

    for key, template in templates.items():
        on_init, on_bar = compile_strategy_script_handlers(template["code"])
        assert on_init is not None, key
        assert on_bar is not None, key
        result = _run_template(template["code"], df, overrides[key])
        assert result["engine"]["version"] == "quantdinger-script-backtest-v3", key
        assert result["equityCurve"], key


def test_representative_v3_templates_emit_orders_on_targeted_market_shapes():
    templates = _seed_templates()
    cases = {
        "ema_trend_pullback": (
            _frame([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 108, 113, 114, 115]),
            {"fast_ema": 3, "slow_ema": 8, "atr_period": 3, "pullback_pct": 0.01, "min_atr_pct": 0, "exit_buffer_pct": 0.004, "cooldown_bars": 0, "target_pct": 0.2},
            "ema_pullback_recovery",
        ),
        "rsi_mean_reversion": (
            _frame([100, 100, 100, 99, 98, 99, 100, 101]),
            {"rsi_period": 3, "regime_period": 3, "oversold": 50, "overbought": 50, "exit_level": 55, "target_pct": 0.2},
            "rsi_confirmed_reversion",
        ),
        "macd_momentum": (
            _frame([120 - i for i in range(30)] + [91, 92, 93, 95, 98, 102, 107, 113, 120, 128, 137]),
            {"fast": 2, "slow": 5, "signal": 2, "regime_ema": 2, "target_pct": 0.2},
            "macd_momentum_cross",
        ),
        "turtle_breakout_lite": (
            _mixed_frame(),
            {"entry_lookback": 8, "exit_lookback": 4, "atr_period": 4, "risk_pct": 0.02, "add_atr": 0.2, "max_target_pct": 0.3},
            "turtle_breakout",
        ),
        "volatility_stop_trend": (
            _mixed_frame(),
            {"ema_period": 12, "atr_period": 4, "stop_atr": 1.2, "breakout_lookback": 4, "target_pct": 0.2},
            "volatility_trend_entry",
        ),
    }

    for key, (df, params, reason) in cases.items():
        result = _run_template(templates[key]["code"], df, params)
        assert result["engine"]["orderCount"] >= 1, key
        assert reason in [order["reason"] for order in result["orders"]], key


def test_ema_template_both_mode_can_open_long_and_short_positions():
    template = _seed_templates()["ema_trend_pullback"]
    long_setup = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 108, 113, 114, 115]
    short_setup = [120, 119, 118, 117, 116, 115, 114, 113, 112, 111, 110, 109, 108, 112, 107, 106, 105]
    result = _run_template(
        template["code"],
        _frame(long_setup + [100] * 20 + short_setup),
        {
            "fast_ema": 3,
            "slow_ema": 8,
            "atr_period": 3,
            "pullback_pct": 0.01,
            "min_atr_pct": 0,
            "exit_buffer_pct": 0.004,
            "cooldown_bars": 0,
            "target_pct": 0.2,
        },
        direction="both",
    )

    opened_sides = {
        order["positionSide"]
        for order in result["orders"]
        if order.get("status") == "filled" and not order.get("reduceOnly")
    }
    assert opened_sides == {"long", "short"}
