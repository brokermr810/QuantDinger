# QuantDinger Strategy Development Guide

This guide defines the current QuantDinger executable strategy contract. In this document, "strategy" means **ScriptStrategy**: Python code that can be backtested, run live, produce order intents, and pass marketplace review.

If you only want to draw moving averages, lamps, zones, or visual markers, use the [Indicator Development Guide](./INDICATOR_DEV_GUIDE.md). Indicators cannot place orders or be backtested directly. To trade an indicator idea, convert it through the Indicator-to-Strategy workflow and validate the generated ScriptStrategy.

---

## 1. AI Generation Entry Points

QuantDinger currently has three core generation contracts:

| Entry | Output | Boundary |
| --- | --- | --- |
| Indicator AI generation | Chart Indicator | produces `output` for chart display only |
| Homepage strategy quick tool | ScriptStrategy | generates executable strategy code from an idea |
| Indicator-to-Strategy | ScriptStrategy | translates visual indicator semantics into runtime order intents |

Indicator-to-Strategy is not a copy-paste operation. It interprets visual signals and maps them into explicit strategy intents. For a long-only dual moving average indicator:

- `Golden` / `buy` -> `open_long`
- `Death` / `sell` -> `close_long`
- not automatically `open_short`

Short entries should appear only when the user explicitly asks for shorting, both-side trading, or reversal logic.

---

## 2. ScriptStrategy Shape

Every strategy must include:

```python
"""
Strategy Name
One or two neutral sentences describing logic, markets, entries, exits, and risk controls.
"""

def on_init(ctx):
    ...

def on_bar(ctx, bar):
    ...
```

Rules:

- The first non-empty docstring line is the strategy name.
- Following non-empty lines are the strategy description.
- Do not expose name or description as `ctx.param(...)`.
- `on_init(ctx)` initializes parameters and state.
- `on_bar(ctx, bar)` runs once for each bar.

`bar` supports:

```python
bar["open"]
bar["high"]
bar["low"]
bar["close"]
bar["volume"]
bar["timestamp"]
```

### Optional Code Headers

ScriptStrategy metadata has two layers:

- The opening triple-quoted docstring owns the strategy name and description.
- Optional `# key: value` headers can own a small number of runtime defaults.

Recommended shape:

```python
"""
EMA Pullback Long
Trades long pullbacks in an EMA uptrend with optional stop and take-profit controls.
"""
# timeframe: 4H
# signal_timing: next_bar_open
# exit_owner: engine

def on_init(ctx):
    ...
```

Supported headers:

| Header | Values | Meaning |
| --- | --- | --- |
| `# timeframe: 1D` | `1m`, `3m`, `5m`, `15m`, `30m`, `1H`, `4H`, `1D`, `1W` | Code-owned default K-line period. Overrides saved panel config in backtests/live snapshots. |
| `# kline_timeframe: 1D` | same as `timeframe` | Alias for `timeframe`. |
| `# signal_timing: next_bar_open` | `next_bar_open`, `same_bar_close` | Execution timing. `next_bar_open` is the default and recommended. |
| `# exit_owner: engine` | `engine`, `strategy`, `indicator` | Whether server-side risk exits can close positions. Use `engine` or omit it for engine-managed `# @strategy` risk annotations; `strategy` is accepted for historical templates and currently still allows engine risk; only `indicator` disables server-side price exits. |

Rules:

- Do not put symbol, market, direction, investment amount, or leverage in headers; those belong to the run panel.
- Do not write these headers casually. If absent, the run panel and saved strategy config decide.
- Prefer `next_bar_open`. Do not create manual `pending_signal` state only to delay execution by one bar.
- `same_bar_close` is more optimistic and should be used only when explicitly requested.
- `signal_form` and `flip_mode` are legacy indicator-conversion headers. New ScriptStrategy code should not rely on them.

### Code-Owned Risk Annotations

`# @strategy ...` annotations are still supported for ScriptStrategy code. They are not chart-indicator syntax and they are not `ctx.param(...)` UI knobs. They declare code-owned backtest/live risk defaults that the snapshot resolver passes into the execution engine.

Example:

```python
# @strategy entryPct 1
# @strategy stopLossPct 0.04
# @strategy takeProfitPct 0.08
# @strategy trailingEnabled true
# @strategy trailingStopPct 0.015
# @strategy trailingActivationPct 0.03
# @strategy maxHoldingBars 12
# exit_owner: engine
```

Supported annotations:

| Annotation | Value | Meaning |
| --- | --- | --- |
| `# @strategy entryPct 1` | `0.01` to `1` | Fraction of the run-panel investment amount used per entry. `1` means 100%. |
| `# @strategy stopLossPct 0.04` | `0` to `1` | Server-side stop-loss ratio. `0.04` means 4%. |
| `# @strategy takeProfitPct 0.08` | `0` to `5` | Server-side take-profit ratio. `0.08` means 8%. |
| `# @strategy trailingEnabled true` | `true` / `false` | Enables trailing-stop logic when paired with trailing values. |
| `# @strategy trailingStopPct 0.015` | `0` to `1` | Trailing distance ratio. `0.015` means 1.5%. |
| `# @strategy trailingActivationPct 0.03` | `0` to `1` | Profit ratio required before trailing stop activates. |
| `# @strategy maxHoldingBars 12` | integer `>= 0` | Maximum holding bars before engine-managed exit. `0` disables it. |

Rules:

- Use these annotations only when risk should be owned by the code itself.
- All percentage-like values are ratios, not whole percentages: write `0.04` for 4%, not `4`.
- These values are read by backtests and live snapshots. If they are absent, engine-managed risk defaults to off except entry sizing.
- `exit_owner: engine` allows engine-managed stops, take-profits, trailing stops, and max-holding exits to close positions.
- `exit_owner: strategy` is a historical template value; the current runtime does not treat it as "disable engine risk". New templates should prefer `engine` or omit the header.
- `exit_owner: indicator` is an advanced compatibility switch for the old indicator-conversion path. It means exits are fully owned by code-generated `close_*` intents and server-side price exits should not close positions.
- If the script implements its own hard stop, take-profit, trailing exit, or staged exits, do not also write equivalent `@strategy` risk annotations.
- Grid, DCA, and martingale are delivered as Trading Robots while still producing editable standard strategy code. DCA and martingale express their state machines in `on_bar`; grid declares its configuration through `ctx.configure_robot(...)` in `on_init`, while the host supplies durable resting orders, fill polling, and reconciliation.
- Do not put these annotations in chart-only indicators.

---

## 3. Product Panel vs Strategy Code

The run panel owns:

- symbol / market
- spot or swap
- trade direction: long / short / both
- investment amount
- leverage
- account, notification, and live-risk switches

Strategy code owns:

- entry, exit, scale-in, scale-out conditions
- periods, thresholds, multipliers, layer counts, cooldowns
- state persistence and duplicate-order protection
- logs, basket checkpoints, and strategy-specific risk logic

Do not declare run-panel fields as parameters:

```python
# Wrong
ctx.direction = ctx.param("direction", "long")
ctx.market_type = ctx.param("market_type", "swap")
ctx.investment_amount = ctx.param("investment_amount", 1000)
ctx.leverage = ctx.param("leverage", 3)
ctx.base_notional = ctx.param("base_notional", 50)
```

Read runtime context instead:

```python
direction = ctx.direction
market_type = ctx.market_type
budget = float(ctx.investment_amount or 0)
leverage = float(ctx.leverage or 1)
```

### Backtest and Live Runtime Model

The professional strategy path is:

```text
ScriptStrategy Code
    -> ScriptBacktestRunner
    -> BacktestContext
    -> BrokerSimulator
    -> Trades / Equity Curve / Audit / Replay
```

In backtests, strategy code runs once per K-line bar. With the default `signal_timing: next_bar_open`, an order created from confirmed bar N is submitted to the broker at bar N+1 open. The broker immediately updates cash, margin, positions, fees, slippage, and equity; the next bar sees the latest account state.

Live trading has two clocks:

- Price tick: normal script strategies sync latest price about every 10 seconds by default for server-side stop-loss, take-profit, trailing stop, order status, and notifications. Override with `STRATEGY_TICK_INTERVAL_SEC`.
- K-line signal clock: strict mode is on by default. Signals are calculated only after a new strategy-timeframe bar has closed. The scheduler polls near the natural timeframe boundary plus about 2 seconds by default, controlled by `KLINE_BOUNDARY_POLL_OFFSET_SEC`.

For example, if a user starts a 1H strategy at 10:20, the runtime loads historical bars immediately; the next new closed-bar signal check happens around 11:00:02, not 11:20.

Strict mode means:

- Signals are confirmed on closed bars to stay close to backtest semantics.
- Stop-loss, take-profit, and trailing stop checks use the latest price tick and do not wait for bar close.
- Normal script strategies have same-candle de-duplication and a signal state machine to avoid repeated open/stop/re-open loops on one K-line.
- Non-strict mode updates the forming bar with current price and may evaluate more often. It is faster, but may diverge from backtests and should be used only when the user explicitly wants intrabar triggering.

### Core Context API

Strategy code should rely only on these core context capabilities:

| Category | API |
| --- | --- |
| Time and market | `ctx.current_dt`, `ctx.symbol`, `ctx.market_type`, `ctx.direction`, `ctx.leverage` |
| Account | `ctx.initial_capital`, `ctx.equity`, `ctx.available_cash`, `ctx.available_margin` |
| Positions | `ctx.position`, `ctx.positions` |
| Data | `ctx.bars(count)` |
| Parameters and state | `ctx.param(name, default)`, `ctx.state.get(name)`, `ctx.state.set(name, value)` |
| Orders | `ctx.open_long(...)`, `ctx.close_long(...)`, `ctx.open_short(...)`, `ctx.close_short(...)`, `ctx.order_value(...)`, `ctx.order_target(...)` |
| Diagnostics | `ctx.log(...)` |

---

## 4. Parameters

Declare strategy knobs in `on_init(ctx)`:

```python
def on_init(ctx):
    ctx.fast_period = ctx.param("fast_period", 12)
    ctx.slow_period = ctx.param("slow_period", 36)
    ctx.cooldown_bars = ctx.param("cooldown_bars", 0)
    ctx.stop_loss_pct = ctx.param("stop_loss_pct", 0.0)
    ctx.take_profit_pct = ctx.param("take_profit_pct", 0.0)
```

Rules:

- Every `ctx.param` call must have a default.
- Do not repeatedly call `ctx.param` inside `on_bar`.
- Only strategy knobs belong here; symbol, direction, budget, and leverage do not.
- `*_pct` values use ratios: `0.02 = 2%`, `0.8 = 80%`.
- If the user did not request risk controls, default them to `0` or off.

---

## 5. Explicit Order Intents

QuantDinger uses explicit intents:

| Intent | Meaning |
| --- | --- |
| `open_long` | open or create a long leg |
| `close_long` | close the long leg only; does not open short |
| `open_short` | open or create a short leg |
| `close_short` | close the short leg only; does not open long |
| `add_long` | increase an existing long leg |
| `add_short` | increase an existing short leg |
| `reduce_long` | partially reduce a long leg |
| `reduce_short` | partially reduce a short leg |

Reversal must be two explicit actions:

```text
close_long -> open_short
close_short -> open_long
```

Only generate reversal/flip logic when the user explicitly asks for it. Do not interpret `sell`, `close_long`, or `Death` as `open_short` by default.

---

## 6. Basket API

New strategies should prefer baskets when sizing by quote currency. `notional` means quote currency amount, such as USDT.

Hard rules:

- `ctx.basket(side)` accepts only `"long"` or `"short"`.
- If the runtime object exposes `ctx.side`, it must also contain only `"long"` or `"short"`. Do not use `"open"`, `"close"`, `"buy"`, `"sell"`, or `"both"` as a side value.
- Never use `"buy"` or `"sell"` as basket side.
- `open_child_order(...)` must include `layer=` and `order=` every time.
- Valid actions are `"open"`, `"add"`, `"reduce"`, and `"close"`.

Mapping:

| side | action | strategy intent |
| --- | --- | --- |
| long | open | `open_long` |
| long | add | `add_long` |
| long | reduce | `reduce_long` |
| long | close | `close_long` |
| short | open | `open_short` |
| short | add | `add_short` |
| short | reduce | `reduce_short` |
| short | close | `close_short` |

Example:

```python
ctx.basket("long").open_child_order(
    layer=1,
    order=1,
    notional=quote_amount,
    price=price,
    action="open",
    payload={"reason": "golden_cross"},
)

ctx.basket("long").open_child_order(
    layer=1,
    order=2,
    notional=quote_amount,
    price=price,
    action="close",
    payload={"reason": "death_cross"},
)
```

---

## 7. Direct Order API

Direct intent helpers are useful for simple strategies:

```python
ctx.open_long(price=price, amount=base_qty, reason="entry")
ctx.add_long(price=price, amount=base_qty, reason="scale_in")
ctx.reduce_long(price=price, amount=base_qty, reason="partial_exit")
ctx.close_long(price=price, reason="exit")

ctx.open_short(price=price, amount=base_qty, reason="entry")
ctx.add_short(price=price, amount=base_qty, reason="scale_in")
ctx.reduce_short(price=price, amount=base_qty, reason="partial_exit")
ctx.close_short(price=price, reason="exit")

ctx.order_value(side="long", value=quote_amount, reason="budget_entry")
ctx.order_target(side="long", target_value=target_quote_amount, reason="rebalance")
```

Important:

- Direct `amount` is base quantity, not quote notional.
- `ctx.order_value(...)` orders by quote-currency value and is suitable for budget-based entries.
- `ctx.order_target(...)` moves a side toward a target quote-currency exposure and is suitable for rebalancing.
- Prefer basket `notional` for budget-based entries.
- `ctx.buy()` and `ctx.sell()` are simple directional helpers and should not be used for scale-in, reversal, or complex scripts.
- AI-generated strategies should avoid generic buy/sell auto semantics.

---

## 8. State Management

Strategies with cooldowns, layers, scale-ins, exits, or re-entry limits must use `ctx.state`.

Common state fields:

```python
ctx.state.set("bar_index", current_bar)
ctx.state.set("last_order_bar", current_bar)
ctx.state.set("entry_price", price)
ctx.state.set("layer", 1)
ctx.state.set("pending_entry", False)
ctx.state.set("cooldown_until", current_bar + ctx.cooldown_bars)
```

Duplicate-order protection:

```python
bar_index = int(ctx.state.get("bar_index", -1) or -1) + 1
ctx.state.set("bar_index", bar_index)

last_order_bar = int(ctx.state.get("last_order_bar", -999999) or -999999)
if last_order_bar == bar_index:
    return

# issue order...
ctx.state.set("last_order_bar", bar_index)
```

Do not put all logic behind:

```python
if ctx.position.is_flat():
    ...
    return
```

If a strategy supports scale-in, add/reduce/close logic must still run after a same-side position exists.

---

## 9. Spot and Swap Rules

Spot:

- long only
- leverage fixed to 1
- short intents are rejected

Swap:

- long, short, and both-side modes are supported
- leverage, funding, slippage, and fees come from runtime/backtest config

The script may read `ctx.market_type` and `ctx.direction` for guards, but should not hard-code them as parameters.

---

## 10. Risk Controls

If the user did not request risk controls, default them off:

```python
ctx.stop_loss_pct = ctx.param("stop_loss_pct", 0.0)
ctx.take_profit_pct = ctx.param("take_profit_pct", 0.0)
```

Simple long stop/take-profit pattern:

```python
entry_price = float(ctx.state.get("entry_price", 0.0) or 0.0)
if entry_price > 0 and ctx.position.has_long():
    if ctx.stop_loss_pct > 0 and price <= entry_price * (1.0 - ctx.stop_loss_pct):
        ctx.basket("long").open_child_order(
            layer=1,
            order=99,
            notional=0,
            price=price,
            action="close",
            payload={"reason": "stop_loss"},
        )
        ctx.state.set("last_order_bar", bar_index)
        return
```

Trailing exits, partial take-profits, and break-even stops require explicit state fields and duplicate-order guards.

---

## 11. Indicator-to-Strategy Rules

Conversion must preserve the indicator's visual signal meaning:

| Indicator visual signal | Default strategy meaning |
| --- | --- |
| `buy` / `Golden` / `Bullish` | `open_long` in long-only mode |
| `sell` / `Death` / `Bearish exit` | `close_long` in long-only mode |
| explicit bearish short entry | may become `open_short` |
| explicit reversal request | close first, then open opposite |
| explicit add/reduce request | use `add_*` / `reduce_*` or basket action |

Do not:

- copy indicator `output` into strategy code
- turn `sell` directly into a short entry
- use `ctx.basket("buy")` or `ctx.basket("sell")`
- omit `layer=` / `order=`
- silently add grid, DCA, martingale, layers, active TP/SL, or reversal behavior

---

## 12. Full Example: EMA Long-Only Strategy

```python
"""
Dual EMA Long Strategy
Long-only EMA crossover strategy. Golden crosses open a long position, death crosses close the long position, and optional stop/take-profit defaults are off.
"""

def on_init(ctx):
    ctx.fast_period = ctx.param("fast_period", 12)
    ctx.slow_period = ctx.param("slow_period", 26)
    ctx.order_pct = ctx.param("order_pct", 1.0)
    ctx.cooldown_bars = ctx.param("cooldown_bars", 0)
    ctx.stop_loss_pct = ctx.param("stop_loss_pct", 0.0)
    ctx.take_profit_pct = ctx.param("take_profit_pct", 0.0)
    ctx.state.set("bar_index", -1)
    ctx.state.set("last_order_bar", -999999)
    ctx.state.set("entry_price", 0.0)

def _ema(values, period):
    if not values:
        return []
    alpha = 2.0 / (float(period) + 1.0)
    out = []
    ema = None
    for value in values:
        price = float(value)
        ema = price if ema is None else alpha * price + (1.0 - alpha) * ema
        out.append(ema)
    return out

def _quote_amount(ctx):
    try:
        budget = float(ctx.investment_amount or 0.0)
    except Exception:
        budget = 0.0
    pct = max(0.0, min(1.0, float(ctx.order_pct or 0.0)))
    return budget * pct

def on_bar(ctx, bar):
    bar_index = int(ctx.state.get("bar_index", -1) or -1) + 1
    ctx.state.set("bar_index", bar_index)

    price = float(bar["close"])
    history = ctx.bars(max(int(ctx.slow_period) + 3, 5))
    closes = [float(item["close"]) for item in history]
    if len(closes) < max(int(ctx.fast_period), int(ctx.slow_period)) + 2:
        return

    fast = _ema(closes, int(ctx.fast_period))
    slow = _ema(closes, int(ctx.slow_period))
    golden = fast[-1] > slow[-1] and fast[-2] <= slow[-2]
    death = fast[-1] < slow[-1] and fast[-2] >= slow[-2]

    last_order_bar = int(ctx.state.get("last_order_bar", -999999) or -999999)
    if last_order_bar == bar_index:
        return
    cooldown_until = int(ctx.state.get("cooldown_until", -1) or -1)
    if cooldown_until >= bar_index:
        return

    entry_price = float(ctx.state.get("entry_price", 0.0) or 0.0)

    if ctx.position.has_long() and entry_price > 0:
        if ctx.stop_loss_pct > 0 and price <= entry_price * (1.0 - float(ctx.stop_loss_pct)):
            ctx.basket("long").open_child_order(layer=1, order=90, notional=0, price=price, action="close", payload={"reason": "stop_loss"})
            ctx.state.set("last_order_bar", bar_index)
            return
        if ctx.take_profit_pct > 0 and price >= entry_price * (1.0 + float(ctx.take_profit_pct)):
            ctx.basket("long").open_child_order(layer=1, order=91, notional=0, price=price, action="close", payload={"reason": "take_profit"})
            ctx.state.set("last_order_bar", bar_index)
            return

    if golden and not ctx.position.has_long():
        quote = _quote_amount(ctx)
        if quote > 0:
            ctx.basket("long").open_child_order(layer=1, order=1, notional=quote, price=price, action="open", payload={"reason": "golden_cross"})
            ctx.state.set("entry_price", price)
            ctx.state.set("last_order_bar", bar_index)
            if int(ctx.cooldown_bars or 0) > 0:
                ctx.state.set("cooldown_until", bar_index + int(ctx.cooldown_bars))
        return

    if death and ctx.position.has_long():
        ctx.basket("long").open_child_order(layer=1, order=2, notional=0, price=price, action="close", payload={"reason": "death_cross"})
        ctx.state.set("entry_price", 0.0)
        ctx.state.set("last_order_bar", bar_index)
```

---

## 13. Backtest and Publishing Requirements

Strategies can have multiple saved versions. To avoid publishing untested code:

- Code must be saved as a Script Source.
- The strategy must have at least one successful backtest record.
- Publishing is rejected by both frontend and backend until a successful backtest exists.
- Backtest symbol, market, timeframe, parameters, and results should match the intended strategy use.

Before publishing:

- validation passes
- no indicator `output/plots/signals` contract remains
- run-panel fields are not declared with `ctx.param`
- no `ctx.basket("buy")` or `ctx.basket("sell")`
- every child order has `layer=` and `order=`
- spot strategies have no short intent
- sell/death semantics are not accidentally written as short entries

---

## 14. Common Validation Hints

| Hint | Meaning | Fix |
| --- | --- | --- |
| `MISSING_ON_INIT` | `on_init(ctx)` is missing | add init handler |
| `MISSING_ON_BAR` | `on_bar(ctx, bar)` is missing | add bar handler |
| `CTX_PARAM_MISSING_DEFAULT` | `ctx.param` has no default | use `ctx.param("name", default)` |
| `CTX_PARAM_RUN_PANEL_FIELD` | run-panel field declared as parameter | read `ctx.direction`, etc. |
| `INDICATOR_OUTPUT_CONTRACT` | indicator output remains in strategy | remove output/plots/signals |
| `BASKET_CHILD_ORDER_MISSING_LAYER_ORDER` | child order lacks layer/order | pass `layer=` and `order=` |
| `BASKET_SIDE_MUST_BE_LONG_OR_SHORT` | basket side is invalid | use `"long"` or `"short"` only |

---

## 15. Best Practices

- Use indicators to make ideas visible; use ScriptStrategy to execute them.
- Default templates should focus on trend, breakout, moving average, momentum, mean reversion, and volatility-stop logic. Do not use grid, DCA, or martingale as ordinary strategy templates.
- Keep defaults conservative.
- Separate open, add, reduce, and close.
- Reversal is close first, then open opposite.
- Scale-in logic needs max layers, price distance, cooldown, and stop protection.
- Keep loops bounded by lookback windows.
- Log important state changes without spamming.
- Save a new version and rerun backtests after meaningful changes.
