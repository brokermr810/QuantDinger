"""
Fast Analysis API Routes

New high-performance analysis endpoints that replace the slow multi-agent system.
"""
from flask import Blueprint, request, jsonify, g

from app.utils.auth import login_required
from app.utils.logger import get_logger
from app.services.fast_analysis import get_fast_analysis_service
from app.services.analysis_memory import get_analysis_memory

logger = get_logger(__name__)

fast_analysis_bp = Blueprint('fast_analysis', __name__)


@fast_analysis_bp.route('/analyze', methods=['POST'])
@login_required
def analyze():
    """
    Fast AI analysis for any symbol.
    
    POST /api/fast-analysis/analyze
    Body: {
        "market": "Crypto" | "USStock" | "AShare" | "Forex" | ...,
        "symbol": "BTC/USDT" | "AAPL" | ...,
        "language": "zh-CN" | "en-US" (optional),
        "model": "openai/gpt-4o" (optional),
        "timeframe": "1D" (optional)
    }
    
    Returns:
        Fast analysis result with actionable recommendations.
    """
    try:
        data = request.get_json() or {}
        
        market = (data.get('market') or '').strip()
        symbol = (data.get('symbol') or '').strip()
        language = data.get('language', 'en-US')
        model = data.get('model')
        timeframe = data.get('timeframe', '1D')
        
        if not market or not symbol:
            return jsonify({
                'code': 0,
                'msg': 'market and symbol are required',
                'data': None
            }), 400
        
        # Get current user's ID to associate analysis with user
        user_id = getattr(g, 'user_id', None)
        
        service = get_fast_analysis_service()
        result = service.analyze(
            market=market,
            symbol=symbol,
            language=language,
            model=model,
            timeframe=timeframe,
            user_id=user_id
        )
        
        if result.get('error'):
            return jsonify({
                'code': 0,
                'msg': result['error'],
                'data': result
            }), 500
        
        # memory_id is already set in service.analyze() -> _store_analysis_memory()
        # No need to store again here (would create duplicates)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': result
        })
        
    except Exception as e:
        logger.error(f"Fast analysis API failed: {e}", exc_info=True)
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500


@fast_analysis_bp.route('/analyze-legacy', methods=['POST'])
@login_required
def analyze_legacy():
    """
    Fast analysis with legacy format output.
    For backward compatibility with existing frontend.
    
    POST /api/fast-analysis/analyze-legacy
    Body: Same as /analyze
    
    Returns:
        Result in multi-agent format for frontend compatibility.
    """
    try:
        data = request.get_json() or {}
        
        market = (data.get('market') or '').strip()
        symbol = (data.get('symbol') or '').strip()
        language = data.get('language', 'en-US')
        model = data.get('model')
        timeframe = data.get('timeframe', '1D')
        
        if not market or not symbol:
            return jsonify({
                'code': 0,
                'msg': 'market and symbol are required',
                'data': None
            }), 400
        
        service = get_fast_analysis_service()
        result = service.analyze_legacy_format(
            market=market,
            symbol=symbol,
            language=language,
            model=model,
            timeframe=timeframe
        )
        
        if result.get('error'):
            return jsonify({
                'code': 0,
                'msg': result['error'],
                'data': result
            }), 500
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': result
        })
        
    except Exception as e:
        logger.error(f"Fast analysis legacy API failed: {e}", exc_info=True)
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500


@fast_analysis_bp.route('/history', methods=['GET'])
@login_required
def get_history():
    """
    Get analysis history for a symbol.
    
    GET /api/fast-analysis/history?market=Crypto&symbol=BTC/USDT&days=7&limit=10
    """
    try:
        market = request.args.get('market', '').strip()
        symbol = request.args.get('symbol', '').strip()
        days = int(request.args.get('days', 7))
        limit = min(int(request.args.get('limit', 10)), 50)
        
        if not market or not symbol:
            return jsonify({
                'code': 0,
                'msg': 'market and symbol are required',
                'data': None
            }), 400
        
        memory = get_analysis_memory()
        history = memory.get_recent(market, symbol, days, limit)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': {
                'items': history,
                'total': len(history)
            }
        })
        
    except Exception as e:
        logger.error(f"Get history failed: {e}")
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500


@fast_analysis_bp.route('/history/all', methods=['GET'])
@login_required
def get_all_history():
    """
    Get all analysis history with pagination.
    
    GET /api/fast-analysis/history/all?page=1&pagesize=20
    """
    try:
        page = int(request.args.get('page', 1))
        pagesize = min(int(request.args.get('pagesize', 20)), 50)
        
        # Get current user's ID to filter history
        user_id = getattr(g, 'user_id', None)
        
        memory = get_analysis_memory()
        result = memory.get_all_history(user_id=user_id, page=page, page_size=pagesize)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': {
                'list': result['items'],
                'total': result['total'],
                'page': result['page'],
                'pagesize': result['page_size']
            }
        })
        
    except Exception as e:
        logger.error(f"Get all history failed: {e}")
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500


@fast_analysis_bp.route('/history/<int:memory_id>', methods=['DELETE'])
@login_required
def delete_history(memory_id: int):
    """
    Delete a history record.
    
    DELETE /api/fast-analysis/history/123
    """
    try:
        # Get current user's ID to ensure they can only delete their own records
        user_id = getattr(g, 'user_id', None)
        
        memory = get_analysis_memory()
        success = memory.delete_history(memory_id, user_id=user_id)
        
        if success:
            return jsonify({
                'code': 1,
                'msg': 'Deleted successfully',
                'data': None
            })
        else:
            return jsonify({
                'code': 0,
                'msg': 'Record not found or no permission',
                'data': None
            }), 404
        
    except Exception as e:
        logger.error(f"Delete history failed: {e}")
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500


@fast_analysis_bp.route('/feedback', methods=['POST'])
@login_required
def submit_feedback():
    """
    Submit user feedback on an analysis.
    
    POST /api/fast-analysis/feedback
    Body: {
        "memory_id": 123,
        "feedback": "helpful" | "not_helpful" | "accurate" | "inaccurate"
    }
    """
    try:
        data = request.get_json() or {}
        
        memory_id = int(data.get('memory_id', 0))
        feedback = (data.get('feedback') or '').strip()
        
        if not memory_id or not feedback:
            return jsonify({
                'code': 0,
                'msg': 'memory_id and feedback are required',
                'data': None
            }), 400
        
        valid_feedback = ['helpful', 'not_helpful', 'accurate', 'inaccurate']
        if feedback not in valid_feedback:
            return jsonify({
                'code': 0,
                'msg': f'feedback must be one of: {valid_feedback}',
                'data': None
            }), 400
        
        memory = get_analysis_memory()
        success = memory.record_feedback(memory_id, feedback)
        
        return jsonify({
            'code': 1 if success else 0,
            'msg': 'success' if success else 'failed',
            'data': None
        })
        
    except Exception as e:
        logger.error(f"Submit feedback failed: {e}")
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500


@fast_analysis_bp.route('/performance', methods=['GET'])
@login_required
def get_performance():
    """
    Get AI analysis performance statistics.
    
    GET /api/fast-analysis/performance?market=Crypto&symbol=BTC/USDT&days=30
    """
    try:
        market = request.args.get('market', '').strip() or None
        symbol = request.args.get('symbol', '').strip() or None
        days = int(request.args.get('days', 30))
        
        memory = get_analysis_memory()
        stats = memory.get_performance_stats(market, symbol, days)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': stats
        })
        
    except Exception as e:
        logger.error(f"Get performance failed: {e}")
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500


@fast_analysis_bp.route('/similar-patterns', methods=['GET'])
@login_required
def get_similar_patterns():
    """
    Get similar historical patterns for current market conditions.
    
    GET /api/fast-analysis/similar-patterns?market=Crypto&symbol=BTC/USDT
    """
    try:
        market = request.args.get('market', '').strip()
        symbol = request.args.get('symbol', '').strip()
        
        if not market or not symbol:
            return jsonify({
                'code': 0,
                'msg': 'market and symbol are required',
                'data': None
            }), 400
        
        # Get current indicators
        service = get_fast_analysis_service()
        data = service._collect_market_data(market, symbol)
        indicators = data.get('indicators', {})
        
        # Find similar patterns
        memory = get_analysis_memory()
        patterns = memory.get_similar_patterns(market, symbol, indicators)
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': {
                'patterns': patterns,
                'current_indicators': {
                    'rsi': indicators.get('rsi', {}).get('value'),
                    'macd_signal': indicators.get('macd', {}).get('signal'),
                    'trend': indicators.get('moving_averages', {}).get('trend'),
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Get similar patterns failed: {e}")
        return jsonify({
            'code': 0,
            'msg': str(e),
            'data': None
        }), 500
