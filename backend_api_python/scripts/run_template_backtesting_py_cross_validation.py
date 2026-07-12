from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DEPS = ROOT / ".test_deps"
if TEST_DEPS.exists() and str(TEST_DEPS) not in sys.path:
    sys.path.insert(0, str(TEST_DEPS))

from backtesting import Strategy  # noqa: E402
from backtesting.lib import FractionalBacktest  # noqa: E402

from app.services.backtest_engine import BacktestConfig, ScriptBacktestRunner  # noqa: E402
from scripts.run_template_cross_validation import (  # noqa: E402
    CASES,
    INITIAL_CAPITAL,
    OUTPUT_DIR,
    _fetch_okx_ohlcv,
    _load_templates,
)


def _to_bt_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    ).copy()
    return out[["Open", "High", "Low", "Close", "Volume"]].dropna()


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (float(period) + 1.0)
    out = float(values[0])
    for value in values[1:]:
        out = float(value) * k + out * (1.0 - k)
    return out


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (float(period) + 1.0)
    out: list[float] = []
    ema = float(values[0])
    for value in values:
        ema = float(value) * k + ema * (1.0 - k)
        out.append(ema)
    return out


def _atr(high: list[float], low: list[float], close: list[float], period: int) -> float:
    if len(close) < period + 1:
        return 0.0
    trs = []
    for i in range(len(close) - int(period), len(close)):
        trs.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    return sum(trs) / len(trs) if trs else 0.0


def _rsi(values: list[float], period: int) -> float:
    if len(values) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(len(values) - int(period), len(values)):
        change = float(values[i]) - float(values[i - 1])
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    if avg_loss <= 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    mean = _mean(values)
    return (sum((float(v) - mean) * (float(v) - mean) for v in values) / len(values)) ** 0.5 if values else 0.0


def _with_terminal_sentinel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    last = out.iloc[-1].copy()
    close = float(last["Close"])
    last["Open"] = close
    last["High"] = close
    last["Low"] = close
    last["Close"] = close
    try:
        step = out.index[-1] - out.index[-2]
        next_index = out.index[-1] + step
    except Exception:
        next_index = out.index[-1] + pd.Timedelta(days=1)
    out.loc[next_index] = last
    return out


def _make_reference_strategy(template_key: str, params: dict[str, Any], last_signal_index: int | None = None):
    class ReferenceStrategy(Strategy):
        def init(self):
            self.template_key = template_key
            self.p = params
            self.turtle_added = False
            self.vol_stop = 0.0

        def next(self):
            i = len(self.data.Close) - 1
            if self.position and last_signal_index is not None and i >= int(last_signal_index):
                return
            if not self.position and last_signal_index is not None and i >= int(last_signal_index):
                return
            close = [float(v) for v in self.data.Close]
            high = [float(v) for v in self.data.High]
            low = [float(v) for v in self.data.Low]
            price = close[-1]
            if price <= 0:
                return
            key = self.template_key
            if key == "ema_trend_pullback":
                self._ema_trend_pullback(close, high, low, price)
            elif key == "donchian_breakout":
                self._donchian_breakout(close, high, low, price)
            elif key == "atr_channel_breakout":
                self._atr_channel_breakout(close, high, low, price)
            elif key == "rsi_mean_reversion":
                self._rsi_mean_reversion(close, price)
            elif key == "macd_momentum":
                self._macd_momentum(close)
            elif key == "bollinger_reversion":
                self._bollinger_reversion(close, price)
            elif key == "turtle_breakout_lite":
                self._turtle_breakout(close, high, low, price)
            elif key == "volatility_stop_trend":
                self._volatility_stop(close, high, low, price)

        def _buy_fraction(self, value: float) -> None:
            size = max(0.0, min(0.999, float(value or 0.0)))
            if size > 0:
                self.buy(size=size)

        def _ema_trend_pullback(self, close, high, low, price):
            fast_n = int(self.p["fast_ema"])
            slow_n = int(self.p["slow_ema"])
            atr_n = int(self.p["atr_period"])
            need = max(slow_n, atr_n) + 5
            if len(close) < need:
                return
            fast = _ema(close[-fast_n:], fast_n)
            slow = _ema(close[-slow_n:], slow_n)
            prev_fast = _ema(close[-fast_n - 1:-1], fast_n)
            atr = _atr(high, low, close, atr_n)
            liquid = atr / price >= float(self.p["min_atr_pct"]) if price > 0 else False
            trend = fast > slow
            recovered = close[-2] <= prev_fast * (1.0 - float(self.p["pullback_pct"])) and price > fast
            if self.position:
                if not trend:
                    self.position.close()
                return
            if trend and recovered and liquid:
                self._buy_fraction(float(self.p["target_pct"]))

        def _donchian_breakout(self, close, high, low, price):
            entry_n = int(self.p["entry_lookback"])
            exit_n = int(self.p["exit_lookback"])
            atr_n = int(self.p["atr_period"])
            need = max(entry_n, exit_n, atr_n) + 2
            if len(close) < need:
                return
            entry_high = max(high[-entry_n - 1:-1])
            entry_low = min(low[-entry_n - 1:-1])
            exit_low = min(low[-exit_n - 1:-1])
            atr = _atr(high, low, close, atr_n)
            wide_enough = (entry_high - entry_low) >= atr * float(self.p["min_range_atr"])
            if self.position:
                if price < exit_low:
                    self.position.close()
                return
            if wide_enough and price > entry_high:
                self._buy_fraction(float(self.p["target_pct"]))

        def _atr_channel_breakout(self, close, high, low, price):
            ema_n = int(self.p["ema_period"])
            atr_n = int(self.p["atr_period"])
            slope_n = int(self.p["slope_lookback"])
            need = max(ema_n, atr_n) + slope_n + 2
            if len(close) < need:
                return
            ema = _ema(close[-ema_n:], ema_n)
            ema_prev = _ema(close[-ema_n - slope_n:-slope_n], ema_n)
            atr = _atr(high, low, close, atr_n)
            upper = ema + atr * float(self.p["atr_mult"])
            slope_ok = ema > ema_prev
            if self.position:
                if price < ema:
                    self.position.close()
                return
            if slope_ok and price > upper:
                self._buy_fraction(float(self.p["target_pct"]))

        def _rsi_mean_reversion(self, close, price):
            rsi_n = int(self.p["rsi_period"])
            regime_n = int(self.p["regime_period"])
            need = max(rsi_n + 3, regime_n + 1)
            if len(close) < need:
                return
            rsi = _rsi(close, rsi_n)
            regime = _mean(close[-regime_n:])
            regime_ok = price >= regime
            confirm = price > close[-2]
            if self.position:
                if rsi >= float(self.p["exit_level"]):
                    self.position.close()
                return
            if regime_ok and confirm and rsi <= float(self.p["oversold"]):
                self._buy_fraction(float(self.p["target_pct"]))

        def _macd_momentum(self, close):
            fast_n = int(self.p["fast"])
            slow_n = int(self.p["slow"])
            sig_n = int(self.p["signal"])
            regime_n = int(self.p["regime_ema"])
            need = max(regime_n, slow_n + sig_n + 10)
            if len(close) < need:
                return
            window = close[-need:]
            fast = _ema_series(window, fast_n)
            slow = _ema_series(window, slow_n)
            macd = [fast[i] - slow[i] for i in range(len(window))]
            sig = _ema_series(macd, sig_n)
            hist = [macd[i] - sig[i] for i in range(len(macd))]
            regime = _ema_series(window, regime_n)[-1]
            long_signal = hist[-1] > 0 and hist[-1] > hist[-2]
            long_decay = hist[-1] < hist[-2]
            if self.position:
                if long_decay:
                    self.position.close()
                return
            if close[-1] > regime and long_signal:
                self._buy_fraction(float(self.p["target_pct"]))

        def _bollinger_reversion(self, close, price):
            period = int(self.p["period"])
            if len(close) < period + 2:
                return
            window = close[-period - 1:-1]
            mid = _mean(window)
            dev = _std(window)
            if dev <= 0 or mid <= 0:
                return
            upper = mid + dev * float(self.p["std_mult"])
            lower = mid - dev * float(self.p["std_mult"])
            bandwidth = (upper - lower) / mid
            z = (price - mid) / dev
            if self.position:
                if abs(z) <= float(self.p["exit_z"]):
                    self.position.close()
                return
            if bandwidth >= float(self.p["min_bandwidth"]) and price <= lower:
                self._buy_fraction(float(self.p["target_pct"]))

        def _turtle_breakout(self, close, high, low, price):
            entry_n = int(self.p["entry_lookback"])
            exit_n = int(self.p["exit_lookback"])
            atr_n = int(self.p["atr_period"])
            need = max(entry_n, exit_n, atr_n) + 2
            if len(close) < need:
                return
            atr = _atr(high, low, close, atr_n)
            if atr <= 0:
                return
            entry_high = max(high[-entry_n - 1:-1])
            exit_low = min(low[-exit_n - 1:-1])
            equity = float(self.equity)
            unit_value = min(equity * float(self.p["max_target_pct"]) * 0.5, equity * float(self.p["risk_pct"]) * price / atr)
            unit_fraction = unit_value / equity if equity > 0 else 0.0
            if self.position:
                entry = float(self.trades[-1].entry_price) if self.trades else price
                if price >= entry + atr * float(self.p["add_atr"]) and not self.turtle_added:
                    self._buy_fraction(unit_fraction)
                    self.turtle_added = True
                if price < exit_low:
                    self.position.close()
                    self.turtle_added = False
                return
            if price > entry_high:
                self._buy_fraction(unit_fraction)

        def _volatility_stop(self, close, high, low, price):
            ema_n = int(self.p["ema_period"])
            atr_n = int(self.p["atr_period"])
            lookback = int(self.p["breakout_lookback"])
            need = max(ema_n, atr_n, lookback) + 2
            if len(close) < need:
                return
            ema = _ema(close[-ema_n:], ema_n)
            atr = _atr(high, low, close, atr_n)
            entry_high = max(high[-lookback - 1:-1])
            if self.position:
                candidate = price - atr * float(self.p["stop_atr"])
                self.vol_stop = max(self.vol_stop, candidate) if self.vol_stop > 0 else candidate
                if price <= self.vol_stop:
                    self.position.close()
                return
            if price > ema and price > entry_high:
                self._buy_fraction(float(self.p["target_pct"]))
                self.vol_stop = price - atr * float(self.p["stop_atr"])

    return ReferenceStrategy


def _run_quantdinger(code: str, params: dict[str, Any], df: pd.DataFrame, symbol: str, timeframe: str) -> dict[str, Any]:
    config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        commission=0.0,
        slippage=0.0,
        leverage=1,
        trade_direction="long",
        timeframe=timeframe,
        market_type="spot",
        signal_timing="next_bar_open",
        intrabar_mode="conservative",
    )
    return ScriptBacktestRunner(
        config=config,
        code=code,
        params=params,
        runtime={"symbol": symbol},
    ).run(df=df, start_date=df.index[0].to_pydatetime(), end_date=df.index[-1].to_pydatetime())


def _run_backtesting_py(template_key: str, params: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    frame = _to_bt_frame(df)
    last_signal_index = len(frame) - 1
    frame = _with_terminal_sentinel(frame)
    strategy = _make_reference_strategy(template_key, params, last_signal_index=last_signal_index)
    stats = FractionalBacktest(
        frame,
        strategy,
        cash=INITIAL_CAPITAL,
        commission=0.0,
        spread=0.0,
        trade_on_close=False,
        finalize_trades=True,
    ).run()
    return {
        "final_equity": round(float(stats.get("Equity Final [$]", 0.0)), 2),
        "total_return_pct": round(float(stats.get("Return [%]", 0.0)), 2),
        "max_drawdown_pct": round(float(stats.get("Max. Drawdown [%]", 0.0)), 2),
        "trades": int(stats.get("# Trades", 0) or 0),
        "win_rate_pct": round(float(stats.get("Win Rate [%]", 0.0) or 0.0), 2),
    }


def _as_metrics(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_equity": round(float(result.get("finalEquity") or 0.0), 2),
        "total_return_pct": round(float(result.get("totalReturn") or 0.0), 2),
        "max_drawdown_pct": round(float(result.get("maxDrawdown") or 0.0), 2),
        "trades": int(result.get("totalTrades") or 0),
        "win_rate_pct": round(float(result.get("winRate") or 0.0), 2),
    }


def _compare(qd: dict[str, Any], bt: dict[str, Any]) -> dict[str, Any]:
    final_diff = round(qd["final_equity"] - bt["final_equity"], 2)
    return_diff = round(qd["total_return_pct"] - bt["total_return_pct"], 2)
    trade_diff = int(qd["trades"] - bt["trades"])
    direction_match = (
        (qd["total_return_pct"] > 0 and bt["total_return_pct"] > 0)
        or (qd["total_return_pct"] < 0 and bt["total_return_pct"] < 0)
        or (abs(qd["total_return_pct"]) < 1e-9 and abs(bt["total_return_pct"]) < 1e-9)
    )
    passed = abs(final_diff) <= 50.0 and abs(return_diff) <= 0.5 and abs(trade_diff) <= 2 and direction_match
    return {
        "passed": passed,
        "final_equity_diff": final_diff,
        "return_pct_diff": return_diff,
        "trade_count_diff": trade_diff,
        "return_direction_match": direction_match,
        "tolerance": {
            "final_equity_abs": 50.0,
            "return_pct_abs": 0.5,
            "trade_count_abs": 2,
        },
    }


def main() -> None:
    templates = _load_templates()
    rows = []
    for case in CASES:
        key = case["template_key"]
        print(f"external validating {key} {case['symbol']} {case['timeframe']}...", flush=True)
        df = _fetch_okx_ohlcv(case["symbol"], case["timeframe"], int(case["bars"]))
        qd_result = _run_quantdinger(templates[key]["code"], dict(case["params"]), df, case["symbol"], case["timeframe"])
        qd_metrics = _as_metrics(qd_result)
        bt_metrics = _run_backtesting_py(key, dict(case["params"]), df)
        rows.append(
            {
                "template_key": key,
                "title": templates[key]["title"],
                "symbol": case["symbol"],
                "timeframe": case["timeframe"],
                "data_source": "OKX public history-candles",
                "start": df.index[0].isoformat(),
                "end": df.index[-1].isoformat(),
                "bars": len(df),
                "params": case["params"],
                "validation_scope": "Strategy signal and next-bar-open execution parity. Engine-managed @strategy risk controls, fees, and slippage are disabled in both engines for this external comparison. Backtesting.py receives a terminal sentinel bar matching QuantDinger's final close-out price.",
                "quantdinger": qd_metrics,
                "backtesting_py_0_6_5": bt_metrics,
                "comparison": _compare(qd_metrics, bt_metrics),
            }
        )
    report = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "external_engine": "Backtesting.py 0.6.5",
        "primary_engine": "QuantDinger ScriptBacktestRunner",
        "all_passed": all(row["comparison"]["passed"] for row in rows),
        "results": rows,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "template_backtesting_py_cross_validation_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"saved: {out}", flush=True)


if __name__ == "__main__":
    main()
