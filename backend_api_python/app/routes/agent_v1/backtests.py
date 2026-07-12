"""Async V2 backtest endpoints (class B).

Submit returns a job_id; the agent polls /jobs/{id} until done. This endpoint
uses the same V2 execution model as the human Backtest Center.
"""
from __future__ import annotations

from typing import Any

from app.services.unified_backtest import UnifiedBacktestService
from app.services.strategy_warmup import resolve_startup_candle_count
from app.services.backtest_limits import validate_backtest_range
from app.utils.agent_auth import (
    SCOPE_B, agent_required, current_token, current_user_id,
    instrument_allowed, market_allowed, with_idempotency,
)
from app.utils.agent_jobs import submit_job
from app.utils.logger import get_logger
from flask import request

from . import agent_v1_bp
from ._helpers import envelope, error, get_json_or_400
from ._security import assert_indicator_code_size

logger = get_logger(__name__)
_backtest = UnifiedBacktestService()


def _parse_date(s: Any) -> Any:
    from datetime import datetime
    if not s:
        return None
    if hasattr(s, "year"):
        return s
    text = str(s)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    raise ValueError(f"Invalid date: {text}")


def _run_backtest(payload: dict) -> Any:
    """Adapter: call ScriptStrategy backtest with the agent payload shape."""
    from app.services.backtest_execution import (
        default_commission_if_missing,
        default_slippage_if_missing,
        merge_strict_mode_into_strategy_config,
        parse_strict_mode,
    )

    code = (payload.get("code") or payload.get("strategy_code") or payload.get("scriptCode") or "").strip()
    if not code:
        raise ValueError("code (ScriptStrategy code) is required")

    market = payload.get("market") or "Crypto"
    symbol = payload.get("symbol")
    timeframe = payload.get("timeframe") or "1D"
    market_type = str(payload.get("marketType") or payload.get("market_type") or "").strip().lower()
    if market_type in ("futures", "future", "perp", "perpetual"):
        market_type = "swap"
    if market_type not in ("spot", "swap"):
        market_type = ""
    exchange_id = str(payload.get("exchangeId") or payload.get("exchange_id") or "").strip().lower()
    if not symbol:
        raise ValueError("symbol is required")

    start_date = _parse_date(payload.get("start_date") or payload.get("startDate"))
    end_date = _parse_date(payload.get("end_date") or payload.get("endDate"))
    if not start_date or not end_date:
        raise ValueError("start_date and end_date are required (YYYY-MM-DD)")

    strict_mode = parse_strict_mode(
        payload.get("strictMode", payload.get("strict_mode")),
        default=True,
    )
    strategy_config = merge_strict_mode_into_strategy_config(
        payload.get("strategy_config") or payload.get("strategyConfig") or {},
        strict_mode,
    )
    script_params = payload.get("script_params") or payload.get("params") or {}
    warmup_bars = resolve_startup_candle_count(code, script_params)
    range_error = validate_backtest_range(
        market=market,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date.replace(hour=23, minute=59, second=59),
        warmup_bars=warmup_bars,
    )
    if range_error:
        raise ValueError(range_error["msg"])

    initial_capital = float(payload.get("initial_capital") or payload.get("initialCapital") or 10000)
    commission = default_commission_if_missing(payload.get("commission"))
    slippage = default_slippage_if_missing(payload.get("slippage"))
    leverage = int(payload.get("leverage") or 1)
    trade_direction = payload.get("trade_direction") or payload.get("tradeDirection") or "long"
    strategy_config = {
        **(strategy_config if isinstance(strategy_config, dict) else {}),
        "script_params": script_params if isinstance(script_params, dict) else {},
        "market_type": market_type or None,
    }
    snapshot = {
        "strategy_id": payload.get("strategy_id") or payload.get("strategyId"),
        "strategy_name": payload.get("strategy_name") or payload.get("strategyName") or "Agent ScriptStrategy",
        "strategy_type": "ScriptStrategy",
        "strategy_mode": payload.get("strategy_mode") or payload.get("strategyMode") or "script",
        "run_type": "strategy_script",
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "market_type": market_type or None,
        "exchange_id": exchange_id or None,
        "initial_capital": initial_capital,
        "commission": commission,
        "slippage": slippage,
        "leverage": leverage,
        "trade_direction": trade_direction,
        "strict_mode": strict_mode,
        "code": code,
        "strategy_config": strategy_config,
        "user_id": int(payload.get("__user_id") or 1),
    }
    return _backtest.run_strategy_snapshot(
        snapshot,
        start_date=start_date,
        end_date=end_date.replace(hour=23, minute=59, second=59),
    )


@agent_v1_bp.route("/backtest/run", methods=["POST"])
@agent_required(SCOPE_B)
def create_backtest():
    """Submit a backtest job. Returns 202 with `job_id` for polling."""
    body, err = get_json_or_400()
    if err:
        return err

    market = body.get("market") or "Crypto"
    symbol = body.get("symbol")
    if body.get("indicator_code"):
        return error(400, "Indicators are chart-only. Submit ScriptStrategy code in `code`.", http=400)
    code = (body.get("code") or body.get("strategy_code") or body.get("scriptCode") or "").strip()
    if code:
        try:
            assert_indicator_code_size(code)
        except ValueError as ve:
            return error(400, str(ve))
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if symbol and not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    with with_idempotency("backtest") as existing:
        if existing:
            return envelope({
                "job_id": existing["job_id"],
                "status": existing["status"],
                "duplicate": True,
            }, message="idempotent replay")

    payload = dict(body)
    payload["__user_id"] = current_user_id()
    job = submit_job(
        user_id=current_user_id(),
        agent_token_id=int(current_token().get("id")),
        kind="backtest",
        request_payload=payload,
        runner=_run_backtest,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    return envelope(job, message="queued", status=202)
