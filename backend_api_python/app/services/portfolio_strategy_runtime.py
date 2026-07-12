"""Sandboxed portfolio-strategy contract and target-weight validation."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

import numpy as np
import pandas as pd


FORBIDDEN_ORDER_METHODS = frozenset({
    "buy", "sell", "order", "order_value", "order_target_value",
    "open_long", "close_long", "add_long", "reduce_long",
    "open_short", "close_short", "add_short", "reduce_short",
})
SUPPORTED_REBALANCE_FREQUENCIES = frozenset({"daily", "weekly", "monthly"})
_EPSILON = 1e-9


class PortfolioStrategyError(ValueError):
    """Stable portfolio-strategy contract error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PortfolioConstraints:
    long_only: bool = True
    max_weight: float = 1.0
    gross_limit: float = 1.0
    net_limit: float = 1.0
    min_weight: float = 0.0

    def normalized(self) -> "PortfolioConstraints":
        max_weight = _positive(self.max_weight, "portfolio.invalidMaxWeight")
        gross_limit = _positive(self.gross_limit, "portfolio.invalidGrossLimit")
        net_limit = _positive(self.net_limit, "portfolio.invalidNetLimit")
        min_weight = max(0.0, float(self.min_weight or 0.0))
        if max_weight > gross_limit + _EPSILON:
            raise PortfolioStrategyError("portfolio.maxWeightExceedsGross")
        return PortfolioConstraints(
            long_only=bool(self.long_only),
            max_weight=max_weight,
            gross_limit=gross_limit,
            net_limit=net_limit,
            min_weight=min_weight,
        )


@dataclass(frozen=True)
class TargetWeightPlan:
    weights: dict[str, float]
    gross_exposure: float
    net_exposure: float
    cash_weight: float
    rebalance_group: str = ""

    def as_dict(self) -> dict:
        return {
            "weights": dict(self.weights),
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "cash_weight": self.cash_weight,
            "rebalance_group": self.rebalance_group,
        }


class PortfolioContext:
    """Context exposed to `on_init` and `on_rebalance` handlers."""

    def __init__(
        self,
        *,
        universe: Iterable[str],
        params: Optional[Mapping[str, Any]] = None,
        constraints: Optional[PortfolioConstraints] = None,
        runtime: Optional[Mapping[str, Any]] = None,
    ):
        self.universe = tuple(sorted({str(symbol or "").strip().upper() for symbol in universe if symbol}))
        self._universe_set = frozenset(self.universe)
        self._params = dict(params or {})
        self.constraints = (constraints or PortfolioConstraints()).normalized()
        self.runtime = dict(runtime or {})
        from app.services.ai_decision import UnavailableAIDecisionClient

        self.ai = UnavailableAIDecisionClient()
        self.current_dt: Any = None
        self._plan: Optional[TargetWeightPlan] = None
        self._logs: list[str] = []

    def update_universe(self, symbols: Iterable[str]) -> None:
        """Replace the point-in-time eligible universe before a rebalance call."""
        normalized = tuple(sorted({
            str(symbol or "").strip().upper() for symbol in symbols if symbol
        }))
        self.universe = normalized
        self._universe_set = frozenset(normalized)

    def param(self, name: str, default: Any = None, **_: Any) -> Any:
        key = str(name or "").strip()
        if not key:
            raise PortfolioStrategyError("portfolio.invalidParameterName")
        if key not in self._params:
            self._params[key] = default
        return self._params[key]

    @staticmethod
    def rank(scores: Mapping[str, Any], *, descending: bool = True) -> list[str]:
        clean = _clean_scores(scores)
        return [
            symbol for symbol, _ in sorted(
                clean.items(),
                key=lambda item: ((-item[1]) if descending else item[1], item[0]),
            )
        ]

    def top_n(self, scores: Mapping[str, Any], n: int, *, descending: bool = True) -> list[str]:
        count = max(0, int(n or 0))
        return [symbol for symbol in self.rank(scores, descending=descending) if symbol in self._universe_set][:count]

    def equal_weight(self, symbols: Iterable[str], *, max_weight: Optional[float] = None) -> TargetWeightPlan:
        selected = sorted({str(symbol or "").strip().upper() for symbol in symbols if symbol})
        if not selected:
            return self.set_target_weights({})
        cap = self.constraints.max_weight if max_weight is None else min(
            self.constraints.max_weight,
            _positive(max_weight, "portfolio.invalidMaxWeight"),
        )
        weight = min(1.0 / len(selected), cap)
        return self.set_target_weights({symbol: weight for symbol in selected})

    def long_only_top_n(
        self,
        scores: Mapping[str, Any],
        *,
        n: int,
        max_weight: Optional[float] = None,
    ) -> TargetWeightPlan:
        if not self.constraints.long_only:
            raise PortfolioStrategyError("portfolio.longOnlyHelperRequiresLongOnly")
        return self.equal_weight(self.top_n(scores, n, descending=True), max_weight=max_weight)

    @staticmethod
    def factor(factor_id: str, panel: Mapping[str, pd.DataFrame], **params: Any) -> dict[str, float]:
        from app.services.factors import compute_panel_factor

        return compute_panel_factor(factor_id, panel, params)

    def bind_ai(self, client: Any) -> None:
        self.ai = client

    def ask_ai(self, prompt: str = "", **kwargs: Any):
        return self.ai.evaluate(prompt, **kwargs)

    def set_target_weights(
        self,
        weights: Mapping[str, Any],
        *,
        gross_limit: Optional[float] = None,
        net_limit: Optional[float] = None,
        rebalance_group: str = "",
    ) -> TargetWeightPlan:
        if self._plan is not None:
            raise PortfolioStrategyError("portfolio.targetWeightsAlreadySet")
        constraints = self.constraints
        effective = PortfolioConstraints(
            long_only=constraints.long_only,
            max_weight=constraints.max_weight,
            gross_limit=_tightened_limit(
                constraints.gross_limit, gross_limit, "portfolio.grossLimitCannotRelax",
            ),
            net_limit=_tightened_limit(
                constraints.net_limit, net_limit, "portfolio.netLimitCannotRelax",
            ),
            min_weight=constraints.min_weight,
        ).normalized()
        self._plan = validate_target_weights(
            weights,
            universe=self._universe_set,
            constraints=effective,
            rebalance_group=rebalance_group,
        )
        return self._plan

    def log(self, message: Any) -> None:
        self._logs.append(str(message or "")[:1000])

    def consume_plan(self) -> TargetWeightPlan:
        return self._plan or validate_target_weights(
            {}, universe=self._universe_set, constraints=self.constraints,
        )

    def reset_rebalance(self, current_dt: Any) -> None:
        self.current_dt = current_dt
        self._plan = None

    def flush_logs(self) -> list[str]:
        logs = list(self._logs)
        self._logs.clear()
        return logs


def validate_target_weights(
    raw_weights: Mapping[str, Any],
    *,
    universe: Iterable[str],
    constraints: Optional[PortfolioConstraints] = None,
    rebalance_group: str = "",
) -> TargetWeightPlan:
    """Validate a target portfolio without silently normalizing user intent."""
    if not isinstance(raw_weights, Mapping):
        raise PortfolioStrategyError("portfolio.targetWeightsMustBeMapping")
    limits = (constraints or PortfolioConstraints()).normalized()
    allowed = frozenset(str(symbol or "").strip().upper() for symbol in universe)
    weights: dict[str, float] = {}
    for raw_symbol, raw_weight in raw_weights.items():
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol or symbol not in allowed:
            raise PortfolioStrategyError("portfolio.symbolOutsideUniverse")
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError) as exc:
            raise PortfolioStrategyError("portfolio.invalidWeight") from exc
        if not math.isfinite(weight):
            raise PortfolioStrategyError("portfolio.invalidWeight")
        if limits.long_only and weight < -_EPSILON:
            raise PortfolioStrategyError("portfolio.negativeWeightInLongOnly")
        if abs(weight) > limits.max_weight + _EPSILON:
            raise PortfolioStrategyError("portfolio.maxWeightExceeded")
        if abs(weight) <= max(_EPSILON, limits.min_weight):
            continue
        weights[symbol] = weight

    weights = dict(sorted(weights.items()))
    gross = sum(abs(weight) for weight in weights.values())
    net = sum(weights.values())
    if gross > limits.gross_limit + _EPSILON:
        raise PortfolioStrategyError("portfolio.grossLimitExceeded")
    if abs(net) > limits.net_limit + _EPSILON:
        raise PortfolioStrategyError("portfolio.netLimitExceeded")
    cash_weight = max(0.0, 1.0 - max(0.0, net)) if limits.long_only else 0.0
    return TargetWeightPlan(
        weights=weights,
        gross_exposure=round(gross, 12),
        net_exposure=round(net, 12),
        cash_weight=round(cash_weight, 12),
        rebalance_group=str(rebalance_group or "")[:128],
    )


def rebalance_dates(index: Iterable[Any], frequency: str) -> list[pd.Timestamp]:
    """Return the first available trading session of each requested period."""
    normalized_frequency = str(frequency or "").strip().lower()
    if normalized_frequency not in SUPPORTED_REBALANCE_FREQUENCIES:
        raise PortfolioStrategyError("portfolio.invalidRebalanceFrequency")
    dates = pd.DatetimeIndex(pd.to_datetime(list(index))).sort_values().unique()
    if normalized_frequency == "daily":
        return [pd.Timestamp(item) for item in dates]
    periods = dates.to_period("W-SUN" if normalized_frequency == "weekly" else "M")
    selected: list[pd.Timestamp] = []
    seen = set()
    for timestamp, period in zip(dates, periods):
        key = str(period)
        if key not in seen:
            seen.add(key)
            selected.append(pd.Timestamp(timestamp))
    return selected


def validate_portfolio_strategy_code(code: str) -> None:
    """Reject mixed CTA/portfolio contracts before sandbox execution."""
    if not str(code or "").strip():
        raise PortfolioStrategyError("portfolio.emptyStrategy")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise PortfolioStrategyError("portfolio.invalidSyntax") from exc
    functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if "on_rebalance" not in functions:
        raise PortfolioStrategyError("portfolio.onRebalanceRequired")
    if "on_bar" in functions:
        raise PortfolioStrategyError("portfolio.onBarNotAllowed")
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            raise PortfolioStrategyError("portfolio.asyncNotAllowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in FORBIDDEN_ORDER_METHODS:
                raise PortfolioStrategyError("portfolio.directOrderNotAllowed")


def compile_portfolio_strategy_handlers(code: str) -> tuple[Optional[Callable], Callable]:
    """Compile a portfolio strategy into optional init and required rebalance handlers."""
    validate_portfolio_strategy_code(code)
    from app.utils.safe_exec import build_safe_builtins, safe_exec_with_validation

    exec_env = {"__builtins__": build_safe_builtins(), "np": np, "pd": pd}
    result = safe_exec_with_validation(
        code=code,
        exec_globals=exec_env,
        exec_locals=exec_env,
        timeout=60,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "portfolio.strategyCompileFailed")
    on_init = exec_env.get("on_init")
    on_rebalance = exec_env.get("on_rebalance")
    if not callable(on_rebalance):
        raise PortfolioStrategyError("portfolio.onRebalanceRequired")
    return (on_init if callable(on_init) else None), on_rebalance


def _clean_scores(scores: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(scores, Mapping):
        raise PortfolioStrategyError("portfolio.scoresMustBeMapping")
    clean: dict[str, float] = {}
    for raw_symbol, raw_value in scores.items():
        symbol = str(raw_symbol or "").strip().upper()
        try:
            score = float(raw_value)
        except (TypeError, ValueError):
            continue
        if symbol and math.isfinite(score):
            clean[symbol] = score
    return clean


def _positive(value: Any, code: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioStrategyError(code) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise PortfolioStrategyError(code)
    return parsed


def _tightened_limit(configured: float, requested: Optional[float], code: str) -> float:
    if requested is None:
        return configured
    parsed = _positive(requested, code)
    if parsed > configured + _EPSILON:
        raise PortfolioStrategyError(code)
    return parsed
