"""
Indicator APIs (local-first).

These endpoints are used by the frontend `/indicator-analysis` page.
In the original architecture, the frontend called PHP endpoints like:
`/addons/quantdinger/indicator/getIndicators`.

For local mode, we expose Python equivalents under `/api/indicator/*`.
"""

from __future__ import annotations

import json
import os
import re
import time
import traceback
from typing import Any, Dict, List
from flask import Response, g, jsonify, request
from app.openapi.blueprint import HumanBlueprint as Blueprint

from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.services.ai_generation_contracts import (
    INDICATOR_GENERATION_CONTRACT,
    INDICATOR_REPAIR_REQUIREMENTS,
)
from app.services.indicator_workspace import is_indicator_ide_listable, resolve_indicator_asset_type
from app.services.indicator_versions import (
    ensure_indicator_version_schema,
    get_version as get_indicator_code_version,
    insert_indicator_version,
    list_versions as list_indicator_code_versions,
    restore_version as restore_indicator_code_version,
)
from app.utils.auth import login_required
from app.services.indicator_params import IndicatorParamsParser
from app.services.indicator_validation import (
    generate_mock_df,
    indicator_debug_summary,
    merge_indicator_params,
    validate_indicator_code,
)
from app.services.indicator_translator import (
    translate_indicator,
    SUPPORTED_LANGUAGES as _SUPPORTED_LANGUAGES_FOR_TRANSLATE,
)
import requests

logger = get_logger(__name__)

indicator_blp = Blueprint("indicator", __name__)


def _sse_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _now_ts() -> int:
    return int(time.time())


def _extract_indicator_meta_from_code(code: str) -> Dict[str, str]:
    """
    Extract indicator name/description from python code.
    Expected variables:
      my_indicator_name = "..."
      my_indicator_description = "..."
    """
    if not code or not isinstance(code, str):
        return {"name": "", "description": ""}

    # Simple assignment capture for single/double quoted strings.
    name_match = re.search(r'^\s*my_indicator_name\s*=\s*([\'"])(.*?)\1\s*$', code, re.MULTILINE)
    desc_match = re.search(r'^\s*my_indicator_description\s*=\s*([\'"])(.*?)\1\s*$', code, re.MULTILINE)

    name = (name_match.group(2).strip() if name_match else "")[:100]
    description = (desc_match.group(2).strip() if desc_match else "")[:500]
    return {"name": name, "description": description}


def _ensure_indicator_version_schema(cur) -> None:
    ensure_indicator_version_schema(cur)


def _insert_indicator_version(cur, indicator_id: int, user_id: int, name: str, description: str, code: str) -> int:
    return insert_indicator_version(cur, indicator_id, user_id, name, description, code)


def _row_to_indicator(row: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """
    Map database row -> frontend expected indicator shape.

    Frontend uses:
    - id, name, description, code
    - is_buy (1 bought, 0 custom)
    - user_id / userId
    - end_time (optional)
    """
    is_encrypted = int(row.get("is_encrypted") or 0)
    is_buy = int(row.get("is_buy") or 0)
    code_hidden = bool(is_encrypted and is_buy)
    runtime_code = row.get("code") or ""
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id") if row.get("user_id") is not None else user_id,
        "is_buy": is_buy,
        "end_time": row.get("end_time") if row.get("end_time") is not None else 1,
        "name": row.get("name") or "",
        "code": "" if code_hidden else (row.get("code") or ""),
        # Hidden marketplace purchases still need executable code for chart
        # rendering. Keep the editor-facing `code` blank, but authorize the
        # current owner's local copy to run.
        "runtime_code": runtime_code if code_hidden else "",
        "description": row.get("description") or "",
        "publish_to_community": row.get("publish_to_community") if row.get("publish_to_community") is not None else 0,
        "pricing_type": row.get("pricing_type") or "free",
        "price": row.get("price") if row.get("price") is not None else 0,
        # VIP-free indicator flag (community publishing)
        "vip_free": 1 if (row.get("vip_free") or 0) else 0,
        "is_encrypted": is_encrypted,
        "code_hidden": 1 if code_hidden else 0,
        "preview_image": row.get("preview_image") or "",
        # Prefer MySQL-like time fields; fallback to legacy local columns.
        "createtime": row.get("createtime") or row.get("created_at"),
        "updatetime": row.get("updatetime") or row.get("updated_at"),
    }


def _generate_mock_df(length=200):
    return generate_mock_df(length)


def _merge_indicator_params(code: str, user_params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return merge_indicator_params(code, user_params)


def _validate_indicator_code_internal(code: str, user_params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return validate_indicator_code(code, user_params)


def _indicator_debug_summary(validation: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return indicator_debug_summary(validation)
def _request_lang(default: str = "zh-CN") -> str:
    raw = (
        request.headers.get("X-App-Lang")
        or request.headers.get("Accept-Language")
        or default
    )
    lang = str(raw or default).split(",", 1)[0].strip()
    return lang or default


def _is_zh_lang(lang: str | None) -> bool:
    return str(lang or "zh-CN").strip().lower().startswith("zh")


def _indicator_ai_text(key: str, lang: str = "zh-CN") -> str:
    texts = {
        "prompt_required": "Prompt cannot be empty",
        "insufficient_credits": "Insufficient credits. Please top up and try again.",
    }
    return texts.get(key, key)


def _indicator_hint_to_text(hint_code: str, params: Dict[str, Any] | None = None, lang: str = "zh-CN") -> str:
    params = params or {}
    if hint_code == "DECLARED_PARAMS_NOT_READ_VIA_PARAMS_GET":
        names = params.get("names") or []
        joined = ", ".join(names) or "parameters"
        return f"Declared parameters are not being read via params.get(...): {joined}."
    if hint_code == "PARAM_DEFAULT_MISMATCH":
        items = params.get("items") or []
        parts = [
            f"{item.get('name')}: @param={item.get('declared')}, params.get fallback={item.get('fallback')}"
            for item in items
        ]
        detail = "; ".join(parts) or "parameter defaults"
        return (
            f"Parameter default mismatch: {detail}. "
            "The # @param default must exactly match the params.get(..., default) fallback."
        )
    if hint_code == "SIGNAL_MARKERS_USE_WHERE_NONE":
        return "Signal markers use where(..., None).tolist(); prefer an explicit None list to avoid NaN rendering issues."
    if hint_code == "MISSING_OUTPUT":
        return "Missing output dictionary."
    if hint_code == "EXECUTION_COLUMNS_IGNORED_FOR_INDICATOR":
        return "Execution columns are ignored in chart indicators. Convert this idea to a script strategy before backtesting or live trading."
    if hint_code == "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR":
        return "# @strategy annotations are ignored in chart indicators. Put risk, sizing, timeframe, and execution rules in Script Strategy code."
    if hint_code == "MISSING_DF_COPY":
        return "Missing df = df.copy()."
    if hint_code == "MISSING_INDICATOR_NAME":
        return "Missing my_indicator_name."
    if hint_code == "MISSING_INDICATOR_DESCRIPTION":
        return "Missing my_indicator_description."
    if hint_code == "NDARRAY_PANDAS_METHOD_MISUSE":
        symbol = params.get("symbol") or "ndarray"
        method = params.get("method") or "?"
        return (
            f"Pandas method called on a numpy ndarray: {symbol}.{method}(...). "
            "Wrap with pd.Series(arr, index=df.index) before calling pandas methods, "
            "or rewrite with pandas-native .where/.clip/.abs."
        )
    if hint_code == "HELPER_RETURNS_NDARRAY":
        names_str = params.get("names_str") or ", ".join(params.get("names") or []) or "helper"
        return (
            f"User helpers return numpy ndarray: {names_str}. "
            "Downstream .rolling/.fillna/.shift/.ewm/.iloc on the result will AttributeError; "
            "have the helper return a Series instead (e.g. num / den.replace(0, np.nan).fillna(0))."
        )
    if hint_code == "RUNTIME_ERROR_ON_VERIFY":
        error_type = params.get("error_type") or "RuntimeError"
        detail = params.get("detail") or ""
        return f"Sandbox dry-run raised {error_type}: {detail}."
    if hint_code == "FUTURE_DATA_LEAK":
        snippet = params.get("snippet") or "?"
        kind = params.get("kind") or ""
        kind_en = {
            "shift": "negative shift",
            "iloc": "forward iloc offset",
            "bars_ago": "negative bars_ago",
        }.get(kind, kind or "unknown pattern")
        return (
            f"Future data leak detected ({kind_en}): {snippet}. "
            "Backtest is reading bars that haven't happened yet, which can NEVER be reproduced live. "
            "Use .shift(N) with positive N or iloc[i-N] to reference the past instead."
        )
    return f"Code hint detected: {hint_code}"


def _indicator_human_summary(
    initial_validation: Dict[str, Any],
    final_validation: Dict[str, Any],
    auto_fix_applied: bool,
    auto_fix_succeeded: bool,
    returned_candidate: str,
    lang: str = "zh-CN",
) -> Dict[str, Any]:
    initial_hints = initial_validation.get("hints") or []
    final_hints = final_validation.get("hints") or []
    initial_codes = {h.get("code") for h in initial_hints if h.get("code")}
    final_codes = {h.get("code") for h in final_hints if h.get("code")}
    fixed_codes = sorted(initial_codes - final_codes)
    remaining_codes = sorted(final_codes)

    fixed_messages = [
        _indicator_hint_to_text(h.get("code"), h.get("params"), lang=lang)
        for h in initial_hints
        if h.get("code") in fixed_codes
    ]
    remaining_messages = [
        _indicator_hint_to_text(h.get("code"), h.get("params"), lang=lang)
        for h in final_hints
        if h.get("code") in remaining_codes
    ]

    if auto_fix_applied and auto_fix_succeeded:
        title = "AI auto-fixed the indicator code and returned a more stable version"
    elif auto_fix_applied:
        title = "AI attempted to auto-fix the code, but some issues still remain"
    else:
        title = "AI generated indicator code and it passed the current QA flow"

    if returned_candidate == "repaired":
        returned_text = "The returned code is the auto-fixed version."
    else:
        returned_text = "The returned code is the initially generated version."

    return {
        "title": title,
        "returned_text": returned_text,
        "fixed_messages": fixed_messages,
        "remaining_messages": remaining_messages,
    }


@indicator_blp.route("/getIndicators", methods=["GET"])
@login_required
def get_indicators():
    """
    Get indicator list for the current user.

    Response:
      { code: 1, data: [ ... ] }
    """
    try:
        user_id = g.user_id

        with get_db_connection() as db:
            cur = db.cursor()
            # Best-effort schema upgrade for VIP-free indicators
            try:
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS vip_free BOOLEAN DEFAULT FALSE")
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS asset_type VARCHAR(32) DEFAULT 'indicator'")
            except Exception:
                pass
            # Get user's own indicators (both purchased and custom).
            cur.execute(
                """
                SELECT
                  id, user_id, is_buy, end_time, name, code, description,
                  publish_to_community, pricing_type, price, is_encrypted, preview_image, vip_free,
                  COALESCE(asset_type, 'indicator') as asset_type,
                  createtime, updatetime, created_at, updated_at
                FROM qd_indicator_codes
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
            cur.close()

        rows = [
            r for r in rows
            if is_indicator_ide_listable(
                code=r.get("code") or "",
                asset_type=r.get("asset_type") or "indicator",
            )
        ]
        out = [_row_to_indicator(r, user_id) for r in rows]
        return jsonify({"code": 1, "msg": "success", "data": out})
    except Exception as e:
        logger.error(f"get_indicators failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": []}), 500


@indicator_blp.route("/saveIndicator", methods=["POST"])
@login_required
def save_indicator():
    """
    Create or update an indicator for the current user.

    Request (frontend sends many extra fields; we store only the essentials):
      {
        id: number (0 for create),
        name: string,
        code: string,
        description?: string,
        ...
      }
    """
    try:
        data = request.get_json() or {}
        user_id = g.user_id
        indicator_id = int(data.get("id") or 0)
        code = data.get("code") or ""
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        publish_to_community = 1 if data.get("publishToCommunity") or data.get("publish_to_community") else 0
        pricing_type = (data.get("pricingType") or data.get("pricing_type") or "free").strip() or "free"
        vip_free = bool(data.get("vipFree") or data.get("vip_free"))
        code_hidden = bool(data.get("hideCode") or data.get("hide_code") or data.get("codeHidden") or data.get("code_hidden"))
        try:
            price = float(data.get("price") or 0)
        except Exception:
            price = 0.0
        preview_image = (data.get("previewImage") or data.get("preview_image") or "").strip()
        asset_type = (data.get("assetType") or data.get("asset_type") or "indicator").strip() or "indicator"
        if asset_type not in ("indicator", "script_template"):
            asset_type = "indicator"

        asset_type = resolve_indicator_asset_type(code, asset_type)

        if not code or not str(code).strip():
            return jsonify({"code": 0, "msg": "code is required", "data": None}), 400

        if asset_type == "script_template":
            from app.routes.strategy import _validate_strategy_code_internal
            validation = _validate_strategy_code_internal(code)
            if not validation.get("success"):
                return jsonify({
                    "code": 0,
                    "msg": validation.get("message") or "Unsafe script template code",
                    "data": None,
                }), 400
        else:
            from app.utils.safe_exec import validate_code_safety

            is_safe_code, unsafe_reason = validate_code_safety(code)
            if not is_safe_code:
                return jsonify({
                    "code": 0,
                    "msg": f"Unsafe indicator code: {unsafe_reason}",
                    "data": None,
                }), 400

        # Local dev UX: if name/description not provided, derive from code variables.
        if not name or not description:
            meta = _extract_indicator_meta_from_code(code)
            if not name:
                name = meta.get("name") or ""
            if not description:
                description = meta.get("description") or ""

        if not name:
            name = "Custom Indicator"

        now = _now_ts()  # For BIGINT fields (createtime, updatetime)

        user_role = getattr(g, 'user_role', 'user')
        is_admin = user_role == 'admin'
        
        with get_db_connection() as db:
            cur = db.cursor()
            # Best-effort schema upgrade for VIP-free indicators
            try:
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS vip_free BOOLEAN DEFAULT FALSE")
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS asset_type VARCHAR(32) DEFAULT 'indicator'")
                # i18n columns (see services/indicator_translator.py)
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS source_language VARCHAR(16)")
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS name_i18n JSONB")
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS description_i18n JSONB")
                _ensure_indicator_version_schema(cur)
            except Exception:
                pass
            existing_is_buy = 0
            if indicator_id and indicator_id > 0:
                cur.execute(
                    "SELECT is_buy FROM qd_indicator_codes WHERE id = ? AND user_id = ?",
                    (indicator_id, user_id),
                )
                _existing_buy = cur.fetchone()
                existing_is_buy = int((_existing_buy or {}).get("is_buy") or 0)
                if publish_to_community and existing_is_buy == 1:
                    cur.close()
                    return jsonify(
                        {
                            "code": 0,
                            "msg": "purchased_asset_cannot_publish",
                            "data": None,
                        }
                    ), 403
            if indicator_id and indicator_id > 0:
                if publish_to_community:
                    cur.execute(
                        "SELECT publish_to_community, review_status FROM qd_indicator_codes WHERE id = ? AND user_id = ?",
                        (indicator_id, user_id)
                    )
                    existing = cur.fetchone()
                    was_published = existing and existing.get('publish_to_community')
                    new_review_status = 'approved' if is_admin else 'pending'
                    reviewer_id = user_id if is_admin else None
                    if not was_published:
                        cur.execute(
                            """
                            UPDATE qd_indicator_codes
                            SET name = ?, code = ?, description = ?,
                                publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
                                vip_free = ?, asset_type = ?, is_encrypted = ?,
                                review_status = ?, review_note = '',
                                reviewed_at = CASE WHEN ? = 'approved' THEN NOW() ELSE NULL END,
                                reviewed_by = ?,
                                updatetime = ?, updated_at = NOW()
                            WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)
                            """,
                            (name, code, description, publish_to_community, pricing_type, price, preview_image, vip_free, asset_type, 1 if code_hidden else 0,
                             new_review_status, new_review_status, reviewer_id, now, indicator_id, user_id),
                        )
                    else:
                        # Non-admin updates to published assets require review again.
                        cur.execute(
                            """
                            UPDATE qd_indicator_codes
                            SET name = ?, code = ?, description = ?,
                                publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
                                vip_free = ?, asset_type = ?, is_encrypted = ?,
                                review_status = ?, review_note = '',
                                reviewed_at = CASE WHEN ? = 'approved' THEN NOW() ELSE NULL END,
                                reviewed_by = ?,
                                updatetime = ?, updated_at = NOW()
                            WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)
                            """,
                            (name, code, description, publish_to_community, pricing_type, price, preview_image, vip_free, asset_type, 1 if code_hidden else 0,
                             new_review_status, new_review_status, reviewer_id, now, indicator_id, user_id),
                        )
                else:
                    cur.execute(
                        """
                        UPDATE qd_indicator_codes
                        SET name = ?, code = ?, description = ?,
                            publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
                            vip_free = FALSE, asset_type = ?,
                            review_status = NULL, review_note = '', reviewed_at = NULL, reviewed_by = NULL,
                            updatetime = ?, updated_at = NOW()
                        WHERE id = ? AND user_id = ?
                        """,
                        (name, code, description, publish_to_community, pricing_type, price, preview_image, asset_type, now, indicator_id, user_id),
                    )
            else:
                review_status = None
                if publish_to_community:
                    review_status = 'approved' if is_admin else 'pending'
                cur.execute(
                    """
                    INSERT INTO qd_indicator_codes
                      (user_id, is_buy, end_time, name, code, description,
                       publish_to_community, pricing_type, price, preview_image, vip_free, asset_type, review_status, is_encrypted,
                       createtime, updatetime, created_at, updated_at)
                    VALUES (?, 0, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())
                    """,
                    (user_id, name, code, description, publish_to_community, pricing_type, price, preview_image, vip_free, asset_type, review_status, 1 if code_hidden else 0, now, now),
                )
                indicator_id = int(cur.lastrowid or 0)
            if indicator_id and indicator_id > 0:
                _ensure_indicator_version_schema(cur)
                _insert_indicator_version(cur, indicator_id, user_id, name, description, code)
            db.commit()
            cur.close()

        # ============================================================
        # ============================================================
        if publish_to_community and indicator_id > 0:
            try:
                ui_lang = (
                    request.headers.get('X-App-Lang')
                    or request.headers.get('Accept-Language', '').split(',')[0].strip()
                    or 'en-US'
                )
                if ui_lang not in _SUPPORTED_LANGUAGES_FOR_TRANSLATE:
                    ui_lang = None  # let translator auto-detect

                name_i18n, desc_i18n, src_lang = translate_indicator(
                    name=name,
                    description=description,
                    source_language=ui_lang,
                )

                with get_db_connection() as db:
                    cur = db.cursor()
                    cur.execute(
                        """
                        UPDATE qd_indicator_codes
                        SET source_language = ?,
                            name_i18n = ?,
                            description_i18n = ?,
                            updated_at = NOW()
                        WHERE id = ? AND user_id = ?
                        """,
                        (
                            src_lang,
                            json.dumps(name_i18n, ensure_ascii=False) if name_i18n else None,
                            json.dumps(desc_i18n, ensure_ascii=False) if desc_i18n else None,
                            indicator_id,
                            user_id,
                        ),
                    )
                    db.commit()
                    cur.close()
            except Exception as _e:
                logger.warning(f"save_indicator: i18n translation skipped: {_e}")

        return jsonify({"code": 1, "msg": "success", "data": {"id": indicator_id, "userid": user_id}})
    except Exception as e:
        logger.error(f"save_indicator failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@indicator_blp.route("/versions", methods=["GET"])
@login_required
def list_indicator_versions():
    """List saved code versions for one indicator owned by the current user."""
    try:
        user_id = g.user_id
        indicator_id = int(request.args.get("indicatorId") or request.args.get("indicator_id") or 0)
        if not indicator_id:
            return jsonify({"code": 0, "msg": "indicatorId is required", "data": []}), 400
        ok, rows = list_indicator_code_versions(int(user_id), int(indicator_id))
        if not ok:
            return jsonify({"code": 0, "msg": "indicator not found", "data": []}), 404
        return jsonify({"code": 1, "msg": "success", "data": rows})
    except Exception as e:
        logger.error(f"list_indicator_versions failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": []}), 500
@indicator_blp.route("/versions/<int:version_id>", methods=["GET"])
@login_required
def get_indicator_version(version_id: int):
    """Get one saved code version."""
    try:
        row = get_indicator_code_version(int(g.user_id), int(version_id))
        if not row:
            return jsonify({"code": 0, "msg": "version not found", "data": None}), 404
        return jsonify({"code": 1, "msg": "success", "data": row})
    except Exception as e:
        logger.error(f"get_indicator_version failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
@indicator_blp.route("/versions/restore", methods=["POST"])
@login_required
def restore_indicator_version():
    """Restore one code version to the current indicator and keep the restore as a new version."""
    try:
        data = request.get_json() or {}
        version_id = int(data.get("versionId") or data.get("version_id") or 0)
        if not version_id:
            return jsonify({"code": 0, "msg": "versionId is required", "data": None}), 400
        restored = restore_indicator_code_version(int(g.user_id), int(version_id), _now_ts())
        if not restored:
            return jsonify({"code": 0, "msg": "version not found", "data": None}), 404
        return jsonify({"code": 1, "msg": "success", "data": restored})
    except Exception as e:
        logger.error(f"restore_indicator_version failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500
@indicator_blp.route("/deleteIndicator", methods=["POST"])
@login_required
def delete_indicator():
    """Delete an indicator by id for the current user."""
    try:
        data = request.get_json() or {}
        user_id = g.user_id
        indicator_id = int(data.get("id") or 0)
        if not indicator_id:
            return jsonify({"code": 0, "msg": "id is required", "data": None}), 400

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute(
                """
                SELECT publish_to_community, COALESCE(is_buy, 0) as is_buy
                FROM qd_indicator_codes
                WHERE id = ? AND user_id = ?
                """,
                (indicator_id, user_id),
            )
            row = cur.fetchone()
            if not row:
                cur.close()
                return jsonify({"code": 0, "msg": "indicator not found", "data": None}), 404

            cur.execute(
                "SELECT COUNT(*) AS count FROM qd_indicator_purchases WHERE indicator_id = ?",
                (indicator_id,),
            )
            purchase_count = int((cur.fetchone() or {}).get("count") or 0)
            if int(row.get("publish_to_community") or 0) == 1 or purchase_count > 0:
                # Published or sold assets are marketplace records. Do not hard-delete
                # them because buyers may need the original id to restore their copy.
                # Treat user deletion as an author-initiated unpublish.
                cur.execute(
                    """
                    UPDATE qd_indicator_codes
                    SET publish_to_community = 0,
                        review_status = 'rejected',
                        review_note = 'Author unpublished/deleted local source',
                        updated_at = NOW()
                    WHERE id = ? AND user_id = ?
                    """,
                    (indicator_id, user_id),
                )
            else:
                cur.execute(
                    "DELETE FROM qd_indicator_codes WHERE id = ? AND user_id = ?",
                    (indicator_id, user_id),
                )
            db.commit()
            cur.close()

        return jsonify({"code": 1, "msg": "success", "data": {"unpublished": purchase_count > 0}})
    except Exception as e:
        logger.error(f"delete_indicator failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@indicator_blp.route("/getIndicatorParams", methods=["GET"])
@login_required
def get_indicator_params():
    """
    Return declared `# @param` fields for an indicator.

    Used by the strategy builder to render a parameter form.

    Query params:
        indicator_id: Indicator ID

    Returns:
        params: [
            {
                "name": "ma_fast",
                "type": "int",
                "default": 5,
                "description": "Fast MA period"
            },
            ...
        ]
    """
    try:
        from app.services.indicator_params import get_indicator_params as get_params
        
        indicator_id = request.args.get("indicator_id")
        if not indicator_id:
            return jsonify({"code": 0, "msg": "indicator_id is required", "data": None}), 400
        
        try:
            indicator_id = int(indicator_id)
        except ValueError:
            return jsonify({"code": 0, "msg": "indicator_id must be an integer", "data": None}), 400
        
        params = get_params(indicator_id)
        return jsonify({"code": 1, "msg": "success", "data": params})
        
    except Exception as e:
        logger.error(f"get_indicator_params failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@indicator_blp.route("/aiGenerate", methods=["POST"])
@login_required
def ai_generate():
    """
    SSE endpoint to generate indicator code.

    Frontend expects 'text/event-stream' with chunks:
      data: {"content":"..."}\n\n
    then:
      data: [DONE]\n\n

    Local-first: if OpenRouter key is not configured, we return a reasonable template.
    """
    data = request.get_json() or {}
    lang = _request_lang()
    prompt = (data.get("prompt") or "").strip()
    existing = (data.get("existingCode") or "").strip()
    context = data.get("context") if isinstance(data.get("context"), dict) else {}

    if not prompt:
        # Keep SSE contract (match PHP behavior) so frontend doesn't look "stuck".
        def _err_stream():
            yield "data: " + _sse_json({"error": _indicator_ai_text("prompt_required", lang)}) + "\n\n"
            yield "data: [DONE]\n\n"

        return Response(
            _err_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # QuantDinger indicator IDE: chart render only; strategies are separate script assets.
    SYSTEM_PROMPT = """# Role

You write production-ready **QuantDinger** chart indicator scripts: Python that runs in the Indicator IDE and renders overlays/markers on the K-line chart. Indicators are **not executable strategies**: they must not open, close, size, backtest, or live trade. If a user wants trading logic, keep this file as a visual indicator and let the Strategy Script workflow generate an executable script strategy separately.

# Runtime (strict)

- Environment: browser-side Pyodide-style sandbox **or** API verify sandbox: **no network**, no file I/O, no subprocess.
- **`pd` and `np` are already available.** Do **not** write `import pandas` / `import numpy`. Avoid any `import` unless unavoidable; never import `os`, `sys`, `requests`, `socket`, `subprocess`, `threading`, `sqlite3`, `multiprocessing`, or other I/O/network modules.
- Do **not** use: `eval`, `exec`, `compile`, `open`, `__import__`, `getattr`/`setattr`/`delattr` on untrusted names, `globals`, `vars`, `dir`, or meta-programming to escape the sandbox. `locals()` is allowed if needed to assemble `output` (backtest/verify allow it); avoid `globals()`.
- Allowed imports only: `numpy`, `pandas`, `math`, `json`, `datetime`, `time`, `collections`, `functools`, `itertools`, `statistics`, `decimal`, `fractions`, `copy`. **Never** `import operator`.
- Work **vectorized** with pandas on `df` where possible; avoid O(n) Python loops over every row for core series (rolling/ewm/shift are preferred).

# Series vs ndarray contract (critical - common AI bug source)

This is the #1 reason hand/AI-translated Pine/TDX scripts crash at runtime ("AttributeError: 'numpy.ndarray' object has no attribute 'rolling' / 'fillna' / 'iloc' / 'shift' / 'ewm'"). Pine auto-coerces types; Python does not.

Hard rules:

- `np.where(...)`, `np.maximum(...)`, `np.minimum(...)`, `np.abs(...)` on a Series **may return either a Series or an ndarray** depending on numpy version. **Never chain pandas methods on their result without coercing.** Coerce explicitly: `pd.Series(arr, index=df.index)`.
- A user-defined helper like `def safe_div(a, b): return np.where(b == 0, 0, a / b)` returns **ndarray**. If you want `.fillna` / `.rolling` / `.shift` / `.ewm` / `.tolist()` on it, wrap: `pd.Series(safe_div(a, b), index=df.index)`. Better: rewrite the helper to return a Series directly, e.g. `return (a / b.replace(0, np.nan)).fillna(0)`.
- Any helper that uses `.iloc` (TDX-style `sma`, custom filters, etc.) **MUST receive a Series**. If you call it with `np.where(...)` output you will get AttributeError on the first iteration. Either coerce the argument or make the helper auto-coerce: `if not isinstance(src, pd.Series): src = pd.Series(np.asarray(src), index=df.index)`.
- `pd.Series(some_ndarray)` defaults to a `RangeIndex 0..n-1`. If `df.index` is a `DatetimeIndex` (very common), the new Series will **silently misalign** with `df` columns in subsequent comparisons / `where` / arithmetic. **Always pass `index=df.index`** when wrapping an ndarray that is sized to `len(df)`.

Prefer pandas-native operators that **stay in Series-land**:

- `np.where(cond, a, b)`         -> `a.where(cond, b)`     (returns Series when `a` is Series; `cond` aligned to `a`)
- `np.where(cond, X, 0)`         -> `X.where(cond, 0)` or `pd.Series(0, index=df.index).mask(cond, X)`
- `np.maximum(s, 0)`             -> `s.clip(lower=0)`
- `np.minimum(s, k)`             -> `s.clip(upper=k)`
- `np.abs(s)`                    -> `s.abs()`
- division-by-zero protection    -> `num / den.replace(0, np.nan)` then `.fillna(0)` (do NOT use `np.where(den == 0, ...)` if you need to chain pandas methods)

Self-check before returning code: every place where you call `.rolling` / `.fillna` / `.shift` / `.ewm` / `.iloc` / `.tolist()` - trace back: is the left-hand side a **Series**? If it came from `np.where` / `np.maximum` / `np.minimum` / a custom helper, wrap it first.

# Input: `df`

- `df` is a pandas `DataFrame` aligned to K-line bars (one row per bar).
- You **must** start mutating with: `df = df.copy()`
- Expected columns (use `.get` or try/except only if you document optional columns): `open`, `high`, `low`, `close`, `volume`. A `time` column may exist; do not assume dtypes beyond numeric OHLCV.
- Do not rename or drop required columns in a way that breaks length alignment.

# Required globals (strict)

1. `my_indicator_name = "..."` - short display name (can match `output['name']`).
2. `my_indicator_description = "..."` - one line describing logic and parameters.

# Execution boundary (strict)

- Do **not** create or require execution columns such as `df['open_long']`, `df['close_long']`, `df['open_short']`, `df['close_short']`, `df['add_long']`, or `df['reduce_long']`.
- Do **not** emit `# @strategy`, `# signal_form`, `# exit_owner`, `# flip_mode`, `# timeframe`, risk defaults, position sizing, stop-loss, take-profit, trailing-stop, leverage, or trade-direction settings.
- `output['signals']` are visual chart markers only. They never place orders.
- If the user asks for a strategy, still return a chart indicator here: plots and visual markers that express the idea. The executable strategy belongs in Script Strategy.

# User intent handling

- Treat the user's text as product requirements, not as literal code unless they paste code.
- Infer sensible defaults when the request is incomplete, but keep the code simple, readable, and stable.
- If the user mentions a well-known indicator family, implement the core concept and add useful visual context rather than overfitting to one screenshot.
- Use short English identifiers in code. User-facing labels may follow the user's language when it improves readability.
- The current chart symbol/timeframe may be provided as context. Use it to choose sensible examples only; do **not** hardcode symbol, exchange, timeframe, account, leverage, or risk into indicator code.

# Chart output: `output` dict (strict)

After computation, set:

`output = { 'name': ..., 'plots': [...], 'signals': [...], 'layers': [...] }`  (use the same string keys as below; `layers` is optional)

- **`name`**: str, usually `my_indicator_name`.
- **`plots`**: list of dicts, each with:
  - `name` (str), `data` (list, length **exactly** `len(df)`), `color` (`#RRGGBB`), `overlay` (bool).
  - `type`: optional, e.g. `'line'`.
  - Price-scale series (MA, Bollinger on price): `overlay: True`. Oscillators (RSI 0-100): `overlay: False`.
- **`signals`**: optional list for markers; each item:
  - `type`: `'buy'` or `'sell'`, `text` (short label), `color`, `data`: list length **`len(df)`**, value `None` or a float price for marker Y.
  - Signal markers must usually represent **events**, not continuous states. If a condition can stay true for many bars, mark only the transition bar with an edge/flip condition. This prevents noisy charts and repeated signal notifications.
- **`layers`**: optional list for advanced K-line overlays. Do not add layers by default. Use layers only when the user explicitly asks for zones, channels, support/resistance, invalidation areas, or when one sparse annotation materially improves readability. Prefer plots and signals for normal indicators.
  - Zone layer: `{ 'type': 'zone', 'startIndex': int, 'endIndex': int, 'top': float, 'bottom': float, 'text': str, 'fillColor': '#RRGGBB', 'borderColor': '#RRGGBB', 'opacity': 0.12 }`.
  - Line layer: `{ 'type': 'line', 'startIndex': int, 'endIndex': int, 'price': float, 'text': str, 'color': '#RRGGBB', 'dashed': true }`; for sloped lines use `startPrice` and `endPrice`.
  - Label layer: `{ 'type': 'label', 'index': int, 'price': float, 'text': str, 'color': '#RRGGBB', 'textColor': '#FFFFFF' }`.
  - Prefer `startIndex` / `endIndex` / `index` for generated code because they are stable with the current `df`. `startTime` / `endTime` / `time` are also supported if they match K-line timestamps.
  - Do not use layers as execution signals. Indicators are chart-only.
- **`calculatedVars`**: optional dict for future UI; may be `{}` or omitted.

**Length rule:** every `plot['data']` and every `signal['data']` list must have the **same length as `df`** (same as number of rows). Layer objects do not need per-bar arrays, but their indices/times and prices must be valid for the visible `df`.

# Optional tunable parameters: `# @param`

If the indicator has knobs (periods, thresholds), declare them **once per line** at the top after name/description:

`# @param <name> <int|float|bool|str> <default> <short description>`

Example: `# @param rsi_len int 14 RSI period`

The runtime merges these with user-supplied params.

**Critical:** `# @param` only declares parameters for the UI/runtime. It does **not**
create Python variables automatically. If you declare:

`# @param fast_period int 10 Fast MA period`

you must read it explicitly in code, for example:

`fast_period = params.get('fast_period', 10)`

The fallback default in `params.get` must exactly match the declared `# @param`
default after type conversion. Example: if you declare
`# @param fast_period int 18 Fast MA period`, the code must read
`fast_period = int(params.get('fast_period', 18))`; never use 10, 30, or any
second hard-coded default for the same parameter.

Never use declared parameter names directly unless you first assign them from `params`.

# Strategy defaults

Do not use `# @strategy` in indicator code. Strategy defaults belong in Script Strategy code, not chart indicators.

# Quality bar

- Prefer clear variable names, short comments only where non-obvious.
- Ensure visual markers are useful but not noisy. Do not widen or replace the requested signal condition merely to create more markers.
- Use unambiguous marker text such as `Long Entry`, `Long Exit`, `Short Entry`, `Short Exit`, or `Warning`; a generic bearish/sell marker must not imply a short entry when it only exits a long position.
- For notification-safe markers, convert state signals into one-bar events by default:
  - `def edge(s): s = s.fillna(False).astype(bool); return s & ~s.shift(1).fillna(False)`
  - Use `edge(condition)` for `output['signals']` unless the user explicitly asks for every bar where a condition is true.
  - If the user requests "confirmed next bar" behavior, compute the raw condition on closed bars and shift the event one bar forward for display/notification: `confirmed = edge(raw_condition).shift(1).fillna(False)`.
- For state/regime visuals that should persist across bars, use overlay/non-overlay plots, lamp belts, or sparse layers instead of repeating `output['signals']` markers every bar.
- For signal markers, prefer explicit lists with `None` for empty bars:
  - `buy_marks = [df['low'].iloc[i] * 0.995 if bool(buy_signal.iloc[i]) else None for i in range(len(df))]`
  - `sell_marks = [df['high'].iloc[i] * 1.005 if bool(sell_signal.iloc[i]) else None for i in range(len(df))]`
  - Avoid `series.where(mask, None).tolist()` for marker data because float series may still contain `NaN` instead of real `None`.
- Default to `output['layers'] = []`. Use `output['layers']` only when explicitly requested or when one sparse annotation materially improves readability, for example supply/demand zones, premium/discount ranges, support/resistance lines, BOS/CHoCH labels, or invalidation levels. Do not flood every bar with labels or add large filled zones by habit.
- If the user asks for multi-signal lights, lamp belts, resonance rows, or dashboard-style states, create named non-overlay plot rows that encode each state with stable per-bar arrays, and keep labels concise. Each row should have a clear `name` such as `MACD`, `KDJ`, or `RSI`; do not hardcode a renderer-specific layout unless the requested visual needs it.
- Convert warm-up `NaN` values to either `None` (preferred for sparse/optional lines) or a sensible neutral value for bounded oscillators; avoid drawing misleading zero lines on price overlays.
- Before returning code, self-check:
  1. every declared `# @param` used in code is read via `params.get(...)`
  2. every `params.get('name', fallback)` fallback exactly equals that parameter's declared `# @param` default
  3. no execution columns or `# @strategy` annotations are emitted
  4. every `plot['data']` and `signal['data']` length equals `len(df)`
  5. `output` exists and is a dict
  6. **type audit**: scan every `.rolling` / `.fillna` / `.shift` / `.ewm` / `.iloc` / `.tolist` call site; confirm its left-hand side is a Series. If it came from `np.where` / `np.maximum` / `np.minimum` / a custom helper returning ndarray, you MUST wrap with `pd.Series(arr, index=df.index)` first
  7. **index audit**: any `pd.Series(arr)` where `arr` is ndarray sized `len(df)` MUST pass `index=df.index`, otherwise it will silently misalign with DatetimeIndex-based `df`

# Output format for this chat turn

Return **only** valid Python source: **no** markdown fences, **no** ` ``` `, **no** explanation before or after the code. First non-empty line should be `my_indicator_name` or `# @param` immediately followed by `my_indicator_name`.
""" + "\n\n" + INDICATOR_GENERATION_CONTRACT

    def _template_code() -> str:
        from app.services.indicator_default_template import build_default_indicator_template

        desc = (prompt or "").replace("\n", " ")[:200]
        if not desc:
            desc = "Moving average chart indicator template with visual markers."
        code = build_default_indicator_template(
            name="Custom Indicator",
            description=desc,
        )
        if existing:
            code = "# Existing code was provided as context.\n" + code
        return code

    def _generate_code_via_llm() -> str:
        """Use unified LLMService to support all configured providers (OpenRouter, OpenAI, Grok, etc.)."""
        from app.services.llm import LLMService
        
        llm = LLMService()
        
        # Get provider and model from env config (no frontend override)
        current_provider = llm.provider
        current_model = llm.get_code_generation_model()
        current_api_key = llm.get_api_key()
        base_url = llm.get_base_url()
        
        logger.info(f"AI Code Generation - Provider: {current_provider.value}, Model: {current_model}, Base URL: {base_url}, API Key configured: {bool(current_api_key)}")
        
        # Check if any LLM provider is configured
        if not current_api_key:
            logger.warning("No LLM API key configured, using template code")
            return _template_code()

        def _context_block() -> str:
            if not context:
                return ""
            lines: List[str] = []
            market = str(context.get("market") or "").strip()
            symbol = str(context.get("symbol") or "").strip()
            timeframe = str(context.get("timeframe") or "").strip()
            indicator_name = str(context.get("indicatorName") or "").strip()
            indicator_description = str(context.get("indicatorDescription") or "").strip()
            param_defaults = context.get("paramDefaults")
            if market or symbol or timeframe:
                lines.append(f"- Current chart: market={market or 'unknown'}, symbol={symbol or 'unknown'}, timeframe={timeframe or 'unknown'}")
            if indicator_name:
                lines.append(f"- Current indicator name: {indicator_name}")
            if indicator_description:
                lines.append(f"- Current indicator description: {indicator_description[:300]}")
            if isinstance(param_defaults, dict) and param_defaults:
                try:
                    lines.append("- Existing @param defaults: " + json.dumps(param_defaults, ensure_ascii=False)[:1200])
                except Exception:
                    pass
            if not lines:
                return ""
            return (
                "\n\n# Current IDE context (for intent only; do not hardcode symbol/timeframe/account settings)\n"
                + "\n".join(lines)
            )

        # Build user prompt (match PHP behavior)
        context_text = _context_block()
        user_prompt = prompt + context_text
        if existing:
            user_prompt = (
                "# Existing QuantDinger indicator code (migrate it to the chart-only indicator contract):\n\n```python\n"
                + existing.strip()
                + "\n```\n\n# Change request:\n\n"
                + prompt
                + context_text
                + "\n\nReturn one full replacement indicator: my_indicator_name/description, df = df.copy(), declared @param values must be read via params.get(...), output dict with layers defaulting to [], list lengths == len(df). "
                "Do not emit execution columns, # @strategy, risk, sizing, timeframe, or trade-direction settings. "
                "For visual signals, output one-bar event markers by default; do not repeat markers on every bar while a condition remains true. "
                "For every declared @param, the params.get fallback default must exactly match the declared default. "
                "Python only - no markdown, no prose outside the code."
            )

        temperature = float(os.getenv("OPENROUTER_TEMPERATURE", "0.7") or 0.7)
        
        # Call LLM using the unified API (auto-selects provider based on LLM_PROVIDER env)
        # use_json_mode=False because we want raw Python code output
        content = llm.call_llm_api(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=current_model,
            temperature=temperature,
            use_json_mode=False  # Code generation doesn't need JSON mode
        )
        
        # Clean up markdown code blocks if present
        content = content.strip()
        if content.startswith("```python"):
            content = content[9:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        
        return content.strip() or _template_code()

    AUTO_FIX_HINT_CODES = {
        "DECLARED_PARAMS_NOT_READ_VIA_PARAMS_GET",
        "PARAM_DEFAULT_MISMATCH",
        "SIGNAL_MARKERS_USE_WHERE_NONE",
        "MISSING_OUTPUT",
        "MISSING_DF_COPY",
        "MISSING_INDICATOR_NAME",
        "MISSING_INDICATOR_DESCRIPTION",
        "EXECUTION_COLUMNS_IGNORED_FOR_INDICATOR",
        "STRATEGY_ANNOTATIONS_IGNORED_FOR_INDICATOR",
    }

    def _needs_auto_fix(validation: Dict[str, Any]) -> bool:
        if not validation.get("success"):
            return True
        for hint in validation.get("hints", []):
            if hint.get("code") in AUTO_FIX_HINT_CODES:
                return True
        return False

    def _format_validation_issues(validation: Dict[str, Any]) -> str:
        issues: List[str] = []
        if not validation.get("success"):
            issues.append(f"- Verification failed: {validation.get('msg')}")
            if validation.get("details"):
                issues.append(f"- Details: {validation.get('details')}")
        for hint in validation.get("hints", []):
            code_name = hint.get("code") or "UNKNOWN"
            params = hint.get("params") or {}
            if params:
                issues.append(f"- Hint {code_name}: {json.dumps(params, ensure_ascii=False)}")
            else:
                issues.append(f"- Hint {code_name}")
        return "\n".join(issues) if issues else "- No issues provided"

    def _repair_code_via_llm(bad_code: str, validation: Dict[str, Any]) -> str:
        from app.services.llm import LLMService

        llm = LLMService()
        current_model = llm.get_code_generation_model()
        current_api_key = llm.get_api_key()
        if not current_api_key:
            return bad_code

        issues_text = _format_validation_issues(validation)
        repair_prompt = (
            "You produced QuantDinger indicator code that failed automatic validation. "
            "Fix the code while preserving the user's trading idea and parameters. "
            "Return one full replacement script only.\n\n"
            f"# Original user request\n{prompt}\n\n"
            f"# Validation issues to fix\n{issues_text}\n\n"
            "# Current code\n```python\n"
            + bad_code.strip()
            + "\n```\n\n"
            + INDICATOR_REPAIR_REQUIREMENTS
        )

        content = llm.call_llm_api(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ],
            model=current_model,
            temperature=0.2,
            use_json_mode=False,
        )

        content = (content or "").strip()
        if content.startswith("```python"):
            content = content[9:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip() or bad_code

    def _generate_final_code() -> tuple[str, Dict[str, Any]]:
        try:
            code_text = _generate_code_via_llm()
        except Exception as e:
            logger.error(f"ai_generate LLM failed, fallback to template. Error: {type(e).__name__}: {e}")
            code_text = _template_code()

        validation = _validate_indicator_code_internal(code_text)
        if not _needs_auto_fix(validation):
            debug = {
                "auto_fix_applied": False,
                "auto_fix_succeeded": False,
                "returned_candidate": "initial",
                "initial_validation": _indicator_debug_summary(validation),
                "final_validation": _indicator_debug_summary(validation),
            }
            debug["human_summary"] = _indicator_human_summary(
                validation, validation, False, False, "initial", lang=lang
            )
            logger.info("ai_generate debug=%s", _sse_json(debug))
            return code_text, debug

        logger.warning("ai_generate produced code needing auto-fix: %s", _format_validation_issues(validation))
        try:
            repaired = _repair_code_via_llm(code_text, validation)
        except Exception as e:
            logger.error(f"ai_generate auto-fix failed, returning safe template. Error: {type(e).__name__}: {e}")
            fallback_code = _template_code()
            fallback_validation = _validate_indicator_code_internal(fallback_code)
            debug = {
                "auto_fix_applied": True,
                "auto_fix_succeeded": False,
                "returned_candidate": "template",
                "initial_validation": _indicator_debug_summary(validation),
                "final_validation": _indicator_debug_summary(fallback_validation),
                "auto_fix_error": str(e),
            }
            debug["human_summary"] = _indicator_human_summary(
                validation, fallback_validation, True, False, "template", lang=lang
            )
            logger.info("ai_generate debug=%s", _sse_json(debug))
            return fallback_code, debug

        repaired_validation = _validate_indicator_code_internal(repaired)
        if repaired_validation.get("success") and not _needs_auto_fix(repaired_validation):
            logger.info("ai_generate auto-fix succeeded")
            debug = {
                "auto_fix_applied": True,
                "auto_fix_succeeded": True,
                "returned_candidate": "repaired",
                "initial_validation": _indicator_debug_summary(validation),
                "final_validation": _indicator_debug_summary(repaired_validation),
            }
            debug["human_summary"] = _indicator_human_summary(
                validation, repaired_validation, True, True, "repaired", lang=lang
            )
            logger.info("ai_generate debug=%s", _sse_json(debug))
            return repaired, debug

        repaired_hint_codes = {h.get("code") for h in repaired_validation.get("hints", [])}
        if repaired_validation.get("success"):
            logger.warning("ai_generate auto-fix improved code but some non-blocking issues remain")
            debug = {
                "auto_fix_applied": True,
                "auto_fix_succeeded": True,
                "returned_candidate": "repaired",
                "initial_validation": _indicator_debug_summary(validation),
                "final_validation": _indicator_debug_summary(repaired_validation),
            }
            debug["human_summary"] = _indicator_human_summary(
                validation, repaired_validation, True, True, "repaired", lang=lang
            )
            logger.info("ai_generate debug=%s", _sse_json(debug))
            return repaired, debug

        if repaired_hint_codes.intersection(AUTO_FIX_HINT_CODES):
            logger.warning("ai_generate auto-fix still has blocking issues, returning safe template")
            fallback_code = _template_code()
            fallback_validation = _validate_indicator_code_internal(fallback_code)
            debug = {
                "auto_fix_applied": True,
                "auto_fix_succeeded": False,
                "returned_candidate": "template",
                "initial_validation": _indicator_debug_summary(validation),
                "final_validation": _indicator_debug_summary(fallback_validation),
            }
            debug["human_summary"] = _indicator_human_summary(
                validation, fallback_validation, True, False, "template", lang=lang
            )
            logger.info("ai_generate debug=%s", _sse_json(debug))
            return fallback_code, debug

        debug = {
            "auto_fix_applied": True,
            "auto_fix_succeeded": False,
            "returned_candidate": "repaired",
            "initial_validation": _indicator_debug_summary(validation),
            "final_validation": _indicator_debug_summary(repaired_validation),
        }
        debug["human_summary"] = _indicator_human_summary(
            validation, repaired_validation, True, False, "repaired", lang=lang
        )
        logger.info("ai_generate debug=%s", _sse_json(debug))
        return repaired, debug

    # Capture user_id before generator runs (generator executes outside request context)
    user_id = g.user_id
    def stream():
        from app.services.billing_service import get_billing_service
        billing = get_billing_service()
        ok, msg = billing.check_and_consume(
            user_id=user_id,
            feature='ai_code_gen',
            reference_id=f"ai_code_gen_{user_id}_{int(time.time())}"
        )
        if not ok:
            error_msg = f"Insufficient credits: {msg}" if msg else _indicator_ai_text("insufficient_credits", lang)
            yield "data: " + _sse_json({"error": error_msg}) + "\n\n"
            yield "data: [DONE]\n\n"
            return

        code_text, debug_info = _generate_final_code()

        yield "data: " + _sse_json({"debug": debug_info}) + "\n\n"

        # Stream in chunks (front-end appends).
        chunk_size = 200
        for i in range(0, len(code_text), chunk_size):
            chunk = code_text[i : i + chunk_size]
            yield "data: " + _sse_json({"content": chunk}) + "\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@indicator_blp.route("/codeQualityHints", methods=["POST"])
@login_required
def code_quality_hints():
    """
    Heuristic hints + runtime smoke-execution for indicator code.

    Request body:
        code (required): Indicator source code

    Returns hints with severity, code, and params. Static analysis catches
    structural issues; a sandboxed dry-run surfaces runtime errors before backtest.
    """
    from app.services.indicator_code_quality import analyze_indicator_code_quality

    data = request.get_json() or {}
    code_str = data.get("code") or ""
    hints = analyze_indicator_code_quality(code_str)

    # If static analysis already found a deterministic error, skip the dry-run.
    # We do NOT skip on warn/info because those don't block execution and the user
    # benefits from the runtime check finishing the picture.
    has_static_error = any(h.get("severity") == "error" for h in hints)
    if not has_static_error and code_str.strip():
        try:
            validation = _validate_indicator_code_internal(code_str)
        except Exception as e:  # never let the smoke run break the endpoint
            logger.warning("codeQualityHints dry-run crashed: %s", e)
            validation = None

        if validation is not None and not validation.get("success"):
            error_type = validation.get("error_type") or "RuntimeError"
            detail = validation.get("details") or validation.get("msg") or ""
            # Trim noisy tracebacks: keep only the last meaningful line.
            short_detail = ""
            if detail:
                for line in str(detail).strip().splitlines()[::-1]:
                    line = line.strip()
                    if line and not line.startswith("File "):
                        short_detail = line[:300]
                        break
                if not short_detail:
                    short_detail = str(detail).strip().splitlines()[-1][:300]
            hints.append(
                {
                    "severity": "error",
                    "code": "RUNTIME_ERROR_ON_VERIFY",
                    "params": {
                        "error_type": error_type,
                        "detail": short_detail,
                    },
                }
            )

    return jsonify({"code": 1, "data": {"hints": hints}})


# openapi-compat: legacy import name
indicator_bp = indicator_blp

