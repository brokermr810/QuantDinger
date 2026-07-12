"""Portfolio strategy deployment lifecycle APIs."""

from flask import g, jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.services.portfolio_deployment import (
    PortfolioDeploymentError,
    get_portfolio_deployment_service,
)
from app.utils.auth import login_required
from app.utils.logger import get_logger


logger = get_logger(__name__)
portfolio_deployment_blp = Blueprint("portfolio_deployment", __name__)


def _success(data=None, status: int = 200):
    return jsonify({"code": 1, "msg": "success", "data": data}), status


def _failure(exc: PortfolioDeploymentError):
    return jsonify({"code": 0, "msg": exc.code, "data": None}), 400


@portfolio_deployment_blp.route("", methods=["GET"])
@login_required
def list_deployments():
    try:
        return _success(get_portfolio_deployment_service().list(g.user_id))
    except Exception:
        logger.exception("list portfolio deployments failed")
        return jsonify({"code": 0, "msg": "portfolio.deploymentListFailed", "data": None}), 500


@portfolio_deployment_blp.route("", methods=["POST"])
@login_required
def create_deployment():
    try:
        return _success(
            get_portfolio_deployment_service().create(g.user_id, request.get_json(silent=True) or {}),
            201,
        )
    except PortfolioDeploymentError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("create portfolio deployment failed")
        return jsonify({"code": 0, "msg": "portfolio.deploymentCreateFailed", "data": None}), 500


@portfolio_deployment_blp.route("/<int:deployment_id>", methods=["GET"])
@login_required
def get_deployment(deployment_id: int):
    try:
        return _success(get_portfolio_deployment_service().get(g.user_id, deployment_id))
    except PortfolioDeploymentError as exc:
        return _failure(exc)


@portfolio_deployment_blp.route("/<int:deployment_id>", methods=["PUT"])
@login_required
def update_deployment(deployment_id: int):
    try:
        return _success(get_portfolio_deployment_service().update(
            g.user_id, deployment_id, request.get_json(silent=True) or {}
        ))
    except PortfolioDeploymentError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("update portfolio deployment failed")
        return jsonify({"code": 0, "msg": "portfolio.deploymentUpdateFailed", "data": None}), 500


@portfolio_deployment_blp.route("/<int:deployment_id>", methods=["DELETE"])
@login_required
def delete_deployment(deployment_id: int):
    try:
        return _success(get_portfolio_deployment_service().delete(g.user_id, deployment_id))
    except PortfolioDeploymentError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("delete portfolio deployment failed")
        return jsonify({"code": 0, "msg": "portfolio.deploymentDeleteFailed", "data": None}), 500


@portfolio_deployment_blp.route("/<int:deployment_id>/plans", methods=["GET"])
@login_required
def list_deployment_plans(deployment_id: int):
    try:
        return _success(get_portfolio_deployment_service().list_plans(
            g.user_id, deployment_id, request.args.get("limit", 20, type=int)
        ))
    except PortfolioDeploymentError as exc:
        return _failure(exc)


@portfolio_deployment_blp.route("/<int:deployment_id>/orders/<int:order_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge_deployment_order(deployment_id: int, order_id: int):
    try:
        return _success(get_portfolio_deployment_service().acknowledge_order(
            g.user_id, deployment_id, order_id, request.get_json(silent=True) or {}
        ))
    except PortfolioDeploymentError as exc:
        return _failure(exc)


@portfolio_deployment_blp.route("/<int:deployment_id>/start", methods=["POST"])
@login_required
def start_deployment(deployment_id: int):
    try:
        return _success(get_portfolio_deployment_service().set_status(g.user_id, deployment_id, "running"))
    except PortfolioDeploymentError as exc:
        return _failure(exc)


@portfolio_deployment_blp.route("/<int:deployment_id>/stop", methods=["POST"])
@login_required
def stop_deployment(deployment_id: int):
    try:
        return _success(get_portfolio_deployment_service().set_status(g.user_id, deployment_id, "stopped"))
    except PortfolioDeploymentError as exc:
        return _failure(exc)


@portfolio_deployment_blp.route("/<int:deployment_id>/run", methods=["POST"])
@login_required
def run_deployment(deployment_id: int):
    try:
        return _success(get_portfolio_deployment_service().run_now(g.user_id, deployment_id))
    except PortfolioDeploymentError as exc:
        return _failure(exc)
    except Exception:
        logger.exception("run portfolio deployment failed")
        return jsonify({"code": 0, "msg": "portfolio.deploymentRunFailed", "data": None}), 500
