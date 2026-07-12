"""Script source library API routes."""

from flask import g, jsonify, request

from app.routes.strategy_blueprint import strategy_blp
from app.services.script_source import get_script_source_service
from app.utils.auth import login_required
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _source_payload() -> dict:
    payload = request.get_json(silent=True) or {}
    return payload if isinstance(payload, dict) else {}


def _mask_hidden_source(item: dict | None) -> dict | None:
    if not isinstance(item, dict):
        return item
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    hidden = bool(metadata.get("code_hidden") or metadata.get("hide_code") or False)
    if not hidden:
        return item
    out = dict(item)
    out["code"] = ""
    out["code_hidden"] = 1
    return out


def _is_hidden_source(item: dict | None) -> bool:
    if not isinstance(item, dict):
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return bool(item.get("code_hidden") or metadata.get("code_hidden") or metadata.get("hide_code"))


def _mask_hidden_version(item: dict | None, *, hidden: bool) -> dict | None:
    if not isinstance(item, dict) or not hidden:
        return item
    out = dict(item)
    out["code"] = ""
    out["code_hidden"] = 1
    out["hidden_source"] = 1
    out["restore_disabled"] = 1
    return out


def _has_successful_script_backtest(user_id: int, source_id: int) -> bool:
    from app.services.unified_backtest import UnifiedBacktestService
    rows = UnifiedBacktestService().list_runs(
        user_id=int(user_id),
        asset_type="script",
        asset_id=int(source_id),
        status="success",
        limit=1,
    )
    return bool(rows)


@strategy_blp.route("/strategies/script-templates", methods=["GET"])
@login_required
def list_script_templates():
    try:
        items = get_script_source_service().list_templates()
        return jsonify({"code": 1, "msg": "success", "data": {"items": items, "templates": items}})
    except Exception as exc:
        logger.error("list_script_templates failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": {"items": [], "templates": []}}), 500


@strategy_blp.route("/strategies/script-sources", methods=["GET"])
@login_required
def list_script_sources():
    try:
        items = [_mask_hidden_source(item) for item in get_script_source_service().list_sources(g.user_id)]
        return jsonify({"code": 1, "msg": "success", "data": {"items": items, "sources": items}})
    except Exception as exc:
        logger.error("list_script_sources failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": {"items": []}}), 500


@strategy_blp.route("/strategies/script-sources/detail", methods=["GET"])
@login_required
def get_script_source_detail():
    try:
        source_id = int(request.args.get("id") or request.args.get("sourceId") or 0)
        if not source_id:
            return jsonify({"code": 0, "msg": "source id is required", "data": None}), 400
        item = _mask_hidden_source(get_script_source_service().get_source(source_id, user_id=g.user_id))
        if not item:
            return jsonify({"code": 0, "msg": "script source not found", "data": None}), 404
        return jsonify({"code": 1, "msg": "success", "data": item})
    except Exception as exc:
        logger.error("get_script_source_detail failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@strategy_blp.route("/strategies/script-sources/create", methods=["POST"])
@login_required
def create_script_source():
    try:
        payload = _source_payload()
        payload["user_id"] = g.user_id
        if not str(payload.get("code") or payload.get("strategy_code") or "").strip():
            return jsonify({"code": 0, "msg": "script code is required", "data": None}), 400
        source_id = get_script_source_service().create_source(payload)
        item = _mask_hidden_source(get_script_source_service().get_source(source_id, user_id=g.user_id))
        return jsonify({"code": 1, "msg": "success", "data": item})
    except Exception as exc:
        logger.error("create_script_source failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@strategy_blp.route("/strategies/script-sources/update", methods=["PUT", "POST"])
@login_required
def update_script_source():
    try:
        source_id = int(request.args.get("id") or request.args.get("sourceId") or 0)
        payload = _source_payload()
        source_id = int(payload.get("id") or payload.get("sourceId") or source_id or 0)
        if not source_id:
            return jsonify({"code": 0, "msg": "source id is required", "data": None}), 400
        ok = get_script_source_service().update_source(source_id, g.user_id, payload)
        if not ok:
            return jsonify({"code": 0, "msg": "script source not found", "data": None}), 404
        item = _mask_hidden_source(get_script_source_service().get_source(source_id, user_id=g.user_id))
        return jsonify({"code": 1, "msg": "success", "data": item})
    except Exception as exc:
        logger.error("update_script_source failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@strategy_blp.route("/strategies/script-sources/delete", methods=["DELETE", "POST"])
@login_required
def delete_script_source():
    try:
        payload = _source_payload()
        source_id = int(payload.get("id") or payload.get("sourceId") or request.args.get("id") or 0)
        if not source_id:
            return jsonify({"code": 0, "msg": "source id is required", "data": None}), 400
        ok = get_script_source_service().delete_source(source_id, g.user_id)
        if not ok:
            return jsonify({"code": 0, "msg": "script source not found", "data": None}), 404
        return jsonify({"code": 1, "msg": "success", "data": {"id": source_id}})
    except Exception as exc:
        logger.error("delete_script_source failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@strategy_blp.route("/strategies/script-sources/versions", methods=["GET"])
@login_required
def list_script_source_versions():
    try:
        source_id = int(request.args.get("sourceId") or request.args.get("source_id") or request.args.get("id") or 0)
        if not source_id:
            return jsonify({"code": 0, "msg": "source id is required", "data": []}), 400
        ok, rows = get_script_source_service().list_versions(source_id, g.user_id)
        if not ok:
            return jsonify({"code": 0, "msg": "script source not found", "data": []}), 404
        source = get_script_source_service().get_source(source_id, user_id=g.user_id)
        hidden = _is_hidden_source(source)
        safe_rows = [_mask_hidden_version(row, hidden=hidden) for row in rows]
        return jsonify({"code": 1, "msg": "success", "data": safe_rows})
    except Exception as exc:
        logger.error("list_script_source_versions failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": []}), 500


@strategy_blp.route("/strategies/script-sources/versions/<int:version_id>", methods=["GET"])
@login_required
def get_script_source_version(version_id: int):
    try:
        item = get_script_source_service().get_version(version_id, g.user_id)
        if not item:
            return jsonify({"code": 0, "msg": "version not found", "data": None}), 404
        source_id = int(item.get("source_id") or 0)
        source = get_script_source_service().get_source(source_id, user_id=g.user_id) if source_id else None
        return jsonify({"code": 1, "msg": "success", "data": _mask_hidden_version(item, hidden=_is_hidden_source(source))})
    except Exception as exc:
        logger.error("get_script_source_version failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@strategy_blp.route("/strategies/script-sources/versions/restore", methods=["POST"])
@login_required
def restore_script_source_version():
    try:
        payload = _source_payload()
        version_id = int(payload.get("versionId") or payload.get("version_id") or 0)
        if not version_id:
            return jsonify({"code": 0, "msg": "version id is required", "data": None}), 400
        version = get_script_source_service().get_version(version_id, g.user_id)
        if not version:
            return jsonify({"code": 0, "msg": "version not found", "data": None}), 404
        source_id = int(version.get("source_id") or 0)
        source = get_script_source_service().get_source(source_id, user_id=g.user_id) if source_id else None
        if _is_hidden_source(source):
            return jsonify({
                "code": 0,
                "msg": "Hidden-source script versions cannot be viewed or restored.",
                "data": {"code_hidden": 1, "source_id": source_id},
            }), 403
        item = get_script_source_service().restore_version(version_id, g.user_id)
        if not item:
            return jsonify({"code": 0, "msg": "version not found", "data": None}), 404
        return jsonify({"code": 1, "msg": "success", "data": _mask_hidden_source(item)})
    except Exception as exc:
        logger.error("restore_script_source_version failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500


@strategy_blp.route("/strategies/script-sources/publish", methods=["POST"])
@login_required
def publish_script_source():
    try:
        payload = _source_payload()
        source_id = int(payload.get("sourceId") or payload.get("source_id") or payload.get("id") or 0)
        if not source_id:
            return jsonify({"code": 0, "msg": "source id is required", "data": None}), 400
        source = get_script_source_service().get_source(source_id, user_id=g.user_id)
        if not source:
            return jsonify({"code": 0, "msg": "script source not found", "data": None}), 404

        from app.routes.strategy import _validate_strategy_code_internal
        validation = _validate_strategy_code_internal(source.get("code") or "")
        if not validation.get("success"):
            return jsonify({"code": 0, "msg": validation.get("message") or "Code verification failed", "data": validation}), 400

        if not _has_successful_script_backtest(g.user_id, source_id):
            return jsonify({
                "code": 0,
                "msg": "This script strategy must have at least one successful backtest before publishing.",
                "data": {"source_id": source_id, "requires_backtest": True},
            }), 400

        user_role = getattr(g, "user_role", "user")
        is_admin = user_role == "admin"
        from app.services.community_service import get_community_service
        ok, msg, data = get_community_service().publish_script_template_from_strategy(
            user_id=g.user_id,
            strategy_id=0,
            code=source.get("code") or "",
            name=(payload.get("name") or source.get("name") or "").strip(),
            description=(payload.get("description") or source.get("description") or "").strip(),
            pricing_type=(payload.get("pricingType") or payload.get("pricing_type") or "free").strip() or "free",
            price=payload.get("price") or 0,
            vip_free=bool(payload.get("vipFree") or payload.get("vip_free") or False),
            code_hidden=bool(payload.get("codeHidden") or payload.get("code_hidden") or payload.get("hideCode") or False),
            is_admin=is_admin,
            existing_indicator_id=int(payload.get("indicatorId") or payload.get("indicator_id") or 0),
            source_id=source_id,
        )
        if data is not None:
            data["source_id"] = source_id
        if not ok:
            return jsonify({"code": 0, "msg": msg, "data": data}), 400
        return jsonify({"code": 1, "msg": "success", "data": data})
    except Exception as exc:
        logger.error("publish_script_source failed: %s", exc)
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 500
