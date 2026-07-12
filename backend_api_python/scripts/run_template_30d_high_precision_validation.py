from __future__ import annotations

import json
import math
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
from scripts.run_template_backtesting_py_cross_validation import (  # noqa: E402
    _as_metrics,
    _compare,
    _run_backtesting_py,
    _run_quantdinger,
)
from scripts.run_template_cross_validation import (  # noqa: E402
    CASES,
    COMMISSION,
    INITIAL_CAPITAL,
    OKX_URL,
    OUTPUT_DIR,
    SLIPPAGE,
    _load_templates,
)


TEST_DAYS = 30
EXECUTION_AUDIT_BAR = "5m"
REQUEST_LIMIT = 100
DATA_DIR = OUTPUT_DIR / "high_precision_data"


def _timeframe_minutes(timeframe: str) -> int:
    unit = timeframe[-1].upper()
    value = int(timeframe[:-1])
    if unit == "M":
        return value
    if unit == "H":
        return value * 60
    if unit == "D":
        return value * 24 * 60
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _target_bars(timeframe: str, days: int = TEST_DAYS) -> int:
    minutes = _timeframe_minutes(timeframe)
    return max(1, math.ceil(days * 24 * 60 / minutes))


def _execution_audit_target_bars(strategy_timeframe: str) -> int:
    extra = math.ceil(_timeframe_minutes(strategy_timeframe) / _timeframe_minutes(EXECUTION_AUDIT_BAR)) + 12
    return _target_bars(EXECUTION_AUDIT_BAR) + extra


def _cache_path(symbol: str, timeframe: str, target: int) -> Path:
    safe_symbol = symbol.replace("-", "_")
    safe_timeframe = timeframe.replace("/", "_")
    return DATA_DIR / f"{safe_symbol}_{safe_timeframe}_{target}bars.csv"


def _fetch_okx_ohlcv_count(symbol: str, timeframe: str, target: int) -> pd.DataFrame:
    cache = _cache_path(symbol, timeframe, target)
    if cache.exists():
        cached = pd.read_csv(cache, index_col="timestamp", parse_dates=True)
        if len(cached) >= target:
            return cached.sort_index().tail(target)

    rows: dict[int, list[Any]] = {}
    after: str | None = None
    max_pages = math.ceil(target / REQUEST_LIMIT) + 10
    for _ in range(max_pages):
        params = {"instId": symbol, "bar": timeframe, "limit": str(REQUEST_LIMIT)}
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
        time.sleep(0.05)
    if len(rows) < target:
        raise RuntimeError(f"insufficient OKX candles for {symbol} {timeframe}: {len(rows)} < {target}")
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
    ).sort_index()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(_cache_path(symbol, timeframe, target), index_label="timestamp")
    return frame


def _strategy_config_from_code(code: str) -> dict[str, Any]:
    cfg = StrategyConfigParser.build_nested_cfg_from_code(code)
    cfg["market_type"] = "spot"
    cfg.setdefault("execution", {})["intrabarMode"] = "conservative"
    return cfg


def _run_full_engine(code: str, params: dict[str, Any], df: pd.DataFrame, symbol: str, timeframe: str) -> dict[str, Any]:
    config = BacktestConfig.from_strategy_config(
        _strategy_config_from_code(code),
        initial_capital=INITIAL_CAPITAL,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        leverage=1,
        trade_direction="long",
        timeframe=timeframe,
    )
    result = ScriptBacktestRunner(
        config=config,
        code=code,
        params=params,
        runtime={"symbol": symbol},
    ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())
    return {"config": config, "result": result}


def _bar_window(df: pd.DataFrame, bar_index: int, timeframe: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(df.index[bar_index])
    if bar_index + 1 < len(df.index):
        return start, pd.Timestamp(df.index[bar_index + 1])
    return start, start + pd.Timedelta(minutes=_timeframe_minutes(timeframe))


def _expected_market_fill(row: pd.Series, side: str, slippage: float) -> float:
    open_ = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    if side == "buy":
        return min(max(open_ * (1.0 + slippage), low), high)
    return min(max(open_ * (1.0 - slippage), low), high)


def _audit_with_low_timeframe(
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    result: dict[str, Any],
    config: BacktestConfig,
    timeframe: str,
) -> dict[str, Any]:
    filled_orders = [order for order in result.get("orders") or [] if order.get("status") == "filled"]
    missing_low_windows: list[dict[str, Any]] = []
    market_mismatches: list[dict[str, Any]] = []
    risk_mismatches: list[dict[str, Any]] = []
    market_checked = 0
    market_confirmed = 0
    risk_checked = 0
    risk_confirmed = 0
    low_open_max_diff_pct = 0.0
    risk_reasons = {"stop_loss", "take_profit", "trailing_stop"}

    for order in filled_orders:
        bar_index = int(order.get("submittedBar") or 0)
        if bar_index >= len(high_df):
            missing_low_windows.append({"order_id": order.get("id"), "reason": "submitted_bar_out_of_range"})
            continue
        start, end = _bar_window(high_df, bar_index, timeframe)
        low_window = low_df[(low_df.index >= start) & (low_df.index < end)]
        if low_window.empty:
            missing_low_windows.append({
                "order_id": order.get("id"),
                "bar_start": start.isoformat(),
                "bar_end": end.isoformat(),
            })
            continue

        side = str(order.get("side") or "")
        reason = str(order.get("reason") or "")
        script_intent = str(order.get("scriptIntent") or "")
        fill_price = float(order.get("avgFillPrice") or 0.0)
        high_row = high_df.iloc[bar_index]

        if script_intent:
            market_checked += 1
            expected = _expected_market_fill(high_row, side, float(config.slippage or 0.0))
            first_low_open = float(low_window.iloc[0]["open"])
            high_open = float(high_row["open"])
            open_diff_pct = abs(first_low_open - high_open) / high_open * 100.0 if high_open else 0.0
            low_open_max_diff_pct = max(low_open_max_diff_pct, open_diff_pct)
            price_ok = math.isclose(fill_price, expected, rel_tol=0, abs_tol=max(1e-8, expected * 1e-8))
            open_ok = open_diff_pct <= 0.05
            if price_ok and open_ok:
                market_confirmed += 1
            else:
                market_mismatches.append({
                    "order_id": order.get("id"),
                    "script_intent": script_intent,
                    "expected_fill": round(expected, 10),
                    "actual_fill": round(fill_price, 10),
                    "high_open": high_open,
                    "first_low_open": first_low_open,
                    "open_diff_pct": round(open_diff_pct, 6),
                    "bar_start": start.isoformat(),
                })
        elif reason in risk_reasons:
            risk_checked += 1
            low_min = float(low_window["low"].min())
            high_max = float(low_window["high"].max())
            if side == "sell":
                touched = high_max >= fill_price if reason == "take_profit" else low_min <= fill_price
            else:
                touched = low_min <= fill_price if reason == "take_profit" else high_max >= fill_price
            if touched:
                risk_confirmed += 1
            else:
                risk_mismatches.append({
                    "order_id": order.get("id"),
                    "reason": reason,
                    "side": side,
                    "fill_price": fill_price,
                    "low_window_min": low_min,
                    "low_window_max": high_max,
                    "bar_start": start.isoformat(),
                    "bar_end": end.isoformat(),
                })

    passed = not missing_low_windows and not market_mismatches and not risk_mismatches
    return {
        "passed": passed,
        "execution_audit_bar": EXECUTION_AUDIT_BAR,
        "low_timeframe_bars": len(low_df),
        "filled_orders": len(filled_orders),
        "market_orders_checked": market_checked,
        "market_orders_confirmed": market_confirmed,
        "risk_exits_checked": risk_checked,
        "risk_exits_confirmed": risk_confirmed,
        "low_open_max_diff_pct": round(low_open_max_diff_pct, 6),
        "missing_low_windows": missing_low_windows[:10],
        "market_mismatches": market_mismatches[:10],
        "risk_mismatches": risk_mismatches[:10],
    }


def _exit_reasons(result: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for trade in result.get("closedTrades") or []:
        reason = str(trade.get("reason") or trade.get("close_reason") or "")
        out[reason] = out.get(reason, 0) + 1
    return out


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _run_case(case: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    high_target = _target_bars(case["timeframe"])
    low_target = _execution_audit_target_bars(case["timeframe"])
    high_df = _fetch_okx_ohlcv_count(case["symbol"], case["timeframe"], high_target)
    low_df = _fetch_okx_ohlcv_count(case["symbol"], EXECUTION_AUDIT_BAR, low_target)

    parity_qd = _run_quantdinger(template["code"], dict(case["params"]), high_df, case["symbol"], case["timeframe"])
    parity_qd_metrics = _as_metrics(parity_qd)
    parity_bt_metrics = _run_backtesting_py(case["template_key"], dict(case["params"]), high_df)
    full_run = _run_full_engine(template["code"], dict(case["params"]), high_df, case["symbol"], case["timeframe"])
    result = full_run["result"]
    config = full_run["config"]
    high_precision = _audit_with_low_timeframe(high_df, low_df, result, config, case["timeframe"])

    return {
        "template_key": case["template_key"],
        "title": template["title"],
        "symbol": case["symbol"],
        "strategy_timeframe": case["timeframe"],
        "execution_audit_timeframe": EXECUTION_AUDIT_BAR,
        "period_days": TEST_DAYS,
        "high_timeframe_start": high_df.index[0].isoformat(),
        "high_timeframe_end": high_df.index[-1].isoformat(),
        "high_timeframe_bars": len(high_df),
        "low_timeframe_start": low_df.index[0].isoformat(),
        "low_timeframe_end": low_df.index[-1].isoformat(),
        "low_timeframe_bars": len(low_df),
        "params": case["params"],
        "backtesting_py_signal_parity": {
            "quantdinger": parity_qd_metrics,
            "backtesting_py_0_6_5": parity_bt_metrics,
            "comparison": _compare(parity_qd_metrics, parity_bt_metrics),
        },
        "full_engine_metrics": {
            "final_equity": round(float(result.get("finalEquity") or 0.0), 2),
            "total_return_pct": round(float(result.get("totalReturn") or 0.0), 2),
            "max_drawdown_pct": round(float(result.get("maxDrawdown") or 0.0), 2),
            "closed_trades": int(result.get("totalTrades") or 0),
            "orders": int((result.get("engine") or {}).get("orderCount") or 0),
            "rejected_orders": int((result.get("engine") or {}).get("rejectedOrderCount") or 0),
            "total_commission": round(float(result.get("totalCommission") or 0.0), 8),
        },
        "exit_reasons": _exit_reasons(result),
        "high_precision_execution_audit": high_precision,
    }


def main() -> None:
    templates = _load_templates()
    missing = [case["template_key"] for case in CASES if case["template_key"] not in templates]
    if missing:
        raise RuntimeError(f"missing templates: {missing}")
    rows = []
    for case in CASES:
        print(
            f"validating 30d high precision {case['template_key']} "
            f"{case['symbol']} {case['timeframe']} with {EXECUTION_AUDIT_BAR} audit...",
            flush=True,
        )
        rows.append(_run_case(case, templates[case["template_key"]]))

    report = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "period_days": TEST_DAYS,
        "data_source": "OKX public history-candles",
        "primary_engine": "QuantDinger ScriptBacktestRunner",
        "external_engine": "Backtesting.py 0.6.5",
        "method": [
            "Run each template on its configured strategy timeframe for the latest 30 days.",
            "Compare signal and next-bar-open execution parity against Backtesting.py with fees, slippage, and engine risk disabled.",
            "Run the full QuantDinger engine with template risk, commission, and slippage enabled.",
            "Audit every filled order against 5m candles inside the submitted strategy bar.",
        ],
        "results": rows,
        "all_backtesting_py_parity_passed": all(
            row["backtesting_py_signal_parity"]["comparison"]["passed"] for row in rows
        ),
        "all_high_precision_execution_passed": all(
            row["high_precision_execution_audit"]["passed"] for row in rows
        ),
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "template_30d_high_precision_validation_report.json"
    safe_report = _json_safe(report)
    out.write_text(json.dumps(safe_report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(safe_report, ensure_ascii=False, indent=2, allow_nan=False), flush=True)
    print(f"saved: {out}", flush=True)


if __name__ == "__main__":
    main()
