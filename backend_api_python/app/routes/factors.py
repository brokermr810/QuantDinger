"""Factor catalog and research APIs."""

from flask import jsonify, request

from app.openapi.blueprint import HumanBlueprint as Blueprint
from app.services.factors import FactorError, get_factor, list_factors
from app.services.factors.research import information_coefficient, quantile_returns, winsorize_zscore
from app.utils.auth import login_required
from app.utils.logger import get_logger


logger = get_logger(__name__)
factors_blp = Blueprint("factors", __name__)


@factors_blp.route("", methods=["GET"])
@login_required
def factor_catalog():
    try:
        data = list_factors(
            category=str(request.args.get("category") or "").strip(),
            factor_type=str(request.args.get("type") or request.args.get("factor_type") or "").strip(),
        )
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception:
        logger.exception("factor catalog failed")
        return jsonify({"code": 0, "msg": "factor.listFailed", "data": None}), 500


@factors_blp.route("/<string:factor_id>", methods=["GET"])
@login_required
def factor_detail(factor_id: str):
    try:
        return jsonify({"code": 1, "msg": "success", "data": get_factor(factor_id).metadata()})
    except FactorError as exc:
        return jsonify({"code": 0, "msg": exc.code, "data": None}), 404


@factors_blp.route("/research", methods=["POST"])
@login_required
def factor_research():
    try:
        payload = request.get_json(silent=True) or {}
        scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
        returns = payload.get("forwardReturns") or payload.get("forward_returns") or {}
        if not isinstance(returns, dict):
            returns = {}
        normalized = winsorize_zscore(scores)
        data = {
            "normalizedScores": normalized,
            "statistics": information_coefficient(normalized, returns),
            "quantileReturns": quantile_returns(
                normalized,
                returns,
                quantiles=int(payload.get("quantiles") or 5),
            ),
        }
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception:
        logger.exception("factor research failed")
        return jsonify({"code": 0, "msg": "factor.researchFailed", "data": None}), 500
