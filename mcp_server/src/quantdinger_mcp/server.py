"""QuantDinger MCP server.

This server is intentionally a thin wrapper over the QuantDinger Agent
Gateway (`/api/agent/v1`). The REST API stays the source of truth; MCP only
exposes a curated tool surface for agent clients.
"""
from __future__ import annotations

import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .security import (
    assert_code_size,
    assert_indicator_code_size,
    assert_json_dict,
    consume_job_stream,
    poll_job_until_terminal,
    redact_secrets,
)


# Registered tool names (for tests / docs drift checks).
MCP_TOOL_NAMES = (
    "whoami",
    "check_health",
    "list_markets",
    "search_symbols",
    "get_klines",
    "get_price",
    "list_strategies",
    "get_strategy",
    "runtime_overview",
    "stop_strategy",
    "place_quick_order",
    "list_jobs",
    "get_job",
    "wait_for_job",
    "stream_job_until_done",
    "get_indicator_authoring_contract",
    "validate_indicator_code",
    "save_indicator",
    "list_indicators",
    "get_indicator",
    "create_strategy",
    "update_strategy",
    "submit_backtest",
    "regime_detect",
    "submit_experiment_pipeline",
    "submit_structured_tune",
    "submit_ai_optimize",
    "list_portfolio_positions",
    "list_paper_orders",
)


def _env(name: str, required: bool = True) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value and required:
        print(f"[quantdinger-mcp] missing required env var: {name}", file=sys.stderr)
        sys.exit(2)
    return value


BASE_URL = _env("QUANTDINGER_BASE_URL").rstrip("/")
AGENT_TOKEN = _env("QUANTDINGER_AGENT_TOKEN")
TIMEOUT_S = float(os.environ.get("QUANTDINGER_TIMEOUT_S", "60"))
JOB_STREAM_MAX_EVENTS = int(os.environ.get("QUANTDINGER_MCP_JOB_STREAM_MAX_EVENTS", "200"))
JOB_STREAM_MAX_SECONDS = float(os.environ.get("QUANTDINGER_MCP_JOB_STREAM_MAX_SECONDS", "300"))
JOB_POLL_MAX_SECONDS = float(os.environ.get("QUANTDINGER_MCP_JOB_POLL_MAX_SECONDS", "300"))


_client = httpx.Client(
    base_url=BASE_URL,
    timeout=TIMEOUT_S,
    headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
)
_public_client = httpx.Client(base_url=BASE_URL, timeout=min(TIMEOUT_S, 15.0))


def _get(path: str, params: dict | None = None) -> Any:
    return _unwrap(_client.get(path, params=params or {}))


def _post(path: str, json: dict | None = None, headers: dict | None = None) -> Any:
    return _unwrap(_client.post(path, json=json or {}, headers=headers or {}))


def _patch(path: str, json: dict | None = None) -> Any:
    return _unwrap(_client.patch(path, json=json or {}))


def _unwrap(r: httpx.Response) -> Any:
    try:
        body = r.json()
    except Exception:
        return {"error": True, "status": r.status_code, "text": r.text[:2000]}
    if r.status_code >= 400:
        return {"error": True, "status": r.status_code, "body": body}
    if isinstance(body, dict) and "data" in body:
        data = body["data"]
        return redact_secrets(data) if isinstance(data, (dict, list)) else data
    return redact_secrets(body) if isinstance(body, (dict, list)) else body


mcp = FastMCP(
    "quantdinger",
    instructions=(
        "Tools for the QuantDinger self-hosted quant platform. "
        "All tools are tenant-scoped via the configured agent token. "
        "Live order placement is available only through place_quick_order with "
        "T scope, confirm_order=true, and confirm_live_trading=true when the "
        "token is not paper-only. Server-side live trading flags still apply. "
        "Runtime overview is available, and stop_strategy can stop a tenant-owned "
        "strategy when the token has T scope. "
        "SECURITY: never log or paste the agent token; responses may include "
        "redacted (***) credential placeholders; do not attempt to recover them. "
        "INDICATOR WORKFLOW: indicators are chart-only. Use "
        "get_indicator_authoring_contract, validate_indicator_code, and "
        "save_indicator for visual indicator code. Do not backtest indicator code "
        "directly. "
        "STRATEGY WORKFLOW: executable strategies must be ScriptStrategy code "
        "with on_init(ctx) and on_bar(ctx, bar). Use create_strategy with "
        "strategy_code or script_source_id. Use submit_backtest with full "
        "ScriptStrategy Python code only. "
        "Long jobs: use wait_for_job or stream_job_until_done (bounded). "
        "submit_ai_optimize consumes server LLM quota; call only when explicitly "
        "requested. Never pass natural language to backtest `code`."
    ),
)


# Read-class tools


@mcp.tool()
def whoami() -> Any:
    """Return the calling token's identity, scopes, and allowlists."""
    return _get("/api/agent/v1/whoami")


@mcp.tool()
def check_health() -> Any:
    """Public liveness probe (no token required). Does not expose tenant data."""
    r = _public_client.get("/api/agent/v1/health")
    try:
        body = r.json()
    except Exception:
        return {"ok": r.status_code == 200, "status": r.status_code}
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


@mcp.tool()
def list_markets() -> Any:
    """List markets the configured token is allowed to query."""
    return _get("/api/agent/v1/markets")


@mcp.tool()
def search_symbols(market: str, keyword: str = "", limit: int = 20) -> Any:
    """Find symbols in a market."""
    limit = max(1, min(100, int(limit)))
    return _get(
        f"/api/agent/v1/markets/{market}/symbols",
        params={"keyword": keyword, "limit": limit},
    )


@mcp.tool()
def get_klines(
    market: str,
    symbol: str,
    timeframe: str = "1D",
    limit: int = 300,
    before_time: int | None = None,
) -> Any:
    """Return OHLCV bars for a symbol."""
    limit = max(1, min(2000, int(limit)))
    params = {"market": market, "symbol": symbol, "timeframe": timeframe, "limit": limit}
    if before_time is not None:
        params["before_time"] = int(before_time)
    return _get("/api/agent/v1/klines", params=params)


@mcp.tool()
def get_price(market: str, symbol: str) -> Any:
    """Latest price for a symbol."""
    return _get("/api/agent/v1/price", params={"market": market, "symbol": symbol})


@mcp.tool()
def list_strategies(limit: int = 50) -> Any:
    """List the tenant's strategies (compact projection)."""
    limit = max(1, min(200, int(limit)))
    return _get("/api/agent/v1/strategies", params={"limit": limit})


@mcp.tool()
def get_strategy(strategy_id: int) -> Any:
    """Get a strategy by id (tenant-scoped; secrets redacted)."""
    return _get(f"/api/agent/v1/strategies/{int(strategy_id)}")


@mcp.tool()
def runtime_overview() -> Any:
    """Compact runtime overview for this tenant."""
    return _get("/api/agent/v1/runtime/overview")


@mcp.tool()
def stop_strategy(strategy_id: int, confirm_stop: bool = False) -> Any:
    """Stop one tenant-owned strategy (requires T scope and confirmation)."""
    if not confirm_stop:
        return {
            "error": True,
            "status": 400,
            "body": {
                "message": (
                    "Stopping a strategy changes runtime state. Re-call with "
                    "confirm_stop=true after explicit user approval."
                ),
            },
        }
    return _post(f"/api/agent/v1/strategies/{int(strategy_id)}/stop")


@mcp.tool()
def place_quick_order(
    market: str,
    symbol: str,
    side: str,
    qty: float,
    order_type: str = "market",
    limit_price: float | None = None,
    credential_id: int | None = None,
    market_type: str = "spot",
    leverage: int = 1,
    margin_mode: str | None = None,
    idempotency_key: str | None = None,
    confirm_order: bool = False,
    confirm_live_trading: bool = False,
) -> Any:
    """Place a quick order through Agent Gateway (requires T scope)."""
    if not confirm_order:
        return {
            "error": True,
            "status": 400,
            "body": {
                "message": (
                    "Order placement changes account state. Re-call with "
                    "confirm_order=true after explicit user approval."
                ),
            },
        }

    identity = _get("/api/agent/v1/whoami")
    if isinstance(identity, dict) and identity.get("paper_only") is False and not confirm_live_trading:
        return {
            "error": True,
            "status": 400,
            "body": {
                "message": (
                    "This Agent Token is live-capable. Re-call with "
                    "confirm_live_trading=true after explicit user approval."
                ),
            },
        }

    payload: dict[str, Any] = {
        "market": market,
        "symbol": symbol,
        "side": side,
        "qty": float(qty),
        "order_type": order_type,
        "market_type": market_type,
        "leverage": int(leverage or 1),
    }
    if limit_price is not None:
        payload["limit_price"] = float(limit_price)
    if credential_id is not None:
        payload["credential_id"] = int(credential_id)
    if margin_mode:
        payload["margin_mode"] = margin_mode
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    return _post("/api/agent/v1/quick-trade/orders", json=payload, headers=headers)


@mcp.tool()
def get_job(job_id: str) -> Any:
    """Poll a previously submitted backtest / experiment job."""
    return _get(f"/api/agent/v1/jobs/{job_id}")


@mcp.tool()
def list_jobs(kind: str | None = None, limit: int = 50) -> Any:
    """List recent jobs for this tenant. Optional `kind` filter."""
    limit = max(1, min(200, int(limit)))
    params: dict[str, Any] = {"limit": limit}
    if kind:
        params["kind"] = kind
    return _get("/api/agent/v1/jobs", params=params)


@mcp.tool()
def wait_for_job(
    job_id: str,
    timeout_s: float | None = None,
    interval_s: float = 2.0,
) -> Any:
    """Poll a job until it succeeds/fails or timeout."""
    cap = float(timeout_s if timeout_s is not None else JOB_POLL_MAX_SECONDS)
    cap = max(5.0, min(600.0, cap))
    interval = max(0.5, min(30.0, float(interval_s)))
    return poll_job_until_terminal(
        lambda jid: _get(f"/api/agent/v1/jobs/{jid}"),
        job_id,
        timeout_s=cap,
        interval_s=interval,
    )


@mcp.tool()
def stream_job_until_done(
    job_id: str,
    since_seq: int = 0,
    max_events: int | None = None,
    max_seconds: float | None = None,
) -> Any:
    """Consume job SSE with hard caps."""
    events_cap = int(max_events if max_events is not None else JOB_STREAM_MAX_EVENTS)
    events_cap = max(1, min(500, events_cap))
    seconds_cap = float(max_seconds if max_seconds is not None else JOB_STREAM_MAX_SECONDS)
    seconds_cap = max(5.0, min(600.0, seconds_cap))
    out = consume_job_stream(
        _client,
        f"/api/agent/v1/jobs/{job_id}/stream",
        since_seq=int(since_seq or 0),
        max_events=events_cap,
        max_seconds=seconds_cap,
    )
    if isinstance(out.get("events"), list):
        out["events"] = redact_secrets(out["events"])
    if isinstance(out.get("result"), dict):
        out["result"] = redact_secrets(out["result"])
    return out


# Indicator workspace


@mcp.tool()
def get_indicator_authoring_contract() -> Any:
    """Fetch chart-only indicator I/O contract + starter Python template."""
    return _get("/api/agent/v1/indicators/authoring-contract")


@mcp.tool()
def validate_indicator_code(code: str, indicator_params: dict | None = None) -> Any:
    """Sandbox-validate chart-only indicator Python without saving."""
    assert_indicator_code_size(code)
    params = assert_json_dict("indicator_params", indicator_params)
    return _post(
        "/api/agent/v1/indicators/validate",
        json={"code": code, "indicator_params": params},
    )


@mcp.tool()
def save_indicator(
    code: str,
    name: str | None = None,
    description: str | None = None,
    indicator_id: int | None = None,
    validate: bool = True,
) -> Any:
    """Save chart-only indicator code into the user's indicator library."""
    assert_indicator_code_size(code)
    payload: dict[str, Any] = {"code": code, "validate": validate}
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    if indicator_id:
        payload["indicator_id"] = int(indicator_id)
    return _post("/api/agent/v1/indicators", json=payload)


@mcp.tool()
def list_indicators(limit: int = 50) -> Any:
    """List saved indicators for this tenant (no code bodies)."""
    limit = max(1, min(200, int(limit)))
    return _get("/api/agent/v1/indicators", params={"limit": limit})


@mcp.tool()
def get_indicator(indicator_id: int) -> Any:
    """Fetch one chart indicator including its Python source."""
    return _get(f"/api/agent/v1/indicators/{int(indicator_id)}")


# Strategy workspace


@mcp.tool()
def create_strategy(
    strategy_name: str,
    market_category: str,
    trading_config: dict,
    strategy_code: str | None = None,
    script_source_id: int | None = None,
    strategy_mode: str = "script",
    execution_mode: str = "signal",
    strategy_type: str = "ScriptStrategy",
) -> Any:
    """Create a stopped ScriptStrategy.

    Current QuantDinger strategy assets are ScriptStrategy-only. Indicators are
    chart-only; convert an indicator idea into ScriptStrategy code before using
    this tool.
    """
    tc = assert_json_dict("trading_config", trading_config)
    if strategy_type != "ScriptStrategy":
        return {
            "error": True,
            "status": 400,
            "body": {
                "message": "Indicators are chart-only. create_strategy accepts ScriptStrategy only.",
            },
        }
    if strategy_code:
        assert_code_size(strategy_code, label="Strategy code")
    source_id = script_source_id or tc.get("script_source_id") or tc.get("scriptSourceId")
    if not strategy_code and not source_id:
        return {
            "error": True,
            "status": 400,
            "body": {
                "message": "Pass strategy_code or script_source_id for a ScriptStrategy.",
            },
        }
    if source_id:
        tc["script_source_id"] = int(source_id)

    payload: dict[str, Any] = {
        "strategy_name": strategy_name,
        "strategy_type": "ScriptStrategy",
        "market_category": market_category,
        "execution_mode": execution_mode,
        "trading_config": tc,
        "status": "stopped",
        "strategy_mode": strategy_mode or "script",
    }
    if strategy_code:
        payload["strategy_code"] = strategy_code
    return _post("/api/agent/v1/strategies", json=payload)


@mcp.tool()
def update_strategy(strategy_id: int, patch: dict) -> Any:
    """Patch a strategy (scope W). Cannot set status=running without scope T."""
    body = assert_json_dict("patch", patch)
    if str(body.get("status") or "").strip().lower() == "running":
        return {
            "error": True,
            "status": 403,
            "body": {
                "message": (
                    "Activating a strategy (status=running) requires T scope. "
                    "Use the runtime/trading path with an explicitly scoped token."
                ),
            },
        }
    return _patch(f"/api/agent/v1/strategies/{int(strategy_id)}", json=body)


# Backtest / experiments


@mcp.tool()
def submit_backtest(
    code: str,
    market: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 10000,
    commission: float = 0.001,
    slippage: float | None = None,
    leverage: int = 1,
    trade_direction: str = "long",
    strict_mode: bool = True,
    strategy_config: dict | None = None,
    script_params: dict | None = None,
    market_type: str | None = None,
    idempotency_key: str | None = None,
) -> Any:
    """Submit a ScriptStrategy backtest.

    `code` must be full ScriptStrategy Python using `on_init(ctx)` and
    `on_bar(ctx, bar)`. Chart indicator code is not accepted by the Agent v1
    backtest endpoint.
    """
    assert_code_size(code, label="Strategy code")
    payload: dict[str, Any] = {
        "code": code,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": initial_capital,
        "commission": commission,
        "leverage": leverage,
        "trade_direction": trade_direction,
        "strictMode": strict_mode,
        "strategy_config": assert_json_dict("strategy_config", strategy_config),
        "script_params": assert_json_dict("script_params", script_params),
    }
    if slippage is not None:
        payload["slippage"] = slippage
    if market_type:
        payload["market_type"] = market_type
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    return _post("/api/agent/v1/backtest/run", json=payload, headers=headers)


@mcp.tool()
def regime_detect(
    market: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> Any:
    """Detect the current market regime (synchronous)."""
    return _post(
        "/api/agent/v1/experiments/regime/detect",
        json={
            "market": market,
            "symbol": symbol,
            "timeframe": timeframe,
            "startDate": start_date,
            "endDate": end_date,
        },
    )


@mcp.tool()
def submit_experiment_pipeline(payload: dict, idempotency_key: str | None = None) -> Any:
    """Submit a legacy grid pipeline job (scope B)."""
    body = assert_json_dict("payload", payload)
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
    return _post("/api/agent/v1/experiments/pipeline", json=body, headers=headers)


@mcp.tool()
def submit_structured_tune(payload: dict) -> Any:
    """Submit a grid/random tuning job. Returns a job for polling."""
    return _post("/api/agent/v1/experiments/structured-tune", json=assert_json_dict("payload", payload))


@mcp.tool()
def submit_ai_optimize(payload: dict, confirm_llm_usage: bool = False) -> Any:
    """Submit an LLM-driven multi-round optimization job (scope B)."""
    if not confirm_llm_usage:
        return {
            "error": True,
            "status": 400,
            "body": {
                "message": (
                    "submit_ai_optimize consumes LLM quota. Re-call with "
                    "confirm_llm_usage=true after explicit user approval."
                ),
            },
        }
    return _post("/api/agent/v1/experiments/ai-optimize", json=assert_json_dict("payload", payload))


# Portfolio (read-only)


@mcp.tool()
def list_portfolio_positions() -> Any:
    """Manual portfolio positions for this tenant (read-only, scope R)."""
    return _get("/api/agent/v1/portfolio/positions")


@mcp.tool()
def list_paper_orders() -> Any:
    """Recent paper orders submitted via agent trading APIs (scope R)."""
    return _get("/api/agent/v1/portfolio/paper-orders")


_TRANSPORTS = {"stdio", "sse", "streamable-http"}


def _resolve_transport() -> str:
    raw = (os.environ.get("QUANTDINGER_MCP_TRANSPORT") or "stdio").strip().lower()
    if raw in ("http", "streaming-http", "streamable_http"):
        raw = "streamable-http"
    if raw not in _TRANSPORTS:
        print(
            f"[quantdinger-mcp] unknown transport '{raw}'. "
            f"Expected one of: {sorted(_TRANSPORTS)} (or http/streaming-http alias).",
            file=sys.stderr,
        )
        sys.exit(2)
    return raw


def _apply_http_settings_from_env() -> None:
    host = (os.environ.get("QUANTDINGER_MCP_HOST") or "").strip()
    port_raw = (os.environ.get("QUANTDINGER_MCP_PORT") or "").strip()
    settings = getattr(mcp, "settings", None)
    if settings is None:
        return
    if host:
        try:
            settings.host = host
        except Exception:
            pass
    if port_raw:
        try:
            settings.port = int(port_raw)
        except Exception:
            print(
                f"[quantdinger-mcp] invalid QUANTDINGER_MCP_PORT='{port_raw}', ignoring.",
                file=sys.stderr,
            )


def main() -> None:
    """Entrypoint."""
    transport = _resolve_transport()
    if transport in ("sse", "streamable-http"):
        _apply_http_settings_from_env()
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
