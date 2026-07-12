"""Unified strategy workbench asset routes."""

from flask import g, jsonify, request

from app.routes.strategy_blueprint import strategy_blp
from app.services.strategy_assets import get_strategy_asset_service
from app.utils.auth import login_required
from app.utils.logger import get_logger

logger = get_logger(__name__)


@strategy_blp.route("/strategy-assets", methods=["GET"])
@login_required
def list_strategy_assets():
    """Return executable script strategy assets."""
    try:
        asset_type = str(request.args.get("type") or request.args.get("assetType") or "").strip().lower()
        keyword = str(request.args.get("q") or request.args.get("keyword") or "").strip().lower()
        items = get_strategy_asset_service().list_assets(int(g.user_id))
        if asset_type:
            items = [item for item in items if str(item.get("asset_type") or "").lower() == asset_type]
        if keyword:
            items = [
                item for item in items
                if keyword in str(item.get("name") or "").lower()
                or keyword in str(item.get("description") or "").lower()
            ]
        counts = {
            "all": len(items),
            "indicator": 0,
            "script": sum(1 for item in items if item.get("asset_type") == "script"),
            "portfolio_strategy": sum(1 for item in items if item.get("asset_type") == "portfolio_strategy"),
            "bot": sum(1 for item in items if item.get("asset_type") == "bot"),
        }
        return jsonify({"code": 1, "msg": "success", "data": {"items": items, "counts": counts}})
    except Exception as exc:
        logger.error("list_strategy_assets failed: %s", exc, exc_info=True)
        return jsonify({"code": 0, "msg": str(exc), "data": {"items": [], "counts": {}}}), 500
