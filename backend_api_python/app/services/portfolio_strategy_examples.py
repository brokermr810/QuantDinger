"""Built-in portfolio strategy examples for the backtest workbench."""

from __future__ import annotations


PORTFOLIO_STRATEGY_EXAMPLES = (
    {
        "id": -1001,
        "template_key": "portfolio_momentum_top_n",
        "name_i18n_key": "portfolioTemplate.momentum.name",
        "description_i18n_key": "portfolioTemplate.momentum.description",
        "icon": "rise",
        "accent": "blue",
        "param_schema": {"params": [
            {"name": "top_n", "type": "integer", "default": 10, "min": 1, "max": 100, "step": 1, "label_key": "portfolioTemplate.params.topN.label", "description_key": "portfolioTemplate.params.topN.description"},
            {"name": "lookback", "type": "integer", "default": 60, "min": 2, "max": 252, "step": 1, "label_key": "portfolioTemplate.params.lookback.label", "description_key": "portfolioTemplate.params.lookback.description"},
        ]},
        "code": '''"""
Cross-sectional Momentum Top-N

Rank the point-in-time universe by trailing return and hold equal-weight leaders.
"""

def on_init(ctx):
    ctx.param("top_n", 10, min=1, max=100, step=1)
    ctx.param("lookback", 60, min=2, max=252, step=1)

def on_rebalance(ctx, panel):
    top_n = int(ctx.param("top_n", 10))
    lookback = int(ctx.param("lookback", 60))
    scores = ctx.factor("momentum", panel, period=lookback)
    ctx.long_only_top_n(scores, n=top_n)
''',
    },
    {
        "id": -1002,
        "template_key": "portfolio_low_volatility_top_n",
        "name_i18n_key": "portfolioTemplate.lowVolatility.name",
        "description_i18n_key": "portfolioTemplate.lowVolatility.description",
        "icon": "safety",
        "accent": "cyan",
        "param_schema": {"params": [
            {"name": "top_n", "type": "integer", "default": 10, "min": 1, "max": 100, "step": 1, "label_key": "portfolioTemplate.params.topN.label", "description_key": "portfolioTemplate.params.topN.description"},
            {"name": "lookback", "type": "integer", "default": 20, "min": 2, "max": 252, "step": 1, "label_key": "portfolioTemplate.params.lookback.label", "description_key": "portfolioTemplate.params.lookback.description"},
        ]},
        "code": '''"""
Cross-sectional Low Volatility Top-N

Rank the point-in-time universe by realized volatility and hold the lowest-risk names.
"""

def on_init(ctx):
    ctx.param("top_n", 10, min=1, max=100, step=1)
    ctx.param("lookback", 20, min=2, max=252, step=1)

def on_rebalance(ctx, panel):
    top_n = int(ctx.param("top_n", 10))
    lookback = int(ctx.param("lookback", 20))
    volatility = ctx.factor("realized_volatility", panel, period=lookback)
    scores = {symbol: -value for symbol, value in volatility.items()}
    ctx.long_only_top_n(scores, n=top_n)
''',
    },
    {
        "id": -1003,
        "template_key": "portfolio_mean_reversion_top_n",
        "name_i18n_key": "portfolioTemplate.meanReversion.name",
        "description_i18n_key": "portfolioTemplate.meanReversion.description",
        "icon": "sync",
        "accent": "purple",
        "param_schema": {"params": [
            {"name": "top_n", "type": "integer", "default": 10, "min": 1, "max": 100, "step": 1, "label_key": "portfolioTemplate.params.topN.label", "description_key": "portfolioTemplate.params.topN.description"},
            {"name": "lookback", "type": "integer", "default": 20, "min": 2, "max": 252, "step": 1, "label_key": "portfolioTemplate.params.lookback.label", "description_key": "portfolioTemplate.params.lookback.description"},
        ]},
        "code": '''"""
Cross-sectional Mean Reversion Top-N

Rank the point-in-time universe by negative trailing return and hold recent laggards.
"""

def on_init(ctx):
    ctx.param("top_n", 10, min=1, max=100, step=1)
    ctx.param("lookback", 20, min=2, max=252, step=1)

def on_rebalance(ctx, panel):
    top_n = int(ctx.param("top_n", 10))
    lookback = int(ctx.param("lookback", 20))
    momentum = ctx.factor("momentum", panel, period=lookback)
    scores = {symbol: -value for symbol, value in momentum.items()}
    ctx.long_only_top_n(scores, n=top_n)
''',
    },
    {
        "id": -1004,
        "template_key": "portfolio_small_cap_top_n",
        "name_i18n_key": "portfolioTemplate.smallCap.name",
        "description_i18n_key": "portfolioTemplate.smallCap.description",
        "icon": "fund",
        "accent": "gold",
        "param_schema": {"params": [
            {"name": "top_n", "type": "integer", "default": 10, "min": 1, "max": 100, "step": 1, "label_key": "portfolioTemplate.params.topN.label", "description_key": "portfolioTemplate.params.topN.description"},
        ]},
        "code": '''"""
Cross-sectional Small Cap Top-N

Rank eligible securities by point-in-time market capitalization and hold the smallest companies.
"""

def on_init(ctx):
    ctx.param("top_n", 10, min=1, max=100, step=1)

def on_rebalance(ctx, panel):
    top_n = int(ctx.param("top_n", 10))
    market_caps = ctx.factor("market_cap", panel)
    scores = {symbol: -value for symbol, value in market_caps.items() if value > 0}
    ctx.long_only_top_n(scores, n=top_n)
''',
    },
)


def list_portfolio_strategy_examples() -> list[dict]:
    return [dict(item) for item in PORTFOLIO_STRATEGY_EXAMPLES]
