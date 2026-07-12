# Agent Quickstart 閳?using QuantDinger from an AI agent

This quickstart shows how to drive the QuantDinger Agent Gateway
(`/api/agent/v1`) from any AI / automation client. It assumes you already
have the stack running (see the root `README.md`) and admin credentials.

For the full design, see [AI_INTEGRATION_DESIGN.md](AI_INTEGRATION_DESIGN.md).
For the machine-readable contract, see [agent-openapi.json](agent-openapi.json).

---

## 1. Issue an agent token (one-time)

Tokens are minted by a logged-in human user (Profile 閳?**My Agent Token**) or
by an admin via `/api/agent/v1/admin/tokens`. Agents never mint tokens for
themselves. Get a normal JWT first (login UI or `/api/auth/login`), then:

```bash
curl -X POST http://localhost:8888/api/agent/v1/me/tokens \
  -H "Authorization: Bearer <USER_JWT>" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "my-research-bot",
        "scopes": "R,B",
        "markets": "Crypto,USStock",
        "instruments": "*",
        "rate_limit_per_min": 120,
        "expires_in_days": 30
      }'
```

Admin equivalent (may include `C` scope):

```bash
curl -X POST http://localhost:8888/api/agent/v1/admin/tokens \
  -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "my-research-bot",
        "scopes": "R,B",
        "markets": "Crypto,USStock",
        "instruments": "*",
        "rate_limit_per_min": 120,
        "expires_in_days": 30
      }'
```

Response (the full token is shown **once**):

```json
{
  "code": 0,
  "message": "issued",
  "data": {
    "id": 1,
    "name": "my-research-bot",
    "token": "qd_agent_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "token_prefix": "qd_agent_xxxxxxxx",
    "scopes": ["B","R"],
    "markets": ["Crypto","USStock"],
    "paper_only": true
  }
}
```

Store the `token` value somewhere safe (password manager, secrets store).
The server only keeps a hash 閳?there is no way to recover it later.

### Scope cheat sheet

| Scope | Class                      | Default | Notes |
|-------|----------------------------|---------|-------|
| `R`   | Read                       | yes     | Market data, strategies, jobs |
| `W`   | Workspace write            | no      | Create / patch strategies     |
| `B`   | Backtest / simulation      | no      | Async jobs                    |
| `N`   | Notifications & misc side-effects | no | rate-limited                  |
| `C`   | Credentials                | no      | admin only; not exposed to agents |
| `T`   | Trading / capital          | no      | paper-only by default; live requires opt-in |

---

## 2. Smoke-test the token

```bash
TOKEN=qd_agent_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

curl -s http://localhost:8888/api/agent/v1/health
curl -s http://localhost:8888/api/agent/v1/whoami \
  -H "Authorization: Bearer $TOKEN"
```

`/health` is public; `/whoami` should echo your token's scopes and allowlists.

---

## 3. Read market data (class R)

```bash
curl -s "http://localhost:8888/api/agent/v1/markets" \
  -H "Authorization: Bearer $TOKEN"

curl -s "http://localhost:8888/api/agent/v1/markets/Crypto/symbols?keyword=BTC&limit=5" \
  -H "Authorization: Bearer $TOKEN"

curl -s "http://localhost:8888/api/agent/v1/klines?market=Crypto&symbol=BTC/USDT&timeframe=1D&limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 4. Run a backtest (class B, async)

```bash
curl -s -X POST http://localhost:8888/api/agent/v1/backtest/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: ma-cross-2024-q1-001" \
  -d '{
        "code": "fast = SMA(close, 10)\nslow = SMA(close, 30)\nopen_long = CROSSOVER(fast, slow).fillna(False).astype(bool)\nopen_short = CROSSUNDER(fast, slow).fillna(False).astype(bool)\ndf[\"open_long\"] = open_long\ndf[\"close_short\"] = open_long\ndf[\"open_short\"] = open_short\ndf[\"close_long\"] = open_short",
        "market": "Crypto",
        "symbol": "BTC/USDT",
        "timeframe": "1D",
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "strictMode": true
      }'
```

You get back `{ job_id, status: "queued" }`. Poll:

```bash
curl -s "http://localhost:8888/api/agent/v1/jobs/<job_id>" \
  -H "Authorization: Bearer $TOKEN"
```

When `status` becomes `succeeded`, the backtest result is in `result`.

Set `"strictMode": true` (default) for live-aligned next-bar-open execution;
`false` uses the aggressive MTF/bar path (matches the IDE non-strict toggle).

The `Idempotency-Key` header makes retries safe: the second call with the
same key returns the original job instead of submitting a duplicate.

### 4.1 Code generation contract

Agents must choose the contract by asset type. Do not mix indicator code and strategy code in the same generated artifact.

| Asset type | Contract | Where to read more |
|------------|----------|--------------------|
| Chart indicator | Compute visual `output` only. No orders, no backtest columns, no `# @strategy`. | [`docs/INDICATOR_DEV_GUIDE.md`](../INDICATOR_DEV_GUIDE.md) |
| Script Strategy | Implement `on_init(ctx)` and `on_bar(ctx, bar)`, then emit explicit order intents through `ctx.open_long`, `ctx.close_long`, `ctx.open_short`, `ctx.close_short`, `ctx.add_long`, and `ctx.add_short`. | [`docs/STRATEGY_DEV_GUIDE.md`](../STRATEGY_DEV_GUIDE.md) |
| Indicator-to-strategy conversion | Explain the indicator visually, then translate its chart signals into explicit Script Strategy intents. | [`docs/STRATEGY_DEV_GUIDE.md`](../STRATEGY_DEV_GUIDE.md) |

For normal AI generation and product workflows, Script Strategy is the only executable strategy contract. A generated strategy must not return old DataFrame execution columns such as `df['open_long']`, `df['close_long']`, `df['open_short']`, or `df['close_short']`. Those columns belong only to a legacy low-level compatibility path and should not be generated for users.

Default conversion rule for a two-signal long-only indicator:

```text
buy / golden cross  -> ctx.open_long(...)
sell / death cross  -> ctx.close_long(...)
```

Do not infer reversal or short selling from a two-signal indicator. Generate short-side intents only when the user explicitly asks for short, both-side, reverse, hedge, or similar behavior.

Basket strategies have one extra rule: `ctx.side` must be `"long"` or `"short"` only. Basket child orders must pass both keyword-only arguments:

```python
ctx.open_child_order(layer=layer, order=order)
```

The backtest center owns market, symbol, timeframe, leverage, fees, slippage, date range, and starting capital. Generated strategy code should not override those run-panel settings unless the user explicitly asks for a code-owned default parameter.

### 4.2 Stream partial results (SSE)

For long-running jobs (`ai-optimize`, `structured-tune`, multi-round
pipelines) the Gateway exposes a Server-Sent Events stream so an LLM client
can react to partial results without polling:

```bash
curl -N "http://localhost:8888/api/agent/v1/jobs/<job_id>/stream" \
  -H "Authorization: Bearer $TOKEN"
```

Frame types:

| Event      | When                                             | Payload |
|------------|--------------------------------------------------|---------|
| `snapshot` | first frame; current row from `qd_agent_jobs`    | full job record |
| `progress` | each call the runner makes to `on_progress(...)` | `{seq, ts, data, terminal}` |
| `ping`     | every ~15s while idle                            | `{ts}` (keepalive) |
| `result`   | once, just before close                          | `{job_id, status, result, error}` |

Reconnect with `?since=<seq>` (or the standard `Last-Event-ID` header) to
resume from a known sequence number. If the job already finished, the server
returns the `snapshot` and `result` frames immediately and closes 閳?your
client doesn't need a separate code path.

---

## 5. Indicators (class R / W)

Agents author indicators as **Python scripts**, not via the human SSE
`aiGenerate` endpoint. Start with the authoring contract:

```bash
curl -s http://localhost:8888/api/agent/v1/indicators/authoring-contract \
  -H "Authorization: Bearer $TOKEN"
```

Validate without saving (R):

```bash
curl -s -X POST http://localhost:8888/api/agent/v1/indicators/validate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "code": "df = df.copy()\noutput = {\"name\":\"Example\", \"plots\": [], \"signals\": [], \"layers\": []}" }'
```

Save into the tenant library so it appears in the IDE list (W; max 512 KiB):

```bash
curl -s -X POST http://localhost:8888/api/agent/v1/indicators \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "name": "my-ma-cross", "code": "..." }'
```

Indicators are chart-only. They can be saved and edited through the indicator
library, but they cannot be backtested directly and cannot be embedded as an
executable strategy. Convert the idea to ScriptStrategy code before backtesting
or live trading.

---

## 6. Strategies (class R / W)

```bash
# list (R)
curl -s "http://localhost:8888/api/agent/v1/strategies" -H "Authorization: Bearer $TOKEN"

# create (W) - never auto-runs; status defaults to 'stopped'
curl -s -X POST http://localhost:8888/api/agent/v1/strategies \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "strategy_name": "ma-cross-bot",
        "strategy_type": "ScriptStrategy",
        "market_category": "Crypto",
        "strategy_mode": "script",
        "strategy_code": "def on_init(ctx):\n    pass\n\ndef on_bar(ctx, bar):\n    pass\n",
        "trading_config": { "symbol": "BTC/USDT", "timeframe": "1D",
                            "initial_capital": 10000, "leverage": 1 } }'
```

Switching `status` to `running` requires a `T` scope on the token (see
the design doc for the rationale).

---

## 7. Trading (class T) 閳?paper-only by default

A token with `T` is hard-gated:

1. The token must explicitly set `paper_only=false` (default is `true`).
2. The deployment must set env `AGENT_LIVE_TRADING_ENABLED=true` to allow live.

Until both are set, every `T` call records a **paper** order in
`qd_agent_paper_orders` using the latest market price as the simulated fill:

```bash
curl -s -X POST http://localhost:8888/api/agent/v1/quick-trade/orders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "market": "Crypto", "symbol": "BTC/USDT",
        "side": "buy", "qty": 0.001 }'
```

Cancel any open paper orders for this tenant in one call:

```bash
curl -s -X POST http://localhost:8888/api/agent/v1/quick-trade/kill-switch \
  -H "Authorization: Bearer $TOKEN"
```

---

## 8. Audit & revoke (admin)

```bash
# recent agent calls (this tenant)
curl -s "http://localhost:8888/api/agent/v1/admin/audit?limit=50" \
  -H "Authorization: Bearer <ADMIN_JWT>"

# list / revoke tokens
curl -s "http://localhost:8888/api/agent/v1/admin/tokens" \
  -H "Authorization: Bearer <ADMIN_JWT>"

curl -s -X DELETE "http://localhost:8888/api/agent/v1/admin/tokens/1" \
  -H "Authorization: Bearer <ADMIN_JWT>"
```

Revoking a token sets its status to `revoked`; subsequent calls with that
token return `401`.

---

## 9. MCP integration (optional)

For AI clients that speak MCP (Cursor, Claude-style desktops, cloud agents),
see [`mcp_server/README.md`](../../mcp_server/README.md) for the Python server
that wraps Read + Workspace write + Backtest tools from the Gateway.

**Not exposed via MCP (by design):** live/paper trading (`quick-trade/*`),
admin token issuance, and credential vault access. Use REST with appropriately
scoped tokens when you explicitly need those capabilities.

MCP long-running jobs: use `wait_for_job` or bounded `stream_job_until_done`
instead of opening raw SSE yourself.

Two transports are supported via `QUANTDINGER_MCP_TRANSPORT`:

* `stdio` (default) 閳?desktop IDEs that spawn the server as a subprocess.
* `sse` / `streamable-http` 閳?cloud agents and remote IDEs that connect to a
  long-running HTTP endpoint. Combine with `QUANTDINGER_MCP_HOST` /
  `QUANTDINGER_MCP_PORT`.

---

## 10. Errors

All `/api/agent/v1/...` errors share this envelope:

```json
{
  "code":      400,
  "message":   "human-readable reason",
  "details":   "...",
  "retriable": false
}
```

| HTTP | Meaning                              | Retry? |
|------|--------------------------------------|--------|
| 401  | Missing / invalid / expired token    | no (re-issue) |
| 403  | Token lacks scope or allowlist       | no |
| 404  | Resource not found in this tenant    | no |
| 429  | Rate limit (per token)               | yes (after 60s) |
| 500  | Internal error                        | sometimes |
| 502  | Upstream data source failure          | yes |
| 501  | Live trading requested but not enabled| no |
