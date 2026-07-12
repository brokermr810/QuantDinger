"""Built-in executor strategy contracts and preview helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


EXECUTOR_TYPES = ("grid", "dca", "martingale", "layered_martingale")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _ratio(value: Any, default: float = 0.0) -> float:
    out = _float(value, default)
    if abs(out) > 1:
        out = out / 100.0
    return out


def _ratio_list(value: Any, defaults: List[float], *, expected: int = 0) -> List[float]:
    raw_values: List[Any]
    if isinstance(value, (list, tuple)):
        raw_values = list(value)
    elif isinstance(value, str) and value.strip():
        raw_values = [part.strip() for part in value.split(",") if part.strip()]
    else:
        raw_values = []
    out = [_ratio(item, 0.0) for item in raw_values]
    if not out:
        out = list(defaults)
    target = max(0, int(expected or 0))
    if target > 0:
        if not out:
            out = [0.0]
        while len(out) < target:
            out.append(out[-1])
        out = out[:target]
    return [max(0.0, float(item or 0.0)) for item in out]


def _side(value: Any, *, allow_neutral: bool = False) -> str:
    out = str(value or "long").strip().lower()
    if allow_neutral and out == "neutral":
        return "neutral"
    return "short" if out == "short" else "long"


def _market_type(value: Any) -> str:
    out = str(value or "swap").strip().lower()
    if out in ("future", "futures", "perp", "perpetual"):
        return "swap"
    return "spot" if out == "spot" else "swap"


def _linspace(start: float, end: float, count: int) -> List[float]:
    if count <= 1:
        return [round((start + end) / 2.0, 8)]
    step = (end - start) / float(count - 1)
    return [round(start + step * i, 8) for i in range(count)]


def _geospace(start: float, end: float, count: int) -> List[float]:
    if count <= 1 or start <= 0 or end <= 0:
        return _linspace(start, end, count)
    ratio = (end / start) ** (1.0 / float(count - 1))
    return [round(start * (ratio ** i), 8) for i in range(count)]


def _basket_take_profit_price(
    *,
    total_quote: float,
    total_quantity: float,
    side: str,
    take_profit: float,
) -> float:
    if total_quote <= 0 or total_quantity <= 0:
        return 0.0
    average_price = total_quote / total_quantity
    if side == "short":
        return average_price * (1.0 - take_profit)
    return average_price * (1.0 + take_profit)


@dataclass
class ExecutorLevel:
    level: int
    action: str
    side: str
    price: float
    amount_quote: float
    take_profit_price: float = 0.0
    trigger_pct: float = 0.0
    state: str = "not_active"
    layer_index: int = 0
    order_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "layer_index": self.layer_index or self.level,
            "order_index": self.order_index or 1,
            "action": self.action,
            "side": self.side,
            "price": round(float(self.price or 0.0), 8),
            "amount_quote": round(float(self.amount_quote or 0.0), 8),
            "take_profit_price": round(float(self.take_profit_price or 0.0), 8),
            "trigger_pct": round(float(self.trigger_pct or 0.0), 8),
            "state": self.state,
        }


@dataclass
class ExecutorPreview:
    executor_type: str
    config: Dict[str, Any]
    levels: List[ExecutorLevel] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "executor_type": self.executor_type,
            "config": dict(self.config),
            "levels": [level.to_dict() for level in self.levels],
            "warnings": list(self.warnings),
            "summary": {
                "level_count": len(self.levels),
                "total_amount_quote": round(sum(level.amount_quote for level in self.levels), 8),
                "first_price": round(self.levels[0].price, 8) if self.levels else 0.0,
                "last_price": round(self.levels[-1].price, 8) if self.levels else 0.0,
            },
        }


def normalize_executor_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    executor_type = str(raw.get("executor_type") or raw.get("type") or "grid").strip().lower()
    if executor_type not in EXECUTOR_TYPES:
        raise ValueError(f"unsupported_executor_type:{executor_type}")
    symbol = str(raw.get("symbol") or "BTC/USDT").strip() or "BTC/USDT"
    market_type = _market_type(raw.get("market_type") or raw.get("marketType"))
    side = _side(raw.get("side"), allow_neutral=executor_type == "grid")
    if side == "neutral" and market_type == "spot":
        raise ValueError("NEUTRAL_GRID_REQUIRES_SWAP")
    leverage = max(1, _int(raw.get("leverage"), 1))
    execution_mode = str(raw.get("execution_mode") or raw.get("executionMode") or "signal").strip().lower()
    if execution_mode not in ("signal", "live"):
        execution_mode = "signal"
    return {
        **raw,
        "executor_type": executor_type,
        "symbol": symbol,
        "side": side,
        "market_type": market_type,
        "leverage": leverage,
        "execution_mode": execution_mode,
    }


def preview_executor(payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = normalize_executor_payload(payload)
    kind = cfg["executor_type"]
    if kind == "grid":
        preview = _preview_grid(cfg)
    elif kind == "dca":
        preview = _preview_dca(cfg)
    elif kind == "martingale":
        preview = _preview_martingale(cfg)
    else:
        preview = _preview_layered_martingale(cfg)
    return preview.to_dict()


def executor_templates() -> Dict[str, Any]:
    return {
        "items": [
            {
                "executor_type": "grid",
                "defaults": {
                    "side": "long",
                    "market_type": "swap",
                    "timeframe": "1m",
                    "start_price": 98000,
                    "end_price": 102000,
                    "limit_price": 97000,
                    "grid_count": 8,
                    "total_amount_quote": 800,
                    "initial_position_pct": 0.2,
                    "take_profit_pct": 0.004,
                    "max_open_orders": 4,
                    "grid_mode": "arithmetic",
                    "min_spread_between_orders": 0.0005,
                },
            },
            {
                "executor_type": "dca",
                "defaults": {
                    "side": "long",
                    "market_type": "swap",
                    "timeframe": "1m",
                    "entry_price": 100000,
                    "base_order_size": 100,
                    "safety_order_size": 120,
                    "price_deviation_pct": 0.015,
                    "step_multiplier": 1.2,
                    "volume_multiplier": 1.15,
                    "max_layers": 5,
                    "take_profit_pct": 0.006,
                    "max_entry_drift_pct": 0.03,
                },
            },
            {
                "executor_type": "martingale",
                "defaults": {
                    "side": "long",
                    "market_type": "swap",
                    "timeframe": "1m",
                    "entry_price": 100000,
                    "base_order_size": 80,
                    "safety_order_size": 100,
                    "price_deviation_pct": 0.012,
                    "step_multiplier": 1.4,
                    "volume_multiplier": 1.6,
                    "max_layers": 5,
                    "take_profit_pct": 0.005,
                    "hard_stop_pct": 0.12,
                    "max_entry_drift_pct": 0.03,
                },
            },
            {
                "executor_type": "layered_martingale",
                "defaults": {
                    "side": "long",
                    "market_type": "swap",
                    "timeframe": "1m",
                    "entry_price": 100000,
                    "layer_count": 5,
                    "orders_per_layer": 3,
                    "base_order_size": 100,
                    "volume_multiplier": 1.8,
                    "intra_spacing_1_pct": 0.005,
                    "intra_spacing_2_pct": 0.008,
                    "inter_spacing_1_pct": 0.012,
                    "inter_spacing_2_pct": 0.015,
                    "inter_spacing_3_pct": 0.018,
                    "inter_spacing_4_pct": 0.022,
                    "take_profit_pct": 0.006,
                    "hard_stop_pct": 0.12,
                    "max_entry_drift_pct": 0.03,
                },
            },
        ]
    }


def build_executor_strategy_payload(payload: Dict[str, Any], *, user_id: int) -> Dict[str, Any]:
    cfg = normalize_executor_payload(payload)
    exchange_config = cfg.get("exchange_config") or cfg.get("exchangeConfig") or {}
    if not isinstance(exchange_config, dict):
        exchange_config = {}
    if cfg["execution_mode"] == "live" and not exchange_config.get("credential_id"):
        raise ValueError("LIVE_EXECUTOR_CREDENTIAL_REQUIRED")
    preview = preview_executor(cfg)
    kind = cfg["executor_type"]
    strategy_name = str(cfg.get("strategy_name") or cfg.get("name") or f"{kind.upper()} {cfg['symbol']}").strip()
    market_category = str(cfg.get("market_category") or cfg.get("market") or "Crypto").strip() or "Crypto"
    timeframe = str(cfg.get("timeframe") or "1m").strip() or "1m"
    initial_capital = max(10.0, _float(cfg.get("initial_capital") or cfg.get("investment_amount"), 1000.0))
    trade_direction = "long" if cfg["market_type"] == "spot" else cfg["side"]
    executor_config = preview["config"]
    take_profit_pct = _ratio(executor_config.get("take_profit_pct"), 0.0)
    hard_stop_pct = _ratio(executor_config.get("hard_stop_pct"), 0.0)
    trading_config = {
        "symbol": cfg["symbol"],
        "timeframe": timeframe,
        "market_type": cfg["market_type"],
        "trade_direction": trade_direction,
        "leverage": cfg["leverage"],
        "initial_capital": initial_capital,
        "investment_amount": initial_capital,
        "tick_interval_sec": 1 if kind in ("layered_martingale", "martingale", "dca") else None,
        "take_profit_pct": take_profit_pct,
        "stop_loss_pct": hard_stop_pct,
        "strategy_family": "executor",
        "executor_type": kind,
        "executor_config": executor_config,
        "executor_preview": preview,
        "bot_type": kind,
        "bot_params": _legacy_bot_params(kind, executor_config),
        "strategy_config": {
            "risk": {
                "takeProfitPct": take_profit_pct,
                "stopLossPct": hard_stop_pct,
            }
        },
    }
    generated_code = _executor_strategy_code(kind, executor_config, preview)
    strategy_code = (
        f'"""\n{strategy_name}\n'
        f'Editable {kind.replace("_", " ")} robot strategy generated from the visual builder.\n'
        f'"""\n\n# timeframe: {timeframe}\n\n{generated_code}'
    )
    return {
        "user_id": user_id,
        "strategy_name": strategy_name,
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "bot",
        "strategy_code": strategy_code,
        "market_category": market_category,
        "execution_mode": cfg["execution_mode"],
        "status": "stopped",
        "symbol": cfg["symbol"],
        "timeframe": timeframe,
        "market_type": cfg["market_type"],
        "trade_direction": trade_direction,
        "leverage": cfg["leverage"],
        "initial_capital": initial_capital,
        "trading_config": trading_config,
        "exchange_config": exchange_config,
        "notification_config": cfg.get("notification_config") or cfg.get("notificationConfig") or {},
    }


def _preview_grid(cfg: Dict[str, Any]) -> ExecutorPreview:
    start = _float(cfg.get("start_price") or cfg.get("startPrice"), 0.0)
    end = _float(cfg.get("end_price") or cfg.get("endPrice"), 0.0)
    total = max(0.0, _float(cfg.get("total_amount_quote") or cfg.get("totalAmountQuote"), 0.0))
    count = max(1, _int(cfg.get("grid_count") or cfg.get("gridCount"), 1))
    side = cfg["side"]
    mode = str(cfg.get("grid_mode") or cfg.get("gridMode") or "arithmetic").strip().lower()
    take_profit = max(0.0, _ratio(cfg.get("take_profit_pct") or cfg.get("takeProfitPct"), 0.004))
    warnings: List[str] = []
    if start <= 0 or end <= 0 or start == end:
        warnings.append("invalid_price_bounds")
    if total <= 0:
        warnings.append("missing_total_amount_quote")
    low, high = sorted([start, end])
    prices = _geospace(low, high, count) if mode == "geometric" else _linspace(low, high, count)
    if side == "long":
        prices = sorted(prices, reverse=True)
    amount = total / max(1, len(prices))
    levels = []
    for idx, price in enumerate(prices, start=1):
        level_side = side
        if side == "neutral":
            level_side = "long" if idx <= len(prices) / 2.0 else "short"
        tp = price * (1.0 + take_profit) if level_side == "long" else price * (1.0 - take_profit)
        levels.append(ExecutorLevel(idx, "open", level_side, price, amount, tp, 0.0))
    initial_position_raw = (
        cfg.get("initial_position_pct")
        if "initial_position_pct" in cfg
        else cfg.get("initialPositionPct", 0.2)
    )
    initial_position_pct = min(1.0, max(0.0, _ratio(initial_position_raw, 0.2)))
    if side == "neutral":
        initial_position_pct = 0.0
    config = {
        "side": side,
        "market_type": cfg["market_type"],
        "start_price": low,
        "end_price": high,
        "limit_price": _float(cfg.get("limit_price") or cfg.get("limitPrice"), low if side == "long" else high),
        "grid_count": count,
        "grid_mode": mode if mode in ("arithmetic", "geometric") else "arithmetic",
        "total_amount_quote": total,
        "initial_position_pct": initial_position_pct,
        "take_profit_pct": take_profit,
        "max_open_orders": max(1, _int(cfg.get("max_open_orders") or cfg.get("maxOpenOrders"), 4)),
        "min_spread_between_orders": max(0.0, _ratio(cfg.get("min_spread_between_orders") or cfg.get("minSpreadBetweenOrders"), 0.0005)),
        "order_frequency": max(0, _int(cfg.get("order_frequency") or cfg.get("orderFrequency"), 0)),
        "leverage": cfg["leverage"],
    }
    return ExecutorPreview("grid", config, levels, warnings)


def _preview_dca(cfg: Dict[str, Any]) -> ExecutorPreview:
    return _preview_layered_dca(cfg, "dca")


def _preview_martingale(cfg: Dict[str, Any]) -> ExecutorPreview:
    return _preview_layered_dca(cfg, "martingale")


def _preview_layered_martingale(cfg: Dict[str, Any]) -> ExecutorPreview:
    entry = _float(cfg.get("entry_price") or cfg.get("entryPrice"), 0.0)
    layer_count = max(1, _int(cfg.get("layer_count") or cfg.get("layerCount"), 5))
    orders_per_layer = max(1, _int(cfg.get("orders_per_layer") or cfg.get("ordersPerLayer"), 3))
    base = max(0.0, _float(cfg.get("base_order_size") or cfg.get("baseOrderSize"), 0.0))
    volume_mult = max(1.0, _float(cfg.get("volume_multiplier") or cfg.get("volumeMultiplier"), 1.8))
    take_profit = max(0.0, _ratio(cfg.get("take_profit_pct") or cfg.get("takeProfitPct"), 0.006))
    hard_stop = max(0.0, _ratio(cfg.get("hard_stop_pct") or cfg.get("hardStopPct"), 0.0))
    max_entry_drift = max(0.0, _ratio(cfg.get("max_entry_drift_pct") or cfg.get("maxEntryDriftPct"), 0.03))
    side = cfg["side"]
    intra_defaults = [
        _ratio(cfg.get("intra_spacing_1_pct") or cfg.get("intraSpacing1Pct"), 0.005),
        _ratio(cfg.get("intra_spacing_2_pct") or cfg.get("intraSpacing2Pct"), 0.008),
    ]
    inter_defaults = [
        _ratio(cfg.get("inter_spacing_1_pct") or cfg.get("interSpacing1Pct"), 0.012),
        _ratio(cfg.get("inter_spacing_2_pct") or cfg.get("interSpacing2Pct"), 0.015),
        _ratio(cfg.get("inter_spacing_3_pct") or cfg.get("interSpacing3Pct"), 0.018),
        _ratio(cfg.get("inter_spacing_4_pct") or cfg.get("interSpacing4Pct"), 0.022),
    ]
    intra_spacings = _ratio_list(
        cfg.get("intra_spacings") or cfg.get("intraSpacings"),
        intra_defaults,
        expected=max(0, orders_per_layer - 1),
    )
    inter_spacings = _ratio_list(
        cfg.get("inter_spacings") or cfg.get("interSpacings"),
        inter_defaults,
        expected=max(0, layer_count - 1),
    )
    warnings: List[str] = []
    if entry <= 0:
        warnings.append("missing_entry_price")
    if base <= 0:
        warnings.append("missing_base_order_size")
    levels: List[ExecutorLevel] = []
    price = entry
    seq = 1
    cumulative_quote = 0.0
    cumulative_quantity = 0.0
    for layer_idx in range(1, layer_count + 1):
        for order_idx in range(1, orders_per_layer + 1):
            if seq == 1:
                price = entry
                trigger = 0.0
            elif order_idx == 1:
                spacing = inter_spacings[layer_idx - 2] if layer_idx >= 2 and inter_spacings else 0.0
                price = price * (1.0 - spacing) if side == "long" else price * (1.0 + spacing)
                trigger = spacing
            else:
                spacing = intra_spacings[order_idx - 2] if intra_spacings else 0.0
                price = price * (1.0 - spacing) if side == "long" else price * (1.0 + spacing)
                trigger = spacing
            amount = base * (volume_mult ** (order_idx - 1))
            cumulative_quote += amount
            if price > 0:
                cumulative_quantity += amount / price
            tp = _basket_take_profit_price(
                total_quote=cumulative_quote,
                total_quantity=cumulative_quantity,
                side=side,
                take_profit=take_profit,
            )
            levels.append(
                ExecutorLevel(
                    seq,
                    "open" if seq == 1 else "add",
                    side,
                    price,
                    amount,
                    tp,
                    trigger,
                    layer_index=layer_idx,
                    order_index=order_idx,
                )
            )
            seq += 1
    config = {
        "side": side,
        "market_type": cfg["market_type"],
        "entry_price": entry,
        "layer_count": layer_count,
        "orders_per_layer": orders_per_layer,
        "base_order_size": base,
        "volume_multiplier": volume_mult,
        "intra_spacings": intra_spacings,
        "inter_spacings": inter_spacings,
        "take_profit_pct": take_profit,
        "hard_stop_pct": hard_stop,
        "max_entry_drift_pct": max_entry_drift,
        "leverage": cfg["leverage"],
    }
    return ExecutorPreview("layered_martingale", config, levels, warnings)


def _preview_layered_dca(cfg: Dict[str, Any], kind: str) -> ExecutorPreview:
    entry = _float(cfg.get("entry_price") or cfg.get("entryPrice"), 0.0)
    base = max(0.0, _float(cfg.get("base_order_size") or cfg.get("baseOrderSize"), 0.0))
    safety = max(0.0, _float(cfg.get("safety_order_size") or cfg.get("safetyOrderSize"), base))
    max_layers = max(1, _int(cfg.get("max_layers") or cfg.get("maxLayers"), 1))
    deviation = max(0.0, _ratio(cfg.get("price_deviation_pct") or cfg.get("priceDeviationPct"), 0.01))
    step_mult = max(1.0, _float(cfg.get("step_multiplier") or cfg.get("stepMultiplier"), 1.0))
    volume_mult = max(1.0, _float(cfg.get("volume_multiplier") or cfg.get("volumeMultiplier"), 1.0))
    take_profit = max(0.0, _ratio(cfg.get("take_profit_pct") or cfg.get("takeProfitPct"), 0.005))
    max_entry_drift = max(0.0, _ratio(cfg.get("max_entry_drift_pct") or cfg.get("maxEntryDriftPct"), 0.03))
    side = cfg["side"]
    warnings: List[str] = []
    if entry <= 0:
        warnings.append("missing_entry_price")
    if base <= 0:
        warnings.append("missing_base_order_size")
    levels = []
    cumulative_deviation = 0.0
    cumulative_quote = 0.0
    cumulative_quantity = 0.0
    for layer in range(1, max_layers + 1):
        if layer == 1:
            amount = base
            price = entry
            trigger = 0.0
        else:
            trigger = deviation * (step_mult ** (layer - 2))
            cumulative_deviation += trigger
            price = entry * (1.0 - cumulative_deviation) if side == "long" else entry * (1.0 + cumulative_deviation)
            amount = safety * (volume_mult ** (layer - 2))
        cumulative_quote += amount
        if price > 0:
            cumulative_quantity += amount / price
        tp = _basket_take_profit_price(
            total_quote=cumulative_quote,
            total_quantity=cumulative_quantity,
            side=side,
            take_profit=take_profit,
        )
        levels.append(ExecutorLevel(layer, "open" if layer == 1 else "add", side, price, amount, tp, trigger))
    config = {
        "side": side,
        "market_type": cfg["market_type"],
        "entry_price": entry,
        "base_order_size": base,
        "safety_order_size": safety,
        "max_layers": max_layers,
        "price_deviation_pct": deviation,
        "step_multiplier": step_mult,
        "volume_multiplier": volume_mult,
        "take_profit_pct": take_profit,
        "hard_stop_pct": max(0.0, _ratio(cfg.get("hard_stop_pct") or cfg.get("hardStopPct"), 0.0)),
        "max_entry_drift_pct": max_entry_drift,
        "leverage": cfg["leverage"],
    }
    return ExecutorPreview(kind, config, levels, warnings)


def _legacy_bot_params(kind: str, config: Dict[str, Any]) -> Dict[str, Any]:
    side = config.get("side") or "long"
    take_profit_pct = float(config.get("take_profit_pct") or 0.0)
    hard_stop_pct = float(config.get("hard_stop_pct") or 0.0)
    base = float(config.get("base_order_size") or 0.0)
    safety = float(config.get("safety_order_size") or base or 0.0)
    max_layers = max(1, int(config.get("max_layers") or 1))
    volume_multiplier = max(1.0, float(config.get("volume_multiplier") or 1.0))
    total_amount = float(config.get("total_amount_quote") or 0.0)
    if total_amount <= 0 and kind in ("dca", "martingale"):
        total_amount = base
        for layer in range(2, max_layers + 1):
            total_amount += safety * (volume_multiplier ** (layer - 2))
    if kind == "grid":
        return {
            "lowerPrice": config.get("start_price"),
            "upperPrice": config.get("end_price"),
            "gridCount": config.get("grid_count"),
            "amountPerGrid": (
                float(config.get("total_amount_quote") or 0.0) / max(1, int(config.get("grid_count") or 1))
            ),
            "gridMode": config.get("grid_mode") or "arithmetic",
            "gridDirection": config.get("side") or "long",
            "orderMode": "maker",
            "boundaryAction": "pause",
            "initialPositionPct": float(config.get("initial_position_pct") or 0.0) * 100.0,
            "maxOpenOrders": config.get("max_open_orders") or 999999,
            "minSpreadBetweenOrders": config.get("min_spread_between_orders") or 0.0,
            "orderFrequency": config.get("order_frequency") or 0,
        }
    if kind == "martingale":
        return {
            "direction": side,
            "multiplier": volume_multiplier,
            "maxLayers": max_layers,
            "priceDropPct": float(config.get("price_deviation_pct") or 0.0) * 100.0,
            "takeProfitPct": take_profit_pct * 100.0,
            "stopLossPct": hard_stop_pct * 100.0,
            "trailingTpEnabled": False,
            "trailingTpCallbackPct": 0.8,
            "waterfallProtection": True,
            "waterfallDropPct": max(0.005, float(config.get("price_deviation_pct") or 0.0) * 2.0),
        }
    if kind == "dca":
        return {
            "direction": side,
            "frequency": "every_bar",
            "amountEach": base,
            "totalBudget": total_amount,
            "dipBuyEnabled": True,
            "dipThreshold": float(config.get("price_deviation_pct") or 0.0) * 100.0,
            "takeProfitPct": take_profit_pct,
            "stopLossPct": hard_stop_pct,
        }
    if kind == "layered_martingale":
        return {
            "direction": side,
            "layerCount": int(config.get("layer_count") or 5),
            "ordersPerLayer": int(config.get("orders_per_layer") or 3),
            "baseOrderSize": base,
            "multiplier": volume_multiplier,
            "intraSpacings": list(config.get("intra_spacings") or []),
            "interSpacings": list(config.get("inter_spacings") or []),
            "takeProfitPct": take_profit_pct,
            "stopLossPct": hard_stop_pct,
        }
    return dict(config)


def executor_runtime_params(kind: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Compile an editable robot definition into host runtime parameters."""
    clean_kind = str(kind or "").strip().lower()
    if clean_kind not in EXECUTOR_TYPES:
        raise ValueError(f"unsupported_executor_type:{clean_kind}")
    if not isinstance(config, dict):
        raise ValueError("invalid_executor_config")
    return _legacy_bot_params(clean_kind, dict(config))


def _executor_strategy_code(kind: str, config: Dict[str, Any], preview: Dict[str, Any]) -> str:
    if kind == "grid":
        return _grid_strategy_code(config, preview)
    if kind in ("dca", "martingale"):
        return _layered_dca_strategy_code(kind, config, preview)
    if kind == "layered_martingale":
        return _layered_martingale_strategy_code(config, preview)
    return """def on_bar(ctx, bar):
    pass
"""


def _grid_strategy_code(config: Dict[str, Any], preview: Dict[str, Any]) -> str:
    levels = [
        {
            "level": int((item or {}).get("level") or 0),
            "side": str((item or {}).get("side") or "long"),
            "price": float((item or {}).get("price") or 0.0),
            "amount_quote": float((item or {}).get("amount_quote") or 0.0),
        }
        for item in (preview.get("levels") or [])
    ]
    take_profit = float(config.get("take_profit_pct") or 0.0)
    return f'''# Built-in grid robot definition.
# Live mode uses durable resting orders, fill polling, and reconciliation from the host.
# Backtests use the candle high/low crossing model below and therefore remain bar-resolution simulations.

ROBOT_CONFIG = {repr(dict(config))}
GRID_LEVELS = {repr(levels)}
TAKE_PROFIT = {take_profit!r}

def on_init(ctx):
    ctx.configure_robot("grid", ROBOT_CONFIG)
    if ctx.state.get("grid_submitted") is None:
        ctx.state.set("grid_submitted", {{}})
    ctx.log("grid robot configured")

def _is_backtest(ctx):
    return str(ctx.runtime.get("execution_environment", "")).lower() == "backtest"

def _position(ctx, side):
    try:
        return ctx.positions.get(side, {{}})
    except Exception:
        return {{}}

def _reset_side(ctx, side):
    submitted = dict(ctx.state.get("grid_submitted", {{}}) or {{}})
    for key in list(submitted.keys()):
        if key.startswith(side + ":"):
            submitted.pop(key, None)
    ctx.state.set("grid_submitted", submitted)

def on_bar(ctx, bar):
    if not _is_backtest(ctx):
        return
    submitted = dict(ctx.state.get("grid_submitted", {{}}) or {{}})
    for side in ("long", "short"):
        position = _position(ctx, side)
        size = float(position.get("size", 0.0) or 0.0)
        entry = float(position.get("entry_price", 0.0) or 0.0)
        if size <= 0 or entry <= 0 or TAKE_PROFIT <= 0:
            continue
        reached = bar.high >= entry * (1.0 + TAKE_PROFIT) if side == "long" else bar.low <= entry * (1.0 - TAKE_PROFIT)
        if reached:
            ctx.basket(side).close_all(reason="grid_take_profit")
            _reset_side(ctx, side)
            return
    for level in GRID_LEVELS:
        side = str(level.get("side") or "long")
        price = float(level.get("price") or 0.0)
        amount = float(level.get("amount_quote") or 0.0)
        key = "%s:%s" % (side, int(level.get("level") or 0))
        if submitted.get(key) or price <= 0 or amount <= 0:
            continue
        if float(bar.low) <= price <= float(bar.high):
            side_has_orders = any(existing.startswith(side + ":") for existing in submitted)
            ctx.basket(side).open_child_order(
                layer=int(level.get("level") or 1),
                order=1,
                notional=amount,
                price=price,
                action="add" if side_has_orders else "open",
                payload={{"reason": "grid_level"}},
            )
            submitted[key] = True
    ctx.state.set("grid_submitted", submitted)
'''


def _layered_dca_strategy_code(kind: str, config: Dict[str, Any], preview: Dict[str, Any]) -> str:
    levels = preview.get("levels") if isinstance(preview, dict) else []
    prices = [float((level or {}).get("price") or 0.0) for level in levels or []]
    amounts = [float((level or {}).get("amount_quote") or 0.0) for level in levels or []]
    side = str(config.get("side") or "long").strip().lower()
    if side not in ("long", "short"):
        side = "long"
    take_profit = float(config.get("take_profit_pct") or 0.0)
    hard_stop = float(config.get("hard_stop_pct") or 0.0)
    max_entry_drift = float(config.get("max_entry_drift_pct") or 0.0)
    label = "Martingale" if kind == "martingale" else "DCA"
    return f"""# Built-in {label} executor.
# Prices and quote amounts are generated from the executor config before runtime.

PRICES = {repr(prices)}
AMOUNTS = {repr(amounts)}
SIDE = {repr(side)}
TAKE_PROFIT = {take_profit!r}
HARD_STOP = {hard_stop!r}
MAX_ENTRY_DRIFT = {max_entry_drift!r}

def on_init(ctx):
    if ctx.state.get("next_level") is None:
        ctx.state.set("next_level", 0)
    if ctx.state.get("total_cost") is None:
        ctx.state.set("total_cost", 0.0)
    if ctx.state.get("total_qty") is None:
        ctx.state.set("total_qty", 0.0)

def _reset(ctx):
    ctx.state.update({{"next_level": 0, "total_cost": 0.0, "total_qty": 0.0}})

def _has_position(ctx):
    try:
        return bool(ctx.position and float(ctx.position.get("size", 0)) > 0)
    except Exception:
        return False

def _avg_price(ctx):
    try:
        actual = float(ctx.position.get("entry_price", 0) or 0)
        if actual > 0:
            return actual
    except Exception:
        pass
    total_cost = float(ctx.state.get("total_cost", 0.0) or 0.0)
    total_qty = float(ctx.state.get("total_qty", 0.0) or 0.0)
    return total_cost / total_qty if total_cost > 0 and total_qty > 0 else 0.0

def _entry_due(level, price):
    if level <= 0:
        return True
    target = float(PRICES[level] or 0.0)
    if target <= 0:
        return False
    if SIDE == "short":
        return price >= target
    return price <= target

def _open_level(ctx, level, price):
    amount = float(AMOUNTS[level] or 0.0)
    if amount <= 0 or price <= 0:
        return
    ctx.basket(SIDE).open_child_order(
        layer=level + 1,
        order=1,
        notional=amount,
        price=price,
        action="open" if level == 0 else "add",
        payload={{"reason": "{kind}_level"}},
    )
    ctx.state.set("next_level", level + 1)
    ctx.state.set("total_cost", float(ctx.state.get("total_cost", 0.0) or 0.0) + amount)
    ctx.state.set("total_qty", float(ctx.state.get("total_qty", 0.0) or 0.0) + (amount / price))
    ctx.log("{label} level %d submitted: %.2f quote @ %.8f" % (level + 1, amount, price))

def on_bar(ctx, bar):
    price = float(bar.close or 0.0)
    if price <= 0 or not PRICES or not AMOUNTS:
        return
    next_level = int(ctx.state.get("next_level", 0) or 0)
    if next_level == 0 and MAX_ENTRY_DRIFT > 0 and float(PRICES[0] or 0.0) > 0:
        entry_drift = abs(price - float(PRICES[0])) / float(PRICES[0])
        if entry_drift > MAX_ENTRY_DRIFT:
            ctx.log("{label} entry blocked: market drift %.4f exceeds %.4f" % (entry_drift, MAX_ENTRY_DRIFT))
            return
    has_pos = _has_position(ctx)
    if not has_pos and next_level > 0:
        _reset(ctx)
        next_level = 0

    if has_pos:
        avg = _avg_price(ctx)
        if avg > 0:
            if SIDE == "short":
                profit = (avg - price) / avg
                loss = (price - avg) / avg
            else:
                profit = (price - avg) / avg
                loss = (avg - price) / avg
            if TAKE_PROFIT > 0 and profit >= TAKE_PROFIT:
                ctx.basket(SIDE).close_all(reason="{kind}_take_profit")
                _reset(ctx)
                ctx.log("{label} take-profit submitted")
                return
            if HARD_STOP > 0 and loss >= HARD_STOP:
                ctx.basket(SIDE).close_all(reason="{kind}_hard_stop")
                _reset(ctx)
                ctx.log("{label} hard-stop submitted")
                return

    if next_level < len(PRICES) and _entry_due(next_level, price):
        _open_level(ctx, next_level, price)
"""


def _layered_martingale_strategy_code(config: Dict[str, Any], preview: Dict[str, Any]) -> str:
    levels = preview.get("levels") if isinstance(preview, dict) else []
    prices = [float((level or {}).get("price") or 0.0) for level in levels or []]
    amounts = [float((level or {}).get("amount_quote") or 0.0) for level in levels or []]
    layer_indexes = [int((level or {}).get("layer_index") or 0) for level in levels or []]
    order_indexes = [int((level or {}).get("order_index") or 0) for level in levels or []]
    side = str(config.get("side") or "long").strip().lower()
    if side not in ("long", "short"):
        side = "long"
    take_profit = float(config.get("take_profit_pct") or 0.0)
    hard_stop = float(config.get("hard_stop_pct") or 0.0)
    max_entry_drift = float(config.get("max_entry_drift_pct") or 0.0)
    return f"""# Built-in layered martingale basket executor.
# It runs sequential basket child orders: layer -> order -> next layer.

PRICES = {repr(prices)}
AMOUNTS = {repr(amounts)}
LAYERS = {repr(layer_indexes)}
ORDERS = {repr(order_indexes)}
SIDE = {repr(side)}
TAKE_PROFIT = {take_profit!r}
HARD_STOP = {hard_stop!r}
MAX_ENTRY_DRIFT = {max_entry_drift!r}

def on_init(ctx):
    if ctx.state.get("next_index") is None:
        ctx.state.set("next_index", 0)
    if ctx.state.get("total_cost") is None:
        ctx.state.set("total_cost", 0.0)
    if ctx.state.get("total_qty") is None:
        ctx.state.set("total_qty", 0.0)

def _reset(ctx):
    ctx.state.update({{"next_index": 0, "total_cost": 0.0, "total_qty": 0.0}})

def _has_position(ctx):
    try:
        return bool(ctx.position and float(ctx.position.get("size", 0)) > 0)
    except Exception:
        return False

def _avg_price(ctx):
    try:
        actual = float(ctx.position.get("entry_price", 0) or 0)
        if actual > 0:
            return actual
    except Exception:
        pass
    total_cost = float(ctx.state.get("total_cost", 0.0) or 0.0)
    total_qty = float(ctx.state.get("total_qty", 0.0) or 0.0)
    return total_cost / total_qty if total_cost > 0 and total_qty > 0 else 0.0

def _entry_due(index, price):
    if index <= 0:
        return True
    target = float(PRICES[index] or 0.0)
    if target <= 0:
        return False
    if SIDE == "short":
        return price >= target
    return price <= target

def _submit_child(ctx, index, price):
    amount = float(AMOUNTS[index] or 0.0)
    if amount <= 0 or price <= 0:
        return
    layer = int(LAYERS[index] or 1)
    order = int(ORDERS[index] or 1)
    action = "open" if index == 0 else "add"
    ctx.basket(SIDE).open_child_order(
        layer=layer,
        order=order,
        notional=amount,
        price=price,
        action=action,
        payload={{"reason": "layered_martingale_child"}},
    )
    ctx.state.set("next_index", index + 1)
    ctx.state.set("total_cost", float(ctx.state.get("total_cost", 0.0) or 0.0) + amount)
    ctx.state.set("total_qty", float(ctx.state.get("total_qty", 0.0) or 0.0) + (amount / price))
    ctx.log("Layered martingale L%d/O%d submitted: %.2f quote @ %.8f" % (layer, order, amount, price))

def on_bar(ctx, bar):
    price = float(bar.close or 0.0)
    if price <= 0 or not PRICES or not AMOUNTS:
        return
    next_index = int(ctx.state.get("next_index", 0) or 0)
    if next_index == 0 and MAX_ENTRY_DRIFT > 0 and float(PRICES[0] or 0.0) > 0:
        entry_drift = abs(price - float(PRICES[0])) / float(PRICES[0])
        if entry_drift > MAX_ENTRY_DRIFT:
            ctx.log("Layered martingale entry blocked: market drift %.4f exceeds %.4f" % (entry_drift, MAX_ENTRY_DRIFT))
            return
    has_pos = _has_position(ctx)
    if not has_pos and next_index > 0:
        _reset(ctx)
        next_index = 0

    if has_pos:
        avg = _avg_price(ctx)
        if avg > 0:
            if SIDE == "short":
                profit = (avg - price) / avg
                loss = (price - avg) / avg
            else:
                profit = (price - avg) / avg
                loss = (avg - price) / avg
            if TAKE_PROFIT > 0 and profit >= TAKE_PROFIT:
                ctx.basket(SIDE).close_all(reason="layered_martingale_take_profit")
                _reset(ctx)
                ctx.log("Layered martingale average take-profit submitted")
                return
            if HARD_STOP > 0 and loss >= HARD_STOP:
                ctx.basket(SIDE).close_all(reason="layered_martingale_hard_stop")
                _reset(ctx)
                ctx.log("Layered martingale hard-stop submitted")
                return

    if next_index < len(PRICES) and _entry_due(next_index, price):
        _submit_child(ctx, next_index, price)
"""
