"""Unified V2 candle-level backtest service for ctx ScriptStrategy code."""
import hashlib
import json
import math
import re
import time as _time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

import pandas as pd
import numpy as np

from app.data_sources import DataSourceFactory
from app.utils.logger import get_logger
from app.utils.db import get_db_connection
from app.utils.risk_guard import trailing_exit_locks_net_profit
from app.services.backtest_execution import DEFAULT_COMMISSION
from app.services.backtest_cache import KlineCache
from app.services.strategy_warmup import warmup_start_date
from app.services.strategy_contract import resolve_script_strategy_contract

logger = get_logger(__name__)


_kline_cache = KlineCache()


class UnifiedBacktestService:
    """Single backtest service used by the Backtest Center and agent APIs."""
    
    # Timeframe in seconds
    TIMEFRAME_SECONDS = {
        '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
        '1H': 3600, '4H': 14400, '1D': 86400, '1W': 604800
    }
    
    ENGINE_VERSION = 'quantdinger-backtest-engine-v2'

    def __init__(self):
        self._storage_schema_ready = False

    def _slice_to_backtest_window(
        self,
        df: pd.DataFrame,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        rs = pd.Timestamp(start_date)
        re = pd.Timestamp(end_date)
        out = df[(df.index >= rs) & (df.index <= re)].copy()
        if getattr(df, "attrs", None):
            out.attrs.update(df.attrs)
        out.attrs.pop("backtestActualRange", None)
        if not out.empty:
            actual_start = pd.Timestamp(out.index.min())
            actual_end = pd.Timestamp(out.index.max())
            if actual_start > rs or actual_end < re:
                out.attrs["backtestActualRange"] = {
                    "requestedStart": str(rs),
                    "requestedEnd": str(re),
                    "actualStart": str(actual_start),
                    "actualEnd": str(actual_end),
                }
        return out

    def _sanitize_strategy_params(
        self,
        params: Optional[Dict[str, Any]],
        param_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Enforce the V2 runtime parameter contract before user code sees it.

        Script strategy params are code-native values. A ``*_pct`` value of
        ``0.06`` means 6%, and ``6`` means 6. No UI/schema percentage conversion
        is applied here.
        """
        if not isinstance(params, dict):
            return {}

        period_tokens = (
            "period", "lookback", "window", "length", "len", "bars",
            "ema", "sma", "rsi", "adx", "ma",
        )
        non_period_tokens = (
            "pct", "percent", "ratio", "rate", "mult", "multiplier",
            "threshold", "distance", "width", "bandwidth", "risk",
            "target", "stop", "pullback", "activation",
        )
        zero_allowed_tokens = ("cooldown", "delay", "wait", "pause")
        sanitized: Dict[str, Any] = {}

        for key, value in params.items():
            name = str(key or "").strip()
            lowered = name.lower()
            if not name:
                continue

            try:
                numeric = float(value)
            except Exception:
                sanitized[name] = value
                continue

            if not math.isfinite(numeric):
                continue

            name_parts = [part for part in re.split(r"[^a-z0-9]+", lowered) if part]
            is_non_period_numeric = any(token in name_parts for token in non_period_tokens)
            is_period_like = (
                not is_non_period_numeric
                and (
                    lowered in period_tokens
                    or any(lowered.endswith(f"_{token}") for token in period_tokens)
                    or lowered.endswith("_atr_period")
                )
            )
            zero_allowed = any(token in name_parts for token in zero_allowed_tokens)
            if is_period_like and not zero_allowed:
                numeric = max(1.0, numeric)
                sanitized[name] = int(round(numeric))
                continue

            if zero_allowed:
                numeric = max(0.0, numeric)

            sanitized[name] = int(numeric) if float(numeric).is_integer() and isinstance(value, int) else numeric

        return sanitized

    def _order_diagnostics(self, engine_result: Dict[str, Any], trade_direction: str) -> Dict[str, Any]:
        """Return compact counts from broker orders and executions."""
        direction = str(trade_direction or "both").lower()
        if direction not in ("long", "short", "both"):
            direction = "both"
        orders = engine_result.get("orders") if isinstance(engine_result, dict) else []
        if not isinstance(orders, list):
            orders = []
        trades = engine_result.get("trades") if isinstance(engine_result, dict) else []
        if not isinstance(trades, list):
            trades = []

        def count_orders(*actions: str, status: Optional[str] = None) -> int:
            wanted = set(actions)
            total = 0
            for order in orders:
                if not isinstance(order, dict):
                    continue
                intent = str(order.get("scriptIntent") or order.get("script_intent") or "").lower()
                reason = str(order.get("reason") or "").lower()
                action = intent or reason
                if action not in wanted:
                    continue
                if status and str(order.get("status") or "").lower() != status:
                    continue
                total += 1
            return total

        def count_trades(*actions: str) -> int:
            wanted = set(actions)
            total = 0
            for trade in trades:
                if isinstance(trade, dict) and str(trade.get("type") or "").lower() in wanted:
                    total += 1
            return total

        normalized = {
            "open_long": count_trades("open_long"),
            "close_long": count_trades("close_long"),
            "open_short": count_trades("open_short"),
            "close_short": count_trades("close_short"),
            "add_long": count_orders("add_long", status="filled"),
            "add_short": count_orders("add_short", status="filled"),
            "reduce_long": count_orders("reduce_long", status="filled"),
            "reduce_short": count_orders("reduce_short", status="filled"),
        }
        entry_signals = (
            normalized["open_long"]
            + normalized["open_short"]
            + normalized["add_long"]
            + normalized["add_short"]
        )
        exit_signals = (
            normalized["close_long"]
            + normalized["close_short"]
            + normalized["reduce_long"]
            + normalized["reduce_short"]
        )
        rejected = sum(
            1
            for order in orders
            if isinstance(order, dict) and str(order.get("status") or "").lower() == "rejected"
        )
        return {
            "raw": dict(normalized),
            "normalized": normalized,
            "tradeDirection": direction,
            "entrySignals": entry_signals,
            "exitSignals": exit_signals,
            "orderCount": len(orders),
            "rejectedOrderCount": rejected,
        }

    def _attach_warmup_to_result(
        self,
        result: Dict[str, Any],
        *,
        warmup_bars: int,
        warmup_start: datetime,
        requested_start: datetime,
        effective_start: datetime,
        available_warmup_bars: int,
        requested_start_warmup_bars: int,
    ) -> None:
        if warmup_bars <= 0:
            return
        ea = dict(result.get("executionAssumptions") or {})
        ea["scriptWarmupBars"] = int(warmup_bars)
        ea["scriptWarmupStart"] = str(warmup_start)
        ea["requestedStart"] = str(requested_start)
        ea["effectiveTradingStart"] = str(effective_start)
        ea["availableWarmupBars"] = int(available_warmup_bars)
        ea["requestedStartWarmupBars"] = int(requested_start_warmup_bars)
        ea["warmupReady"] = bool(available_warmup_bars >= warmup_bars)
        ea["warmupAdjustedStart"] = bool(pd.Timestamp(effective_start) > pd.Timestamp(requested_start))
        result["executionAssumptions"] = ea

    def ensure_storage_schema(self) -> None:
        if self._storage_schema_ready:
            return
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS run_type VARCHAR(50) DEFAULT 'strategy_script'")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS strategy_id INTEGER")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS strategy_name VARCHAR(255) DEFAULT ''")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS asset_type VARCHAR(50) DEFAULT ''")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS asset_id INTEGER")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS config_snapshot TEXT DEFAULT ''")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS engine_version VARCHAR(50) DEFAULT ''")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS code_hash VARCHAR(128) DEFAULT ''")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS exchange_id VARCHAR(50) NOT NULL DEFAULT ''")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS market_type VARCHAR(20) NOT NULL DEFAULT 'spot'")
                cur.execute("ALTER TABLE qd_backtest_runs ADD COLUMN IF NOT EXISTS instrument_id VARCHAR(120) NOT NULL DEFAULT ''")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy_id ON qd_backtest_runs(strategy_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_run_type ON qd_backtest_runs(run_type)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_asset ON qd_backtest_runs(asset_type, asset_id)")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qd_backtest_trades (
                        id SERIAL PRIMARY KEY,
                        run_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL DEFAULT 1,
                        strategy_id INTEGER,
                        trade_index INTEGER DEFAULT 0,
                        trade_time VARCHAR(64) DEFAULT '',
                        trade_type VARCHAR(64) DEFAULT '',
                        side VARCHAR(32) DEFAULT '',
                        price DOUBLE PRECISION DEFAULT 0,
                        amount DOUBLE PRECISION DEFAULT 0,
                        profit DOUBLE PRECISION DEFAULT 0,
                        balance DOUBLE PRECISION DEFAULT 0,
                        reason VARCHAR(64) DEFAULT '',
                        payload_json TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_id ON qd_backtest_trades(run_id)")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qd_backtest_equity_points (
                        id SERIAL PRIMARY KEY,
                        run_id INTEGER NOT NULL,
                        point_index INTEGER DEFAULT 0,
                        point_time VARCHAR(64) DEFAULT '',
                        point_value DOUBLE PRECISION DEFAULT 0,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_backtest_equity_points_run_id ON qd_backtest_equity_points(run_id)")
                db.commit()
                cur.close()
            self._storage_schema_ready = True
        except Exception:
            logger.warning("Failed to ensure backtest storage schema", exc_info=True)

    def _detect_trade_side(self, trade_type: str) -> str:
        ty = str(trade_type or '').strip().lower()
        if 'long' in ty:
            return 'long'
        if 'short' in ty:
            return 'short'
        return ''
    
    def persist_run(
        self,
        *,
        user_id: int,
        market: str,
        symbol: str,
        timeframe: str,
        exchange_id: str,
        market_type: str,
        instrument_id: str,
        start_date_str: str,
        end_date_str: str,
        initial_capital: float,
        commission: float,
        slippage: float,
        leverage: int,
        trade_direction: str,
        strategy_config: Optional[Dict[str, Any]] = None,
        config_snapshot: Optional[Dict[str, Any]] = None,
        status: str = 'success',
        error_message: str = '',
        result: Optional[Dict[str, Any]] = None,
        strategy_id: Optional[int] = None,
        strategy_name: str = '',
        run_type: str = 'strategy_script',
        asset_type: str = '',
        asset_id: Optional[int] = None,
        code: str = '',
    ) -> Optional[int]:
        self.ensure_storage_schema()
        run_id = None
        engine_version = self.ENGINE_VERSION
        if isinstance(result, dict):
            engine_info = result.get('engine')
            if isinstance(engine_info, dict) and engine_info.get('version'):
                engine_version = str(engine_info.get('version'))
            else:
                assumptions = result.get('executionAssumptions')
                if isinstance(assumptions, dict) and assumptions.get('engineVersion'):
                    engine_version = str(assumptions.get('engineVersion'))
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO qd_backtest_runs
                    (user_id, strategy_id, strategy_name, asset_type, asset_id, run_type, market, symbol,
                     exchange_id, market_type, instrument_id, timeframe,
                     start_date, end_date, initial_capital, commission, slippage, leverage, trade_direction,
                     strategy_config, config_snapshot, engine_version, code_hash, status, error_message, result_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
                    """,
                    (
                        int(user_id or 1),
                        int(strategy_id) if strategy_id is not None else None,
                        str(strategy_name or ''),
                        str(asset_type or ''),
                        int(asset_id) if asset_id is not None else None,
                        str(run_type or 'strategy_script'),
                        str(market or ''),
                        str(symbol or ''),
                        str(exchange_id or ''),
                        str(market_type or 'spot'),
                        str(instrument_id or ''),
                        str(timeframe or ''),
                        str(start_date_str or ''),
                        str(end_date_str or ''),
                        float(initial_capital or 0),
                        float(commission or 0),
                        float(slippage or 0),
                        int(leverage or 1),
                        str(trade_direction or 'long'),
                        json.dumps(strategy_config or {}, ensure_ascii=False),
                        json.dumps(config_snapshot or {}, ensure_ascii=False),
                        engine_version,
                        hashlib.sha256(str(code or '').encode('utf-8')).hexdigest() if code else '',
                        str(status or 'success'),
                        str(error_message or ''),
                        json.dumps(result or {}, ensure_ascii=False) if result else ''
                    )
                )
                run_id = cur.lastrowid

                if run_id and status == 'success' and isinstance(result, dict):
                    completed_trades = (
                        result.get('closedTrades')
                        or result.get('tradeRecords')
                        or result.get('trades')
                        or []
                    )
                    for idx, trade in enumerate(completed_trades, start=1):
                        trade_side = (
                            trade.get('side')
                            or trade.get('direction')
                            or self._detect_trade_side(trade.get('type'))
                        )
                        cur.execute(
                            """
                            INSERT INTO qd_backtest_trades
                            (run_id, user_id, strategy_id, trade_index, trade_time, trade_type, side, price, amount, profit, balance, reason, payload_json, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())
                            """,
                            (
                                int(run_id),
                                int(user_id or 1),
                                int(strategy_id) if strategy_id is not None else None,
                                idx,
                                str(trade.get('exit_time') or trade.get('time') or ''),
                                str(trade.get('type') or trade.get('side') or ''),
                                str(trade_side or ''),
                                float(trade.get('exit_price') or trade.get('price') or 0),
                                float(trade.get('qty') or trade.get('amount') or 0),
                                float(trade.get('profit') or 0),
                                float(trade.get('balance') or 0),
                                str(trade.get('reason') or trade.get('close_reason') or ''),
                                json.dumps(trade or {}, ensure_ascii=False),
                            )
                        )

                    for idx, point in enumerate((result.get('equityCurve') or []), start=1):
                        cur.execute(
                            """
                            INSERT INTO qd_backtest_equity_points
                            (run_id, point_index, point_time, point_value, created_at)
                            VALUES (?, ?, ?, ?, NOW())
                            """,
                            (
                                int(run_id),
                                idx,
                                str(point.get('time') or ''),
                                float(point.get('value') or point.get('equity') or 0),
                            )
                        )

                db.commit()
                cur.close()
        except Exception:
            logger.warning("Failed to persist backtest run", exc_info=True)
        return run_id

    def list_runs(
        self,
        *,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        strategy_id: Optional[int] = None,
        asset_type: str = '',
        asset_id: Optional[int] = None,
        run_type: Optional[str] = None,
        status: str = '',
        symbol: str = '',
        market: str = '',
        timeframe: str = '',
    ) -> List[Dict[str, Any]]:
        self.ensure_storage_schema()
        where = ["user_id = ?"]
        params: List[Any] = [int(user_id or 1)]
        if strategy_id is not None:
            where.append("strategy_id = ?")
            params.append(int(strategy_id))
        if asset_type:
            where.append("asset_type = ?")
            params.append(str(asset_type))
        if asset_id is not None:
            where.append("asset_id = ?")
            params.append(int(asset_id))
        if run_type:
            where.append("run_type = ?")
            params.append(str(run_type))
        if status:
            where.append("status = ?")
            params.append(str(status))
        if symbol:
            where.append("symbol = ?")
            params.append(str(symbol))
        if market:
            where.append("market = ?")
            params.append(str(market))
        if timeframe:
            where.append("timeframe = ?")
            params.append(str(timeframe))

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                f"""
                SELECT id, user_id, strategy_id, strategy_name, asset_type, asset_id, run_type, market, symbol,
                       exchange_id, market_type, instrument_id, timeframe,
                       start_date, end_date, initial_capital, commission, slippage, leverage, trade_direction,
                       strategy_config, config_snapshot, engine_version, code_hash, status, error_message,
                       result_json, created_at
                FROM qd_backtest_runs
                WHERE {" AND ".join(where)}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, int(limit), int(offset)),
            )
            rows = cur.fetchall() or []
            cur.close()

        return [self._hydrate_run_row(r, include_result=False) for r in rows]

    def get_run(self, *, user_id: int, run_id: int) -> Optional[Dict[str, Any]]:
        self.ensure_storage_schema()
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT id, user_id, strategy_id, strategy_name, asset_type, asset_id, run_type, market, symbol,
                       exchange_id, market_type, instrument_id, timeframe,
                       start_date, end_date, initial_capital, commission, slippage, leverage, trade_direction,
                       strategy_config, config_snapshot, engine_version, code_hash, status, error_message,
                       result_json, created_at
                FROM qd_backtest_runs
                WHERE id = ? AND user_id = ?
                """,
                (int(run_id), int(user_id or 1)),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            return None
        return self._hydrate_run_row(row, include_result=True)

    def _hydrate_run_row(self, row: Dict[str, Any], include_result: bool = True) -> Dict[str, Any]:
        item = dict(row or {})
        try:
            item['strategy_config'] = json.loads(item.get('strategy_config') or '{}')
        except Exception:
            item['strategy_config'] = {}
        try:
            item['config_snapshot'] = json.loads(item.get('config_snapshot') or '{}')
        except Exception:
            item['config_snapshot'] = {}
        try:
            result = json.loads(item.get('result_json') or '{}')
        except Exception:
            result = {}

        item['total_return'] = result.get('totalReturn')
        item['total_return_pct'] = item['total_return']
        item['annual_return'] = result.get('annualReturn')
        item['win_rate'] = result.get('winRate')
        item['total_trades'] = result.get('totalTrades')
        ea = result.get('executionAssumptions') or {}
        pi = result.get('precision_info') or {}
        exec_cfg = (item.get('config_snapshot') or {}).get('executionConfig') or {}
        mtf_active = bool(ea.get('mtfActive') or pi.get('enabled'))
        strict_mode = ea.get('strictMode')
        if strict_mode is None:
            strict_mode = exec_cfg.get('strictMode')
        if strict_mode is None:
            timing = str(
                ea.get('signalTiming')
                or (item.get('strategy_config') or {}).get('execution', {}).get('signalTiming')
                or ''
            ).lower()
            strict_mode = timing not in ('same_bar_close', 'current_bar_close', 'bar_close', 'close')
        simulation_mode = str(
            ea.get('simulationMode') or pi.get('mode') or pi.get('precision') or ''
        ).lower()
        if strict_mode:
            summary_mode = 'strict'
        elif mtf_active or simulation_mode in ('aggressive_1m', 'mtf'):
            summary_mode = 'aggressive_1m'
        else:
            summary_mode = 'aggressive_bar'
        item['simulation_summary'] = {
            'mode': summary_mode,
            'strictMode': bool(strict_mode),
            'execTimeframe': ea.get('executionTimeframe') or pi.get('timeframe') or item.get('timeframe'),
            'mtfFallbackReason': ea.get('mtfFallbackReason') or pi.get('fallback_reason'),
        }
        if include_result:
            result = self._hydrate_persisted_result(item.get('id'), result)
            item['result'] = result
        item.pop('result_json', None)
        return item

    def _hydrate_persisted_result(self, run_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        if not run_id:
            return result
        hydrated = dict(result or {})
        needs_trades = not (
            hydrated.get('closedTrades')
            or hydrated.get('tradeRecords')
            or hydrated.get('trade_records')
            or hydrated.get('trades')
        )
        needs_equity = not (
            hydrated.get('equityCurve')
            or hydrated.get('equity_curve')
            or hydrated.get('balanceCurve')
            or hydrated.get('balance_curve')
        )
        if not needs_trades and not needs_equity:
            return hydrated

        try:
            with get_db_connection() as db:
                cur = db.cursor()
                if needs_trades:
                    cur.execute(
                        """
                        SELECT trade_index, trade_time, trade_type, side, price, amount, profit, balance, reason, payload_json
                        FROM qd_backtest_trades
                        WHERE run_id = ?
                        ORDER BY trade_index ASC, id ASC
                        """,
                        (int(run_id),),
                    )
                    trade_rows = cur.fetchall() or []
                    trades: List[Dict[str, Any]] = []
                    for row in trade_rows:
                        payload: Dict[str, Any] = {}
                        try:
                            payload = json.loads(row.get('payload_json') or '{}')
                        except Exception:
                            payload = {}
                        trade = {
                            'tradeNo': row.get('trade_index'),
                            'time': row.get('trade_time'),
                            'type': row.get('trade_type'),
                            'side': row.get('side'),
                            'price': row.get('price'),
                            'amount': row.get('amount'),
                            'profit': row.get('profit'),
                            'balance': row.get('balance'),
                            'reason': row.get('reason'),
                        }
                        trades.append({**trade, **payload})
                    hydrated['closedTrades'] = trades
                    hydrated['tradeRecords'] = trades
                    if not hydrated.get('trades'):
                        hydrated['trades'] = trades
                    if not hydrated.get('totalTrades') and trades:
                        hydrated['totalTrades'] = len(trades)

                if needs_equity:
                    cur.execute(
                        """
                        SELECT point_time, point_value
                        FROM qd_backtest_equity_points
                        WHERE run_id = ?
                        ORDER BY point_index ASC, id ASC
                        """,
                        (int(run_id),),
                    )
                    equity_rows = cur.fetchall() or []
                    equity_curve = [
                        {'time': row.get('point_time'), 'value': row.get('point_value')}
                        for row in equity_rows
                    ]
                    hydrated['equityCurve'] = equity_curve
                cur.close()
        except Exception:
            logger.warning("Failed to hydrate persisted backtest result for run %s", run_id, exc_info=True)
        return hydrated
    
    def run_strategy_snapshot(
        self,
        snapshot: Dict[str, Any],
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        if not snapshot:
            raise ValueError("strategy snapshot is required")

        code = snapshot.get('code') or ''
        market = snapshot.get('market') or 'Crypto'
        symbol = snapshot.get('symbol') or ''
        timeframe = snapshot.get('timeframe') or '1D'
        initial_capital = float(snapshot.get('initial_capital') or 10000)
        commission = float(snapshot.get('commission') or 0)
        slippage = float(snapshot.get('slippage') or 0)
        leverage = int(snapshot.get('leverage') or 1)
        trade_direction = str(snapshot.get('trade_direction') or 'long')
        strategy_config = snapshot.get('strategy_config') or {}
        run_type = str(snapshot.get('run_type') or 'strategy_script')
        config_snapshot = snapshot.get('config_snapshot') if isinstance(snapshot.get('config_snapshot'), dict) else {}
        market_config = config_snapshot.get('marketConfig') if isinstance(config_snapshot.get('marketConfig'), dict) else {}
        market_type = snapshot.get('market_type') or market_config.get('marketType')
        exchange_id = snapshot.get('exchange_id') or market_config.get('exchangeId')

        if run_type != 'strategy_script':
            raise ValueError(
                "Indicators are chart-only. Use run_type='strategy_script' with ScriptStrategy code for backtesting."
            )
        return self._run_script_strategy(
            code=code,
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            leverage=leverage,
            trade_direction=trade_direction,
            strategy_config=strategy_config,
            market_type=market_type,
            exchange_id=exchange_id,
        )

    def _run_script_strategy(
        self,
        *,
        code: str,
        market: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        commission: float,
        slippage: float,
        leverage: int,
        trade_direction: str,
        strategy_config: Optional[Dict[str, Any]] = None,
        market_type: Optional[str] = None,
        exchange_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        contract = resolve_script_strategy_contract(code, strategy_config)
        param_schema = (
            strategy_config.get('param_schema')
            if isinstance(strategy_config, dict) and isinstance(strategy_config.get('param_schema'), dict)
            else {}
        )
        param_sources = self._sanitize_strategy_params(contract['parameters'], param_schema)
        warmup_bars = int(contract['startupCandleCount'] or 0)
        signal_start_date = warmup_start_date(start_date, timeframe, warmup_bars, market)

        df_full = self._fetch_kline_data(
            market,
            symbol,
            timeframe,
            signal_start_date,
            end_date,
            market_type=market_type,
            exchange_id=exchange_id,
        )
        if df_full.empty:
            raise ValueError("No candle data available in the backtest date range")
        df_full.attrs['timeframe'] = timeframe
        requested_start_warmup_bars = int((df_full.index < pd.Timestamp(start_date)).sum())
        effective_start_date = start_date
        if requested_start_warmup_bars < warmup_bars:
            missing_bars = warmup_bars - requested_start_warmup_bars
            formal_rows = df_full[df_full.index >= pd.Timestamp(start_date)]
            if len(formal_rows) <= missing_bars:
                raise ValueError(
                    f"BACKTEST_WARMUP_INSUFFICIENT required={warmup_bars} "
                    f"available={requested_start_warmup_bars}"
                )
            effective_start_date = pd.Timestamp(formal_rows.index[missing_bars - 1]).to_pydatetime()
        available_warmup_bars = int((df_full.index < pd.Timestamp(effective_start_date)).sum())

        df = self._slice_to_backtest_window(df_full, effective_start_date, end_date)
        if df.empty:
            raise ValueError("No candle data available in the backtest date range")
        df.attrs['timeframe'] = timeframe

        from app.services.backtest_engine import BacktestConfig, ScriptStrategyBacktestRunner

        engine_config = dict(strategy_config or {})
        if market_type:
            engine_config['market_type'] = market_type
            engine_config['marketType'] = market_type
        cfg = BacktestConfig.from_strategy_config(
            engine_config,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            leverage=leverage,
            trade_direction=trade_direction,
            timeframe=timeframe,
        )
        cfg.timeframe = timeframe
        runner = ScriptStrategyBacktestRunner(
            config=cfg,
            code=code,
            params=param_sources,
            runtime={
                'initial_capital': initial_capital,
                'investment_amount': initial_capital,
                'leverage': leverage,
                'trade_direction': cfg.trade_direction,
                'symbol': symbol,
                'market_type': cfg.market_type,
                'timeframe': timeframe,
                'strategy_config': engine_config,
                'trading_start': effective_start_date,
                'startup_candle_count': warmup_bars,
            },
        )
        engine_result = runner.run(
            df=df_full,
            start_date=effective_start_date,
            end_date=end_date,
        )
        self._last_engine_result = engine_result
        script_logs = engine_result.get('logs') or []
        equity_curve = engine_result.get('equityCurve') or []
        trades = engine_result.get('trades') or []
        total_commission = float(engine_result.get('totalCommission') or 0.0)
        signal_diagnostics = self._order_diagnostics(engine_result, cfg.trade_direction)
        exec_cfg = (strategy_config or {}).get('execution') or {}
        signal_timing = str(exec_cfg.get('signalTiming') or 'next_bar_open').strip().lower()
        signal_tf_seconds = self.TIMEFRAME_SECONDS.get(timeframe, 3600)
        for trade in trades:
            if isinstance(trade, dict) and not trade.get('bar_time'):
                trade['bar_time'] = trade.get('time')
        self._annotate_signal_bar_times(trades, signal_tf_seconds, signal_timing)
        metrics = self._metrics_from_engine_or_fallback(
            equity_curve,
            trades,
            initial_capital,
            timeframe,
            effective_start_date,
            end_date,
            total_commission,
        )
        result = self._format_result(metrics, equity_curve, trades)
        result['logs'] = script_logs
        result['precision_info'] = {
            'enabled': False,
            'timeframe': timeframe,
            'precision': 'standard',
            'message': 'Using standard strategy script backtest'
        }
        ea = self._execution_assumptions(
            strategy_config,
            simulation_mode='script_strategy_engine',
            signal_timeframe=timeframe,
            commission=commission,
            slippage=slippage,
        )
        ea['scriptBacktest'] = True
        ea['strictMode'] = bool(((strategy_config or {}).get('execution') or {}).get('signalTiming', 'next_bar_open') in ('next_bar_open', 'next_open', 'nextopen', 'next'))
        ea['simulationMode'] = 'script_strategy_engine'
        ea['fillRule'] = 'next_bar_open' if ea['strictMode'] else 'same_bar_close'
        ea['engineVersion'] = 'quantdinger-script-backtest-v3'
        if market_type:
            ea['marketType'] = market_type
        if exchange_id:
            ea['exchangeId'] = exchange_id
        result['executionAssumptions'] = ea
        result['signalDiagnostics'] = signal_diagnostics
        self._attach_buy_hold_benchmark(result, df, initial_capital, symbol)
        self._attach_replay_bars_to_result(result, df)
        self._attach_actual_range_to_result(result, df)
        self._attach_data_snapshot_to_result(
            result,
            df,
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            market_type=market_type or cfg.market_type,
            exchange_id=exchange_id or "",
        )
        self._attach_warmup_to_result(
            result,
            warmup_bars=warmup_bars,
            warmup_start=signal_start_date,
            requested_start=start_date,
            effective_start=effective_start_date,
            available_warmup_bars=available_warmup_bars,
            requested_start_warmup_bars=requested_start_warmup_bars,
        )
        return result

    @staticmethod
    def _attach_replay_bars_to_result(result: Dict[str, Any], df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        if len(df) > 5000:
            return
        required = {"open", "high", "low", "close"}
        if not required.issubset(set(df.columns)):
            return
        bars: List[Dict[str, Any]] = []
        frame = df.copy()
        for timestamp, row in frame.iterrows():
            try:
                bars.append({
                    "time": pd.to_datetime(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": round(float(row.get("open") or 0.0), 8),
                    "high": round(float(row.get("high") or 0.0), 8),
                    "low": round(float(row.get("low") or 0.0), 8),
                    "close": round(float(row.get("close") or 0.0), 8),
                    "volume": round(float(row.get("volume") or 0.0), 8),
                })
            except Exception:
                continue
        if bars:
            result["replayData"] = {
                "bars": bars,
                "source": "script_backtest_input",
            }
            result["replay"] = {
                "bars": bars,
            }

    @staticmethod
    def _attach_actual_range_to_result(result: Dict[str, Any], df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        attrs = getattr(df, "attrs", None) or {}
        actual_range = dict(attrs.get("backtestActualRange") or {})
        actual_range.setdefault("actualStart", str(pd.Timestamp(df.index.min())))
        actual_range.setdefault("actualEnd", str(pd.Timestamp(df.index.max())))
        ea = dict(result.get("executionAssumptions") or {})
        ea["actualDataRange"] = actual_range
        ea["requestedRangeAdjusted"] = bool(attrs.get("backtestActualRange"))
        result["executionAssumptions"] = ea
        result["startDate"] = actual_range["actualStart"]
        result["endDate"] = actual_range["actualEnd"]

    @staticmethod
    def _attach_data_snapshot_to_result(
        result: Dict[str, Any],
        df: pd.DataFrame,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        market_type: str,
        exchange_id: str,
    ) -> None:
        if df is None or df.empty:
            return
        columns = [name for name in ("open", "high", "low", "close", "volume") if name in df.columns]
        snapshot_frame = df[columns].copy()
        snapshot_frame.index = pd.to_datetime(snapshot_frame.index)
        canonical = snapshot_frame.to_csv(
            index=True,
            date_format="%Y-%m-%dT%H:%M:%S.%f",
            float_format="%.12g",
            lineterminator="\n",
        )
        data_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        snapshot = {
            "sha256": data_hash,
            "rowCount": int(len(snapshot_frame)),
            "start": str(snapshot_frame.index.min()),
            "end": str(snapshot_frame.index.max()),
            "columns": columns,
            "market": str(market or ""),
            "symbol": str(symbol or ""),
            "timeframe": str(timeframe or ""),
            "marketType": str(market_type or ""),
            "exchangeId": str(exchange_id or ""),
        }
        result["dataSnapshot"] = snapshot
        result["dataHash"] = data_hash
        ea = dict(result.get("executionAssumptions") or {})
        ea["dataSnapshot"] = snapshot
        result["executionAssumptions"] = ea

    def _attach_buy_hold_benchmark(
        self,
        result: Dict[str, Any],
        df: pd.DataFrame,
        initial_capital: float,
        symbol: str = "",
    ) -> None:
        if df is None or df.empty or "close" not in df.columns:
            return
        curve = result.get("equityCurve") or []
        if not curve:
            return
        try:
            price_frame = df[["close"]].copy()
            price_frame["close"] = pd.to_numeric(price_frame["close"], errors="coerce").replace([np.inf, -np.inf], np.nan)
            price_frame = price_frame.dropna()
            price_frame = price_frame[price_frame["close"] > 0]
            if price_frame.empty:
                return
            start_price = float(price_frame["close"].iloc[0])
            end_price = float(price_frame["close"].iloc[-1])
            if start_price <= 0:
                return
            final_value = float(initial_capital or 0.0) * end_price / start_price
            benchmark_return = ((final_value - float(initial_capital or 0.0)) / float(initial_capital or 1.0) * 100.0)
            benchmark_curve = []
            for timestamp, row in self._sample_dataframe(price_frame, 500).iterrows():
                close_price = float(row.get("close") or 0.0)
                if close_price <= 0:
                    continue
                benchmark_curve.append({
                    "time": str(timestamp),
                    "value": round(float(initial_capital or 0.0) * close_price / start_price, 2),
                    "price": round(close_price, 8),
                })
            result["benchmarkReturn"] = round(benchmark_return, 2)
            result["benchmarkFinalValue"] = round(final_value, 2)
            result["benchmarkStartPrice"] = round(start_price, 8)
            result["benchmarkEndPrice"] = round(end_price, 8)
            result["benchmarkCurve"] = benchmark_curve
            result["benchmark"] = {
                "type": "buy_hold_spot",
                "label": "Spot buy-and-hold",
                "symbol": symbol or "",
                "return": result.get("benchmarkReturn"),
                "finalValue": result.get("benchmarkFinalValue"),
                "startPrice": result.get("benchmarkStartPrice"),
                "endPrice": result.get("benchmarkEndPrice"),
                "curve": benchmark_curve,
            }
            try:
                result["alphaReturn"] = round(float(result.get("totalReturn") or 0.0) - benchmark_return, 2)
            except Exception:
                pass
        except Exception:
            return

    @staticmethod
    def _sample_dataframe(df: pd.DataFrame, max_size: int) -> pd.DataFrame:
        if df is None or df.empty or len(df) <= max_size:
            return df
        if max_size <= 2:
            return df.iloc[[0, -1]]
        step = max(1, math.ceil((len(df) - 1) / (max_size - 1)))
        sampled = df.iloc[::step]
        if sampled.index[-1] != df.index[-1]:
            sampled = pd.concat([sampled, df.iloc[[-1]]])
        if len(sampled) > max_size:
            sampled = pd.concat([sampled.iloc[: max_size - 1], df.iloc[[-1]]])
        return sampled

    def _fetch_kline_data(
        self,
        market: str,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        market_type: Optional[str] = None,
        exchange_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch candle data for ScriptStrategy backtests."""
        total_seconds = max(1.0, (end_date - start_date).total_seconds())
        tf_seconds = self.TIMEFRAME_SECONDS.get(timeframe, 86400)
        limit = int(math.ceil(total_seconds / tf_seconds * 1.15) + 200)
        after_time = int((start_date - timedelta(days=1)).timestamp())
        before_time = int((end_date + timedelta(days=1)).timestamp())

        mt_key = str(market_type or "").strip().lower()
        ex_key = str(exchange_id or "").strip().lower()
        cache_key = f"{market}:{symbol}:{timeframe}:{mt_key}:{ex_key}:{start_date.date()}:{end_date.date()}"
        cached = _kline_cache.get(cache_key)
        if cached is not None and not cached.empty:
            return cached

        try:
            kline_data = DataSourceFactory.get_kline(
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                before_time=before_time,
                after_time=after_time,
                exchange_id=exchange_id,
                market_type=market_type,
            )
        except Exception as exc:
            logger.warning(
                "K-line fetch failed for %s:%s %s via %s/%s: %s",
                market,
                symbol,
                timeframe,
                exchange_id or "default",
                market_type or "default",
                exc,
            )
            return pd.DataFrame()

        if not kline_data:
            try:
                kline_data = DataSourceFactory.get_kline(
                    market=market,
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=min(max(limit, 300), 5000),
                    before_time=before_time,
                    after_time=None,
                    exchange_id=exchange_id,
                    market_type=market_type,
                )
                if kline_data:
                    logger.warning(
                        "Using recent available candles for %s:%s %s via %s/%s because the requested window returned no data",
                        market,
                        symbol,
                        timeframe,
                        exchange_id or "default",
                        market_type or "default",
                    )
            except Exception as exc:
                logger.warning(
                    "Recent-candle fallback failed for %s:%s %s via %s/%s: %s",
                    market,
                    symbol,
                    timeframe,
                    exchange_id or "default",
                    market_type or "default",
                    exc,
                )
                return pd.DataFrame()

        if not kline_data:
            return pd.DataFrame()

        try:
            df = pd.DataFrame(kline_data)
            if df.empty or "time" not in df.columns:
                return pd.DataFrame()
            try:
                df["time"] = pd.to_datetime(df["time"], unit="s")
            except (ValueError, OverflowError):
                try:
                    df["time"] = pd.to_datetime(df["time"], unit="ms")
                except (ValueError, OverflowError):
                    df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time").sort_index()
            if df.empty:
                return pd.DataFrame()

            requested_start = pd.Timestamp(start_date)
            requested_end = pd.Timestamp(end_date)
            data_start = pd.Timestamp(df.index.min())
            data_end = pd.Timestamp(df.index.max())
            effective_start = max(requested_start, data_start)
            effective_end = min(requested_end, data_end)
            if effective_start <= effective_end:
                out = df[(df.index >= effective_start) & (df.index <= effective_end)].copy()
            else:
                return pd.DataFrame()
            if out.empty:
                return pd.DataFrame()
            if effective_start != requested_start or effective_end != requested_end:
                out.attrs["backtestActualRange"] = {
                    "requestedStart": str(requested_start),
                    "requestedEnd": str(requested_end),
                    "actualStart": str(effective_start),
                    "actualEnd": str(effective_end),
                }
            _kline_cache.put(cache_key, out, timeframe)
            return out
        except Exception as exc:
            logger.error("Error processing K-line data: %s", exc)
            logger.error(traceback.format_exc())
            return pd.DataFrame()
    
    def _metrics_from_engine_or_fallback(
        self,
        equity_curve: List[Dict[str, Any]],
        trades: List[Dict[str, Any]],
        initial_capital: float,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        total_commission: float,
    ) -> Dict[str, Any]:
        """Use the unified engine analyzer output; old metric math is fallback only."""
        engine_result = getattr(self, '_last_engine_result', None)
        if isinstance(engine_result, dict) and engine_result:
            curve_final = initial_capital
            try:
                if equity_curve:
                    curve_final = float(equity_curve[-1].get('value', curve_final))
            except Exception:
                curve_final = initial_capital
            metric_keys = (
                'total_return', 'totalReturn', 'max_drawdown', 'maxDrawdown',
                'sharpe_ratio', 'sharpeRatio', 'win_rate', 'winRate',
                'profit_factor', 'profitFactor', 'total_trades', 'totalTrades',
                'winning_trades', 'winningTrades', 'losing_trades', 'losingTrades',
                'avg_win', 'avgWin', 'avg_loss', 'avgLoss',
                'best_trade', 'bestTrade', 'worst_trade', 'worstTrade',
                'avg_trade', 'avgTrade', 'annual_return', 'annualReturn',
                'final_equity', 'finalEquity', 'total_commission', 'totalCommission',
                'sortino_ratio', 'sortinoRatio', 'calmar_ratio', 'calmarRatio',
            )
            metrics = {key: engine_result[key] for key in metric_keys if key in engine_result}
            if metrics:
                metrics.setdefault('totalReturn', engine_result.get('totalReturn', engine_result.get('total_return', 0.0)))
                metrics.setdefault('maxDrawdown', engine_result.get('maxDrawdown', engine_result.get('max_drawdown', 0.0)))
                metrics.setdefault('sharpeRatio', engine_result.get('sharpeRatio', engine_result.get('sharpe_ratio', 0.0)))
                metrics.setdefault('winRate', engine_result.get('winRate', engine_result.get('win_rate', 0.0)))
                metrics.setdefault('profitFactor', engine_result.get('profitFactor', engine_result.get('profit_factor', 0.0)))
                metrics.setdefault('totalTrades', engine_result.get('totalTrades', engine_result.get('total_trades', 0)))
                metrics.setdefault('winningTrades', engine_result.get('winningTrades', engine_result.get('winning_trades', 0)))
                metrics.setdefault('losingTrades', engine_result.get('losingTrades', engine_result.get('losing_trades', 0)))
                metrics.setdefault('bestTrade', engine_result.get('bestTrade', engine_result.get('best_trade', 0.0)))
                metrics.setdefault('worstTrade', engine_result.get('worstTrade', engine_result.get('worst_trade', 0.0)))
                metrics.setdefault('avgTrade', engine_result.get('avgTrade', engine_result.get('avg_trade', 0.0)))
                metrics.setdefault('finalEquity', engine_result.get('finalEquity', engine_result.get('final_equity', curve_final)))
                metrics.setdefault('totalProfit', round(curve_final - float(initial_capital or 0.0), 2))
                metrics.setdefault('totalCommission', engine_result.get('totalCommission', engine_result.get('total_commission', total_commission)))
                return metrics
        return self._calculate_metrics(
            equity_curve,
            trades,
            initial_capital,
            timeframe,
            start_date,
            end_date,
            total_commission,
        )

    def _calculate_metrics(
        self,
        equity_curve: List,
        trades: List,
        initial_capital: float,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        total_commission: float = 0
    ) -> Dict:
        """Calculate backtest metrics."""
        if not equity_curve:
            return {}
        
        final_value = equity_curve[-1]['value']
        total_return = (final_value - initial_capital) / initial_capital * 100
        
        # Calculate annualized return: simple, not compound
        # For high-return strategies, compound annualization produces unrealistic numbers
        # Use actual data time range from equity_curve instead of requested start_date/end_date
        # This fixes the issue where data may only be available until a certain date (e.g., TSLA only to January)
        try:
            # Parse actual start and end times from equity_curve
            actual_start_str = equity_curve[0]['time']
            actual_end_str = equity_curve[-1]['time']
            actual_start = datetime.strptime(actual_start_str, '%Y-%m-%d %H:%M')
            actual_end = datetime.strptime(actual_end_str, '%Y-%m-%d %H:%M')
            actual_days = (actual_end - actual_start).total_seconds() / 86400
        except (KeyError, ValueError, IndexError) as e:
            # Fallback to requested date range if parsing fails
            logger.warning(f"Failed to parse actual time range from equity_curve: {e}, using requested range")
            actual_days = (end_date - start_date).total_seconds() / 86400
        
        years = actual_days / 365.0
        
        # Simple annualization: annualized return = total return / years
        if years > 0:
            annual_return = total_return / years
        else:
            annual_return = 0
        
        # Calculate max drawdown
        values = [e['value'] for e in equity_curve]
        max_drawdown = self._calculate_max_drawdown(values)
        
        # Calculate Sharpe ratio
        sharpe = self._calculate_sharpe(values, timeframe)
        
        # Calculate total PnL: final equity - initial capital (most accurate)
        total_profit = final_value - initial_capital
        
        # Calculate win rate (all exit trades)
        # Exit trades: trades with profit != 0
        closing_trades = [t for t in trades if t.get('profit', 0) != 0]
        win_trades = [t for t in closing_trades if t['profit'] > 0]
        loss_trades = [t for t in closing_trades if t['profit'] < 0]
        total_trades = len(closing_trades)
        win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0
        
        # Calculate profit factor (= total profit / total loss)
        total_wins = sum(t['profit'] for t in win_trades)
        total_losses = abs(sum(t['profit'] for t in loss_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else (total_wins if total_wins > 0 else 0)
        
        return {
            'totalReturn': round(total_return, 2),
            'annualReturn': round(annual_return, 2),
            'maxDrawdown': round(max_drawdown, 2),
            'sharpeRatio': round(sharpe, 2),
            'winRate': round(win_rate, 2),
            'profitFactor': round(profit_factor, 2),
            'totalTrades': total_trades,
            'totalProfit': round(total_profit, 2),
            'totalCommission': round(total_commission, 2)
        }
    
    def _calculate_max_drawdown(self, values: List[float]) -> float:
        """Calculate maximum drawdown."""
        if not values:
            return 0
        
        peak = values[0]
        max_dd = 0
        
        for value in values:
            if value > peak:
                peak = value
            dd = (peak - value) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        return -max_dd
    
    def _calculate_sharpe(self, values: List[float], timeframe: str = '1D', risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sharpe ratio.
        
        Args:
            values: Equity curve values.
            timeframe: Bar timeframe.
            risk_free_rate: Annualized risk-free rate.
        """
        if len(values) < 2:
            return 0
        
        # Filter out zero values (post-liquidation data), avoid division by 0
        valid_values = [v for v in values if v > 0]
        if len(valid_values) < 2:
            return 0
        
        # Determine annualization factor by timeframe
        annualization_factor = {
            '1m': 252 * 24 * 60,      # 1m candle: ~362,880
            '5m': 252 * 24 * 12,      # 5m candle: ~72,576
            '15m': 252 * 24 * 4,      # 15m candle: ~24,192
            '30m': 252 * 24 * 2,      # 30m candle: ~12,096
            '1H': 252 * 24,           # 1H candle: 6,048
            '4H': 252 * 6,            # 4H candle: 1,512
            '1D': 252,                # 1D candle: 252
            '1W': 52                  # 1W candle: 52
        }.get(timeframe, 252)
        
        try:
            # Calculate period returns
            returns = np.diff(valid_values) / valid_values[:-1]
            
            # Filter invalid values
            returns = returns[np.isfinite(returns)]
            if len(returns) == 0:
                return 0
            
            # Annualized mean return
            avg_return = np.mean(returns) * annualization_factor
            
            # Annualized std (volatility)
            std_return = np.std(returns) * np.sqrt(annualization_factor)
            
            if std_return == 0 or not np.isfinite(std_return):
                return 0
            
            # Sharpe ratio = (annualized return - risk-free rate) / annualized volatility
            sharpe = (avg_return - risk_free_rate) / std_return
            return sharpe if np.isfinite(sharpe) else 0
        except Exception as e:
            logger.warning(f"Sharpe ratio calculation failed: {e}")
            return 0
    
    def _execution_assumptions(
        self,
        strategy_config: Optional[Dict[str, Any]],
        *,
        simulation_mode: str,
        signal_timeframe: Optional[str] = None,
        execution_timeframe: Optional[str] = None,
        mtf_requested: bool = False,
        mtf_active: bool = False,
        mtf_fallback_reason: Optional[str] = None,
        commission: Optional[float] = None,
        slippage: Optional[float] = None,
        backtest_preset: Optional[str] = None,
        strict_mode_aligned: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Human-facing metadata so the UI can explain how trades were timed vs chart markers.
        Keys use camelCase for JSON consumers (frontend).
        """
        cfg = strategy_config or {}
        raw = str((cfg.get('execution') or {}).get('signalTiming') or 'next_bar_open').strip().lower()
        intrabar_mode = str(
            (cfg.get('execution') or {}).get('intrabarMode')
            or (cfg.get('execution') or {}).get('intrabar_mode')
            or cfg.get('intrabarMode')
            or cfg.get('intrabar_mode')
            or 'conservative'
        ).strip().lower()
        is_next_open = raw in ('next_bar_open', 'next_open', 'nextopen', 'next')
        if raw in ('bar_close', 'close', 'same_bar_close', 'current_bar_close'):
            timing_key = 'same_bar_close'
        elif is_next_open:
            timing_key = 'next_bar_open'
        else:
            timing_key = raw
        default_fill = 'open' if is_next_open else 'close'
        payload: Dict[str, Any] = {
            'signalTiming': timing_key,
            'signalTimingRaw': raw,
            'defaultFillPrice': default_fill,
            'simulationMode': simulation_mode,
            'strategyTimeframe': signal_timeframe,
            'executionTimeframe': execution_timeframe,
            'engineVersion': self.ENGINE_VERSION,
            'intrabarMode': intrabar_mode,
            'mtfRequested': bool(mtf_requested),
            'mtfActive': bool(mtf_active),
        }
        if mtf_fallback_reason:
            payload['mtfFallbackReason'] = mtf_fallback_reason
        try:
            if commission is not None:
                payload['commission'] = round(float(commission), 6)
        except (TypeError, ValueError):
            pass
        try:
            if slippage is not None:
                payload['slippage'] = round(float(slippage), 6)
        except (TypeError, ValueError):
            pass
        if backtest_preset:
            payload['backtestPreset'] = str(backtest_preset)
        if strict_mode_aligned is not None:
            payload['strictModeAligned'] = bool(strict_mode_aligned)
        return payload

    @staticmethod
    def _annotate_signal_bar_times(
        trades: List[Dict[str, Any]],
        signal_tf_seconds: int,
        signal_timing: str,
    ) -> None:
        """Backfill `signal_bar_time` onto every trade for chart double-display.

        Convention for the frontend overlay layer:
          * `bar_time`        = chart-aligned EXECUTION bar (what user sees as fill)
          * `signal_bar_time` = chart-aligned SIGNAL bar (where the rule fired)

        For pure signal-triggered open/close (no _stop/_profit/_trailing/liquidation
        suffix) under `next_bar_open`, signal bar is exactly one signal_tf BEFORE
        the execution bar. For SL/TP/trailing/liquidation triggers, there is no
        meaningful "signal bar"; they fire intra-bar from the price path, so we
        align signal_bar_time to bar_time so the renderer only draws a single marker.
        For `bar_close` execution mode, signal and execution coincide on the same bar.
        """
        if not trades:
            return
        delta_seconds = int(signal_tf_seconds) if signal_tf_seconds else 0
        use_offset = (
            delta_seconds > 0
            and str(signal_timing or '').strip().lower()
            in ('next_bar_open', 'next_open', 'nextopen', 'next')
        )
        delta = timedelta(seconds=delta_seconds) if use_offset else timedelta(0)
        for trade in trades:
            if 'signal_bar_time' in trade:
                continue
            bt = trade.get('bar_time') or trade.get('time')
            if not bt:
                trade['signal_bar_time'] = None
                continue
            ty = str(trade.get('type') or '').lower()
            price_path_trigger = (
                '_stop' in ty
                or '_profit' in ty
                or '_trailing' in ty
                or ty == 'liquidation'
            )
            if not use_offset or price_path_trigger:
                trade['signal_bar_time'] = bt
                continue
            try:
                bt_dt = pd.to_datetime(bt)
                trade['signal_bar_time'] = (bt_dt - delta).strftime('%Y-%m-%d %H:%M')
            except Exception:
                trade['signal_bar_time'] = bt

    def _format_result(
        self,
        metrics: Dict,
        equity_curve: List,
        trades: List
    ) -> Dict[str, Any]:
        """Format backtest result for API responses."""
        def sample_curve(rows: List[Dict[str, Any]], max_size: int) -> List[Dict[str, Any]]:
            if len(rows) <= max_size:
                return list(rows)
            if max_size <= 2:
                return [rows[0], rows[-1]]
            step = math.ceil((len(rows) - 1) / (max_size - 1))
            sampled = rows[::step]
            if sampled[-1] is not rows[-1]:
                sampled.append(rows[-1])
            if len(sampled) > max_size:
                sampled = sampled[: max_size - 1] + [rows[-1]]
            return sampled

        # Simplify equity curve for the API, while always preserving the final equity point.
        max_points = 500
        equity_curve = sample_curve(equity_curve, max_points)
        
        # Clean NaN/Inf values for JSON serialization
        def clean_value(value):
            """Clean NaN/Inf values."""
            if isinstance(value, float):
                if np.isnan(value) or np.isinf(value):
                    return 0
            return value
        
        # Clean metrics
        cleaned_metrics = {}
        for key, value in metrics.items():
            cleaned_metrics[key] = clean_value(value)
        
        # Clean equity_curve
        cleaned_curve = []
        for item in equity_curve:
            cleaned_curve.append({
                'time': item['time'],
                'value': clean_value(item['value'])
            })
        
        # Clean trades
        cleaned_trades = []
        # Don't truncate trades: return all (frontend can paginate)
        def infer_trade_reason(trade_type: str) -> str:
            t = str(trade_type or '').lower()
            if 'liquidation' in t:
                return 'liquidation'
            if 'trailing' in t:
                return 'trailing_stop'
            if 'stop' in t:
                return 'stop_loss'
            if 'profit' in t:
                return 'take_profit'
            if 'reduce' in t:
                return 'reduce_position'
            if 'add' in t:
                return 'add_position'
            if 'close' in t:
                return 'signal_close'
            return ''

        for trade in trades:
            cleaned_trade = {}
            for key, value in trade.items():
                cleaned_trade[key] = clean_value(value)
            inferred_reason = infer_trade_reason(cleaned_trade.get('type'))
            if inferred_reason and not cleaned_trade.get('reason'):
                cleaned_trade['reason'] = inferred_reason
            if not cleaned_trade.get('close_reason'):
                cleaned_trade['close_reason'] = cleaned_trade.get('reason') or inferred_reason
            cleaned_trades.append(cleaned_trade)

        def as_float(value, default: float = 0.0) -> float:
            try:
                number = float(value)
                return number if np.isfinite(number) else default
            except Exception:
                return default

        def infer_side(trade: Dict[str, Any]) -> str:
            raw = " ".join([
                str(trade.get('position_side') or ''),
                str(trade.get('side') or ''),
                str(trade.get('direction') or ''),
                str(trade.get('type') or ''),
            ]).lower()
            return 'short' if 'short' in raw else 'long'

        def is_open_trade(trade: Dict[str, Any]) -> bool:
            t = str(trade.get('type') or '').lower()
            return t.startswith('open_') or t.startswith('add_') or t in ('buy', 'sell_short')

        def is_close_trade(trade: Dict[str, Any]) -> bool:
            t = str(trade.get('type') or '').lower()
            if t.startswith('close_') or t in ('sell', 'cover', 'liquidation'):
                return True
            return as_float(trade.get('profit', trade.get('pnl', trade.get('realized_pnl'))), 0.0) != 0.0

        def build_closed_trades(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            open_positions: Dict[str, Dict[str, Any]] = {}
            closed: List[Dict[str, Any]] = []

            for row in rows:
                side = infer_side(row)
                price = as_float(row.get('price') or row.get('entry_price') or row.get('exit_price'))
                qty = as_float(row.get('amount') or row.get('quantity') or row.get('qty') or row.get('size'))
                fee = as_float(row.get('commission') or row.get('fee'))
                row_time = row.get('time') or row.get('date') or row.get('timestamp') or row.get('bar_time')

                if is_open_trade(row) and price > 0 and qty > 0:
                    pos = open_positions.get(side)
                    if not pos:
                        open_positions[side] = {
                            'side': side,
                            'entry_time': row_time,
                            'entry_price': price,
                            'amount': qty,
                            'commission': fee,
                            'entry_reason': row.get('reason') or row.get('type') or '',
                        }
                        continue
                    total_qty = pos['amount'] + qty
                    if total_qty > 0 and qty > 0:
                        pos['entry_price'] = ((pos['entry_price'] * pos['amount']) + (price * qty)) / total_qty
                        pos['amount'] = total_qty
                    pos['commission'] += fee
                    continue

                if not is_close_trade(row) or price <= 0:
                    continue

                pos = open_positions.get(side)
                close_qty = qty
                if pos:
                    if close_qty <= 0:
                        close_qty = pos.get('amount') or 0.0
                    if close_qty <= 0:
                        continue
                    entry_price = pos.get('entry_price') or as_float(row.get('entry_price'))
                    entry_time = pos.get('entry_time') or row.get('entry_time') or row_time
                    open_fee = pos.get('commission') or 0.0
                    entry_reason = pos.get('entry_reason') or ''
                else:
                    entry_price = as_float(row.get('entry_price'))
                    entry_time = row.get('entry_time') or row_time
                    open_fee = 0.0
                    entry_reason = row.get('entry_reason') or ''
                    if entry_price <= 0 or close_qty <= 0:
                        continue

                closed.append({
                    'id': len(closed) + 1,
                    'side': side,
                    'type': side.upper(),
                    'entry_time': entry_time,
                    'exit_time': row.get('exit_time') or row_time,
                    'entry_price': round(entry_price, 8),
                    'exit_price': round(price, 8),
                    'amount': round(close_qty, 8),
                    'quantity': round(close_qty, 8),
                    'profit': round(as_float(row.get('profit', row.get('pnl', row.get('realized_pnl')))), 2),
                    'balance': round(as_float(row.get('balance') or row.get('cash') or row.get('equity')), 2),
                    'commission': round(open_fee + fee, 8),
                    'holding_bars': row.get('holding_bars'),
                    'entry_reason': entry_reason,
                    'close_reason': row.get('close_reason') or row.get('reason') or infer_trade_reason(row.get('type')) or row.get('type') or '',
                    'order_id': row.get('order_id'),
                })

                if pos:
                    pos['amount'] = max(0.0, pos.get('amount', 0.0) - close_qty)
                    if pos['amount'] <= 1e-12:
                        open_positions.pop(side, None)

            return closed

        def normalize_closed_trades(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            normalized: List[Dict[str, Any]] = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                cleaned = {key: clean_value(value) for key, value in row.items()}
                side = infer_side(cleaned)
                profit = as_float(cleaned.get('profit', cleaned.get('pnl', cleaned.get('realized_pnl'))))
                normalized.append({
                    **cleaned,
                    'id': cleaned.get('id') or cleaned.get('tradeNo') or cleaned.get('trade_no') or len(normalized) + 1,
                    'tradeNo': cleaned.get('tradeNo') or cleaned.get('trade_no') or cleaned.get('id') or len(normalized) + 1,
                    'side': side,
                    'type': cleaned.get('type') or side.upper(),
                    'entry_time': cleaned.get('entry_time') or cleaned.get('entryTime') or cleaned.get('open_time') or cleaned.get('time'),
                    'exit_time': cleaned.get('exit_time') or cleaned.get('exitTime') or cleaned.get('close_time') or cleaned.get('time'),
                    'entry_price': round(as_float(cleaned.get('entry_price', cleaned.get('entryPrice'))), 8),
                    'exit_price': round(as_float(cleaned.get('exit_price', cleaned.get('exitPrice'))), 8),
                    'amount': round(as_float(cleaned.get('amount', cleaned.get('quantity', cleaned.get('qty')))), 8),
                    'quantity': round(as_float(cleaned.get('quantity', cleaned.get('amount', cleaned.get('qty')))), 8),
                    'profit': round(profit, 2),
                    'pnl': round(profit, 2),
                    'balance': round(as_float(cleaned.get('balance', cleaned.get('cash', cleaned.get('equity')))), 2),
                    'commission': round(as_float(cleaned.get('commission', cleaned.get('fee'))), 8),
                    'close_reason': cleaned.get('close_reason') or cleaned.get('reason') or infer_trade_reason(cleaned.get('type')) or cleaned.get('type') or '',
                })
            return normalized

        engine_result = getattr(self, '_last_engine_result', None)
        engine_closed_trades = []
        if isinstance(engine_result, dict):
            raw_closed = engine_result.get('closedTrades') or engine_result.get('tradeRecords') or []
            if isinstance(raw_closed, list):
                engine_closed_trades = normalize_closed_trades(raw_closed)

        built_closed_trades = build_closed_trades(cleaned_trades)

        def has_realized_profit(rows: List[Dict[str, Any]]) -> bool:
            return any(abs(as_float(item.get('profit'))) > 1e-9 for item in rows or [])

        if built_closed_trades and (
            not engine_closed_trades
            or (has_realized_profit(built_closed_trades) and not has_realized_profit(engine_closed_trades))
        ):
            closed_trades = built_closed_trades
        else:
            closed_trades = engine_closed_trades or built_closed_trades
        direction_counts = {
            'long': sum(1 for item in closed_trades if item.get('side') == 'long'),
            'short': sum(1 for item in closed_trades if item.get('side') == 'short'),
        }
        closed_count = len(closed_trades)
        closed_wins = sum(1 for item in closed_trades if as_float(item.get('profit')) > 0)
        closed_losses = sum(1 for item in closed_trades if as_float(item.get('profit')) < 0)
        closed_profits = [as_float(item.get('profit')) for item in closed_trades]
        best_trade = round(max(closed_profits), 2) if closed_profits else 0
        worst_trade = round(min(closed_profits), 2) if closed_profits else 0
        avg_trade = round(sum(closed_profits) / len(closed_profits), 2) if closed_profits else 0
        
        payload = {
            **cleaned_metrics,
            'equityCurve': cleaned_curve,
            'trades': cleaned_trades,
            'rawTrades': cleaned_trades,
            'closedTrades': closed_trades,
            'tradeRecords': closed_trades,
            'tradeDirections': direction_counts,
            'totalTrades': closed_count,
            'winningTrades': closed_wins,
            'losingTrades': closed_losses,
            'winRate': round((closed_wins / closed_count) * 100, 2) if closed_count else 0,
            'bestTrade': best_trade,
            'worstTrade': worst_trade,
            'avgTrade': avg_trade,
            'largestWin': best_trade,
            'largestLoss': worst_trade,
        }
        if cleaned_curve:
            final_equity = as_float(cleaned_curve[-1].get('value'))
            payload['finalEquity'] = round(final_equity, 2)
            if 'totalProfit' not in payload:
                payload['totalProfit'] = round(final_equity - as_float(payload.get('initialCapital')), 2)
        if isinstance(engine_result, dict):
            for key in (
                'grossProfit',
                'grossLoss',
                'avgWin',
                'avgLoss',
                'expectancy',
                'largestWin',
                'largestLoss',
                'bestTrade',
                'worstTrade',
                'avgTrade',
                'maxConsecutiveLosses',
                'avgHoldingBars',
                'totalFundingPaid',
            ):
                if key in engine_result and key not in ('bestTrade', 'worstTrade', 'avgTrade', 'largestWin', 'largestLoss'):
                    payload[key] = clean_value(engine_result.get(key))
            payload['orders'] = engine_result.get('orders') or []
            payload['engine'] = engine_result.get('engine') or {}
        return payload


