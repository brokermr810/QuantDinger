from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.script_semantic_harness import run_script_semantics


EXPECTED_TEMPLATE_KEYS = {
    "classic_ema_atr_trend",
    "donchian_breakout_pyramid",
    "bollinger_reversion_basket",
    "range_grid_basket",
    "dca_accumulator",
    "sequential_martingale",
    "layered_martingale_basket",
    "keltner_retest_breakout",
}


def _seed_templates():
    path = Path(__file__).resolve().parents[1] / "migrations" / "init.sql"
    sql = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\('(?P<key>[^']+)',\s*'(?P<title>[^']+)',\s*'(?P<desc>(?:[^']|'')*)',\s*"
        r"\$(?P<tag>qdtpl\d+)\$(?P<code>.*?)\$(?P=tag)\$,\s*"
        r"'(?P<schema>\{.*?\})'::jsonb",
        re.DOTALL,
    )
    out = {}
    for match in pattern.finditer(sql):
        key = match.group("key")
        if key not in EXPECTED_TEMPLATE_KEYS:
            continue
        out[key] = {
            "title": match.group("title"),
            "code": match.group("code"),
            "schema": json.loads(match.group("schema")),
        }
    return out


def _defaults(template):
    params = {}
    for item in template["schema"].get("params") or []:
        value = item.get("default")
        if item.get("type") == "percent" and value is not None:
            value = float(value) / 100.0
        params[item["name"]] = value
    return params


def _bars(closes, *, pad=0.0):
    rows = []
    for i, close in enumerate(closes):
        rows.append(
            {
                "open": close,
                "high": close * (1.0 + pad),
                "low": close * (1.0 - pad),
                "close": close,
                "volume": 1000.0,
                "time": f"2026-01-{(i % 28) + 1:02d} 00:00",
            }
        )
    return rows


def _intents(result):
    return [order.intent for order in result.orders]


def _reasons(result):
    return [order.reason for order in result.orders]


@pytest.fixture(scope="module")
def templates():
    return _seed_templates()


def test_all_eight_seed_templates_are_present(templates):
    assert set(templates) == EXPECTED_TEMPLATE_KEYS


def test_classic_ema_atr_trend_opens_on_trend_and_closes_on_trail(templates):
    params = {**_defaults(templates["classic_ema_atr_trend"]), "fast_ema": 2, "slow_ema": 4, "atr_period": 2, "stop_atr": 1.0, "trail_atr": 1.0, "cooldown_bars": 0}
    result = run_script_semantics(
        templates["classic_ema_atr_trend"]["code"],
        _bars([100, 100, 101, 102, 103, 104, 105, 90], pad=0.01),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result) == ["open_long", "close_long"]
    assert _reasons(result) == ["ema_atr_entry", "ema_atr_stop"]
    assert result.orders[0].bar_index < result.orders[1].bar_index


def test_donchian_breakout_pyramid_opens_adds_and_exits(templates):
    params = {**_defaults(templates["donchian_breakout_pyramid"]), "entry_lookback": 4, "exit_lookback": 3, "max_layers": 3, "step_pct": 0.01, "hard_stop_price_pct": 0.05, "cooldown_bars": 0}
    result = run_script_semantics(
        templates["donchian_breakout_pyramid"]["code"],
        _bars([100, 101, 102, 103, 106, 108, 110, 90], pad=0.0),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result)[:3] == ["open_long", "add_long", "close_long"]
    assert _reasons(result)[:3] == ["donchian_breakout", "donchian_pyramid", "donchian_exit"]


def test_bollinger_reversion_opens_on_lower_band_and_exits_on_rebound(templates):
    params = {**_defaults(templates["bollinger_reversion_basket"]), "period": 5, "std_mult": 1.5, "max_layers": 3, "take_profit_price_pct": 0.01, "hard_stop_price_pct": 0.2}
    result = run_script_semantics(
        templates["bollinger_reversion_basket"]["code"],
        _bars([100, 100, 100, 100, 100, 100, 90, 100]),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result)[:2] == ["open_long", "close_long"]
    assert _reasons(result)[:2] == ["bollinger_entry", "bollinger_exit"]


def test_range_grid_opens_in_low_zone_and_exits_on_profit(templates):
    params = {**_defaults(templates["range_grid_basket"]), "lookback": 5, "grid_levels": 6, "take_profit_price_pct": 0.01, "range_buffer_pct": 0.02}
    result = run_script_semantics(
        templates["range_grid_basket"]["code"],
        _bars([100, 105, 110, 108, 106, 101, 105, 107]),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result)[:2] == ["open_long", "close_long"]
    assert _reasons(result)[:2] == ["grid_entry", "grid_exit"]


def test_dca_accumulator_buys_on_schedule_adds_on_dip_and_exits_on_profit(templates):
    params = {**_defaults(templates["dca_accumulator"]), "interval_bars": 2, "dip_pct": 0.05, "take_profit_price_pct": 0.1, "hard_stop_price_pct": 0.4}
    result = run_script_semantics(
        templates["dca_accumulator"]["code"],
        _bars([100, 100, 94, 94, 112]),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result)[:3] == ["open_long", "add_long", "close_long"]
    assert _reasons(result)[:3] == ["dca_open", "dca_add", "dca_exit"]


def test_sequential_martingale_opens_adds_on_spacing_and_exits_on_profit(templates):
    params = {**_defaults(templates["sequential_martingale"]), "spacing_pct": 0.02, "take_profit_price_pct": 0.01, "hard_stop_price_pct": 0.3}
    result = run_script_semantics(
        templates["sequential_martingale"]["code"],
        _bars([100, 97, 101]),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result)[:3] == ["open_long", "add_long", "close_long"]
    assert _reasons(result)[:3] == ["martingale_open", "martingale_add", "martingale_exit"]


def test_sequential_martingale_respects_total_budget_cap(templates):
    params = {
        **_defaults(templates["sequential_martingale"]),
        "total_budget_usdt": 100,
        "initial_order_usdt": 80,
        "first_order_pct": 0.5,
        "multiplier": 3.0,
        "spacing_pct": 0.01,
        "take_profit_price_pct": 0.5,
        "hard_stop_price_pct": 0.9,
    }
    result = run_script_semantics(
        templates["sequential_martingale"]["code"],
        _bars([100, 98, 96, 94]),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "spot", "investment_amount": 10000},
    )

    assert _intents(result)[:2] == ["open_long", "add_long"]
    assert len([x for x in _intents(result) if x in ("open_long", "add_long")]) == 2
    assert result.orders[0].amount == pytest.approx(0.8)
    assert result.orders[1].amount == pytest.approx(20 / 98)


def test_layered_martingale_opens_adds_on_split_spacing_and_exits(templates):
    params = {**_defaults(templates["layered_martingale_basket"]), "split_spacing_pct": 0.02, "layer_spacing_pct": 0.04, "take_profit_price_pct": 0.01, "hard_stop_price_pct": 0.3}
    result = run_script_semantics(
        templates["layered_martingale_basket"]["code"],
        _bars([100, 97, 101]),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result)[:3] == ["open_long", "add_long", "close_long"]
    assert _reasons(result)[:3] == ["layered_martingale_open", "layered_martingale_add", "layered_martingale_exit"]


def test_keltner_retest_breakout_waits_for_breakout_then_retest(templates):
    params = {**_defaults(templates["keltner_retest_breakout"]), "ema_period": 2, "atr_period": 2, "channel_mult": 0.0, "retest_buffer_pct": 0.2, "trail_atr": 0.5}
    result = run_script_semantics(
        templates["keltner_retest_breakout"]["code"],
        _bars([100, 100, 100, 100, 100, 110, 101, 81], pad=0.001),
        params=params,
        runtime_config={"trade_direction": "long", "market_type": "swap", "investment_amount": 10000},
    )

    assert _intents(result)[:2] == ["open_long", "close_long"]
    assert _reasons(result)[:2] == ["keltner_retest", "keltner_trail_exit"]
