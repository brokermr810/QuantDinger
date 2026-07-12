"""Built-in executor strategy routes."""

from __future__ import annotations

import traceback

from flask import g, jsonify, request

from app.routes.strategy_blueprint import strategy_blp
from app.routes.strategy_services import get_strategy_service
from app.services.strategy_runtime.executors import (
    build_executor_strategy_payload,
    executor_templates,
    preview_executor,
)
from app.utils.auth import login_required
from app.utils.logger import get_logger


logger = get_logger(__name__)


@strategy_blp.route("/strategies/executors/templates", methods=["GET"])
@login_required
def get_executor_templates():
    try:
        return jsonify({"code": 1, "msg": "success", "data": executor_templates()})
    except Exception as exc:
        logger.error("get_executor_templates failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": {"items": []}}), 500


@strategy_blp.route("/strategies/executors/preview", methods=["POST"])
@login_required
def preview_executor_strategy():
    try:
        payload = request.get_json() or {}
        return jsonify({"code": 1, "msg": "success", "data": preview_executor(payload)})
    except Exception as exc:
        logger.error("preview_executor_strategy failed: %s", exc)
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 400


@strategy_blp.route("/strategies/executors/generate", methods=["POST"])
@login_required
def generate_executor_strategy():
    try:
        payload = request.get_json() or {}
        user_id = int(getattr(g, "user_id", None) or payload.get("user_id") or 1)
        strategy_payload = build_executor_strategy_payload(payload, user_id=user_id)
        return jsonify({
            "code": 1,
            "msg": "success",
            "data": {
                "strategy_name": strategy_payload["strategy_name"],
                "strategy_code": strategy_payload["strategy_code"],
                "market_category": strategy_payload["market_category"],
                "symbol": strategy_payload["symbol"],
                "timeframe": strategy_payload["timeframe"],
                "market_type": strategy_payload["market_type"],
                "trade_direction": strategy_payload["trade_direction"],
                "leverage": strategy_payload["leverage"],
                "initial_capital": strategy_payload["initial_capital"],
                "trading_config": strategy_payload["trading_config"],
            },
        })
    except Exception as exc:
        logger.error("generate_executor_strategy failed: %s", exc)
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 400


@strategy_blp.route("/strategies/executors/create", methods=["POST"])
@login_required
def create_executor_strategy():
    try:
        payload = request.get_json() or {}
        user_id = int(getattr(g, "user_id", None) or payload.get("user_id") or 1)
        strategy_payload = build_executor_strategy_payload(payload, user_id=user_id)
        strategy_id = get_strategy_service().create_strategy(strategy_payload)
        strategy = get_strategy_service().get_strategy(strategy_id, user_id=user_id) or {"id": strategy_id}
        return jsonify({"code": 1, "msg": "success", "data": {"id": strategy_id, "strategy": strategy}})
    except Exception as exc:
        logger.error("create_executor_strategy failed: %s", exc)
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 400
