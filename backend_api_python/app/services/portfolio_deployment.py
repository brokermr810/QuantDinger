"""Portfolio strategy deployment records and lifecycle controls."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from app.services.portfolio_strategy_runtime import validate_portfolio_strategy_code
from app.services.portfolio_strategy_runtime import (
    PortfolioConstraints,
    PortfolioContext,
    compile_portfolio_strategy_handlers,
)
from app.services.market_schedule import latest_completed_session, next_rebalance_run
from app.utils.db import get_db_connection


ALLOWED_FREQUENCIES = frozenset({"daily", "weekly", "monthly"})
ALLOWED_EXECUTION_MODES = frozenset({"live", "notify_only"})
SUPPORTED_SCHEDULE_MARKETS = frozenset({"USStock", "HKStock", "AStock", "CNStock", "Crypto", "Cryptocurrency"})


class PortfolioDeploymentError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class PortfolioDeploymentDeferred(PortfolioDeploymentError):
    pass


class PortfolioDeploymentService:
    """Persist deployment instances while strategy logic remains in source code."""

    def list(self, user_id: int) -> list[dict]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT d.*, s.code AS source_code, s.description AS source_description,
                       u.code AS universe_code, u.name_i18n_key AS universe_name_i18n_key,
                       u.market AS universe_market
                FROM qd_portfolio_deployments d
                JOIN qd_script_sources s ON s.id = d.source_id
                JOIN qd_universes u ON u.id = d.universe_id
                WHERE d.user_id = ?
                ORDER BY d.updated_at DESC, d.id DESC
                """,
                (int(user_id),),
            )
            rows = cur.fetchall() or []
            cur.close()
        return [self._row(item) for item in rows]

    def get(self, user_id: int, deployment_id: int) -> dict:
        rows = [item for item in self.list(user_id) if int(item["id"]) == int(deployment_id)]
        if not rows:
            raise PortfolioDeploymentError("portfolio.deploymentNotFound")
        return rows[0]

    def list_plans(self, user_id: int, deployment_id: int, limit: int = 20) -> list[dict]:
        deployment = self.get(user_id, deployment_id)
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT * FROM qd_portfolio_rebalance_plans
                WHERE user_id = ? AND strategy_id = ?
                ORDER BY signal_time DESC, created_at DESC
                LIMIT ?
                """,
                (int(user_id), int(deployment["strategy_id"]), max(1, min(100, int(limit)))),
            )
            plans = [dict(row) for row in (cur.fetchall() or [])]
            for plan in plans:
                cur.execute(
                    """
                    SELECT id, symbol, side, action, quantity, reference_price,
                           estimated_notional, estimated_fee, current_weight,
                           target_weight, status, actual_quantity, actual_price,
                           pending_order_id, error_code, acknowledged_at
                    FROM qd_portfolio_rebalance_orders
                    WHERE plan_id = ? ORDER BY CASE WHEN side = 'sell' THEN 0 ELSE 1 END, symbol
                    """,
                    (plan["plan_id"],),
                )
                plan["orders"] = [dict(row) for row in (cur.fetchall() or [])]
                for key in ("target_weights_json", "current_weights_json", "diagnostics_json"):
                    value = plan.pop(key, {} if key != "diagnostics_json" else [])
                    if isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except Exception:
                            value = {} if key != "diagnostics_json" else []
                    plan[key.removesuffix("_json")] = value
            cur.close()
        return plans

    def acknowledge_order(self, user_id: int, deployment_id: int, order_id: int, payload: dict) -> dict:
        deployment = self.get(user_id, deployment_id)
        if deployment.get("execution_mode") != "notify_only":
            raise PortfolioDeploymentError("portfolio.manualAckNotifyOnly")
        outcome = str(payload.get("outcome") or "").strip().lower()
        if outcome not in {"executed", "skipped"}:
            raise PortfolioDeploymentError("portfolio.invalidAcknowledgement")
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT o.*, p.strategy_id, p.execution_mode
                FROM qd_portfolio_rebalance_orders o
                JOIN qd_portfolio_rebalance_plans p ON p.plan_id = o.plan_id
                WHERE o.id = ? AND p.user_id = ? AND p.strategy_id = ?
                FOR UPDATE
                """,
                (int(order_id), int(user_id), int(deployment["strategy_id"])),
            )
            order = cur.fetchone() or {}
            if not order:
                raise PortfolioDeploymentError("portfolio.rebalanceOrderNotFound")
            if str(order.get("status") or "") in {"user_executed", "user_skipped"}:
                db.rollback()
                return {"id": int(order_id), "status": order["status"]}
            if outcome == "skipped":
                cur.execute(
                    "UPDATE qd_portfolio_rebalance_orders SET status = 'user_skipped', acknowledged_at = NOW(), updated_at = NOW() WHERE id = ?",
                    (int(order_id),),
                )
            else:
                planned_quantity = float(order.get("quantity") or 0.0)
                quantity = float(payload.get("quantity") or planned_quantity)
                price = float(payload.get("price") or order.get("reference_price") or 0.0)
                if quantity <= 0 or quantity > planned_quantity + 1e-8 or price <= 0:
                    raise PortfolioDeploymentError("portfolio.invalidFill")
                symbol = str(order.get("symbol") or "").upper()
                cur.execute(
                    "SELECT quantity, average_price FROM qd_portfolio_deployment_positions WHERE deployment_id = ? AND symbol = ? FOR UPDATE",
                    (int(deployment_id), symbol),
                )
                position = cur.fetchone() or {}
                old_quantity = float(position.get("quantity") or 0.0)
                old_average = float(position.get("average_price") or 0.0)
                side = str(order.get("side") or "")
                if side == "sell" and quantity > old_quantity + 1e-8:
                    raise PortfolioDeploymentError("portfolio.fillExceedsPosition")
                new_quantity = old_quantity + quantity if side == "buy" else old_quantity - quantity
                new_average = (
                    ((old_quantity * old_average) + (quantity * price)) / new_quantity
                    if side == "buy" and new_quantity > 1e-12 else old_average
                )
                if new_quantity <= 1e-12:
                    cur.execute(
                        "DELETE FROM qd_portfolio_deployment_positions WHERE deployment_id = ? AND symbol = ?",
                        (int(deployment_id), symbol),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO qd_portfolio_deployment_positions
                          (deployment_id, symbol, quantity, average_price, updated_at)
                        VALUES (?, ?, ?, ?, NOW())
                        ON CONFLICT (deployment_id, symbol) DO UPDATE
                        SET quantity = EXCLUDED.quantity, average_price = EXCLUDED.average_price, updated_at = NOW()
                        """,
                        (int(deployment_id), symbol, new_quantity, new_average),
                    )
                fee_rate = float(order.get("estimated_fee") or 0.0) / max(float(order.get("estimated_notional") or 0.0), 1e-12)
                cash_delta = quantity * price * (-1.0 - fee_rate if side == "buy" else 1.0 - fee_rate)
                cur.execute(
                    "UPDATE qd_portfolio_deployments SET cash_balance = COALESCE(cash_balance, 0) + ?, updated_at = NOW() WHERE id = ? AND user_id = ?",
                    (cash_delta, int(deployment_id), int(user_id)),
                )
                cur.execute(
                    """
                    UPDATE qd_portfolio_rebalance_orders
                    SET status = 'user_executed', actual_quantity = ?, actual_price = ?,
                        acknowledged_at = NOW(), updated_at = NOW()
                    WHERE id = ?
                    """,
                    (quantity, price, int(order_id)),
                )
            cur.execute(
                """
                UPDATE qd_portfolio_rebalance_plans
                SET status = CASE WHEN NOT EXISTS (
                    SELECT 1 FROM qd_portfolio_rebalance_orders
                    WHERE plan_id = ? AND status NOT IN ('user_executed', 'user_skipped')
                ) THEN 'acknowledged' ELSE status END, updated_at = NOW()
                WHERE plan_id = ?
                """,
                (order["plan_id"], order["plan_id"]),
            )
            db.commit()
            cur.close()
        return {"id": int(order_id), "status": f"user_{outcome}"}

    def create(self, user_id: int, payload: dict) -> dict:
        source_id = _required_int(payload.get("sourceId") or payload.get("source_id"), "portfolio.sourceRequired")
        universe_id = _required_int(payload.get("universeId") or payload.get("universe_id"), "portfolio.universeRequired")
        execution_mode = str(payload.get("executionMode") or payload.get("execution_mode") or "notify_only").strip().lower()
        frequency = str(payload.get("rebalanceFrequency") or payload.get("rebalance_frequency") or "weekly").strip().lower()
        credential_id = int(payload.get("credentialId") or payload.get("credential_id") or 0)
        if execution_mode not in ALLOWED_EXECUTION_MODES:
            raise PortfolioDeploymentError("portfolio.invalidExecutionMode")
        if frequency not in ALLOWED_FREQUENCIES:
            raise PortfolioDeploymentError("portfolio.invalidRebalanceFrequency")
        if execution_mode == "live" and credential_id <= 0:
            raise PortfolioDeploymentError("portfolio.credentialRequiredForLive")

        source, universe, exchange_config = self._validate_links(
            user_id=user_id,
            source_id=source_id,
            universe_id=universe_id,
            credential_id=credential_id,
            execution_mode=execution_mode,
        )
        code = str(source.get("code") or "")
        validate_portfolio_strategy_code(code)
        name = str(payload.get("name") or source.get("name") or "").strip()[:255]
        if not name:
            raise PortfolioDeploymentError("portfolio.deploymentNameRequired")
        config = _deployment_config(payload)
        market = str(universe.get("market") or "Mixed")
        config["schedule_market"] = market
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                INSERT INTO qd_strategies_trading
                  (user_id, strategy_name, strategy_type, market_category,
                   execution_mode, status, symbol, timeframe, initial_capital,
                   leverage, market_type, exchange_config, trading_config,
                   strategy_mode, strategy_code, created_at, updated_at)
                VALUES (?, ?, 'PortfolioStrategy', ?, ?, 'stopped', ?, '1D', ?,
                        1, 'spot', ?, ?, 'portfolio', ?, NOW(), NOW())
                RETURNING id
                """,
                (
                    int(user_id), name, market, "live" if execution_mode == "live" else "signal",
                    f"universe:{universe_id}", float(config["initial_capital"]),
                    json.dumps(exchange_config, ensure_ascii=False),
                    json.dumps({
                        "source_id": source_id,
                        "universe_id": universe_id,
                        "rebalance_frequency": frequency,
                        "portfolio_config": config,
                    }, ensure_ascii=False),
                    code,
                ),
            )
            strategy_id = int((cur.fetchone() or {}).get("id") or 0)
            cur.execute(
                """
                INSERT INTO qd_portfolio_deployments
                  (user_id, strategy_id, source_id, universe_id, name,
                   execution_mode, credential_id, rebalance_frequency,
                   status, config_json, cash_balance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'stopped', ?::jsonb, ?, NOW(), NOW())
                RETURNING id
                """,
                (
                    int(user_id), strategy_id, source_id, universe_id, name,
                    execution_mode, credential_id, frequency,
                    json.dumps(config, ensure_ascii=False), float(config["initial_capital"]),
                ),
            )
            deployment_id = int((cur.fetchone() or {}).get("id") or 0)
            db.commit()
            cur.close()
        return self.get(user_id, deployment_id)

    def update(self, user_id: int, deployment_id: int, payload: dict) -> dict:
        current = self.get(user_id, deployment_id)
        if str(current.get("status") or "stopped").lower() == "running":
            raise PortfolioDeploymentError("portfolio.stopBeforeEdit")

        source_id = _required_int(
            payload.get("sourceId") or payload.get("source_id") or current.get("source_id"),
            "portfolio.sourceRequired",
        )
        universe_id = _required_int(
            payload.get("universeId") or payload.get("universe_id") or current.get("universe_id"),
            "portfolio.universeRequired",
        )
        execution_mode = str(
            payload.get("executionMode")
            or payload.get("execution_mode")
            or current.get("execution_mode")
            or "notify_only"
        ).strip().lower()
        frequency = str(
            payload.get("rebalanceFrequency")
            or payload.get("rebalance_frequency")
            or current.get("rebalance_frequency")
            or "weekly"
        ).strip().lower()
        credential_id = int(
            payload.get("credentialId")
            or payload.get("credential_id")
            or (current.get("credential_id") if execution_mode == "live" else 0)
            or 0
        )
        if execution_mode not in ALLOWED_EXECUTION_MODES:
            raise PortfolioDeploymentError("portfolio.invalidExecutionMode")
        if frequency not in ALLOWED_FREQUENCIES:
            raise PortfolioDeploymentError("portfolio.invalidRebalanceFrequency")
        if execution_mode == "live" and credential_id <= 0:
            raise PortfolioDeploymentError("portfolio.credentialRequiredForLive")

        source, universe, exchange_config = self._validate_links(
            user_id=user_id,
            source_id=source_id,
            universe_id=universe_id,
            credential_id=credential_id,
            execution_mode=execution_mode,
        )
        code = str(source.get("code") or "")
        validate_portfolio_strategy_code(code)
        name = str(payload.get("name") or current.get("name") or source.get("name") or "").strip()[:255]
        if not name:
            raise PortfolioDeploymentError("portfolio.deploymentNameRequired")

        merged_payload = {**(current.get("config") or {}), **payload}
        config = _deployment_config(merged_payload)
        market = str(universe.get("market") or "Mixed")
        config["schedule_market"] = market
        strategy_id = int(current.get("strategy_id") or 0)
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE qd_strategies_trading
                SET strategy_name = ?, market_category = ?, execution_mode = ?,
                    symbol = ?, timeframe = '1D', initial_capital = ?, leverage = 1,
                    market_type = 'spot', exchange_config = ?, trading_config = ?,
                    strategy_mode = 'portfolio', strategy_code = ?, updated_at = NOW()
                WHERE id = ? AND user_id = ?
                """,
                (
                    name,
                    market,
                    "live" if execution_mode == "live" else "signal",
                    f"universe:{universe_id}",
                    float(config["initial_capital"]),
                    json.dumps(exchange_config, ensure_ascii=False),
                    json.dumps({
                        "source_id": source_id,
                        "universe_id": universe_id,
                        "rebalance_frequency": frequency,
                        "portfolio_config": config,
                    }, ensure_ascii=False),
                    code,
                    strategy_id,
                    int(user_id),
                ),
            )
            cur.execute(
                """
                UPDATE qd_portfolio_deployments
                SET source_id = ?, universe_id = ?, name = ?, execution_mode = ?,
                    credential_id = ?, rebalance_frequency = ?, config_json = ?::jsonb,
                    cash_balance = CASE WHEN cash_balance IS NULL THEN ? ELSE cash_balance END,
                    last_error = '', updated_at = NOW()
                WHERE id = ? AND user_id = ?
                """,
                (
                    source_id,
                    universe_id,
                    name,
                    execution_mode,
                    credential_id,
                    frequency,
                    json.dumps(config, ensure_ascii=False),
                    float(config["initial_capital"]),
                    int(deployment_id),
                    int(user_id),
                ),
            )
            db.commit()
            cur.close()
        return self.get(user_id, deployment_id)

    def delete(self, user_id: int, deployment_id: int) -> dict:
        current = self.get(user_id, deployment_id)
        if str(current.get("status") or "stopped").lower() == "running":
            raise PortfolioDeploymentError("portfolio.stopBeforeDelete")
        strategy_id = int(current.get("strategy_id") or 0)
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "DELETE FROM qd_portfolio_deployments WHERE id = ? AND user_id = ?",
                (int(deployment_id), int(user_id)),
            )
            cur.execute(
                "DELETE FROM qd_strategies_trading WHERE id = ? AND user_id = ?",
                (strategy_id, int(user_id)),
            )
            db.commit()
            cur.close()
        return {"id": int(deployment_id), "strategy_id": strategy_id}

    def set_status(self, user_id: int, deployment_id: int, status: str) -> dict:
        clean = str(status or "").strip().lower()
        if clean not in {"running", "stopped"}:
            raise PortfolioDeploymentError("portfolio.invalidDeploymentStatus")
        current = self.get(user_id, deployment_id)
        next_run = datetime.utcnow() if clean == "running" else None
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE qd_portfolio_deployments
                SET status = ?, next_run_at = ?, last_error = '', updated_at = NOW()
                WHERE id = ? AND user_id = ?
                """,
                (clean, next_run, int(deployment_id), int(user_id)),
            )
            cur.execute(
                "UPDATE qd_strategies_trading SET status = ?, updated_at = NOW() WHERE id = ? AND user_id = ?",
                (clean, int(current["strategy_id"]), int(user_id)),
            )
            db.commit()
            cur.close()
        return self.get(user_id, deployment_id)

    def mark_run(self, user_id: int, deployment_id: int, *, error: str = "") -> None:
        deployment = self.get(user_id, deployment_id)
        try:
            next_run = next_rebalance_run(
                (deployment.get("config") or {}).get("schedule_market") or deployment.get("universe_market") or "USStock",
                deployment["rebalance_frequency"],
                data_delay_minutes=int((deployment.get("config") or {}).get("data_delay_minutes") or 15),
            )
        except Exception:
            next_run = None
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE qd_portfolio_deployments
                SET last_run_at = NOW(), next_run_at = ?, last_error = ?,
                    status = CASE WHEN ? = '' THEN status ELSE 'error' END,
                    updated_at = NOW()
                WHERE id = ? AND user_id = ?
                """,
                (next_run, str(error or "")[:500], str(error or ""), int(deployment_id), int(user_id)),
            )
            db.commit()
            cur.close()

    def run_now(self, user_id: int, deployment_id: int) -> dict:
        deployment = self.get(user_id, deployment_id)
        try:
            result = PortfolioDeploymentRunner(self).run(user_id=user_id, deployment=deployment)
            self.mark_run(user_id, deployment_id)
            return result
        except PortfolioDeploymentDeferred as exc:
            self.defer_run(user_id, deployment_id, code=exc.code)
            raise
        except Exception as exc:
            self.mark_run(user_id, deployment_id, error=str(exc))
            raise

    @staticmethod
    def defer_run(user_id: int, deployment_id: int, *, code: str) -> None:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                UPDATE qd_portfolio_deployments
                SET next_run_at = NOW() + INTERVAL '15 minutes', last_error = ?, updated_at = NOW()
                WHERE id = ? AND user_id = ?
                """,
                (str(code or "")[:500], int(deployment_id), int(user_id)),
            )
            db.commit()
            cur.close()

    @staticmethod
    def _validate_links(
        *,
        user_id: int,
        source_id: int,
        universe_id: int,
        credential_id: int,
        execution_mode: str,
    ) -> tuple[dict, dict, dict]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                "SELECT id, name, code, asset_type FROM qd_script_sources WHERE id = ? AND user_id = ?",
                (source_id, int(user_id)),
            )
            source = cur.fetchone() or {}
            cur.execute(
                "SELECT id, code, market FROM qd_universes WHERE id = ? AND (user_id IS NULL OR user_id = ?)",
                (universe_id, int(user_id)),
            )
            universe = cur.fetchone() or {}
            if str(universe.get("market") or "") == "Mixed":
                cur.execute(
                    """
                    SELECT DISTINCT market FROM qd_universe_members
                    WHERE universe_id = ? AND valid_from <= CURRENT_DATE
                      AND (valid_to IS NULL OR valid_to > CURRENT_DATE)
                      AND market <> ''
                    """,
                    (universe_id,),
                )
                member_markets = {str(row.get("market") or "") for row in (cur.fetchall() or [])}
                if len(member_markets) == 1:
                    universe["market"] = member_markets.pop()
            credential = {}
            if credential_id > 0:
                cur.execute(
                    "SELECT id, exchange_id FROM qd_exchange_credentials WHERE id = ? AND user_id = ?",
                    (credential_id, int(user_id)),
                )
                credential = cur.fetchone() or {}
            cur.close()
        if not source or source.get("asset_type") != "portfolio_strategy":
            raise PortfolioDeploymentError("portfolio.invalidSource")
        if not universe:
            raise PortfolioDeploymentError("portfolio.universeNotFound")
        if str(universe.get("market") or "") not in SUPPORTED_SCHEDULE_MARKETS:
            raise PortfolioDeploymentError("portfolio.marketCalendarUnsupported")
        if execution_mode == "live" and not credential:
            raise PortfolioDeploymentError("portfolio.credentialNotFound")
        if execution_mode == "live" and (
            str(universe.get("market") or "") != "USStock"
            or str(credential.get("exchange_id") or "").lower() != "alpaca"
        ):
            raise PortfolioDeploymentError("portfolio.liveBrokerUnsupported")
        exchange_config = {
            "credential_id": credential_id,
            "exchange_id": str(credential.get("exchange_id") or ""),
        } if credential_id > 0 else {}
        return source, universe, exchange_config

    @staticmethod
    def _row(row: dict) -> dict:
        out = dict(row)
        raw = out.get("config_json")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        out["config"] = raw if isinstance(raw, dict) else {}
        out.pop("config_json", None)
        return out


class PortfolioDeploymentRunner:
    """Evaluate one deployment and dispatch its broker-neutral rebalance plan."""

    def __init__(self, deployment_service: PortfolioDeploymentService):
        self.deployment_service = deployment_service

    def run(self, *, user_id: int, deployment: dict) -> dict:
        from app.services.ai_decision import LiveAIDecisionClient
        from app.services.exchange_execution import resolve_exchange_config
        from app.services.live_trading.factory import create_client
        from app.services.portfolio_backtest_service import PortfolioBacktestService
        from app.services.portfolio_rebalance import (
            PortfolioRebalanceDispatcher,
            PortfolioRebalancePlanner,
            RebalancePlanConfig,
        )
        from app.services.universe import get_universe_service

        config = deployment.get("config") or {}
        now = datetime.utcnow()
        completed_session = latest_completed_session(
            config.get("schedule_market") or deployment.get("universe_market") or "USStock",
            now,
            data_delay_minutes=int(config.get("data_delay_minutes") or 15),
        )
        universe_service = get_universe_service()
        members = universe_service.resolve_members(user_id, int(deployment["universe_id"]), as_of=now.date())
        if not members:
            raise PortfolioDeploymentError("portfolio.universeHasNoData")

        current_quantities: dict[str, float] = {}
        stored_cash = deployment.get("cash_balance")
        cash = float(stored_cash if stored_cash is not None else config.get("initial_capital") or 10_000)
        credential_id = int(deployment.get("credential_id") or 0)
        if credential_id > 0:
            exchange_config = resolve_exchange_config({"credential_id": credential_id}, user_id=user_id)
            client = create_client(exchange_config, market_type="spot")
            account = client.get_account_summary()
            if not account or account.get("success") is False:
                raise PortfolioDeploymentError("portfolio.accountSnapshotFailed")
            cash = float(account.get("cash") or 0.0)
            for row in client.get_positions() or []:
                symbol = str(row.get("symbol") or "").strip().upper()
                quantity = float(row.get("quantity") or row.get("qty") or 0.0)
                if symbol and quantity > 0:
                    current_quantities[symbol] = quantity
            known = {str(item.get("symbol") or "").upper() for item in members}
            for symbol in current_quantities:
                if symbol not in known:
                    members.append({
                        "symbol": symbol,
                        "market": deployment.get("universe_market") or "USStock",
                        "market_type": "spot",
                        "exchange_id": str(exchange_config.get("exchange_id") or ""),
                    })
        else:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    "SELECT symbol, quantity FROM qd_portfolio_deployment_positions WHERE deployment_id = ?",
                    (int(deployment["id"]),),
                )
                current_quantities = {
                    str(row.get("symbol") or "").upper(): float(row.get("quantity") or 0.0)
                    for row in (cur.fetchall() or [])
                    if float(row.get("quantity") or 0.0) > 1e-12
                }
                cur.close()

        fetcher = PortfolioBacktestService()
        frames, skipped = fetcher._fetch_panel(members, now - timedelta(days=500), now)
        eligible = {
            str(item.get("symbol") or "").strip().upper()
            for item in universe_service.resolve_members(user_id, int(deployment["universe_id"]), as_of=now.date())
        }
        panel = {symbol: frame for symbol, frame in frames.items() if symbol in eligible}
        if not panel:
            raise PortfolioDeploymentError("portfolio.noMarketData")
        prices = {
            symbol: float(frame["close"].iloc[-1])
            for symbol, frame in frames.items()
            if frame is not None and not frame.empty
        }
        signal_time = max(frame.index[-1].to_pydatetime() for frame in panel.values())
        if signal_time.date() < completed_session.date():
            raise PortfolioDeploymentDeferred("portfolio.marketDataNotReady")

        on_init, on_rebalance = compile_portfolio_strategy_handlers(str(deployment.get("source_code") or ""))
        context = PortfolioContext(
            universe=eligible,
            params=config.get("params") or {},
            constraints=PortfolioConstraints(
                long_only=True,
                max_weight=float(config.get("max_weight") or 0.1),
                gross_limit=1.0,
                net_limit=1.0,
            ),
            runtime={"mode": "live", "deployment_id": int(deployment["id"])},
        )
        context.bind_ai(LiveAIDecisionClient(
            user_id=user_id,
            strategy_id=int(deployment["strategy_id"]),
            strategy_run_id=0,
            model_config=config.get("ai_model_config") or {},
            runtime=context.runtime,
        ))
        if callable(on_init):
            on_init(context)
        context.reset_rebalance(signal_time)
        on_rebalance(context, panel)
        targets = context.consume_plan()
        snapshot = universe_service.create_snapshot(user_id, int(deployment["universe_id"]), as_of=now.date())
        instrument_contexts = {
            str(item.get("symbol") or "").upper(): item
            for item in members
        }
        plan = PortfolioRebalancePlanner().build(
            portfolio_id=f"deployment:{int(deployment['id'])}",
            universe_id=int(deployment["universe_id"]),
            target_weights=targets.weights,
            current_quantities=current_quantities,
            prices=prices,
            cash=cash,
            signal_time=signal_time,
            execution_mode=str(deployment["execution_mode"]),
            config=RebalancePlanConfig(
                commission_rate=float(config.get("commission_rate") or 0.0005),
                min_trade_value=float(config.get("min_trade_value") or 0.0),
                allow_fractional=bool(config.get("allow_fractional", True)),
                max_weight=float(config.get("max_weight") or 0.1),
            ),
            instrument_contexts=instrument_contexts,
            universe_snapshot_id=str(snapshot.get("snapshot_id") or ""),
        )
        dispatched = PortfolioRebalanceDispatcher().dispatch(
            user_id=user_id,
            strategy_id=int(deployment["strategy_id"]),
            strategy_run_id=0,
            plan=plan,
            notification_channels=config.get("notification_channels") or ["browser"],
        )
        dispatched["logs"] = context.flush_logs()
        dispatched["symbols_skipped"] = skipped
        dispatched["ai_decision_calls"] = int(context.runtime.get("ai_decision_calls") or 0)
        return dispatched


def _deployment_config(payload: dict) -> dict:
    initial_capital = max(10.0, float(payload.get("initialCapital") or payload.get("initial_capital") or 10_000))
    max_weight = float(payload.get("maxWeight") or payload.get("max_weight") or 0.1)
    if not 0 < max_weight <= 1:
        raise PortfolioDeploymentError("portfolio.invalidMaxWeight")
    return {
        "initial_capital": initial_capital,
        "commission_rate": max(0.0, float(payload.get("commission") or payload.get("commission_rate") or 0.0005)),
        "max_weight": max_weight,
        "min_trade_value": max(0.0, float(payload.get("minTradeValue") or payload.get("min_trade_value") or 0)),
        "allow_fractional": bool(payload.get("allowFractional", payload.get("allow_fractional", True))),
        "params": payload.get("params") if isinstance(payload.get("params"), dict) else {},
        "notification_channels": payload.get("notificationChannels") or payload.get("notification_channels") or ["browser"],
        "data_delay_minutes": max(0, min(240, int(payload.get("dataDelayMinutes") or payload.get("data_delay_minutes") or 15))),
    }


def _required_int(value: Any, code: str) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise PortfolioDeploymentError(code) from exc
    if parsed <= 0:
        raise PortfolioDeploymentError(code)
    return parsed


_service: Optional[PortfolioDeploymentService] = None


def get_portfolio_deployment_service() -> PortfolioDeploymentService:
    global _service
    if _service is None:
        _service = PortfolioDeploymentService()
    return _service


class PortfolioDeploymentScheduler:
    """Claim and run due portfolio deployments in a single process."""

    def __init__(self, interval_seconds: float = 60.0):
        self.interval_seconds = max(10.0, float(interval_seconds or 60.0))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="PortfolioDeploymentScheduler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for user_id, deployment_id in self._claim_due():
                    try:
                        get_portfolio_deployment_service().run_now(user_id, deployment_id)
                    except Exception:
                        continue
            finally:
                self._stop.wait(self.interval_seconds)

    @staticmethod
    def _claim_due() -> list[tuple[int, int]]:
        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT id, user_id
                FROM qd_portfolio_deployments
                WHERE status = 'running' AND next_run_at IS NOT NULL AND next_run_at <= NOW()
                ORDER BY next_run_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 5
                """
            )
            rows = cur.fetchall() or []
            ids = [int(row["id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                cur.execute(
                    f"UPDATE qd_portfolio_deployments SET next_run_at = NOW() + INTERVAL '10 minutes' WHERE id IN ({placeholders})",
                    tuple(ids),
                )
            db.commit()
            cur.close()
        return [(int(row["user_id"]), int(row["id"])) for row in rows]


_scheduler: Optional[PortfolioDeploymentScheduler] = None


def start_portfolio_deployment_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = PortfolioDeploymentScheduler()
    _scheduler.start()
