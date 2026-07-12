"""Unified backtest center API."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import itertools
import math
import random
import traceback
from typing import Any, Dict, List, Optional

from flask import g, jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.routes.strategy_services import get_strategy_service
from app.services.backtest_limits import validate_backtest_range
from app.services.backtest_execution import (
    default_commission_if_missing,
    default_slippage_if_missing,
    parse_rate,
)
from app.services.script_source import get_script_source_service
from app.services.strategy_snapshot import StrategySnapshotResolver
from app.services.unified_backtest import UnifiedBacktestService
from app.services.portfolio_backtest_service import (
    PortfolioBacktestRequestError,
    PortfolioBacktestService,
)
from app.services.strategy_warmup import resolve_startup_candle_count
from app.utils.auth import login_required
from app.utils.logger import get_logger

logger = get_logger(__name__)

backtest_center_blp = Blueprint("backtest_center", __name__)
_unified_backtest_service: UnifiedBacktestService | None = None
_portfolio_backtest_service: PortfolioBacktestService | None = None
INDICATOR_CHART_ONLY_MSG = (
    "Indicators are chart-only. Convert the indicator to a script strategy before backtesting or tuning."
)


def get_unified_backtest_service() -> UnifiedBacktestService:
    global _unified_backtest_service
    if _unified_backtest_service is None:
        _unified_backtest_service = UnifiedBacktestService()
    return _unified_backtest_service


def get_portfolio_backtest_service() -> PortfolioBacktestService:
    global _portfolio_backtest_service
    if _portfolio_backtest_service is None:
        _portfolio_backtest_service = PortfolioBacktestService(
            unified_service=get_unified_backtest_service(),
        )
    return _portfolio_backtest_service


def _build_script_source_strategy(source: dict, script_source_id: int, override_config: dict) -> dict:
    override = override_config if isinstance(override_config, dict) else {}
    metadata = source.get("metadata") or {}
    last_run_config = metadata.get("last_run_config") or {}
    market = str(
        override.get("market")
        or override.get("market_category")
        or last_run_config.get("market_category")
        or "Crypto"
    ).strip() or "Crypto"
    return {
        "id": None,
        "strategy_name": override.get("strategy_name") or source.get("name") or f"Script Source #{script_source_id}",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": "script",
        "strategy_code": "",
        "market_category": market,
        "status": "draft",
        "trading_config": {
            **last_run_config,
            **override,
            "market_category": market,
            "script_source_id": script_source_id,
            "param_schema": source.get("param_schema") or {},
        },
    }


def _int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except Exception:
        return None


def _asset_identity(payload: Dict[str, Any]) -> tuple[str, Optional[int]]:
    asset_type = str(
        payload.get("assetType")
        or payload.get("asset_type")
        or payload.get("type")
        or ""
    ).strip().lower()
    if asset_type in {"script_source", "script-strategy"}:
        asset_type = "script"
    if asset_type in {"template", "preset", "bot"}:
        asset_type = "script"
    if asset_type in {"portfolio", "cross_section", "cross-section"}:
        asset_type = "portfolio_strategy"
    asset_id = _int_or_none(
        payload.get("assetId")
        or payload.get("asset_id")
        or payload.get("sourceId")
        or payload.get("source_id")
        or payload.get("indicatorId")
        or payload.get("scriptSourceId")
        or payload.get("strategyId")
    )
    return asset_type, asset_id


def _float_or_default(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except Exception:
        return default


def _backtest_fees(payload: Dict[str, Any]) -> Dict[str, Any]:
    strategy_config = payload.get("strategyConfig") if isinstance(payload.get("strategyConfig"), dict) else {}
    override_config = payload.get("overrideConfig") if isinstance(payload.get("overrideConfig"), dict) else {}
    merged_fees: Dict[str, Any] = {}
    if isinstance(strategy_config.get("fees"), dict):
        merged_fees.update(strategy_config.get("fees") or {})
    if isinstance(override_config.get("fees"), dict):
        merged_fees.update(override_config.get("fees") or {})

    market_type = str(
        payload.get("marketType")
        or payload.get("market_type")
        or override_config.get("market_type")
        or strategy_config.get("market_type")
        or strategy_config.get("marketType")
        or ""
    ).strip().lower()
    if market_type == "spot":
        return {"fundingRateAnnual": 0.0, "fundingIntervalHours": 8.0}

    funding_rate = payload.get("fundingRateAnnual", merged_fees.get("fundingRateAnnual", 0.0))
    funding_interval = payload.get("fundingIntervalHours", merged_fees.get("fundingIntervalHours", 8.0))
    return {
        "fundingRateAnnual": _float_or_default(funding_rate, 0.0),
        "fundingIntervalHours": max(1.0, _float_or_default(funding_interval, 8.0)),
    }


def _merge_backtest_fees(strategy_config: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(strategy_config or {})
    fees = dict(cfg.get("fees") or {})
    fees.update(_backtest_fees(payload))
    cfg["fees"] = fees
    return cfg


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _param_overrides(payload: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    strategy_config = _dict_or_empty(payload.get("strategyConfig"))
    override_config = _dict_or_empty(payload.get("overrideConfig") or payload.get("override_config"))

    for source in (
        _dict_or_empty(strategy_config.get("indicator_params")),
        _dict_or_empty(strategy_config.get("script_params")),
        _dict_or_empty(strategy_config.get("params")),
        _dict_or_empty(override_config.get("indicator_params")),
        _dict_or_empty(override_config.get("script_params")),
        _dict_or_empty(override_config.get("params")),
        _dict_or_empty(override_config.get("paramOverrides")),
        _dict_or_empty(payload.get("paramOverrides") or payload.get("param_overrides")),
    ):
        merged.update(source)
    return merged


def _merge_params_into_config(config: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(config or {})
    if not params:
        return cfg
    current = _dict_or_empty(cfg.get("indicator_params"))
    current.update(params)
    cfg["indicator_params"] = current
    cfg["script_params"] = dict(current)
    cfg["params"] = dict(current)
    cfg["paramOverrides"] = dict(current)
    return cfg


def _should_persist_run(payload: Dict[str, Any]) -> bool:
    value = payload.get("persist", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return value is not False


def _unwrap_tune_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Accept the V2 tuning shape and flatten its backtest base payload."""
    base = payload.get("base")
    if not isinstance(base, dict):
        return dict(payload or {})
    merged = dict(base)
    for key, value in (payload or {}).items():
        if key != "base":
            merged[key] = value
    return merged


def _candidate_values(values: Any) -> List[Any]:
    if not isinstance(values, (list, tuple)):
        return []
    cleaned: List[Any] = []
    for item in values:
        if item is None or item == "":
            continue
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


def _normalize_param_key(key: Any) -> str:
    text = str(key or "").strip()
    if not text:
        return ""
    text = text.replace("[", ".").replace("]", "")
    return text.split(".")[-1].strip()


def _extract_parameter_space(payload: Dict[str, Any]) -> Dict[str, List[Any]]:
    space: Dict[str, List[Any]] = {}
    raw_space = payload.get("parameterSpace") or payload.get("parameter_space") or {}
    if isinstance(raw_space, dict):
        for key, values in raw_space.items():
            clean_key = _normalize_param_key(key)
            vals = _candidate_values(values)
            if clean_key and vals:
                space[clean_key] = vals

    raw_dims = payload.get("dimensions") or payload.get("sweepDimensions") or payload.get("sweep_dimensions") or []
    if isinstance(raw_dims, list):
        for dim in raw_dims:
            if not isinstance(dim, dict) or dim.get("enabled") is False:
                continue
            key = (
                dim.get("paramName")
                or dim.get("param_name")
                or dim.get("name")
                or dim.get("key")
                or dim.get("path")
            )
            clean_key = _normalize_param_key(key)
            vals = _candidate_values(dim.get("values"))
            if clean_key and vals:
                space[clean_key] = vals
    return space


def _set_param_override(payload: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    candidate = deepcopy(payload)
    candidate["persist"] = False
    normalized_params = {
        _normalize_param_key(key): value
        for key, value in (params or {}).items()
        if _normalize_param_key(key)
    }
    current = _dict_or_empty(candidate.get("paramOverrides") or candidate.get("param_overrides"))
    current.update(normalized_params)
    candidate["paramOverrides"] = current
    override_config = _dict_or_empty(candidate.get("overrideConfig") or candidate.get("override_config"))
    for key in ("indicator_params", "script_params", "params", "paramOverrides"):
        merged = _dict_or_empty(override_config.get(key))
        merged.update(current)
        override_config[key] = merged
    candidate["overrideConfig"] = override_config
    return candidate


def _iter_tune_candidates(space: Dict[str, List[Any]], method: str, max_variants: int) -> List[Dict[str, Any]]:
    keys = [key for key, values in space.items() if values]
    if not keys:
        return []
    max_variants = max(1, min(int(max_variants or 60), 240))
    method_key = str(method or "grid").strip().lower()
    combos: List[Dict[str, Any]] = []

    if method_key == "grid":
        for values in itertools.product(*[space[key] for key in keys]):
            combos.append(dict(zip(keys, values)))
            if len(combos) >= max_variants:
                break
    else:
        seen = set()
        attempts = max_variants * 8
        while len(combos) < max_variants and attempts > 0:
            attempts -= 1
            item = {key: random.choice(space[key]) for key in keys}
            sig = tuple((key, item[key]) for key in keys)
            if sig in seen:
                continue
            seen.add(sig)
            combos.append(item)
    return combos


def _metric_value(metrics: Dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        if name in metrics:
            try:
                value = float(metrics.get(name) or 0)
                if math.isfinite(value):
                    return value
            except Exception:
                pass
    return default


def _result_metrics(result: Dict[str, Any]) -> Dict[str, Any]:
    metrics = dict(result.get("metrics") or {})
    for key in (
        "totalReturn", "maxDrawdown", "sharpeRatio", "winRate", "profitFactor",
        "totalTrades", "bestTrade", "worstTrade", "avgTrade",
    ):
        if key not in metrics and key in result:
            metrics[key] = result.get(key)
    return metrics


def _score_result(result: Dict[str, Any]) -> Dict[str, float]:
    metrics = _result_metrics(result)
    total_return = _metric_value(metrics, "totalReturn", "total_return")
    max_drawdown = abs(_metric_value(metrics, "maxDrawdown", "max_drawdown"))
    sharpe = _metric_value(metrics, "sharpeRatio", "sharpe", "sharpe_ratio")
    win_rate = _metric_value(metrics, "winRate", "win_rate")
    profit_factor = _metric_value(metrics, "profitFactor", "profit_factor")
    trades = _metric_value(metrics, "totalTrades", "total_trades")
    score = 50.0
    score += total_return * 1.25
    score -= max_drawdown * 0.85
    score += max(min(sharpe, 5.0), -5.0) * 5.0
    score += min(max(profit_factor, 0.0), 3.0) * 4.5
    score += min(max(win_rate, 0.0), 100.0) * 0.06
    score += min(max(trades, 0.0), 80.0) * 0.08
    if trades <= 0:
        score -= 35.0
    score = max(0.0, min(100.0, score))
    return {
        "overallScore": round(score, 2),
        "returnScore": round(total_return, 4),
        "drawdownScore": round(max_drawdown, 4),
        "sharpeScore": round(sharpe, 4),
        "winRateScore": round(win_rate, 4),
        "profitFactorScore": round(profit_factor, 4),
        "tradeCount": round(trades, 4),
    }


def _grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 68:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _summary_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _result_metrics(result)
    return {
        "totalReturn": _metric_value(metrics, "totalReturn", "total_return"),
        "maxDrawdown": _metric_value(metrics, "maxDrawdown", "max_drawdown"),
        "sharpeRatio": _metric_value(metrics, "sharpeRatio", "sharpe", "sharpe_ratio"),
        "winRate": _metric_value(metrics, "winRate", "win_rate"),
        "profitFactor": _metric_value(metrics, "profitFactor", "profit_factor"),
        "totalTrades": _metric_value(metrics, "totalTrades", "total_trades"),
        "bestTrade": _metric_value(metrics, "bestTrade", "best_trade"),
        "worstTrade": _metric_value(metrics, "worstTrade", "worst_trade"),
        "avgTrade": _metric_value(metrics, "avgTrade", "avg_trade"),
    }


def _split_dates(start_date: str, end_date: str) -> tuple[str, str, str, str, str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if end <= start:
        return start_date, end_date, start_date, end_date, start_date
    split = start + timedelta(seconds=int((end - start).total_seconds() * 0.7))
    split_str = split.strftime("%Y-%m-%d")
    oos_start = (split + timedelta(days=1)).strftime("%Y-%m-%d")
    if oos_start > end_date:
        oos_start = split_str
    return start_date, split_str, oos_start, end_date, split_str


def _run_candidate(payload: Dict[str, Any], user_id: int, asset_type: str, asset_id: Optional[int], params: Dict[str, Any]) -> Dict[str, Any]:
    candidate_payload = _set_param_override(payload, params)
    if asset_type == "script":
        _, result = _run_strategy_backtest(candidate_payload, user_id, asset_type, asset_id)
    else:
        raise ValueError("assetType must be script")
    return result


def _run_strategy_backtest(payload: Dict[str, Any], user_id: int, asset_type: str, asset_id: Optional[int]) -> tuple[Optional[int], Dict[str, Any]]:
    svc = get_unified_backtest_service()
    override_config = payload.get("overrideConfig") or payload.get("override_config") or {}
    if not isinstance(override_config, dict):
        override_config = {}
    override_config = dict(override_config)
    passthrough_pairs = (
        ("market", "market"),
        ("symbol", "symbol"),
        ("marketType", "market_type"),
        ("market_type", "market_type"),
        ("exchangeId", "exchange_id"),
        ("exchange_id", "exchange_id"),
        ("initialCapital", "initialCapital"),
        ("initial_capital", "initial_capital"),
        ("investment_amount", "investment_amount"),
        ("leverage", "leverage"),
        ("tradeDirection", "trade_direction"),
        ("trade_direction", "trade_direction"),
        ("commission", "commission"),
        ("slippage", "slippage"),
        ("fundingRateAnnual", "fundingRateAnnual"),
        ("fundingIntervalHours", "fundingIntervalHours"),
        ("strictMode", "strictMode"),
        ("strict_mode", "strict_mode"),
    )
    for source_key, target_key in passthrough_pairs:
        if source_key in payload:
            override_config[target_key] = payload.get(source_key)
    if payload.get("commissionPct") not in (None, ""):
        override_config["commission"] = parse_rate(
            None,
            pct_value=payload.get("commissionPct"),
            default=default_commission_if_missing(None),
        )
    elif "commission" in override_config:
        override_config["commission"] = parse_rate(
            override_config.get("commission"),
            default=default_commission_if_missing(None),
        )
    if payload.get("slippagePct") not in (None, ""):
        override_config["slippage"] = parse_rate(None, pct_value=payload.get("slippagePct"), default=default_slippage_if_missing(None))
    elif "slippage" in override_config:
        override_config["slippage"] = default_slippage_if_missing(override_config.get("slippage"))
    param_overrides = _param_overrides(payload)
    if param_overrides:
        for key in ("indicator_params", "script_params", "params", "paramOverrides"):
            current = _dict_or_empty(override_config.get(key))
            current.update(param_overrides)
            override_config[key] = current
    override_config = _merge_backtest_fees(override_config, payload)
    if str(override_config.get("market_type") or "").strip().lower() == "spot":
        override_config["leverage"] = 1
        override_config["trade_direction"] = "long"
    start_date_str = str(payload.get("startDate") or "").strip()
    end_date_str = str(payload.get("endDate") or "").strip()
    if not start_date_str or not end_date_str:
        raise ValueError("startDate and endDate are required")

    strategy_id = _int_or_none(payload.get("strategyId"))
    script_source_id = _int_or_none(payload.get("scriptSourceId") or payload.get("sourceId"))
    if asset_type == "script":
        script_source_id = script_source_id or asset_id

    if strategy_id:
        strategy = get_strategy_service().get_strategy(strategy_id, user_id=user_id)
        if not strategy:
            raise ValueError("Strategy not found")
    elif script_source_id:
        source = get_script_source_service().get_source(script_source_id, user_id=user_id)
        if not source:
            raise ValueError("Script source not found")
        strategy = _build_script_source_strategy(source, script_source_id, override_config)
    else:
        raise ValueError("strategyId or scriptSourceId is required")

    resolver = StrategySnapshotResolver(user_id=user_id)
    snapshot = resolver.resolve(strategy, override_config)
    snapshot["user_id"] = user_id
    snapshot["strategy_config"] = _merge_params_into_config(snapshot.get("strategy_config") or {}, param_overrides)
    snapshot["strategy_config"] = _merge_backtest_fees(snapshot.get("strategy_config") or {}, payload)
    if param_overrides:
        resolved_params = snapshot["strategy_config"].get("indicator_params") or {}
        snapshot["indicator_params"] = dict(resolved_params)
        config_snapshot = dict(snapshot.get("config_snapshot") or {})
        signal_config = dict(config_snapshot.get("signalConfig") or {})
        signal_config["indicatorParams"] = dict(resolved_params)
        config_snapshot["signalConfig"] = signal_config
        config_snapshot["paramOverrides"] = dict(resolved_params)
        snapshot["config_snapshot"] = config_snapshot
    for source_key, snapshot_key in (
        ("market", "market"),
        ("symbol", "symbol"),
        ("market_type", "market_type"),
        ("exchange_id", "exchange_id"),
        ("initialCapital", "initial_capital"),
        ("initial_capital", "initial_capital"),
        ("investment_amount", "investment_amount"),
        ("leverage", "leverage"),
        ("trade_direction", "trade_direction"),
        ("commission", "commission"),
        ("slippage", "slippage"),
        ("strictMode", "strict_mode"),
        ("strict_mode", "strict_mode"),
    ):
        if source_key in override_config:
            snapshot[snapshot_key] = override_config.get(source_key)

    if snapshot.get("market_type"):
        snapshot["strategy_config"]["market_type"] = snapshot.get("market_type")
    if str(snapshot.get("market_type") or "").strip().lower() == "spot":
        snapshot["leverage"] = 1
        snapshot["trade_direction"] = "long"
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    timeframe = snapshot.get("timeframe") or "1D"
    warmup_bars = resolve_startup_candle_count(
        snapshot.get("code") or "",
        (snapshot.get("strategy_config") or {}).get("indicator_params")
        if isinstance(snapshot.get("strategy_config"), dict)
        else None,
    )
    range_error = validate_backtest_range(
        market=snapshot.get("market") or "",
        symbol=snapshot.get("symbol") or "",
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        warmup_bars=warmup_bars,
    )
    if range_error:
        raise ValueError(range_error.get("msg") or "Invalid backtest range")

    result = svc.run_strategy_snapshot(snapshot, start_date=start_date, end_date=end_date)
    resolved_params = dict((snapshot.get("strategy_config") or {}).get("indicator_params") or {})
    result["executionAssumptions"] = {
        **(result.get("executionAssumptions") or {}),
        "commission": round(float(snapshot.get("commission") or 0), 6),
        "slippage": round(float(snapshot.get("slippage") or 0), 6),
        "strictMode": bool(snapshot.get("strict_mode", True)),
        "fees": (snapshot.get("strategy_config") or {}).get("fees") or {},
        "parameterSnapshot": resolved_params,
        "parameterCount": len(resolved_params),
    }
    result["parameterSnapshot"] = resolved_params
    result["parameterCount"] = len(resolved_params)
    resolved_asset_type = "script"
    resolved_asset_id = script_source_id
    run_id = None
    if _should_persist_run(payload):
        run_id = svc.persist_run(
            user_id=user_id,
            strategy_id=snapshot.get("strategy_id") or strategy_id,
            strategy_name=snapshot.get("strategy_name") or "",
            run_type=snapshot.get("run_type") or "strategy_script",
            asset_type=resolved_asset_type,
            asset_id=resolved_asset_id,
            market=snapshot.get("market") or "",
            symbol=snapshot.get("symbol") or "",
            timeframe=snapshot.get("timeframe") or "",
            exchange_id=snapshot.get("exchange_id") or "",
            market_type=snapshot.get("market_type") or "spot",
            instrument_id=snapshot.get("instrument_id") or "",
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            initial_capital=float(snapshot.get("initial_capital") or 0),
            commission=float(snapshot.get("commission") or 0),
            slippage=float(snapshot.get("slippage") or 0),
            leverage=int(snapshot.get("leverage") or 1),
            trade_direction=str(snapshot.get("trade_direction") or "long"),
            strategy_config=snapshot.get("strategy_config") or {},
            config_snapshot={
                **(snapshot.get("config_snapshot") or {}),
                "assetType": resolved_asset_type,
                "assetId": resolved_asset_id,
                "fees": (snapshot.get("strategy_config") or {}).get("fees") or {},
                "paramOverrides": (snapshot.get("strategy_config") or {}).get("indicator_params") or {},
            },
            status="success",
            error_message="",
            result=result,
            code=snapshot.get("code") or "",
        )
    return run_id, result


@backtest_center_blp.route("/run", methods=["POST"])
@login_required
def run_unified_backtest():
    payload = request.get_json() or {}
    asset_type, asset_id = _asset_identity(payload)
    try:
        if asset_type == "indicator":
            return jsonify({"code": 0, "msg": INDICATOR_CHART_ONLY_MSG, "data": None}), 400
        if asset_type == "script":
            run_id, result = _run_strategy_backtest(payload, int(g.user_id), asset_type, asset_id)
        elif asset_type == "portfolio_strategy":
            run_id, result = get_portfolio_backtest_service().run(
                user_id=int(g.user_id),
                payload=payload,
            )
        else:
            return jsonify({"code": 0, "msg": "backtest.unsupportedAssetType", "data": None}), 400
        data = dict(result or {})
        data["runId"] = run_id
        data["run_id"] = run_id
        data["result"] = result
        return jsonify({"code": 1, "msg": "success", "data": data})
    except (PortfolioBacktestRequestError, ValueError) as exc:
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        logger.error("run_unified_backtest failed: %s", exc)
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@backtest_center_blp.route("/tune", methods=["POST"])
@backtest_center_blp.route("/structured-tune", methods=["POST"])
@login_required
def tune_unified_backtest():
    raw_payload = request.get_json() or {}
    payload = _unwrap_tune_payload(raw_payload)
    payload["persist"] = False
    asset_type, asset_id = _asset_identity(payload)
    try:
        if asset_type == "indicator":
            return jsonify({"code": 0, "msg": INDICATOR_CHART_ONLY_MSG, "data": None}), 400
        if asset_type != "script":
            return jsonify({"code": 0, "msg": "assetType must be script", "data": None}), 400

        space = _extract_parameter_space(payload)
        if not space:
            return jsonify({"code": 0, "msg": "No tunable parameters detected", "data": None}), 400

        method = str(raw_payload.get("method") or payload.get("method") or "grid").strip().lower() or "grid"
        max_variants = int(raw_payload.get("maxVariants") or raw_payload.get("max_variants") or payload.get("maxVariants") or 60)
        candidates = _iter_tune_candidates(space, method, max_variants)
        if not candidates:
            return jsonify({"code": 0, "msg": "No candidate parameters generated", "data": None}), 400

        started_at = datetime.utcnow().isoformat() + "Z"
        ranked: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        user_id = int(g.user_id)
        for index, params in enumerate(candidates, start=1):
            try:
                result = _run_candidate(payload, user_id, asset_type, asset_id, params)
                score = _score_result(result)
                ranked.append({
                    "name": f"variant_{index}",
                    "rank": index,
                    "method": method,
                    "params": params,
                    "paramOverrides": params,
                    "result": result,
                    "metrics": _summary_from_result(result),
                    "score": score,
                    "grade": _grade(float(score["overallScore"])),
                })
            except Exception as exc:
                errors.append({"name": f"variant_{index}", "params": params, "error": str(exc)})

        if not ranked:
            message = errors[0]["error"] if errors else "All candidates failed"
            return jsonify({"code": 0, "msg": message, "data": {"errors": errors}}), 400

        ranked.sort(key=lambda item: float((item.get("score") or {}).get("overallScore") or 0), reverse=True)
        for index, item in enumerate(ranked, start=1):
            item["rank"] = index

        best = deepcopy(ranked[0])
        start_date = str(payload.get("startDate") or "").strip()
        end_date = str(payload.get("endDate") or "").strip()
        oos_validation = None
        if start_date and end_date:
            try:
                train_start, train_end, test_start, test_end, split_date = _split_dates(start_date, end_date)
                train_payload = dict(payload, startDate=train_start, endDate=train_end, persist=False)
                test_payload = dict(payload, startDate=test_start, endDate=test_end, persist=False)
                train_result = _run_candidate(train_payload, user_id, asset_type, asset_id, best.get("params") or {})
                test_result = _run_candidate(test_payload, user_id, asset_type, asset_id, best.get("params") or {})
                oos_validation = {
                    "enabled": True,
                    "splitDate": split_date,
                    "train": {
                        "range": {"startDate": train_start, "endDate": train_end},
                        "metrics": _summary_from_result(train_result),
                        "score": _score_result(train_result),
                    },
                    "validation": {
                        "range": {"startDate": test_start, "endDate": test_end},
                        "metrics": _summary_from_result(test_result),
                        "score": _score_result(test_result),
                    },
                }
            except Exception as exc:
                oos_validation = {"enabled": False, "error": str(exc)}

        best["oosValidation"] = oos_validation
        finished_at = datetime.utcnow().isoformat() + "Z"
        score_trace = [
            {"index": item["rank"], "score": (item.get("score") or {}).get("overallScore", 0), "name": item.get("name")}
            for item in ranked
        ]
        sensitivity = []
        for key in space.keys():
            values_seen: Dict[str, List[float]] = {}
            for item in ranked:
                value = (item.get("params") or {}).get(key)
                values_seen.setdefault(str(value), []).append(float((item.get("score") or {}).get("overallScore") or 0))
            if values_seen:
                avgs = [sum(v) / len(v) for v in values_seen.values() if v]
                sensitivity.append({
                    "name": key,
                    "label": key,
                    "spread": round(max(avgs) - min(avgs), 4) if avgs else 0,
                    "values": values_seen,
                })
        data = {
            "experiment": {
                "method": method,
                "totalCandidates": len(candidates),
                "evaluated": len(ranked),
                "failed": len(errors),
                "startedAt": started_at,
                "finishedAt": finished_at,
                "assetType": asset_type,
                "assetId": asset_id,
            },
            "bestStrategyOutput": best,
            "best": best,
            "rankedStrategies": ranked,
            "candidates": ranked,
            "rounds": [{"round": 1, "bestScore": (best.get("score") or {}).get("overallScore"), "candidates": ranked}],
            "analytics": {
                "scoreTrace": score_trace,
                "parameterSensitivity": sensitivity,
                "errors": errors,
            },
            "oosValidation": oos_validation,
        }
        return jsonify({"code": 1, "msg": "success", "data": data})
    except ValueError as exc:
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        logger.error("tune_unified_backtest failed: %s", exc)
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@backtest_center_blp.route("/history", methods=["GET"])
@login_required
def list_unified_backtest_history():
    try:
        asset_type = str(request.args.get("assetType") or request.args.get("asset_type") or "").strip().lower()
        asset_id = _int_or_none(request.args.get("assetId") or request.args.get("asset_id"))
        limit = max(1, min(int(request.args.get("limit") or 50), 200))
        offset = max(0, int(request.args.get("offset") or 0))
        rows = get_unified_backtest_service().list_runs(
            user_id=int(g.user_id),
            asset_type=asset_type,
            asset_id=asset_id,
            status=str(request.args.get("status") or "").strip(),
            symbol=str(request.args.get("symbol") or "").strip(),
            market=str(request.args.get("market") or "").strip(),
            timeframe=str(request.args.get("timeframe") or "").strip(),
            limit=limit,
            offset=offset,
        )
        return jsonify({"code": 1, "msg": "success", "data": rows})
    except Exception as exc:
        logger.error("list_unified_backtest_history failed: %s", exc, exc_info=True)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@backtest_center_blp.route("/get", methods=["GET"])
@login_required
def get_unified_backtest_run():
    try:
        run_id = int(request.args.get("runId") or 0)
        if not run_id:
            return jsonify({"code": 0, "msg": "runId is required", "data": None}), 400
        row = get_unified_backtest_service().get_run(user_id=int(g.user_id), run_id=run_id)
        if not row:
            return jsonify({"code": 0, "msg": "run not found", "data": None}), 404
        return jsonify({"code": 1, "msg": "success", "data": row})
    except Exception as exc:
        logger.error("get_unified_backtest_run failed: %s", exc, exc_info=True)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500
