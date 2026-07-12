import pytest

from app.services.strategy_runtime.executors import (
    build_executor_strategy_payload,
    executor_templates,
    preview_executor,
)
from app.services.strategy_script_runtime import StrategyScriptContext, compile_strategy_script_handlers
from app.services.grid.config import GridBotConfig
from app.services.grid.validator import validate_grid_config


def test_executor_templates_expose_grid_dca_and_martingale():
    items = executor_templates()["items"]

    assert {item["executor_type"] for item in items} == {"grid", "dca", "martingale", "layered_martingale"}


def test_live_executor_requires_saved_exchange_credential():
    with pytest.raises(ValueError, match="LIVE_EXECUTOR_CREDENTIAL_REQUIRED"):
        build_executor_strategy_payload(
            {
                "executor_type": "grid",
                "execution_mode": "live",
                "symbol": "BTC/USDT",
                "start_price": 98000,
                "end_price": 102000,
                "grid_count": 5,
                "total_amount_quote": 500,
            },
            user_id=7,
        )

    payload = build_executor_strategy_payload(
        {
            "executor_type": "grid",
            "execution_mode": "live",
            "symbol": "BTC/USDT",
            "start_price": 98000,
            "end_price": 102000,
            "grid_count": 5,
            "total_amount_quote": 500,
            "exchange_config": {"credential_id": 42, "exchange_id": "okx"},
        },
        user_id=7,
    )

    assert payload["execution_mode"] == "live"
    assert payload["exchange_config"] == {"credential_id": 42, "exchange_id": "okx"}


def test_grid_preview_generates_levels_and_legacy_bot_params():
    preview = preview_executor(
        {
            "executor_type": "grid",
            "symbol": "BTC/USDT",
            "side": "long",
            "start_price": 98000,
            "end_price": 102000,
            "grid_count": 5,
            "total_amount_quote": 500,
            "take_profit_pct": 0.005,
        }
    )

    assert preview["summary"]["level_count"] == 5
    assert preview["summary"]["total_amount_quote"] == 500
    assert preview["levels"][0]["price"] > preview["levels"][-1]["price"]

    payload = build_executor_strategy_payload(
        {
            "executor_type": "grid",
            "strategy_name": "Grid Smoke",
            "symbol": "BTC/USDT",
            "start_price": 98000,
            "end_price": 102000,
            "grid_count": 5,
            "total_amount_quote": 500,
        },
        user_id=7,
    )
    cfg = payload["trading_config"]

    assert payload["strategy_mode"] == "bot"
    assert cfg["strategy_family"] == "executor"
    assert cfg["executor_type"] == "grid"
    assert cfg["bot_type"] == "grid"
    assert cfg["bot_params"]["gridCount"] == 5
    assert cfg["bot_params"]["maxOpenOrders"] > 0
    assert payload["strategy_code"].strip()
    on_init, on_bar = compile_strategy_script_handlers(payload["strategy_code"])
    assert on_bar is not None
    context = StrategyScriptContext()
    on_init(context)
    definition = context.runtime["robot_definition"]
    assert definition["robot_type"] == "grid"
    assert definition["config"]["grid_count"] == 5


def test_grid_initial_position_enters_runtime_config():
    payload = build_executor_strategy_payload(
        {
            "executor_type": "grid",
            "side": "long",
            "market_type": "swap",
            "start_price": 98,
            "end_price": 102,
            "grid_count": 4,
            "total_amount_quote": 400,
            "initial_position_pct": 0.25,
        },
        user_id=7,
    )

    bot_params = payload["trading_config"]["bot_params"]
    assert bot_params["initialPositionPct"] == 25


def test_neutral_grid_is_swap_only_and_starts_without_net_position():
    preview = preview_executor(
        {
            "executor_type": "grid",
            "side": "neutral",
            "market_type": "swap",
            "start_price": 98,
            "end_price": 102,
            "grid_count": 4,
            "total_amount_quote": 400,
            "initial_position_pct": 0.25,
        }
    )

    assert preview["config"]["side"] == "neutral"
    assert preview["config"]["initial_position_pct"] == 0
    assert {level["side"] for level in preview["levels"]} == {"long", "short"}

    payload = build_executor_strategy_payload(
        {
            "executor_type": "grid",
            "side": "neutral",
            "market_type": "swap",
            "start_price": 98,
            "end_price": 102,
            "grid_count": 4,
            "total_amount_quote": 400,
        },
        user_id=7,
    )
    assert payload["trade_direction"] == "neutral"
    assert payload["trading_config"]["bot_params"]["gridDirection"] == "neutral"
    assert payload["trading_config"]["bot_params"]["initialPositionPct"] == 0

    with pytest.raises(ValueError, match="NEUTRAL_GRID_REQUIRES_SWAP"):
        preview_executor(
            {
                "executor_type": "grid",
                "side": "neutral",
                "market_type": "spot",
            }
        )


def test_dca_preview_uses_step_and_volume_multipliers():
    preview = preview_executor(
        {
            "executor_type": "dca",
            "side": "long",
            "entry_price": 100,
            "base_order_size": 10,
            "safety_order_size": 20,
            "price_deviation_pct": 0.01,
            "step_multiplier": 2,
            "volume_multiplier": 1.5,
            "max_layers": 4,
        }
    )

    prices = [row["price"] for row in preview["levels"]]
    amounts = [row["amount_quote"] for row in preview["levels"]]

    assert prices == [100, 99, 97, 93]
    assert amounts == [10, 20, 30, 45]

    payload = build_executor_strategy_payload(
        {
            "executor_type": "dca",
            "side": "long",
            "entry_price": 100,
            "base_order_size": 10,
            "safety_order_size": 20,
            "price_deviation_pct": 0.01,
            "step_multiplier": 2,
            "volume_multiplier": 1.5,
            "max_layers": 4,
            "take_profit_pct": 0.02,
        },
        user_id=7,
    )
    bot_params = payload["trading_config"]["bot_params"]

    assert bot_params["frequency"] == "every_bar"
    assert bot_params["amountEach"] == 10
    assert bot_params["totalBudget"] == 105
    assert bot_params["dipThreshold"] == 1.0
    assert payload["trading_config"]["take_profit_pct"] == 0.02
    assert payload["strategy_code"].strip()
    assert compile_strategy_script_handlers(payload["strategy_code"])[1] is not None


def test_martingale_preview_accepts_short_side():
    preview = preview_executor(
        {
            "executor_type": "martingale",
            "side": "short",
            "entry_price": 100,
            "base_order_size": 10,
            "safety_order_size": 20,
            "price_deviation_pct": 0.01,
            "step_multiplier": 2,
            "volume_multiplier": 2,
            "max_layers": 3,
        }
    )

    assert preview["executor_type"] == "martingale"
    assert [row["price"] for row in preview["levels"]] == [100, 101, 103]
    assert [row["amount_quote"] for row in preview["levels"]] == [10, 20, 40]

    payload = build_executor_strategy_payload(
        {
            "executor_type": "martingale",
            "side": "short",
            "entry_price": 100,
            "base_order_size": 10,
            "safety_order_size": 20,
            "price_deviation_pct": 0.01,
            "volume_multiplier": 2,
            "max_layers": 3,
            "take_profit_pct": 0.025,
            "hard_stop_pct": 0.12,
        },
        user_id=7,
    )
    bot_params = payload["trading_config"]["bot_params"]

    assert bot_params["direction"] == "short"
    assert bot_params["multiplier"] == 2
    assert bot_params["maxLayers"] == 3
    assert bot_params["priceDropPct"] == 1.0
    assert bot_params["takeProfitPct"] == 2.5
    assert bot_params["stopLossPct"] == 12.0
    assert payload["strategy_code"].strip()
    assert compile_strategy_script_handlers(payload["strategy_code"])[1] is not None


def test_generated_dca_script_emits_layered_orders():
    payload = build_executor_strategy_payload(
        {
            "executor_type": "dca",
            "side": "long",
            "entry_price": 100,
            "base_order_size": 10,
            "safety_order_size": 20,
            "price_deviation_pct": 0.01,
            "step_multiplier": 2,
            "volume_multiplier": 1.5,
            "max_layers": 3,
        },
        user_id=7,
    )
    on_init, on_bar = compile_strategy_script_handlers(payload["strategy_code"])
    ctx = StrategyScriptContext(initial_balance=1000.0)
    on_init(ctx)

    bar = type("Bar", (), {"close": 100.0})()
    on_bar(ctx, bar)
    assert ctx._orders[-1]["intent"] == "open_long"
    assert ctx._orders[-1]["amount"] == 10

    ctx._orders.clear()
    ctx.position.open_long(100.0, 1.0)
    on_bar(ctx, type("Bar", (), {"close": 99.0})())
    assert ctx._orders[-1]["intent"] == "add_long"
    assert ctx._orders[-1]["amount"] == 20


def test_generated_martingale_script_emits_short_orders():
    payload = build_executor_strategy_payload(
        {
            "executor_type": "martingale",
            "side": "short",
            "entry_price": 100,
            "base_order_size": 10,
            "safety_order_size": 20,
            "price_deviation_pct": 0.01,
            "step_multiplier": 2,
            "volume_multiplier": 2,
            "max_layers": 3,
        },
        user_id=7,
    )
    on_init, on_bar = compile_strategy_script_handlers(payload["strategy_code"])
    ctx = StrategyScriptContext(initial_balance=1000.0)
    on_init(ctx)

    on_bar(ctx, type("Bar", (), {"close": 100.0})())
    assert ctx._orders[-1]["intent"] == "open_short"
    assert ctx._orders[-1]["amount"] == 10


def test_grid_hummingbot_style_fields_enter_runtime_config_and_validation():
    payload = build_executor_strategy_payload(
        {
            "executor_type": "grid",
            "side": "long",
            "start_price": 98000,
            "end_price": 102000,
            "grid_count": 5,
            "total_amount_quote": 500,
            "max_open_orders": 2,
            "min_spread_between_orders": 0.0005,
            "order_frequency": 3,
        },
        user_id=7,
    )
    cfg = GridBotConfig.from_trading_config(payload["trading_config"])

    assert cfg.max_open_orders == 2
    assert cfg.min_spread_between_orders == 0.0005
    assert cfg.order_frequency == 3

    too_tight = dict(payload["trading_config"])
    too_tight["bot_params"] = dict(too_tight["bot_params"])
    too_tight["bot_params"]["minSpreadBetweenOrders"] = 0.02
    ok, msg, _warnings = validate_grid_config(GridBotConfig.from_trading_config(too_tight), initial_capital=1000)
    assert not ok
    assert "minSpreadBetweenOrders" in msg


def test_layered_martingale_preview_builds_five_by_three_basket():
    preview = preview_executor(
        {
            "executor_type": "layered_martingale",
            "side": "long",
            "entry_price": 100,
            "layer_count": 5,
            "orders_per_layer": 3,
            "base_order_size": 10,
            "volume_multiplier": 1.8,
            "intra_spacing_1_pct": 0.005,
            "intra_spacing_2_pct": 0.008,
            "inter_spacing_1_pct": 0.012,
            "inter_spacing_2_pct": 0.015,
            "inter_spacing_3_pct": 0.018,
            "inter_spacing_4_pct": 0.022,
            "take_profit_pct": 0.006,
        }
    )

    levels = preview["levels"]
    assert preview["executor_type"] == "layered_martingale"
    assert preview["summary"]["level_count"] == 15
    assert [row["layer_index"] for row in levels[:3]] == [1, 1, 1]
    assert [row["order_index"] for row in levels[:3]] == [1, 2, 3]
    assert [round(row["amount_quote"], 2) for row in levels[:3]] == [10, 18, 32.4]
    assert levels[3]["layer_index"] == 2
    assert levels[3]["order_index"] == 1
    assert levels[0]["price"] > levels[1]["price"] > levels[2]["price"] > levels[3]["price"]


def test_layered_martingale_strategy_code_emits_basket_child_orders_and_close():
    payload = build_executor_strategy_payload(
        {
            "executor_type": "layered_martingale",
            "side": "long",
            "entry_price": 100,
            "layer_count": 2,
            "orders_per_layer": 3,
            "base_order_size": 10,
            "volume_multiplier": 2,
            "intra_spacing_1_pct": 0.01,
            "intra_spacing_2_pct": 0.02,
            "inter_spacing_1_pct": 0.03,
            "take_profit_pct": 0.01,
        },
        user_id=7,
    )
    assert payload["trading_config"]["executor_type"] == "layered_martingale"
    assert payload["trading_config"]["bot_params"]["layerCount"] == 2
    assert payload["trading_config"]["bot_params"]["ordersPerLayer"] == 3
    assert payload["trading_config"]["tick_interval_sec"] == 1

    on_init, on_bar = compile_strategy_script_handlers(payload["strategy_code"])
    ctx = StrategyScriptContext(initial_balance=1000.0)
    ctx.bind_runtime(strategy_id=0, strategy_run_id=0, symbol="BTC/USDT", trading_config=payload["trading_config"])
    on_init(ctx)

    on_bar(ctx, type("Bar", (), {"close": 100.0})())
    assert ctx._orders[-1]["intent"] == "open_long"
    assert ctx._orders[-1]["script_quote_amount"] == 10
    assert ctx._orders[-1]["layer_index"] == 1
    assert ctx._orders[-1]["order_index"] == 1

    ctx._orders.clear()
    ctx.position.open_long(100.0, 1.0)
    on_bar(ctx, type("Bar", (), {"close": 99.0})())
    assert ctx._orders[-1]["intent"] == "add_long"
    assert ctx._orders[-1]["script_quote_amount"] == 20
    assert ctx._orders[-1]["layer_index"] == 1
    assert ctx._orders[-1]["order_index"] == 2

    ctx._orders.clear()
    on_bar(ctx, type("Bar", (), {"close": 102.0})())
    assert ctx._orders[-1]["intent"] == "close_long"
    assert ctx._orders[-1]["reason"] == "layered_martingale_take_profit"
