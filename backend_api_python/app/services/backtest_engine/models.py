from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIAL = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    commission: float = 0.0
    slippage: float = 0.0
    leverage: float = 1.0
    trade_direction: str = "both"
    timeframe: str = "1D"
    market_type: str = "swap"
    funding_rate_annual: float = 0.0
    funding_interval_hours: float = 8.0
    signal_timing: str = "next_bar_open"
    entry_pct: float = 1.0
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    trailing_enabled: bool = False
    trailing_pct: float = 0.0
    trailing_activation_pct: float = 0.0
    max_holding_bars: int = 0
    strict_bar_fill: bool = True
    intrabar_mode: str = "conservative"
    maintenance_margin_rate: float = 0.005
    liquidation_fee_rate: float = 0.0

    def __post_init__(self) -> None:
        self.trade_direction = _normalize_direction(self.trade_direction)
        self.signal_timing = str(self.signal_timing or "next_bar_open").strip().lower()
        self.intrabar_mode = _normalize_intrabar_mode(self.intrabar_mode)
        self.initial_capital = max(0.0, float(self.initial_capital or 0.0))
        self.commission = max(0.0, float(self.commission or 0.0))
        self.slippage = max(0.0, float(self.slippage or 0.0))
        self.leverage = max(1.0, float(self.leverage or 1.0))
        self.entry_pct = max(float(self.entry_pct or 0.0), 0.0)
        if self.entry_pct > 1:
            self.entry_pct = self.entry_pct / 100.0
        self.entry_pct = min(self.entry_pct, 1.0)
        self.stop_loss_pct = max(0.0, float(self.stop_loss_pct or 0.0))
        self.take_profit_pct = max(0.0, float(self.take_profit_pct or 0.0))
        self.trailing_pct = max(0.0, float(self.trailing_pct or 0.0))
        self.trailing_activation_pct = max(0.0, float(self.trailing_activation_pct or 0.0))
        self.max_holding_bars = max(0, int(self.max_holding_bars or 0))
        self.market_type = str(self.market_type or "swap").strip().lower()
        if self.market_type not in ("spot", "swap"):
            self.market_type = "swap"
        self.funding_rate_annual = float(self.funding_rate_annual or 0.0)
        if abs(self.funding_rate_annual) > 1.5:
            self.funding_rate_annual = self.funding_rate_annual / 100.0
        self.funding_interval_hours = max(1.0, float(self.funding_interval_hours or 8.0))
        self.maintenance_margin_rate = min(0.5, max(0.0, float(self.maintenance_margin_rate or 0.0)))
        self.liquidation_fee_rate = min(0.5, max(0.0, float(self.liquidation_fee_rate or 0.0)))
        if self.market_type == "spot":
            self.leverage = 1.0
            self.trade_direction = "long"
            self.funding_rate_annual = 0.0
        self.strict_bar_fill = self.signal_timing in ("next_bar_open", "next_open", "nextopen", "next")

    @classmethod
    def from_strategy_config(
        cls,
        strategy_config: Optional[Dict[str, Any]],
        *,
        initial_capital: float,
        commission: float,
        slippage: float,
        leverage: float,
        trade_direction: str,
        timeframe: str,
    ) -> "BacktestConfig":
        cfg = strategy_config or {}
        exec_cfg = cfg.get("execution") or {}
        risk_cfg = cfg.get("risk") or {}
        pos_cfg = cfg.get("position") or {}
        trailing_cfg = risk_cfg.get("trailing") or {}
        fees_cfg = cfg.get("fees") or {}
        margin_cfg = cfg.get("margin") or {}
        market_type = str(cfg.get("market_type") or cfg.get("marketType") or "swap").strip().lower()
        signal_timing = str(exec_cfg.get("signalTiming") or "next_bar_open").strip().lower()
        intrabar_mode = _normalize_intrabar_mode(
            exec_cfg.get("intrabarMode")
            or exec_cfg.get("intrabar_mode")
            or cfg.get("intrabarMode")
            or cfg.get("intrabar_mode")
        )
        entry_pct = _to_float(pos_cfg.get("entryPct"), 1.0)
        if entry_pct > 1:
            entry_pct = entry_pct / 100.0
        entry_pct = min(max(entry_pct, 0.0), 1.0)
        stop_loss = _to_float(risk_cfg.get("stopLossPct"), 0.0)
        take_profit = _to_float(risk_cfg.get("takeProfitPct"), 0.0)
        trailing_enabled = bool(trailing_cfg.get("enabled"))
        trailing_pct = _to_float(trailing_cfg.get("pct"), 0.0)
        trailing_activation = _to_float(trailing_cfg.get("activationPct"), 0.0)
        max_holding_bars = _to_int(risk_cfg.get("maxHoldingBars"), 0)
        if trailing_enabled and trailing_pct > 0 and trailing_activation <= 0 and take_profit > 0:
            trailing_activation = take_profit
        return cls(
            initial_capital=float(initial_capital or 0.0),
            commission=max(0.0, float(commission or 0.0)),
            slippage=max(0.0, float(slippage or 0.0)),
            leverage=max(1.0, float(leverage or 1.0)),
            trade_direction=_normalize_direction(trade_direction),
            timeframe=str(timeframe or "1D"),
            market_type=market_type if market_type in ("spot", "swap") else "swap",
            funding_rate_annual=_to_float(fees_cfg.get("fundingRateAnnual"), 0.0),
            funding_interval_hours=_to_float(fees_cfg.get("fundingIntervalHours"), 8.0),
            signal_timing=signal_timing,
            entry_pct=entry_pct,
            stop_loss_pct=max(0.0, stop_loss),
            take_profit_pct=max(0.0, take_profit),
            trailing_enabled=trailing_enabled,
            trailing_pct=max(0.0, trailing_pct),
            trailing_activation_pct=max(0.0, trailing_activation),
            max_holding_bars=max(0, max_holding_bars),
            strict_bar_fill=signal_timing in ("next_bar_open", "next_open", "nextopen", "next"),
            intrabar_mode=intrabar_mode,
            maintenance_margin_rate=_to_float(
                margin_cfg.get("maintenanceMarginRate", cfg.get("maintenanceMarginRate", 0.005)),
                0.005,
            ),
            liquidation_fee_rate=_to_float(
                margin_cfg.get("liquidationFeeRate", cfg.get("liquidationFeeRate", 0.0)),
                0.0,
            ),
        )


@dataclass
class Order:
    id: int
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    position_side: str = ""
    reduce_only: bool = False
    quantity: float = 0.0
    notional: float = 0.0
    limit_price: float = 0.0
    stop_price: float = 0.0
    submitted_bar: int = 0
    created_time: Any = None
    reason: str = ""
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    fee: float = 0.0
    oco_group: str = ""
    valid_until_bar: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Execution:
    order_id: int
    time: Any
    bar_index: int
    side: str
    position_side: str
    quantity: float
    price: float
    fee: float
    pnl: float
    balance: float
    reason: str
    action: str


@dataclass
class Position:
    side: str
    size: float = 0.0
    avg_price: float = 0.0
    highest: float = 0.0
    lowest: float = 0.0
    opened_bar: int = -1
    opened_time: Any = None

    def is_open(self) -> bool:
        return self.size > 1e-12

    def reset(self) -> None:
        self.size = 0.0
        self.avg_price = 0.0
        self.highest = 0.0
        self.lowest = 0.0
        self.opened_bar = -1
        self.opened_time = None

    def mark_extremes(self, high: float, low: float) -> None:
        if not self.is_open():
            return
        if self.highest <= 0:
            self.highest = self.avg_price
        if self.lowest <= 0:
            self.lowest = self.avg_price
        self.highest = max(float(high or 0.0), self.highest)
        self.lowest = min(float(low or 0.0), self.lowest)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_direction(value: Any) -> str:
    direction = str(value or "both").strip().lower()
    return direction if direction in ("long", "short", "both") else "both"


def _normalize_intrabar_mode(value: Any) -> str:
    mode = str(value or "conservative").strip().lower()
    aliases = {
        "safe": "conservative",
        "pessimistic": "conservative",
        "strict": "conservative",
        "normal": "balanced",
        "neutral": "balanced",
        "standard": "balanced",
        "optimistic": "aggressive",
        "fast": "aggressive",
    }
    mode = aliases.get(mode, mode)
    return mode if mode in ("conservative", "balanced", "aggressive") else "conservative"
