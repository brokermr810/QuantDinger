"""
Analysis API routes (local-only).
Implements multi-dimensional analysis plus lightweight task/history APIs for the frontend.
"""
from flask import Blueprint, request, jsonify, Response
import json
import traceback
import time

from app.services.analysis import AnalysisService, reflect_analysis
from app.utils.logger import get_logger
from app.utils.db import get_db_connection
from app.utils.language import detect_request_language

logger = get_logger(__name__)

analysis_bp = Blueprint('analysis', __name__)
DEFAULT_USER_ID = 1

def _now_ts() -> int:
    return int(time.time())

def _normalize_symbol(symbol: str) -> str:
    return (symbol or '').strip().upper()

def _store_task(market: str, symbol: str, model: str, language: str, status: str, result: dict = None, error_message: str = "") -> int:
    now = _now_ts()
    result_json = json.dumps(result or {}, ensure_ascii=False)
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            """
            INSERT INTO qd_analysis_tasks (user_id, market, symbol, model, language, status, result_json, error_message, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (DEFAULT_USER_ID, market, symbol, model or '', language or 'en-US', status, result_json, error_message or '', now, now if status in ['completed', 'failed'] else None)
        )
        task_id = cur.lastrowid
        db.commit()
        cur.close()
    return int(task_id)

def _get_task(task_id: int) -> dict:
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute("SELECT * FROM qd_analysis_tasks WHERE id = ? AND user_id = ?", (task_id, DEFAULT_USER_ID))
        row = cur.fetchone()
        cur.close()
    return row or None

def _parse_result_json(row: dict) -> dict:
    if not row:
        return {}
    raw = row.get('result_json') or ''
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


@analysis_bp.route('/multi', methods=['POST'])
@analysis_bp.route('/multiAnalysis', methods=['POST'])  # compatibility with legacy naming
def multi_analysis():
    """
    Multi-dimensional analysis.

    Request body:
        market: Market (AShare, USStock, HShare, Crypto, Forex, Futures)
        symbol: Symbol
        language: Optional; if omitted we will detect from request headers (X-App-Lang / Accept-Language)
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'code': 0,
                'msg': 'Request body is required',
                'data': None
            }), 400
        
        market = data.get('market', '')
        symbol = data.get('symbol', '')
        language = detect_request_language(request, body=data, default='en-US')
        model = data.get('model', None)
        use_multi_agent = data.get('use_multi_agent', None)  # None -> use backend default
        timeframe = data.get('timeframe', '1D')
        
        if not symbol or not market:
            return jsonify({
                'code': 0,
                'msg': 'Missing required parameters',
                'data': None
            }), 400
        
        # Normalize/defend input for local-only mode.
        market = str(market).strip()
        symbol = _normalize_symbol(symbol)
        language = str(language or 'en-US')
        model = str(model) if model else None

        logger.info(f"Analyze request: {market}:{symbol}, use_multi_agent={use_multi_agent}, model={model}")
        
        # Create analysis service instance (local-only; no paid credits)
        service = AnalysisService(use_multi_agent=use_multi_agent)
        result = service.analyze(market, symbol, language, model=model, timeframe=timeframe)

        # Persist as "completed" history (no paid credits in local mode).
        task_id = _store_task(market, symbol, model or '', language, 'completed', result=result, error_message='')

        # Keep frontend compatible: if it expects task polling, it can still use the id.
        result_payload = dict(result or {})
        result_payload['task_id'] = task_id

        return jsonify({'code': 1, 'msg': 'success', 'data': result_payload})
        
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            market = (data or {}).get('market', '') if 'data' in locals() else ''
            symbol = (data or {}).get('symbol', '') if 'data' in locals() else ''
            language = detect_request_language(request, body=(data or {}), default='en-US')
            model = (data or {}).get('model', '') if 'data' in locals() else ''
            market = str(market).strip()
            symbol = _normalize_symbol(symbol)
            _store_task(market, symbol, model, language, 'failed', result={}, error_message=str(e))
        except Exception:
            pass
        return jsonify({
            'code': 0,
            'msg': f'Analysis failed: {str(e)}',
            'data': None
        }), 500


@analysis_bp.route('/getTaskStatus', methods=['POST'])
def get_task_status():
    """Frontend compatibility: return task status + result by task_id."""
    try:
        data = request.get_json() or {}
        task_id = int(data.get('task_id') or 0)
        if not task_id:
            return jsonify({'code': 0, 'msg': 'Missing task_id', 'data': None}), 400

        row = _get_task(task_id)
        if not row:
            return jsonify({'code': 0, 'msg': 'Task not found', 'data': None}), 404

        payload = {
            'id': row.get('id'),
            'market': row.get('market'),
            'symbol': row.get('symbol'),
            'status': row.get('status'),
            'error_message': row.get('error_message') or '',
            'result': _parse_result_json(row)
        }
        return jsonify({'code': 1, 'msg': 'success', 'data': payload})
    except Exception as e:
        logger.error(f"get_task_status failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@analysis_bp.route('/getHistoryList', methods=['POST'])
def get_history_list():
    """Frontend compatibility: paginated analysis history for the single user."""
    try:
        data = request.get_json() or {}
        page = int(data.get('page') or 1)
        pagesize = int(data.get('pagesize') or 20)
        page = max(page, 1)
        pagesize = min(max(pagesize, 1), 100)
        offset = (page - 1) * pagesize

        with get_db_connection() as db:
            cur = db.cursor()
            cur.execute("SELECT COUNT(1) as cnt FROM qd_analysis_tasks WHERE user_id = ?", (DEFAULT_USER_ID,))
            total = int((cur.fetchone() or {}).get('cnt') or 0)
            cur.execute(
                """
                SELECT id, market, symbol, model, status, error_message, created_at, completed_at, result_json
                FROM qd_analysis_tasks
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (DEFAULT_USER_ID, pagesize, offset)
            )
            rows = cur.fetchall() or []
            cur.close()

        out = []
        for r in rows:
            has_result = bool((r.get('result_json') or '').strip())
            out.append({
                'id': r.get('id'),
                'market': r.get('market'),
                'symbol': r.get('symbol'),
                'model': r.get('model') or '',
                'status': r.get('status'),
                'has_result': has_result,
                'error_message': r.get('error_message') or '',
                'createtime': int(r.get('created_at') or 0),
                'completetime': int(r.get('completed_at') or 0) if r.get('completed_at') else None
            })

        return jsonify({'code': 1, 'msg': 'success', 'data': {'list': out, 'total': total}})
    except Exception as e:
        logger.error(f"get_history_list failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': {'list': [], 'total': 0}}), 500


@analysis_bp.route('/createTask', methods=['POST'])
def create_task():
    """
    Compatibility endpoint for legacy frontend.
    In local-only mode we do not run a separate async worker; we create a completed task record immediately.
    """
    try:
        data = request.get_json() or {}
        market = str((data.get('market') or '')).strip()
        symbol = _normalize_symbol(data.get('symbol'))
        language = detect_request_language(request, body=data, default='en-US')
        model = data.get('model') or ''

        if not market or not symbol:
            return jsonify({'code': 0, 'msg': 'Missing market or symbol', 'data': None}), 400

        # Create a placeholder "pending" task so frontend can show task_id if it needs it.
        task_id = _store_task(market, symbol, str(model), language, 'pending', result={}, error_message='')
        return jsonify({'code': 1, 'msg': 'success', 'data': {'task_id': task_id, 'status': 'pending'}})
    except Exception as e:
        logger.error(f"create_task failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'code': 0, 'msg': str(e), 'data': None}), 500


@analysis_bp.route('/stream', methods=['POST'])
def stream_analysis():
    """Streaming analysis (SSE)."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'code': 0, 'msg': 'Request body is required'}), 400
        
        market = data.get('market', '')
        symbol = data.get('symbol', '')
        language = detect_request_language(request, body=data, default='en-US')
        use_multi_agent = data.get('use_multi_agent', None)
        timeframe = data.get('timeframe', '1D')
        
        def generate():
            try:
                yield f"data: {json.dumps({'status': 'started', 'message': 'Analysis started'})}\n\n"
                
                service = AnalysisService(use_multi_agent=use_multi_agent)
                result = service.analyze(market, symbol, language, timeframe=timeframe)
                
                yield f"data: {json.dumps({'status': 'completed', 'data': result})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
        
        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )
        
    except Exception as e:
        logger.error(f"Streaming analysis failed: {str(e)}")
        return jsonify({'code': 0, 'msg': str(e)}), 500


@analysis_bp.route('/reflect', methods=['POST'])
def reflect():
    """
    Reflection API.
    Learn from post-trade outcomes and update agent memory (local-only).

    Body:
        market: Market
        symbol: Symbol
        decision: BUY/SELL/HOLD
        returns: Optional return percentage
        result: Optional free-text outcome
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'code': 0,
                'msg': 'Request body is required',
                'data': None
            }), 400
        
        market = data.get('market', '')
        symbol = data.get('symbol', '')
        decision = data.get('decision', '')
        returns = data.get('returns', None)
        result = data.get('result', None)
        
        if not symbol or not market or not decision:
            return jsonify({
                'code': 0,
                'msg': 'Missing required parameters (market, symbol, decision)',
                'data': None
            }), 400
        
        logger.info(f"Reflection: {market}:{symbol}, decision={decision}, returns={returns}")
        
        reflect_analysis(market, symbol, decision, returns, result)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': None
        })
        
    except Exception as e:
        logger.error(f"Reflection failed: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Reflection failed: {str(e)}',
            'data': None
        }), 500

