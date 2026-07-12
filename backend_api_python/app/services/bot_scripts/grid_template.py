"""
Grid bot ScriptStrategy placeholder.

Live grid trading is handled by ``app.services.grid`` (resting limit orders +
fill poller). This stub satisfies ScriptStrategy wiring for bot create/edit and
clone-as-script flows without running legacy price-cross logic.
"""
from __future__ import annotations

GRID_BOT_SCRIPT = r'''
# timeframe: 1m
def on_init(ctx):
    ctx.__live_only_template__ = "__QD_LIVE_ONLY_GRID_TEMPLATE__"
    ctx.log("grid bot: live execution uses resting limit-order engine")


def on_bar(ctx, bar):
    pass
'''


def build_grid_bot_script() -> str:
    return GRID_BOT_SCRIPT.strip() + "\n"
