"""
Analysis Memory System 2.0
Simplified memory for fast analysis service.

Features:
1. Store analysis decisions with market context
2. Retrieve similar historical patterns
3. Track decision outcomes for learning
"""
import json
import time
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from app.utils.logger import get_logger
from app.utils.db import get_db_connection

logger = get_logger(__name__)


def _safe_json_parse(val, default=None):
    """安全解析 JSON - 处理已是 Python 对象或字符串的情况"""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val  # 已经是 Python 对象 (PostgreSQL JSONB 自动转换)
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


class AnalysisMemory:
    """
    Simple but effective memory system for AI analysis.
    Uses PostgreSQL for persistence.
    """
    
    def __init__(self):
        self._ensure_table()
    
    def _ensure_table(self):
        """Create memory table if not exists."""
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS qd_analysis_memory (
                        id SERIAL PRIMARY KEY,
                        user_id INT,
                        market VARCHAR(50) NOT NULL,
                        symbol VARCHAR(50) NOT NULL,
                        decision VARCHAR(10) NOT NULL,
                        confidence INT DEFAULT 50,
                        price_at_analysis DECIMAL(24, 8),
                        entry_price DECIMAL(24, 8),
                        stop_loss DECIMAL(24, 8),
                        take_profit DECIMAL(24, 8),
                        summary TEXT,
                        reasons JSONB,
                        risks JSONB,
                        scores JSONB,
                        indicators_snapshot JSONB,
                        created_at TIMESTAMP DEFAULT NOW(),
                        validated_at TIMESTAMP,
                        actual_outcome VARCHAR(20),
                        actual_return_pct DECIMAL(10, 4),
                        was_correct BOOLEAN,
                        user_feedback VARCHAR(20),
                        feedback_at TIMESTAMP
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_analysis_memory_symbol 
                    ON qd_analysis_memory(market, symbol);
                    
                    CREATE INDEX IF NOT EXISTS idx_analysis_memory_created 
                    ON qd_analysis_memory(created_at DESC);
                    
                    CREATE INDEX IF NOT EXISTS idx_analysis_memory_user
                    ON qd_analysis_memory(user_id);
                """)
                db.commit()
                cur.close()
        except Exception as e:
            logger.warning(f"Memory table creation skipped: {e}")
    
    def store(self, analysis_result: Dict[str, Any], user_id: int = None) -> Optional[int]:
        """
        Store an analysis result for future reference.
        
        Args:
            analysis_result: Result from FastAnalysisService.analyze()
            user_id: User ID who created this analysis
        
        Returns:
            Memory ID or None if failed
        """
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                
                # 准备数据
                market = analysis_result.get("market")
                symbol = analysis_result.get("symbol")
                decision = analysis_result.get("decision")
                confidence = analysis_result.get("confidence")
                price = analysis_result.get("market_data", {}).get("current_price")
                entry = analysis_result.get("trading_plan", {}).get("entry_price")
                stop = analysis_result.get("trading_plan", {}).get("stop_loss")
                take = analysis_result.get("trading_plan", {}).get("take_profit")
                summary = analysis_result.get("summary")
                reasons = json.dumps(analysis_result.get("reasons", []))
                risks = json.dumps(analysis_result.get("risks", []))
                scores = json.dumps(analysis_result.get("scores", {}))
                indicators = json.dumps(analysis_result.get("indicators", {}))
                raw = json.dumps(analysis_result)
                
                cur.execute("""
                    INSERT INTO qd_analysis_memory (
                        user_id, market, symbol, decision, confidence,
                        price_at_analysis, entry_price, stop_loss, take_profit,
                        summary, reasons, risks, scores, indicators_snapshot, raw_result
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (user_id, market, symbol, decision, confidence, price, entry, stop, take, 
                      summary, reasons, risks, scores, indicators, raw))
                
                # 使用 lastrowid 属性获取 ID（execute 内部已经处理了 RETURNING）
                memory_id = cur.lastrowid
                db.commit()
                cur.close()
                
                logger.info(f"Stored analysis memory #{memory_id} for {symbol} by user {user_id}")
                return memory_id
                
        except Exception as e:
            logger.error(f"Failed to store analysis memory: {e}", exc_info=True)
            return None
    
    def get_recent(self, market: str, symbol: str, days: int = 7, limit: int = 5) -> List[Dict]:
        """
        Get recent analysis history for a symbol.
        
        Args:
            market: Market type
            symbol: Symbol
            days: Look back period
            limit: Max results
        
        Returns:
            List of historical analyses
        """
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(f"""
                    SELECT 
                        id, decision, confidence, price_at_analysis,
                        summary, reasons, scores,
                        created_at, validated_at, was_correct, actual_return_pct
                    FROM qd_analysis_memory
                    WHERE market = %s AND symbol = %s
                    AND created_at > NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (market, symbol, limit))
                
                rows = cur.fetchall() or []
                cur.close()
                
                results = []
                for row in rows:
                    results.append({
                        "id": row['id'],
                        "decision": row['decision'],
                        "confidence": row['confidence'],
                        "price": float(row['price_at_analysis']) if row['price_at_analysis'] else None,
                        "summary": row['summary'],
                        "reasons": _safe_json_parse(row['reasons'], []),
                        "scores": _safe_json_parse(row['scores'], {}),
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                        "was_correct": row['was_correct'],
                        "actual_return_pct": float(row['actual_return_pct']) if row['actual_return_pct'] else None,
                    })
                
                return results
                
        except Exception as e:
            logger.error(f"Failed to get recent memories: {e}")
            return []

    def get_all_history(self, user_id: int = None, page: int = 1, page_size: int = 20) -> Dict:
        """
        Get all analysis history with pagination.
        
        Args:
            user_id: User ID filter (required to show only user's own history)
            page: Page number (1-indexed)
            page_size: Items per page
        
        Returns:
            Dict with items list and total count
        """
        try:
            offset = (page - 1) * page_size
            
            with get_db_connection() as db:
                cur = db.cursor()
                
                # Build WHERE clause based on user_id
                where_clause = "WHERE user_id = %s" if user_id else ""
                params_count = (user_id,) if user_id else ()
                
                # Get total count
                cur.execute(f"SELECT COUNT(*) as cnt FROM qd_analysis_memory {where_clause}", params_count)
                total_row = cur.fetchone()
                total = total_row['cnt'] if total_row else 0
                
                # Get paginated results
                params = (user_id, page_size, offset) if user_id else (page_size, offset)
                cur.execute(f"""
                    SELECT 
                        id, market, symbol, decision, confidence, price_at_analysis,
                        summary, reasons, scores, indicators_snapshot, raw_result,
                        created_at, validated_at, was_correct, actual_return_pct
                    FROM qd_analysis_memory
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, params)
                
                rows = cur.fetchall() or []
                cur.close()
                
                items = []
                for row in rows:
                    items.append({
                        "id": row['id'],
                        "market": row['market'],
                        "symbol": row['symbol'],
                        "decision": row['decision'],
                        "confidence": row['confidence'],
                        "price": float(row['price_at_analysis']) if row['price_at_analysis'] else None,
                        "summary": row['summary'],
                        "reasons": _safe_json_parse(row['reasons'], []),
                        "scores": _safe_json_parse(row['scores'], {}),
                        "indicators": _safe_json_parse(row['indicators_snapshot'], {}),
                        "full_result": _safe_json_parse(row['raw_result'], None),
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                        "was_correct": row['was_correct'],
                        "actual_return_pct": float(row['actual_return_pct']) if row['actual_return_pct'] else None,
                    })
                
                return {
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size
                }
                
        except Exception as e:
            logger.error(f"Failed to get all history: {e}")
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

    def delete_history(self, memory_id: int, user_id: int = None) -> bool:
        """
        Delete a history record by ID.
        
        Args:
            memory_id: The ID of the analysis memory to delete
            user_id: User ID to ensure user can only delete their own records
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                if user_id:
                    # Only delete if it belongs to the user
                    cur.execute("DELETE FROM qd_analysis_memory WHERE id = %s AND user_id = %s", (memory_id, user_id))
                else:
                    cur.execute("DELETE FROM qd_analysis_memory WHERE id = %s", (memory_id,))
                db.commit()
                affected = cur.rowcount
                cur.close()
                return affected > 0
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False
    
    def get_similar_patterns(self, market: str, symbol: str, 
                             current_indicators: Dict, limit: int = 3) -> List[Dict]:
        """
        Find historical analyses with similar technical patterns.
        
        This is a simplified version - can be enhanced with vector similarity later.
        Currently matches based on:
        - Same symbol
        - Similar RSI range (±10)
        - Same MACD signal direction
        - Validated outcomes preferred
        """
        try:
            rsi = current_indicators.get("rsi", {}).get("value", 50)
            macd_signal = current_indicators.get("macd", {}).get("signal", "neutral")
            
            with get_db_connection() as db:
                cur = db.cursor()
                
                # Simple pattern matching query
                cur.execute("""
                    SELECT 
                        id, decision, confidence, price_at_analysis,
                        summary, reasons, indicators_snapshot,
                        created_at, was_correct, actual_return_pct
                    FROM qd_analysis_memory
                    WHERE market = %s AND symbol = %s
                    AND validated_at IS NOT NULL
                    AND was_correct IS NOT NULL
                    ORDER BY 
                        CASE WHEN was_correct = true THEN 0 ELSE 1 END,
                        created_at DESC
                    LIMIT %s
                """, (market, symbol, limit * 2))  # Get more for filtering
                
                rows = cur.fetchall() or []
                cur.close()
                
                results = []
                for row in rows:
                    indicators = _safe_json_parse(row['indicators_snapshot'], {})
                    hist_rsi = indicators.get("rsi", {}).get("value", 50)
                    hist_macd = indicators.get("macd", {}).get("signal", "neutral")
                    
                    # Simple similarity check
                    rsi_similar = abs(hist_rsi - rsi) <= 15
                    macd_similar = hist_macd == macd_signal
                    
                    if rsi_similar or macd_similar:
                        results.append({
                            "id": row['id'],
                            "decision": row['decision'],
                            "confidence": row['confidence'],
                            "price": float(row['price_at_analysis']) if row['price_at_analysis'] else None,
                            "summary": row['summary'],
                            "was_correct": row['was_correct'],
                            "actual_return_pct": float(row['actual_return_pct']) if row['actual_return_pct'] else None,
                            "similarity": {
                                "rsi_match": rsi_similar,
                                "macd_match": macd_similar,
                            }
                        })
                        
                        if len(results) >= limit:
                            break
                
                return results
                
        except Exception as e:
            logger.error(f"Failed to get similar patterns: {e}")
            return []
    
    def record_feedback(self, memory_id: int, feedback: str) -> bool:
        """
        Record user feedback on an analysis.
        
        Args:
            memory_id: Analysis memory ID
            feedback: 'helpful' | 'not_helpful' | 'accurate' | 'inaccurate'
        """
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute("""
                    UPDATE qd_analysis_memory
                    SET user_feedback = %s, feedback_at = NOW()
                    WHERE id = %s
                """, (feedback, memory_id))
                db.commit()
                cur.close()
                return True
        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
            return False
    
    def validate_past_decisions(self, days_ago: int = 7) -> Dict[str, Any]:
        """
        Validate historical decisions by comparing with actual price movements.
        Run this periodically (e.g., daily) to build learning data.
        
        Args:
            days_ago: Validate decisions from N days ago
        
        Returns:
            Validation statistics
        """
        from app.services.market_data_collector import MarketDataCollector
        collector = MarketDataCollector()
        
        stats = {
            "validated": 0,
            "correct": 0,
            "incorrect": 0,
            "errors": 0,
        }
        
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                
                # Get unvalidated decisions from N days ago
                cur.execute(f"""
                    SELECT id, market, symbol, decision, price_at_analysis
                    FROM qd_analysis_memory
                    WHERE validated_at IS NULL
                    AND created_at < NOW() - INTERVAL '{int(days_ago)} days'
                    AND created_at > NOW() - INTERVAL '{int(days_ago + 1)} days'
                    LIMIT 50
                """)
                
                rows = cur.fetchall() or []
                
                for row in rows:
                    try:
                        # Get current price using MarketDataCollector
                        current_price = collector._get_price(row['market'], row['symbol'])
                        if not current_price or current_price <= 0:
                            continue
                        analysis_price = float(row['price_at_analysis'])
                        
                        if analysis_price <= 0:
                            continue
                        
                        # Calculate return
                        return_pct = ((current_price - analysis_price) / analysis_price) * 100
                        
                        # Determine if decision was correct
                        decision = row['decision']
                        was_correct = False
                        
                        if decision == 'BUY' and return_pct > 2:  # 2% threshold
                            was_correct = True
                        elif decision == 'SELL' and return_pct < -2:
                            was_correct = True
                        elif decision == 'HOLD' and abs(return_pct) <= 5:
                            was_correct = True
                        
                        # Update record
                        cur.execute("""
                            UPDATE qd_analysis_memory
                            SET validated_at = NOW(),
                                actual_return_pct = %s,
                                was_correct = %s
                            WHERE id = %s
                        """, (return_pct, was_correct, row['id']))
                        
                        stats["validated"] += 1
                        if was_correct:
                            stats["correct"] += 1
                        else:
                            stats["incorrect"] += 1
                            
                    except Exception as e:
                        logger.warning(f"Failed to validate memory {row['id']}: {e}")
                        stats["errors"] += 1
                
                db.commit()
                cur.close()
                
        except Exception as e:
            logger.error(f"Validation batch failed: {e}")
        
        accuracy = (stats["correct"] / stats["validated"] * 100) if stats["validated"] > 0 else 0
        stats["accuracy_pct"] = round(accuracy, 2)
        
        logger.info(f"Validation completed: {stats}")
        return stats
    
    def get_performance_stats(self, market: str = None, symbol: str = None, 
                              days: int = 30) -> Dict[str, Any]:
        """
        Get AI performance statistics.
        
        Returns:
            Performance metrics for display
        """
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                
                where_clauses = ["validated_at IS NOT NULL"]
                params = []
                
                if market:
                    where_clauses.append("market = %s")
                    params.append(market)
                if symbol:
                    where_clauses.append("symbol = %s")
                    params.append(symbol)
                
                # Use f-string for interval since psycopg2 doesn't support placeholder in INTERVAL
                where_clauses.append(f"created_at > NOW() - INTERVAL '{int(days)} days'")
                
                where_sql = " AND ".join(where_clauses)
                
                cur.execute(f"""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN was_correct = true THEN 1 ELSE 0 END) as correct,
                        AVG(actual_return_pct) as avg_return,
                        SUM(CASE WHEN decision = 'BUY' THEN 1 ELSE 0 END) as buy_count,
                        SUM(CASE WHEN decision = 'SELL' THEN 1 ELSE 0 END) as sell_count,
                        SUM(CASE WHEN decision = 'HOLD' THEN 1 ELSE 0 END) as hold_count,
                        SUM(CASE WHEN user_feedback = 'helpful' THEN 1 ELSE 0 END) as helpful_count,
                        SUM(CASE WHEN user_feedback IS NOT NULL THEN 1 ELSE 0 END) as feedback_count
                    FROM qd_analysis_memory
                    WHERE {where_sql}
                """, tuple(params) if params else None)
                
                row = cur.fetchone()
                cur.close()
                
                if not row or not row['total']:
                    return {
                        "total_analyses": 0,
                        "accuracy_pct": 0,
                        "avg_return_pct": 0,
                        "user_satisfaction_pct": 0,
                    }
                
                total = row['total']
                correct = row['correct'] or 0
                
                return {
                    "total_analyses": total,
                    "accuracy_pct": round((correct / total * 100) if total > 0 else 0, 2),
                    "avg_return_pct": round(float(row['avg_return'] or 0), 2),
                    "decision_distribution": {
                        "buy": row['buy_count'] or 0,
                        "sell": row['sell_count'] or 0,
                        "hold": row['hold_count'] or 0,
                    },
                    "user_satisfaction_pct": round(
                        (row['helpful_count'] / row['feedback_count'] * 100) 
                        if row['feedback_count'] and row['feedback_count'] > 0 else 0, 2
                    ),
                    "period_days": days,
                }
                
        except Exception as e:
            logger.error(f"Failed to get performance stats: {e}")
            return {
                "total_analyses": 0,
                "accuracy_pct": 0,
                "error": str(e),
            }


# Singleton
_memory_instance = None

def get_analysis_memory() -> AnalysisMemory:
    """Get singleton AnalysisMemory instance."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = AnalysisMemory()
    return _memory_instance
