# QuantDinger MCP server

[![PyPI](https://img.shields.io/pypi/v/quantdinger-mcp?style=flat-square&logo=pypi&logoColor=white)](https://pypi.org/project/quantdinger-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/quantdinger-mcp?style=flat-square&logo=python&logoColor=white)](https://pypi.org/project/quantdinger-mcp/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](../LICENSE)

Thin Model Context Protocol server that exposes a curated subset of the
QuantDinger Agent Gateway (`/api/agent/v1`) as MCP tools, so AI clients
that support MCP (Cursor, Claude-style desktop apps, OpenClaw, NanoBot, etc.)
can drive QuantDinger without writing custom HTTP code.

This package is an **additive** integration. The Agent Gateway REST API
remains the source of truth.

## Security model

- **Order placement is explicit and server-gated.** `place_quick_order`
  requires `T` scope and `confirm_order=true`. If the token is live-capable
  (`paper_only=false`), the MCP call also requires `confirm_live_trading=true`,
  and the backend still requires `AGENT_LIVE_TRADING_ENABLED=true`.
- **Runtime stop is allowed, gated, and explicit.** MCP can read the runtime
  overview and stop a tenant-owned strategy, but stopping requires `T` scope
  and `confirm_stop=true`.
- **Scope gating stays on the server.** The MCP layer forwards your agent
  token; it cannot bypass allowlists or scopes.
- **Defense in depth:** MCP redacts known credential fields (`api_key`,
  `secret`, `passphrase`, …) in JSON responses. The Gateway also redacts
  strategy rows before returning them to agents.
- **Bounded long jobs:** `stream_job_until_done` caps event count and duration;
  `wait_for_job` caps poll time. Tune via env vars below.
- **LLM cost guard:** `submit_ai_optimize` requires `confirm_llm_usage=true`.
- **Payload limits:** indicator and strategy Python source are capped at
  **512 KiB** on both Gateway and MCP client.

## What it exposes

Read-class (R), Workspace write (W), Backtest-class (B), and explicit
Trading-class (T) tools.

| Tool | Class | Purpose |
|------|-------|---------|
| `whoami` | R | Inspect the calling token |
| `check_health` | — | Public liveness (no token) |
| `list_markets` | R | Markets the token may query |
| `search_symbols` | R | Symbols within a market |
| `get_klines` | R | OHLCV bars |
| `get_price` | R | Latest price |
| `list_strategies` | R | Tenant's strategies (compact) |
| `get_strategy` | R | One strategy (secrets redacted) |
| `runtime_overview` | R | Running strategy / position / pending-order overview |
| `stop_strategy` | T | Stop a tenant-owned strategy (`confirm_stop=true`) |
| `place_quick_order` | T | Place paper/live quick order (`confirm_order=true`) |
| `list_jobs` | R | Recent async jobs |
| `get_job` | R | Poll one job |
| `wait_for_job` | R | Poll until terminal or timeout |
| `stream_job_until_done` | R | Bounded SSE consumer |
| `get_indicator_authoring_contract` | R | Indicator I/O contract + starter template |
| `validate_indicator_code` | R | Sandbox validate without save |
| `save_indicator` | W | Persist to indicator library |
| `list_indicators` | R | Tenant indicator list |
| `get_indicator` | R | One indicator with code |
| `create_strategy` | W | Create stopped ScriptStrategy (`strategy_code` or `script_source_id`) |
| `update_strategy` | W | Patch strategy fields (blocks `status=running`) |
| `submit_backtest` | B | Queue a ScriptStrategy backtest (`strict_mode`, `strategy_config`, `script_params`) |
| `regime_detect` | B | Synchronous regime detection |
| `submit_experiment_pipeline` | B | Queue legacy grid pipeline |
| `submit_structured_tune` | B | Queue grid/random tuning |
| `submit_ai_optimize` | B | Queue LLM optimization (requires confirm flag) |
| `list_portfolio_positions` | R | Manual portfolio positions |
| `list_paper_orders` | R | Recent paper orders |

## Install

From PyPI (recommended — works on any machine without cloning the repo):

```bash
pipx install quantdinger-mcp
# or, no install at all (cached on first run):
uvx quantdinger-mcp
# or, into a venv:
pip install quantdinger-mcp
```

Editable install for hacking on the server itself:

```bash
cd mcp_server
pip install -e .
```

## Run

Configuration is env-only so the same binary works in desktop and cloud.

| Variable | Required | Purpose |
|----------|----------|---------|
| `QUANTDINGER_BASE_URL`     | yes | e.g. `http://localhost:8888` |
| `QUANTDINGER_AGENT_TOKEN`  | yes | a token issued via `/api/agent/v1/admin/tokens` |
| `QUANTDINGER_MCP_TRANSPORT`| no  | `stdio` (default), `sse`, or `streamable-http` |
| `QUANTDINGER_MCP_HOST`     | no  | bind host for HTTP transports (default `127.0.0.1`) |
| `QUANTDINGER_MCP_PORT`     | no  | bind port for HTTP transports (default `8000`) |
| `QUANTDINGER_TIMEOUT_S`    | no  | upstream HTTP timeout (default `60`) |
| `QUANTDINGER_MCP_JOB_STREAM_MAX_EVENTS` | no | SSE cap (default `200`) |
| `QUANTDINGER_MCP_JOB_STREAM_MAX_SECONDS` | no | SSE time cap (default `300`) |
| `QUANTDINGER_MCP_JOB_POLL_MAX_SECONDS` | no | `wait_for_job` cap (default `300`) |

### stdio (desktop IDEs)

```bash
QUANTDINGER_BASE_URL=http://localhost:8888 \
QUANTDINGER_AGENT_TOKEN=qd_agent_xxxxx \
quantdinger-mcp
```

### SSE / Streamable HTTP (cloud agents, remote IDEs)

```bash
QUANTDINGER_BASE_URL=http://localhost:8888 \
QUANTDINGER_AGENT_TOKEN=qd_agent_xxxxx \
QUANTDINGER_MCP_TRANSPORT=streamable-http \
QUANTDINGER_MCP_HOST=0.0.0.0 \
QUANTDINGER_MCP_PORT=7800 \
quantdinger-mcp
```

The server is then reachable at `http://<host>:7800/`. Use `sse` instead of
`streamable-http` for clients that only support the older SSE transport.

## Wire into a client

### Local stdio client config

```json
{
  "mcpServers": {
    "quantdinger": {
      "command": "quantdinger-mcp",
      "env": {
        "QUANTDINGER_BASE_URL": "http://localhost:8888",
        "QUANTDINGER_AGENT_TOKEN": "qd_agent_xxxxxxxx"
      }
    }
  }
}
```

### Remote HTTP client config

For clients that connect to an MCP server over HTTP/SSE rather than spawning
a subprocess, point them at the URL the server is bound to (e.g.
`http://your-host:7800`) and let the client handle protocol negotiation.

Never put production exchange keys or admin JWTs in the MCP config — only
agent tokens, scoped to the capabilities the client actually needs.

Recommended scopes:

- Indicator authoring: **R + W**
- ScriptStrategy authoring and backtesting: **R + W + B**
- Runtime overview only: **R**
- Runtime stop from MCP: **R + T** (and call `stop_strategy` with `confirm_stop=true`)
- Quick order placement: **R + T**. Paper orders work with paper-only tokens;
  live orders additionally require `paper_only=false`, `confirm_live_trading=true`,
  and `AGENT_LIVE_TRADING_ENABLED=true` on the backend.

## Common tool calls

MCP clients usually let you ask in natural language, but the examples below
show the exact tool names and required confirmation flags.

### Check connection and token

Ask your MCP client:

```text
Use the QuantDinger MCP tool `whoami` and tell me the token scopes, paper_only
status, and allowed markets.
```

Useful tools:

- `check_health` - verify the backend is reachable.
- `whoami` - inspect scopes, allowlists, and whether the token is paper-only.
- `list_markets` - list markets allowed by the token.

### Read markets

```text
Use `search_symbols` to search Crypto symbols matching BTC, then use
`get_klines` to fetch 300 1H candles for BTC/USDT.
```

Typical parameters:

```json
{
  "market": "Crypto",
  "symbol": "BTC/USDT",
  "timeframe": "1H",
  "limit": 300
}
```

### Create an indicator

Recommended flow:

1. `get_indicator_authoring_contract`
2. `validate_indicator_code`
3. `save_indicator`

Prompt example:

```text
Call `get_indicator_authoring_contract`, write a simple SMA crossover indicator,
validate it with `validate_indicator_code`, then save it with `save_indicator`.
Do not run `submit_backtest` on indicator code; indicators are chart-only.
```

### Create and backtest a ScriptStrategy

Executable strategies must be ScriptStrategy code with `on_init(ctx)` and
`on_bar(ctx, bar)`. To trade an indicator idea, first convert its visual
signals into explicit ScriptStrategy intents such as `ctx.open_long(...)` and
`ctx.close_long(...)`; do not treat a chart `sell` marker as automatic short
entry unless the user explicitly asks for reversal or shorting.

Recommended flow:

1. Write or obtain ScriptStrategy code.
2. `create_strategy` with `strategy_code` or `script_source_id`.
3. `submit_backtest` with the same ScriptStrategy `code`.
4. `wait_for_job` or `stream_job_until_done`.

Prompt example:

```text
Write a long-only EMA crossover ScriptStrategy. Use `submit_backtest` on
BTC/USDT 1H from 2024-01-01 to 2024-06-30 with script_params if needed.
Use `wait_for_job` for the result.
```

### Runtime overview

```text
Use `runtime_overview` and summarize all running strategies, positions,
pending orders, paper orders, and unrealized PnL.
```

Requires scope: **R**

### Stop a strategy

Stopping is a runtime state change, so it requires explicit confirmation:

```text
Stop strategy 123 using `stop_strategy` with `confirm_stop=true`.
```

Tool call shape:

```json
{
  "strategy_id": 123,
  "confirm_stop": true
}
```

Requires scope: **T**

### Place a paper or live quick order

Order placement is always explicit:

```text
Place a small paper quick order on BTC/USDT using `place_quick_order` with
confirm_order=true. Do not use live trading unless I explicitly say so.
```

Paper-order call shape:

```json
{
  "market": "Crypto",
  "symbol": "BTC/USDT",
  "side": "buy",
  "qty": 0.001,
  "order_type": "market",
  "market_type": "spot",
  "confirm_order": true
}
```

Live-order call shape:

```json
{
  "market": "Crypto",
  "symbol": "BTC/USDT",
  "side": "buy",
  "qty": 0.001,
  "order_type": "market",
  "market_type": "spot",
  "credential_id": 1,
  "confirm_order": true,
  "confirm_live_trading": true
}
```

Live orders require all of the following:

- Agent Token has **T** scope.
- Token is issued with `paper_only=false`.
- The backend has `AGENT_LIVE_TRADING_ENABLED=true`.
- The tool call includes `confirm_order=true`.
- The tool call includes `confirm_live_trading=true`.
- `credential_id` points to a saved exchange credential owned by the user.

### Job streaming

For long-running backtests or optimization jobs:

```text
Submit the backtest, then use `stream_job_until_done` with a 300 second cap.
If streaming is unavailable, use `wait_for_job`.
```
