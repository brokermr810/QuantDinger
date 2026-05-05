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
from flask import Blueprint, Response, jsonify, request, g
import pandas as pd
import numpy as np

from app.utils.db import get_db_connection
from app.utils.logger import get_logger
from app.utils.auth import login_required
from app.services.indicator_params import IndicatorCaller, IndicatorParamsParser
import requests

logger = get_logger(__name__)

indicator_bp = Blueprint("indicator", __name__)


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


def _row_to_indicator(row: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """
    Map database row -> frontend expected indicator shape.

    Frontend uses:
    - id, name, description, code
    - is_buy (1 bought, 0 custom)
    - user_id / userId
    - end_time (optional)
    """
    return {
        "id": row.get("id"),
        "user_id": row.get("user_id") if row.get("user_id") is not None else user_id,
        "is_buy": row.get("is_buy") if row.get("is_buy") is not None else 0,
        "end_time": row.get("end_time") if row.get("end_time") is not None else 1,
        "name": row.get("name") or "",
        "code": row.get("code") or "",
        "description": row.get("description") or "",
        "publish_to_community": row.get("publish_to_community") if row.get("publish_to_community") is not None else 0,
        "pricing_type": row.get("pricing_type") or "free",
        "price": row.get("price") if row.get("price") is not None else 0,
        # VIP-free indicator flag (community publishing)
        "vip_free": 1 if (row.get("vip_free") or 0) else 0,
        # Local mode: encryption is not supported; keep field for frontend compatibility (always 0).
        "is_encrypted": 0,
        "preview_image": row.get("preview_image") or "",
        # Prefer MySQL-like time fields; fallback to legacy local columns.
        "createtime": row.get("createtime") or row.get("created_at"),
        "updatetime": row.get("updatetime") or row.get("updated_at"),
    }


def _generate_mock_df(length=200):
    """Generate mock K-line data for verification."""
    from datetime import datetime, timedelta
    
    dates = [datetime.now() - timedelta(minutes=i) for i in range(length)]
    dates.reverse()
    
    # Random walk with trend
    returns = np.random.normal(0, 0.002, length)
    price_path = 10000 * np.exp(np.cumsum(returns))
    
    close = price_path
    high = close * (1 + np.abs(np.random.normal(0, 0.001, length)))
    low = close * (1 - np.abs(np.random.normal(0, 0.001, length)))
    open_p = close * (1 + np.random.normal(0, 0.001, length)) # Slight deviation from close
    # Ensure High is highest and Low is lowest
    high = np.maximum(high, np.maximum(open_p, close))
    low = np.minimum(low, np.minimum(open_p, close))
    
    volume = np.abs(np.random.normal(100, 50, length)) * 1000
    
    df = pd.DataFrame({
        'time': [int(d.timestamp() * 1000) for d in dates],
        'open': open_p,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume
    })
    return df


def _merge_indicator_params(code: str, user_params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    declared_params = IndicatorParamsParser.parse_params(code or "")
    return IndicatorParamsParser.merge_params(declared_params, user_params or {})


def _validate_indicator_code_internal(code: str, user_params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Shared validation for indicator code generation and verifyCode.

    Returns:
      {
        "success": bool,
        "msg": str,
        "error_type": str | None,
        "details": str | None,
        "plots_count": int,
        "signals_count": int,
        "hints": [...]
      }
    """
    from app.services.indicator_code_quality import analyze_indicator_code_quality
    from app.utils.safe_exec import build_safe_builtins, safe_exec_with_validation

    raw = (code or "").strip()
    if not raw:
        return {
            "success": False,
            "msg": "Code is empty",
            "error_type": "EmptyCode",
            "details": None,
            "plots_count": 0,
            "signals_count": 0,
            "hints": [{"severity": "error", "code": "EMPTY_CODE", "params": {}}],
        }

    hints = analyze_indicator_code_quality(raw)
    df = _generate_mock_df()
    merged_params = _merge_indicator_params(raw, user_params)

    exec_env = {
        'df': df.copy(),
        'pd': pd,
        'np': np,
        'params': merged_params,
        'output': None,
    }
    exec_env['__builtins__'] = build_safe_builtins()

    exec_result = safe_exec_with_validation(
        code=raw,
        exec_globals=exec_env,
        exec_locals=exec_env,
        timeout=20,
    )
    if not exec_result.get('success'):
        error_detail = exec_result.get('error') or 'Unknown error'
        is_security = error_detail.startswith('Unsafe code rejected')
        return {
            "success": False,
            "msg": f"{'Security' if is_security else 'Runtime'} Error: {error_detail}",
            "error_type": "SecurityError" if is_security else "RuntimeError",
            "details": error_detail,
            "plots_count": 0,
            "signals_count": 0,
            "hints": hints,
        }

    output = exec_env.get('output')
    if output is None:
        return {
            "success": False,
            "msg": "Missing 'output' variable. Your code must define an 'output' dictionary.",
            "error_type": "MissingOutput",
            "details": None,
            "plots_count": 0,
            "signals_count": 0,
            "hints": hints,
        }

    if not isinstance(output, dict):
        return {
            "success": False,
            "msg": f"'output' must be a dictionary, got {type(output).__name__}",
            "error_type": "InvalidOutputType",
            "details": None,
            "plots_count": 0,
            "signals_count": 0,
            "hints": hints,
        }

    if 'plots' not in output and 'signals' not in output:
        return {
            "success": False,
            "msg": "'output' dict should contain 'plots' or 'signals' list.",
            "error_type": "InvalidOutputStructure",
            "details": None,
            "plots_count": 0,
            "signals_count": 0,
            "hints": hints,
        }

    plots = output.get('plots', [])
    signals = output.get('signals', [])

    for p in plots:
        if 'data' not in p:
            return {
                "success": False,
                "msg": f"Plot '{p.get('name')}' missing 'data' field.",
                "error_type": "InvalidPlot",
                "details": None,
                "plots_count": len(plots),
                "signals_count": len(signals),
                "hints": hints,
            }
        if len(p['data']) != len(df):
            return {
                "success": False,
                "msg": f"Plot '{p.get('name')}' data length ({len(p['data'])}) does not match DataFrame length ({len(df)}).",
                "error_type": "LengthMismatch",
                "details": None,
                "plots_count": len(plots),
                "signals_count": len(signals),
                "hints": hints,
            }

    for s in signals:
        if 'data' not in s:
            return {
                "success": False,
                "msg": f"Signal '{s.get('type')}' missing 'data' field.",
                "error_type": "InvalidSignal",
                "details": None,
                "plots_count": len(plots),
                "signals_count": len(signals),
                "hints": hints,
            }
        if len(s['data']) != len(df):
            return {
                "success": False,
                "msg": f"Signal '{s.get('type')}' data length ({len(s['data'])}) does not match DataFrame length ({len(df)}).",
                "error_type": "LengthMismatch",
                "details": None,
                "plots_count": len(plots),
                "signals_count": len(signals),
                "hints": hints,
            }

    return {
        "success": True,
        "msg": "Verification passed! Code executed successfully.",
        "error_type": None,
        "details": None,
        "plots_count": len(plots),
        "signals_count": len(signals),
        "hints": hints,
    }


def _indicator_debug_summary(validation: Dict[str, Any] | None = None) -> Dict[str, Any]:
    validation = validation or {}
    hints = validation.get("hints") or []
    return {
        "success": bool(validation.get("success")),
        "message": validation.get("msg"),
        "error_type": validation.get("error_type"),
        "hint_codes": [h.get("code") for h in hints if h.get("code")],
        "hint_count": len(hints),
        "plots_count": validation.get("plots_count", 0),
        "signals_count": validation.get("signals_count", 0),
    }


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
    is_zh = _is_zh_lang(lang)
    texts = {
        "prompt_required": "提示词不能为空" if is_zh else "Prompt cannot be empty",
        "insufficient_credits": "积分不足，请充值后重试" if is_zh else "Insufficient credits. Please top up and try again.",
    }
    return texts.get(key, key)


def _indicator_hint_to_text(hint_code: str, params: Dict[str, Any] | None = None, lang: str = "zh-CN") -> str:
    params = params or {}
    is_zh = _is_zh_lang(lang)
    if hint_code == "DECLARED_PARAMS_NOT_READ_VIA_PARAMS_GET":
        names = params.get("names") or []
        joined = "、".join(names) if (names and is_zh) else ", ".join(names)
        if not joined:
            joined = "参数" if is_zh else "parameters"
        return (
            f"已检测到声明的参数未通过 params.get(...) 读取：{joined}。"
            if is_zh else
            f"Declared parameters are not being read via params.get(...): {joined}."
        )
    if hint_code == "SIGNAL_MARKERS_USE_WHERE_NONE":
        return (
            "已检测到信号标记使用 where(..., None).tolist()，建议改为显式 None 列表以避免 NaN 渲染问题。"
            if is_zh else
            "Signal markers use where(..., None).tolist(); prefer an explicit None list to avoid NaN rendering issues."
        )
    if hint_code == "MISSING_OUTPUT":
        return "缺少 output 字典。" if is_zh else "Missing output dictionary."
    if hint_code == "MISSING_BUY_SELL_COLUMNS":
        return "缺少 df['buy'] 或 df['sell'] 信号列。" if is_zh else "Missing df['buy'] or df['sell'] signal columns."
    if hint_code == "MISSING_DF_COPY":
        return "缺少 df = df.copy()。" if is_zh else "Missing df = df.copy()."
    if hint_code == "MISSING_INDICATOR_NAME":
        return "缺少 my_indicator_name。" if is_zh else "Missing my_indicator_name."
    if hint_code == "MISSING_INDICATOR_DESCRIPTION":
        return "缺少 my_indicator_description。" if is_zh else "Missing my_indicator_description."
    if hint_code == "UNKNOWN_STRATEGY_KEY":
        key = params.get('key') or 'unknown'
        return (
            f"存在未知的 @strategy 键：{key}。"
            if is_zh else
            f"Unknown @strategy key detected: {key}."
        )
    if hint_code == "NO_STRATEGY_ANNOTATIONS":
        return "没有声明任何 @strategy 默认配置。" if is_zh else "No @strategy default configuration was declared."
    if hint_code == "NO_STOP_AND_TAKE_PROFIT":
        return "未声明止损和止盈默认配置。" if is_zh else "Stop-loss and take-profit defaults are not declared."
    if hint_code == "NO_STOP_LOSS":
        return "未声明止损默认配置。" if is_zh else "Stop-loss default is not declared."
    if hint_code == "NO_TAKE_PROFIT":
        return "未声明止盈默认配置。" if is_zh else "Take-profit default is not declared."
    return f"检测到代码提示：{hint_code}" if is_zh else f"Code hint detected: {hint_code}"


def _indicator_human_summary(
    initial_validation: Dict[str, Any],
    final_validation: Dict[str, Any],
    auto_fix_applied: bool,
    auto_fix_succeeded: bool,
    returned_candidate: str,
    lang: str = "zh-CN",
) -> Dict[str, Any]:
    is_zh = _is_zh_lang(lang)
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
        title = "AI 已自动修复并返回更稳定的指标代码" if is_zh else "AI auto-fixed the indicator code and returned a more stable version"
    elif auto_fix_applied:
        title = "AI 尝试自动修复，但仍保留部分问题" if is_zh else "AI attempted to auto-fix the code, but some issues still remain"
    else:
        title = "AI 已生成指标代码，并通过当前质检流程" if is_zh else "AI generated indicator code and it passed the current QA flow"

    if returned_candidate == "repaired":
        returned_text = "当前返回的是自动修复后的代码。" if is_zh else "The returned code is the auto-fixed version."
    else:
        returned_text = "当前返回的是首次生成的代码。" if is_zh else "The returned code is the initially generated version."

    return {
        "title": title,
        "returned_text": returned_text,
        "fixed_messages": fixed_messages,
        "remaining_messages": remaining_messages,
    }


@indicator_bp.route("/getIndicators", methods=["GET"])
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
            except Exception:
                pass
            # Get user's own indicators (both purchased and custom).
            cur.execute(
                """
                SELECT
                  id, user_id, is_buy, end_time, name, code, description,
                  publish_to_community, pricing_type, price, is_encrypted, preview_image, vip_free,
                  createtime, updatetime, created_at, updated_at
                FROM qd_indicator_codes
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
            cur.close()

        out = [_row_to_indicator(r, user_id) for r in rows]
        return jsonify({"code": 1, "msg": "success", "data": out})
    except Exception as e:
        logger.error(f"get_indicators failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": []}), 500


@indicator_bp.route("/saveIndicator", methods=["POST"])
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
        try:
            price = float(data.get("price") or 0)
        except Exception:
            price = 0.0
        preview_image = (data.get("previewImage") or data.get("preview_image") or "").strip()

        if not code or not str(code).strip():
            return jsonify({"code": 0, "msg": "code is required", "data": None}), 400

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

        # 检查用户是否是管理员（管理员发布的指标自动通过审核）
        user_role = getattr(g, 'user_role', 'user')
        is_admin = user_role == 'admin'
        
        with get_db_connection() as db:
            cur = db.cursor()
            # Best-effort schema upgrade for VIP-free indicators
            try:
                cur.execute("ALTER TABLE qd_indicator_codes ADD COLUMN IF NOT EXISTS vip_free BOOLEAN DEFAULT FALSE")
            except Exception:
                pass
            # 市场购买的副本不可改库中源码：应「另存为」新建 is_buy=0 的指标再编辑
            if indicator_id and indicator_id > 0:
                cur.execute(
                    "SELECT is_buy FROM qd_indicator_codes WHERE id = ? AND user_id = ?",
                    (indicator_id, user_id),
                )
                _existing_buy = cur.fetchone()
                if _existing_buy and int(_existing_buy.get("is_buy") or 0) == 1:
                    cur.close()
                    return jsonify(
                        {
                            "code": 0,
                            "msg": "indicator_purchased_readonly",
                            "data": None,
                        }
                    ), 403
            if indicator_id and indicator_id > 0:
                # 检查是否从未发布改为发布，需要设置审核状态
                if publish_to_community:
                    cur.execute(
                        "SELECT publish_to_community, review_status FROM qd_indicator_codes WHERE id = ? AND user_id = ?",
                        (indicator_id, user_id)
                    )
                    existing = cur.fetchone()
                    was_published = existing and existing.get('publish_to_community')
                    # 如果之前未发布，现在发布，设置审核状态
                    # 管理员发布的直接通过，普通用户需要待审核
                    new_review_status = 'approved' if is_admin else 'pending'
                    if not was_published:
                        cur.execute(
                            """
                            UPDATE qd_indicator_codes
                            SET name = ?, code = ?, description = ?,
                                publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
                                vip_free = ?,
                                review_status = ?, review_note = '', reviewed_at = NOW(), reviewed_by = ?,
                                updatetime = ?, updated_at = NOW()
                            WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)
                            """,
                            (name, code, description, publish_to_community, pricing_type, price, preview_image, vip_free,
                             new_review_status, user_id if is_admin else None, now, indicator_id, user_id),
                        )
                    else:
                        # 已发布过的更新，保持原审核状态
                        cur.execute(
                            """
                            UPDATE qd_indicator_codes
                            SET name = ?, code = ?, description = ?,
                                publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
                                vip_free = ?,
                                updatetime = ?, updated_at = NOW()
                            WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)
                            """,
                            (name, code, description, publish_to_community, pricing_type, price, preview_image, vip_free, now, indicator_id, user_id),
                        )
                else:
                    # 取消发布，清除审核状态
                    cur.execute(
                        """
                        UPDATE qd_indicator_codes
                        SET name = ?, code = ?, description = ?,
                            publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
                            vip_free = FALSE,
                            review_status = NULL, review_note = '', reviewed_at = NULL, reviewed_by = NULL,
                            updatetime = ?, updated_at = NOW()
                        WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)
                        """,
                        (name, code, description, publish_to_community, pricing_type, price, preview_image, now, indicator_id, user_id),
                    )
            else:
                # 新建指标 - 管理员发布的直接通过，普通用户需要待审核
                review_status = None
                if publish_to_community:
                    review_status = 'approved' if is_admin else 'pending'
                cur.execute(
                    """
                    INSERT INTO qd_indicator_codes
                      (user_id, is_buy, end_time, name, code, description,
                       publish_to_community, pricing_type, price, preview_image, vip_free, review_status,
                       createtime, updatetime, created_at, updated_at)
                    VALUES (?, 0, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())
                    """,
                    (user_id, name, code, description, publish_to_community, pricing_type, price, preview_image, vip_free, review_status, now, now),
                )
                indicator_id = int(cur.lastrowid or 0)
            db.commit()
            cur.close()

        return jsonify({"code": 1, "msg": "success", "data": {"id": indicator_id, "userid": user_id}})
    except Exception as e:
        logger.error(f"save_indicator failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@indicator_bp.route("/deleteIndicator", methods=["POST"])
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
                "DELETE FROM qd_indicator_codes WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)",
                (indicator_id, user_id),
            )
            db.commit()
            cur.close()

        return jsonify({"code": 1, "msg": "success", "data": None})
    except Exception as e:
        logger.error(f"delete_indicator failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": str(e), "data": None}), 500


@indicator_bp.route("/getIndicatorParams", methods=["GET"])
@login_required
def get_indicator_params():
    """
    获取指标的参数声明
    
    用于前端在策略创建时显示可配置的参数表单。
    
    Query params:
        indicator_id: 指标ID
        
    Returns:
        params: [
            {
                "name": "ma_fast",
                "type": "int",
                "default": 5,
                "description": "短期均线周期"
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


@indicator_bp.route("/verifyCode", methods=["POST"])
@login_required
def verify_code():
    """
    Verify/Dry-run indicator code with mock data.
    Checks for:
    - Syntax errors
    - Runtime errors
    - Output format (must define 'output' dict)
    """
    try:
        data = request.get_json() or {}
        code = data.get("code") or ""
        
        if not code or not str(code).strip():
            return jsonify({"code": 0, "msg": "Code is empty", "data": None}), 400

        validation = _validate_indicator_code_internal(code, data.get("params") or {})
        if not validation["success"]:
            return jsonify({
                "code": 0,
                "msg": validation["msg"],
                "data": {
                    "type": validation["error_type"],
                    "details": validation["details"],
                    "hints": validation.get("hints", []),
                }
            })

        return jsonify({
            "code": 1,
            "msg": validation["msg"],
            "data": {
                "plots_count": validation["plots_count"],
                "signals_count": validation["signals_count"],
                "hints": validation.get("hints", []),
            }
        })

    except Exception as e:
        logger.error(f"verify_code failed: {str(e)}", exc_info=True)
        return jsonify({"code": 0, "msg": f"System Error: {str(e)}", "data": None}), 500


@indicator_bp.route("/aiGenerate", methods=["POST"])
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

    if not prompt:
        # Keep SSE contract (match PHP behavior) so frontend doesn't look "stuck".
        def _err_stream():
            yield "data: " + json.dumps({"error": _indicator_ai_text("prompt_required", lang)}, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"

        return Response(
            _err_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # QuantDinger indicator IDE: chart render + backtest; must pass server verifyCode + safe_exec rules.
    SYSTEM_PROMPT = """# Role

You write production-ready **QuantDinger** indicator scripts: Python that runs in the Indicator IDE, renders on the K-line chart, and drives **backtest entries/exits** via boolean signals. Code must be syntactically valid, safe for the host sandbox, and match the exact I/O contract below.

# Runtime (strict)

- Environment: browser-side Pyodide–style sandbox **or** API verify sandbox: **no network**, no file I/O, no subprocess.
- **`pd` and `np` are already available.** Do **not** write `import pandas` / `import numpy`. Avoid any `import` unless unavoidable; never import `os`, `sys`, `requests`, `socket`, `subprocess`, `threading`, `sqlite3`, `multiprocessing`, or other I/O/network modules.
- Do **not** use: `eval`, `exec`, `compile`, `open`, `__import__`, `getattr`/`setattr`/`delattr` on untrusted names, `globals`, `vars`, `dir`, or meta-programming to escape the sandbox. `locals()` is allowed if needed to assemble `output` (backtest/verify allow it); avoid `globals()`.
- Work **vectorized** with pandas on `df` where possible; avoid O(n) Python loops over every row for core series (rolling/ewm/shift are preferred).

# Input: `df`

- `df` is a pandas `DataFrame` aligned to K-line bars (one row per bar).
- You **must** start mutating with: `df = df.copy()`
- Expected columns (use `.get` or try/except only if you document optional columns): `open`, `high`, `low`, `close`, `volume`. A `time` column may exist; do not assume dtypes beyond numeric OHLCV.
- Do not rename or drop required columns in a way that breaks length alignment.

# Required globals (strict)

1. `my_indicator_name = "..."`  — short display name (can match `output['name']`).
2. `my_indicator_description = "..."` — one line describing logic and parameters.

# Backtest contract (strict)

The backtest engine reads **boolean** columns on `df`:

- `df['buy']` — True on bars where a **new** long entry signal is allowed (edge-triggered).
- `df['sell']` — True on bars where a **new** exit / short entry signal is allowed (per product semantics).

Rules:

- Same **index and length** as `df`; dtype boolean (use `.astype(bool)` after fillna).
- **Edge-trigger (mandatory)** unless the user explicitly asks for repeated signals on consecutive bars:
  - `raw_buy = (...condition...)`
  - `buy = raw_buy.fillna(False) & (~raw_buy.shift(1).fillna(False))`
  - Same pattern for `raw_sell` / `sell`.
- Signals represent **confirmation on bar close**; the engine fills on the **next bar open** (live-like). Do not implement intrabar lookahead (e.g. do not use the same bar’s `high` to validate a signal that assumes you bought at that bar’s `open` unless the user clearly wants that research mode).
- Fill NaN from indicators before comparisons; replace division-by-zero (`replace(0, np.nan)` then fill).

# Chart output: `output` dict (strict)

After computation, set:

`output = { 'name': ..., 'plots': [...], 'signals': [...] }`  (use the same string keys as below)

- **`name`**: str, usually `my_indicator_name`.
- **`plots`**: list of dicts, each with:
  - `name` (str), `data` (list, length **exactly** `len(df)`), `color` (`#RRGGBB`), `overlay` (bool).
  - `type`: optional, e.g. `'line'`.
  - Price-scale series (MA, Bollinger on price): `overlay: True`. Oscillators (RSI 0–100): `overlay: False`.
- **`signals`**: optional list for markers; each item:
  - `type`: `'buy'` or `'sell'`, `text` (short label), `color`, `data`: list length **`len(df)`**, value `None` or a float price for marker Y.
- **`calculatedVars`**: optional dict for future UI; may be `{}` or omitted.

**Length rule:** every `plot['data']` and every `signal['data']` list must have the **same length as `df`** (same as number of rows).

# Optional tunable parameters: `# @param`

If the indicator has knobs (periods, thresholds), declare them **once per line** at the top (after name/description or with `@strategy`):

`# @param <name> <int|float|bool|str> <default> <short description>`

Example: `# @param rsi_len int 14 RSI period`

The runtime merges these with user-supplied params.

**Critical:** `# @param` only declares parameters for the UI/runtime. It does **not**
create Python variables automatically. If you declare:

`# @param fast_period int 10 Fast MA period`

you must read it explicitly in code, for example:

`fast_period = params.get('fast_period', 10)`

Never use declared parameter names directly unless you first assign them from `params`.

# Strategy defaults: `# @strategy` (recommended)

Place **after** name/description lines, **one key per line**, no extra prose on the same line:

`# @strategy <key> <value>`

Supported keys (parser-enforced):

- `stopLossPct`, `takeProfitPct`: float **0–1** (e.g. `0.03` = 3% on margin PnL semantics as used by the engine).
- `entryPct`: float **0.01–1.0** (fraction of capital).
- `trailingEnabled`: `true` or `false`.
- `trailingStopPct`, `trailingActivationPct`: float **0–1**.
- `tradeDirection`: exactly `long`, `short`, or `both`.

**Do not** put `leverage` in `@strategy`; users set leverage in the IDE backtest panel.

**Do not** emit `signalTiming`; the product fixes fills to next bar open.

Pick defaults that match the strategy style (trend vs mean-reversion).

# Quality bar

- Prefer clear variable names, short comments only where non-obvious.
- Ensure at least some `buy` and some `sell` True in typical ranges unless the user asked for a rare signal; if logic is too strict, widen thresholds.
- If the user asks for “display only” with no trading, still set `df['buy']`/`df['sell']` to all-False and provide plots.
- For signal markers, prefer explicit lists with `None` for empty bars:
  - `buy_marks = [df['low'].iloc[i] * 0.995 if bool(df['buy'].iloc[i]) else None for i in range(len(df))]`
  - Avoid `series.where(mask, None).tolist()` for marker data because float series may still contain `NaN` instead of real `None`.
- Before returning code, self-check:
  1. every declared `# @param` used in code is read via `params.get(...)`
  2. `df['buy']` and `df['sell']` are assigned boolean Series
  3. every `plot['data']` and `signal['data']` length equals `len(df)`
  4. `output` exists and is a dict

# Output format for this chat turn

Return **only** valid Python source: **no** markdown fences, **no** ` ``` `, **no** explanation before or after the code. First non-empty line should be `my_indicator_name` or a comment block with `@strategy`/`@param` immediately followed by `my_indicator_name`.
"""

    def _template_code() -> str:
        # Fallback template that follows the project expectations.
        header = (
            f"my_indicator_name = \"Custom Indicator\"\n"
            f"my_indicator_description = \"{(prompt or '').replace('\n', ' ')[:200]}\"\n\n"
        )
        body = (
            "# @param rsi_len int 14 RSI period\n\n"
            "rsi_len = params.get('rsi_len', 14)\n"
            "df = df.copy()\n\n"
            "# Example: robust RSI with edge-triggered buy/sell (no position management, no TP/SL on chart)\n"
            "delta = df['close'].diff()\n"
            "gain = delta.clip(lower=0)\n"
            "loss = (-delta).clip(lower=0)\n"
            "# Wilder-style smoothing (stable and avoids early NaN explosion)\n"
            "avg_gain = gain.ewm(alpha=1/rsi_len, adjust=False).mean()\n"
            "avg_loss = loss.ewm(alpha=1/rsi_len, adjust=False).mean()\n"
            "rs = avg_gain / avg_loss.replace(0, np.nan)\n"
            "rsi = 100 - (100 / (1 + rs))\n"
            "rsi = rsi.fillna(50)\n\n"
            "# Raw conditions (avoid overly strict filters)\n"
            "raw_buy = (rsi < 30)\n"
            "raw_sell = (rsi > 70)\n"
            "# One-shot signals\n"
            "buy = (raw_buy.fillna(False) & (~raw_buy.shift(1).fillna(False))).astype(bool)\n"
            "sell = (raw_sell.fillna(False) & (~raw_sell.shift(1).fillna(False))).astype(bool)\n"
            "df['buy'] = buy\n"
            "df['sell'] = sell\n\n"
            "buy_marks = [df['low'].iloc[i] * 0.995 if bool(df['buy'].iloc[i]) else None for i in range(len(df))]\n"
            "sell_marks = [df['high'].iloc[i] * 1.005 if bool(df['sell'].iloc[i]) else None for i in range(len(df))]\n\n"
            "output = {\n"
            "  'name': my_indicator_name,\n"
            "  'plots': [\n"
            "    {'name': 'RSI(14)', 'data': rsi.tolist(), 'color': '#faad14', 'overlay': False}\n"
            "  ],\n"
            "  'signals': [\n"
            "    {'type': 'buy', 'text': 'B', 'data': buy_marks, 'color': '#00E676'},\n"
            "    {'type': 'sell', 'text': 'S', 'data': sell_marks, 'color': '#FF5252'}\n"
            "  ]\n"
            "}\n"
        )
        if existing:
            header = "# Existing code was provided as context.\n" + header
        return header + body

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

        # Build user prompt (match PHP behavior)
        user_prompt = prompt
        if existing:
            user_prompt = (
                "# Existing QuantDinger indicator code (keep working output/buy/sell contract):\n\n```python\n"
                + existing.strip()
                + "\n```\n\n# Change request:\n\n"
                + prompt
                + "\n\nReturn one full replacement script: same QuantDinger rules (my_indicator_name/description, df = df.copy(), declared @param values must be read via params.get(...), df['buy']/df['sell'], output dict, list lengths == len(df)). "
                "Python only — no markdown, no prose outside the code."
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
        
        # Remove think tags (similar to llm.py processing)
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        
        return content.strip() or _template_code()

    AUTO_FIX_HINT_CODES = {
        "DECLARED_PARAMS_NOT_READ_VIA_PARAMS_GET",
        "SIGNAL_MARKERS_USE_WHERE_NONE",
        "MISSING_OUTPUT",
        "MISSING_BUY_SELL_COLUMNS",
        "MISSING_DF_COPY",
        "MISSING_INDICATOR_NAME",
        "MISSING_INDICATOR_DESCRIPTION",
        "UNKNOWN_STRATEGY_KEY",
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
            "# Repair requirements\n"
            "- Keep QuantDinger indicator contract intact.\n"
            "- If code declares # @param, read each declared param via params.get(...).\n"
            "- Ensure df['buy'] and df['sell'] are boolean Series.\n"
            "- Ensure output exists and all plot/signal data lengths equal len(df).\n"
            "- For signal markers, prefer explicit None-or-price lists, not .where(..., None).tolist().\n"
            "- Return Python only, no markdown, no explanation."
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
        
        # Remove think tags (similar to llm.py processing)
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        
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
            logger.info("ai_generate debug=%s", json.dumps(debug, ensure_ascii=False))
            return code_text, debug

        logger.warning("ai_generate produced code needing auto-fix: %s", _format_validation_issues(validation))
        try:
            repaired = _repair_code_via_llm(code_text, validation)
        except Exception as e:
            logger.error(f"ai_generate auto-fix failed, returning first pass. Error: {type(e).__name__}: {e}")
            debug = {
                "auto_fix_applied": True,
                "auto_fix_succeeded": False,
                "returned_candidate": "initial",
                "initial_validation": _indicator_debug_summary(validation),
                "final_validation": _indicator_debug_summary(validation),
                "auto_fix_error": str(e),
            }
            debug["human_summary"] = _indicator_human_summary(
                validation, validation, True, False, "initial", lang=lang
            )
            logger.info("ai_generate debug=%s", json.dumps(debug, ensure_ascii=False))
            return code_text, debug

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
            logger.info("ai_generate debug=%s", json.dumps(debug, ensure_ascii=False))
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
            logger.info("ai_generate debug=%s", json.dumps(debug, ensure_ascii=False))
            return repaired, debug

        if repaired_hint_codes.intersection(AUTO_FIX_HINT_CODES):
            logger.warning("ai_generate auto-fix still has blocking issues, returning first pass")
            debug = {
                "auto_fix_applied": True,
                "auto_fix_succeeded": False,
                "returned_candidate": "initial",
                "initial_validation": _indicator_debug_summary(validation),
                "final_validation": _indicator_debug_summary(repaired_validation),
            }
            debug["human_summary"] = _indicator_human_summary(
                validation, repaired_validation, True, False, "initial", lang=lang
            )
            logger.info("ai_generate debug=%s", json.dumps(debug, ensure_ascii=False))
            return code_text, debug

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
        logger.info("ai_generate debug=%s", json.dumps(debug, ensure_ascii=False))
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
            error_msg = f"积分不足: {msg}" if _is_zh_lang(lang) and msg else _indicator_ai_text("insufficient_credits", lang)
            yield "data: " + json.dumps({"error": error_msg}, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"
            return

        code_text, debug_info = _generate_final_code()

        yield "data: " + json.dumps({"debug": debug_info}, ensure_ascii=False) + "\n\n"

        # Stream in chunks (front-end appends).
        chunk_size = 200
        for i in range(0, len(code_text), chunk_size):
            chunk = code_text[i : i + chunk_size]
            yield "data: " + json.dumps({"content": chunk}, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@indicator_bp.route("/codeQualityHints", methods=["POST"])
@login_required
def code_quality_hints():
    """
    Heuristic hints for indicator code (structure, @strategy risk/position).
    POST /api/indicator/codeQualityHints
    Body: { "code": "..." }
    Returns: { "code": 1, "data": { "hints": [ { "severity", "code", "params" } ] } }
    """
    from app.services.indicator_code_quality import analyze_indicator_code_quality

    data = request.get_json() or {}
    code_str = data.get("code") or ""
    hints = analyze_indicator_code_quality(code_str)
    return jsonify({"code": 1, "data": {"hints": hints}})


@indicator_bp.route("/parseStrategyConfig", methods=["POST"])
@login_required
def parse_strategy_config():
    """
    Parse @strategy annotations from indicator code and return strategy config.
    POST /api/indicator/parseStrategyConfig
    Body: { "code": "..." }
    Returns: { "code": 1, "data": { "strategyConfig": {...}, "indicatorParams": [...] } }
    """
    from app.services.indicator_params import StrategyConfigParser, IndicatorParamsParser
    data = request.get_json() or {}
    code_str = (data.get("code") or "").strip()
    strategy_cfg = StrategyConfigParser.parse(code_str) if code_str else {}
    indicator_params = IndicatorParamsParser.parse_params(code_str) if code_str else []
    return jsonify({
        "code": 1,
        "data": {
            "strategyConfig": strategy_cfg,
            "indicatorParams": indicator_params
        }
    })


@indicator_bp.route("/callIndicator", methods=["POST"])
@login_required
def call_indicator():
    """
    调用另一个指标（供前端 Pyodide 环境使用）
    
    POST /api/indicator/callIndicator
    Body: {
        "indicatorRef": int | str,  # 指标ID或名称
        "klineData": List[Dict],      # K线数据
        "params": Dict,              # 传递给被调用指标的参数（可选）
        "currentIndicatorId": int     # 当前指标ID（用于循环依赖检测，可选）
    }
    
    Returns:
        {
            "code": 1,
            "data": {
                "df": List[Dict],    # 执行后的DataFrame（转换为JSON）
                "columns": List[str]  # DataFrame的列名
            }
        }
    """
    try:
        data = request.get_json() or {}
        indicator_ref = data.get("indicatorRef")
        kline_data = data.get("klineData", [])
        params = data.get("params") or {}
        current_indicator_id = data.get("currentIndicatorId")
        
        if not indicator_ref:
            return jsonify({
                "code": 0,
                "msg": "indicatorRef is required",
                "data": None
            }), 400
        
        if not kline_data or not isinstance(kline_data, list):
            return jsonify({
                "code": 0,
                "msg": "klineData must be a non-empty list",
                "data": None
            }), 400
        
        # 获取用户ID
        user_id = g.user_id
        
        # 创建 IndicatorCaller
        indicator_caller = IndicatorCaller(user_id, current_indicator_id)
        
        # 将前端传入的K线数据转换为DataFrame
        df = pd.DataFrame(kline_data)
        
        # 确保必要的列存在
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                df[col] = 0.0
        
        # 转换数据类型
        df['open'] = df['open'].astype('float64')
        df['high'] = df['high'].astype('float64')
        df['low'] = df['low'].astype('float64')
        df['close'] = df['close'].astype('float64')
        df['volume'] = df['volume'].astype('float64')
        
        # 调用指标
        result_df = indicator_caller.call_indicator(indicator_ref, df, params)
        
        # 将DataFrame转换为JSON格式（前端可以使用的格式）
        result_dict = result_df.to_dict(orient='records')
        
        return jsonify({
            "code": 1,
            "msg": "success",
            "data": {
                "df": result_dict,
                "columns": list(result_df.columns)
            }
        })
        
    except Exception as e:
        logger.error(f"Error calling indicator: {e}", exc_info=True)
        return jsonify({
            "code": 0,
            "msg": str(e),
            "data": None
        }), 500
