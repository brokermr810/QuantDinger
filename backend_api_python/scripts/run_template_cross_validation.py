from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner  # noqa: E402
from app.services.indicator_params import StrategyConfigParser  # noqa: E402


OUTPUT_DIR = ROOT.parents[1] / "outputs"
OKX_URL = "https://www.okx.com/api/v5/market/history-candles"
INITIAL_CAPITAL = 10_000.0
COMMISSION = 0.001
SLIPPAGE = 0.0005

CASES = [
    {
        "template_key": "ema_trend_pullback",
        "symbol": "BTC-USDT",
        "timeframe": "4H",
        "bars": 360,
        "params": {
            "fast_ema": 8,
            "slow_ema": 21,
            "atr_period": 7,
            "pullback_pct": 0.003,
            "min_atr_pct": 0,
            "target_pct": 0.35,
        },
    },
    {
        "template_key": "donchian_breakout",
        "symbol": "ETH-USDT",
        "timeframe": "1D",
        "bars": 360,
        "params": {
            "entry_lookback": 20,
            "exit_lookback": 10,
            "atr_period": 14,
            "min_range_atr": 0,
            "target_pct": 0.35,
        },
    },
    {
        "template_key": "atr_channel_breakout",
        "symbol": "SOL-USDT",
        "timeframe": "1H",
        "bars": 500,
        "params": {
            "ema_period": 24,
            "atr_period": 10,
            "atr_mult": 1.2,
            "slope_lookback": 3,
            "target_pct": 0.3,
        },
    },
    {
        "template_key": "rsi_mean_reversion",
        "symbol": "XRP-USDT",
        "timeframe": "2H",
        "bars": 420,
        "params": {
            "rsi_period": 7,
            "regime_period": 20,
            "oversold": 45,
            "overbought": 55,
            "exit_level": 52,
            "target_pct": 0.25,
        },
    },
    {
        "template_key": "macd_momentum",
        "symbol": "DOGE-USDT",
        "timeframe": "4H",
        "bars": 360,
        "params": {
            "fast": 5,
            "slow": 13,
            "signal": 5,
            "regime_ema": 20,
            "target_pct": 0.3,
        },
    },
    {
        "template_key": "bollinger_reversion",
        "symbol": "ADA-USDT",
        "timeframe": "6H",
        "bars": 360,
        "params": {
            "period": 14,
            "std_mult": 1.5,
            "min_bandwidth": 0,
            "exit_z": 0.25,
            "target_pct": 0.25,
        },
    },
    {
        "template_key": "turtle_breakout_lite",
        "symbol": "LTC-USDT",
        "timeframe": "1D",
        "bars": 360,
        "params": {
            "entry_lookback": 20,
            "exit_lookback": 10,
            "atr_period": 14,
            "risk_pct": 0.02,
            "add_atr": 0.5,
            "max_target_pct": 0.4,
        },
    },
    {
        "template_key": "volatility_stop_trend",
        "symbol": "BCH-USDT",
        "timeframe": "12H",
        "bars": 360,
        "params": {
            "ema_period": 21,
            "atr_period": 10,
            "stop_atr": 2.0,
            "breakout_lookback": 8,
            "target_pct": 0.35,
        },
    },
]


def _load_templates() -> dict[str, dict[str, Any]]:
    sql = (ROOT / "migrations" / "init.sql").read_text(encoding="utf-8")
    pattern = re.compile(
        r"\('(?P<key>[^']+)',\s*'(?P<title>[^']+)',\s*'(?P<desc>(?:[^']|'')*)',\s*"
        r"\$(?P<tag>qdtplv3_\d+)\$(?P<code>.*?)\$(?P=tag)\$,\s*"
        r"'(?P<schema>\{.*?\})'::jsonb",
        re.DOTALL,
    )
    out: dict[str, dict[str, Any]] = {}
    for match in pattern.finditer(sql):
        out[match.group("key")] = {
            "title": match.group("title"),
            "description": match.group("desc").replace("''", "'"),
            "code": match.group("code"),
            "param_schema": json.loads(match.group("schema")),
        }
    return out


def _fetch_okx_ohlcv(symbol: str, bar: str, target: int) -> pd.DataFrame:
    rows: dict[int, list[Any]] = {}
    after: str | None = None
    for _ in range(20):
        params = {"instId": symbol, "bar": bar, "limit": "100"}
        if after:
            params["after"] = after
        response = requests.get(OKX_URL, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "0":
            raise RuntimeError(f"OKX returned {payload.get('code')}: {payload.get('msg')}")
        batch = payload.get("data") or []
        if not batch:
            break
        for item in batch:
            if len(item) < 9 or str(item[8]) != "1":
                continue
            rows[int(item[0])] = item
        oldest = min(int(item[0]) for item in batch if item and item[0])
        after = str(oldest)
        if len(rows) >= target:
            break
        time.sleep(0.08)
    if len(rows) < 80:
        raise RuntimeError(f"insufficient OKX candles for {symbol} {bar}: {len(rows)}")
    data = [rows[ts] for ts in sorted(rows)[-target:]]
    frame = pd.DataFrame(
        {
            "open": [float(item[1]) for item in data],
            "high": [float(item[2]) for item in data],
            "low": [float(item[3]) for item in data],
            "close": [float(item[4]) for item in data],
            "volume": [float(item[5]) for item in data],
        },
        index=pd.to_datetime([int(item[0]) for item in data], unit="ms", utc=True).tz_convert(None),
    )
    return frame.sort_index()


def _strategy_config_from_code(code: str, market_type: str) -> dict[str, Any]:
    cfg = StrategyConfigParser.build_nested_cfg_from_code(code)
    cfg["market_type"] = market_type
    cfg.setdefault("execution", {})["intrabarMode"] = "conservative"
    return cfg


def _run_case(case: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    df = _fetch_okx_ohlcv(case["symbol"], case["timeframe"], int(case["bars"]))
    strategy_cfg = _strategy_config_from_code(template["code"], "spot")
    config = BacktestConfig.from_strategy_config(
        strategy_cfg,
        initial_capital=INITIAL_CAPITAL,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        leverage=1,
        trade_direction="long",
        timeframe=case["timeframe"],
    )
    result = ScriptBacktestRunner(
        config=config,
        code=template["code"],
        params=case["params"],
        runtime={"symbol": case["symbol"]},
    ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())
    audit = _audit_result(df, result, config)
    return {
        "template_key": case["template_key"],
        "title": template["title"],
        "symbol": case["symbol"],
        "timeframe": case["timeframe"],
        "data_source": "OKX public history-candles",
        "start": df.index[0].isoformat(),
        "end": df.index[-1].isoformat(),
        "bars": len(df),
        "params": case["params"],
        "risk_config": {
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "trailing_enabled": config.trailing_enabled,
            "trailing_pct": config.trailing_pct,
            "trailing_activation_pct": config.trailing_activation_pct,
            "max_holding_bars": config.max_holding_bars,
        },
        "run_config": {
            "initial_capital": config.initial_capital,
            "commission": config.commission,
            "slippage": config.slippage,
            "market_type": config.market_type,
            "direction": config.trade_direction,
            "signal_timing": config.signal_timing,
            "intrabar_mode": config.intrabar_mode,
        },
        "metrics": {
            "final_equity": result.get("finalEquity", 0),
            "total_return_pct": result.get("totalReturn", 0),
            "max_drawdown_pct": result.get("maxDrawdown", 0),
            "sharpe": result.get("sharpeRatio", 0),
            "win_rate_pct": result.get("winRate", 0),
            "profit_factor": result.get("profitFactor", 0),
            "closed_trades": result.get("totalTrades", 0),
            "orders": (result.get("engine") or {}).get("orderCount", 0),
            "rejected_orders": (result.get("engine") or {}).get("rejectedOrderCount", 0),
            "total_commission": result.get("totalCommission", 0),
        },
        "exit_reasons": _exit_reasons(result),
        "cross_validation": audit,
    }


def _exit_reasons(result: dict[str, Any]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for trade in result.get("closedTrades") or []:
        reason = str(trade.get("reason") or trade.get("close_reason") or "")
        reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _audit_result(df: pd.DataFrame, result: dict[str, Any], config: BacktestConfig) -> dict[str, Any]:
    orders = [order for order in result.get("orders") or [] if order.get("status") == "filled"]
    cash = float(config.initial_capital)
    qty = 0.0
    avg_entry = 0.0
    price_mismatches = []
    range_mismatches = []
    for order in orders:
        bar_idx = int(order.get("submittedBar") or 0)
        if bar_idx >= len(df):
            price_mismatches.append({"order_id": order.get("id"), "reason": "submitted_bar_out_of_range"})
            continue
        row = df.iloc[bar_idx]
        side = str(order.get("side") or "")
        price = float(order.get("avgFillPrice") or 0.0)
        fee = float(order.get("fee") or 0.0)
        script_intent = str(order.get("scriptIntent") or "")
        reason = str(order.get("reason") or "")
        if script_intent:
            expected = float(row["open"]) * (1.0 + config.slippage if side == "buy" else 1.0 - config.slippage)
            expected = min(max(expected, float(row["low"])), float(row["high"]))
            if not math.isclose(price, expected, rel_tol=0, abs_tol=max(1e-8, expected * 1e-8)):
                price_mismatches.append({"order_id": order.get("id"), "expected": expected, "actual": price})
        elif reason in {"stop_loss", "take_profit", "trailing_stop"}:
            low = float(row["low"]) * (1.0 - config.slippage)
            high = float(row["high"]) * (1.0 + config.slippage)
            if price < low - 1e-8 or price > high + 1e-8:
                range_mismatches.append({"order_id": order.get("id"), "low": low, "high": high, "actual": price})
        order_qty = float(order.get("filledQuantity") or 0.0)
        if side == "buy" and not bool(order.get("reduceOnly")):
            cost = order_qty * price
            new_qty = qty + order_qty
            avg_entry = ((avg_entry * qty) + cost) / new_qty if new_qty > 0 else 0.0
            qty = new_qty
            cash -= cost + fee
        elif side == "sell":
            sell_qty = min(qty, order_qty)
            cash += sell_qty * price - fee
            qty -= sell_qty
            if qty <= 1e-10:
                qty = 0.0
                avg_entry = 0.0
    mark = float(df.iloc[-1]["close"])
    independent_final = round(cash + qty * mark, 2)
    runner_final = round(float(result.get("finalEquity") or 0.0), 2)
    commission_sum = round(sum(float(order.get("fee") or 0.0) for order in orders), 8)
    runner_commission = round(float(result.get("totalCommission") or 0.0), 8)
    closed_count = len(result.get("closedTrades") or [])
    reported_count = int(result.get("totalTrades") or 0)
    passed = (
        not price_mismatches
        and not range_mismatches
        and math.isclose(independent_final, runner_final, rel_tol=0, abs_tol=0.02)
        and math.isclose(commission_sum, runner_commission, rel_tol=0, abs_tol=1e-6)
        and closed_count == reported_count
        and int((result.get("engine") or {}).get("rejectedOrderCount") or 0) == 0
    )
    return {
        "passed": passed,
        "independent_final_equity": independent_final,
        "runner_final_equity": runner_final,
        "final_equity_diff": round(independent_final - runner_final, 6),
        "commission_sum": commission_sum,
        "runner_commission": runner_commission,
        "closed_trade_count": closed_count,
        "reported_total_trades": reported_count,
        "script_order_price_mismatches": price_mismatches[:5],
        "risk_exit_range_mismatches": range_mismatches[:5],
    }


def main() -> None:
    templates = _load_templates()
    missing = [case["template_key"] for case in CASES if case["template_key"] not in templates]
    if missing:
        raise RuntimeError(f"missing templates: {missing}")
    results = []
    for case in CASES:
        print(f"running {case['template_key']} {case['symbol']} {case['timeframe']}...", flush=True)
        results.append(_run_case(case, templates[case["template_key"]]))
    report = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "engine": "ScriptBacktestRunner",
        "cross_validation_method": [
            "Replay filled spot orders independently from serialized orders.",
            "Check script market-order fills against next-bar open plus slippage.",
            "Check risk exits stay inside trigger bar high/low after slippage bounds.",
            "Reconcile independent final equity and commission totals with runner output.",
        ],
        "results": results,
        "all_cross_validation_passed": all(item["cross_validation"]["passed"] for item in results),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "template_cross_validation_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"saved: {out}", flush=True)


if __name__ == "__main__":
    main()
