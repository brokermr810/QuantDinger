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
            ctx.basket("long").open_child_order(
                layer=1,
                order=90,
                notional=0,
                price=price,
                action="close",
                payload={"reason": "stop_loss"},
            )
            ctx.state.set("last_order_bar", bar_index)
            return

        if ctx.take_profit_pct > 0 and price >= entry_price * (1.0 + float(ctx.take_profit_pct)):
            ctx.basket("long").open_child_order(
                layer=1,
                order=91,
                notional=0,
                price=price,
                action="close",
                payload={"reason": "take_profit"},
            )
            ctx.state.set("last_order_bar", bar_index)
            return

    if golden and not ctx.position.has_long():
        quote = _quote_amount(ctx)
        if quote > 0:
            ctx.basket("long").open_child_order(
                layer=1,
                order=1,
                notional=quote,
                price=price,
                action="open",
                payload={"reason": "golden_cross"},
            )
            ctx.state.set("entry_price", price)
            ctx.state.set("last_order_bar", bar_index)
            if int(ctx.cooldown_bars or 0) > 0:
                ctx.state.set("cooldown_until", bar_index + int(ctx.cooldown_bars))
        return

    if death and ctx.position.has_long():
        ctx.basket("long").open_child_order(
            layer=1,
            order=2,
            notional=0,
            price=price,
            action="close",
            payload={"reason": "death_cross"},
        )
        ctx.state.set("entry_price", 0.0)
        ctx.state.set("last_order_bar", bar_index)
