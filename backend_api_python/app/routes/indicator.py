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
    Map SQLite row -> frontend expected indicator shape.

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
            # Get user's own indicators (both purchased and custom).
            cur.execute(
                """
                SELECT
                  id, user_id, is_buy, end_time, name, code, description,
                  publish_to_community, pricing_type, price, is_encrypted, preview_image,
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
                                review_status = ?, review_note = '', reviewed_at = NOW(), reviewed_by = ?,
                                updatetime = ?, updated_at = NOW()
                            WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)
                            """,
                            (name, code, description, publish_to_community, pricing_type, price, preview_image, 
                             new_review_status, user_id if is_admin else None, now, indicator_id, user_id),
                        )
                    else:
                        # 已发布过的更新，保持原审核状态
                        cur.execute(
                            """
                            UPDATE qd_indicator_codes
                            SET name = ?, code = ?, description = ?,
                                publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
                                updatetime = ?, updated_at = NOW()
                            WHERE id = ? AND user_id = ? AND (is_buy IS NULL OR is_buy = 0)
                            """,
                            (name, code, description, publish_to_community, pricing_type, price, preview_image, now, indicator_id, user_id),
                        )
                else:
                    # 取消发布，清除审核状态
                    cur.execute(
                        """
                        UPDATE qd_indicator_codes
                        SET name = ?, code = ?, description = ?,
                            publish_to_community = ?, pricing_type = ?, price = ?, preview_image = ?,
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
                       publish_to_community, pricing_type, price, preview_image, review_status,
                       createtime, updatetime, created_at, updated_at)
                    VALUES (?, 0, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW(), NOW())
                    """,
                    (user_id, name, code, description, publish_to_community, pricing_type, price, preview_image, review_status, now, now),
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

        # 1. Generate mock data
        df = _generate_mock_df()
        
        # 2. Prepare execution environment
        exec_env = {
            'df': df.copy(),
            'pd': pd,
            'np': np,
            'output': None
        }
        
        # 3. Execute code
        try:
            exec(code, exec_env)
        except SyntaxError as e:
            return jsonify({
                "code": 0, 
                "msg": f"Syntax Error at line {e.lineno}: {e.msg}", 
                "data": {"type": "SyntaxError", "line": e.lineno, "details": str(e)}
            })
        except Exception as e:
            # Capture traceback for better debugging
            tb = traceback.format_exc()
            # Extract the line number from the exec() call in the traceback if possible
            # This is tricky because the traceback includes the backend frames. 
            # We'll just return the exception message.
            return jsonify({
                "code": 0, 
                "msg": f"Runtime Error: {str(e)}", 
                "data": {"type": type(e).__name__, "details": tb}
            })
            
        # 4. Check output
        output = exec_env.get('output')
        
        if output is None:
            return jsonify({
                "code": 0, 
                "msg": "Missing 'output' variable. Your code must define an 'output' dictionary.", 
                "data": {"type": "MissingOutput"}
            })
            
        if not isinstance(output, dict):
            return jsonify({
                "code": 0, 
                "msg": f"'output' must be a dictionary, got {type(output).__name__}", 
                "data": {"type": "InvalidOutputType"}
            })
            
        # Check required fields
        if 'plots' not in output and 'signals' not in output:
             return jsonify({
                "code": 0, 
                "msg": "'output' dict should contain 'plots' or 'signals' list.", 
                "data": {"type": "InvalidOutputStructure"}
            })
            
        # Basic check for lengths
        plots = output.get('plots', [])
        signals = output.get('signals', [])
        
        for p in plots:
            if 'data' not in p:
                return jsonify({"code": 0, "msg": f"Plot '{p.get('name')}' missing 'data' field.", "data": {"type": "InvalidPlot"}})
            if len(p['data']) != len(df):
                return jsonify({
                    "code": 0, 
                    "msg": f"Plot '{p.get('name')}' data length ({len(p['data'])}) does not match DataFrame length ({len(df)}).", 
                    "data": {"type": "LengthMismatch"}
                })
                
        for s in signals:
            if 'data' not in s:
                return jsonify({"code": 0, "msg": f"Signal '{s.get('type')}' missing 'data' field.", "data": {"type": "InvalidSignal"}})
            if len(s['data']) != len(df):
                return jsonify({
                    "code": 0, 
                    "msg": f"Signal '{s.get('type')}' data length ({len(s['data'])}) does not match DataFrame length ({len(df)}).", 
                    "data": {"type": "LengthMismatch"}
                })

        return jsonify({
            "code": 1, 
            "msg": "Verification passed! Code executed successfully.", 
            "data": {
                "plots_count": len(plots),
                "signals_count": len(signals)
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
    prompt = (data.get("prompt") or "").strip()
    existing = (data.get("existingCode") or "").strip()

    if not prompt:
        # Keep SSE contract (match PHP behavior) so frontend doesn't look "stuck".
        def _err_stream():
            yield "data: " + json.dumps({"error": "提示词不能为空"}, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"

        return Response(
            _err_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # System prompt copied/adapted from the legacy PHP implementation.
    SYSTEM_PROMPT = """# Role

You are an expert Python quantitative trading developer. Your task is to write custom indicator or strategy scripts for a professional K-line chart component running in a browser (Pyodide environment).

# Context & Environment

1. **Runtime Environment**: Code runs in a browser sandbox, **network access is prohibited** (cannot use `pip` or `requests`).

2. **Pre-installed Libraries**: The system has already imported `pandas as pd` and `numpy as np`. **DO NOT** include `import pandas as pd` or `import numpy as np` in your generated code. Use `pd` and `np` directly.

3. **Input Data**: The system provides a variable `df` (Pandas DataFrame) with index from 0 to N.
   - Columns include: `df['time']` (timestamp), `df['open']`, `df['high']`, `df['low']`, `df['close']`, `df['volume']`.

# Output Requirement (Strict)

At the end of code execution, you **MUST** define a dictionary variable named `output`. The system only reads this variable to render the chart.

Additionally, you MUST define:
- my_indicator_name = "..."
- my_indicator_description = "..."

`output` MUST follow this shape:
output = {
  "name": my_indicator_name,
  "plots": [ { "name": str, "data": list, "color": "#RRGGBB", "overlay": bool, "type": "line" (optional) } ],
  "signals": [ { "type": "buy"|"sell", "text": str, "data": list, "color": "#RRGGBB" } ] (optional),
  "calculatedVars": {} (optional)
}
Where `data` lists MUST have the same length as `df` and use `None` for "no value".

Backtest/execution compatibility (recommended):
- Also set df['buy'] and df['sell'] as boolean columns (same length as df).

# Signal confirmation / execution timing (IMPORTANT)
- Signals are generally confirmed on bar close. The backtest engine may execute them on the next bar open to better match live trading and avoid look-ahead bias.

# Robustness requirements (IMPORTANT)
- Always handle NaN/inf and division-by-zero (common in RSI/BB/RSV calculations).
- Avoid overly restrictive entry/exit logic that results in zero buy or zero sell signals.
  For multi-indicator strategies, do NOT require a crossover AND extreme RSI on the same bar unless explicitly requested.
- Prefer edge-triggered signals (one-shot) to avoid repeated consecutive signals:
  buy = raw_buy.fillna(False) & (~raw_buy.shift(1).fillna(False))
  sell = raw_sell.fillna(False) & (~raw_sell.shift(1).fillna(False))
- If your final conditions produce no buys or no sells in the visible range, relax logically (e.g., remove one filter or widen thresholds).

IMPORTANT: Output Python code directly, without explanations, without descriptions, start directly with code, and do NOT use markdown code blocks like ```python.
"""

    def _template_code() -> str:
        # Fallback template that follows the project expectations.
        header = (
            f"my_indicator_name = \"Custom Indicator\"\n"
            f"my_indicator_description = \"{prompt.replace('\\n', ' ')[:200]}\"\n\n"
        )
        body = (
            "df = df.copy()\n\n"
            "# Example: robust RSI with edge-triggered buy/sell (no position management, no TP/SL on chart)\n"
            "rsi_len = 14\n"
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
            "buy = raw_buy.fillna(False) & (~raw_buy.shift(1).fillna(False))\n"
            "sell = raw_sell.fillna(False) & (~raw_sell.shift(1).fillna(False))\n"
            "df['buy'] = buy.astype(bool)\n"
            "df['sell'] = sell.astype(bool)\n\n"
            "buy_marks = [df['low'].iloc[i] * 0.995 if bool(buy.iloc[i]) else None for i in range(len(df))]\n"
            "sell_marks = [df['high'].iloc[i] * 1.005 if bool(sell.iloc[i]) else None for i in range(len(df))]\n\n"
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
        current_model = llm.get_default_model()
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
                "# Existing Code (modify based on this):\n\n```python\n"
                + existing.strip()
                + "\n```\n\n# Modification Requirements:\n\n"
                + prompt
                + "\n\nPlease generate complete new Python code based on the existing code above and my modification requirements. Output the complete Python code directly, without explanations, without segmentation."
            )

        temperature = float(os.getenv("OPENROUTER_TEMPERATURE", "0.7") or 0.7)
        
        # Call LLM using the unified API (auto-selects provider based on LLM_PROVIDER env)
        # use_json_mode=False because we want raw Python code output
        content = llm.call_llm_api(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
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

    def stream():
        # 不扣任何 QDT：开源本地版直接生成/返回代码
        try:
            code_text = _generate_code_via_llm()
        except Exception as e:
            logger.error(f"ai_generate LLM failed, fallback to template. Error: {type(e).__name__}: {e}")
            code_text = _template_code()

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
