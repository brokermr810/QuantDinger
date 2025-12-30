"""
Agent memory system (local-only).

This module stores agent experiences in SQLite and retrieves relevant past cases
to inject into prompts (RAG-style). It does NOT finetune model weights.

Retrieval (configurable):
- Vector similarity via deterministic local embeddings (default)
- Fallback to difflib text similarity when embeddings are missing

Ranking combines:
- similarity
- recency decay (half-life)
- optional returns weight
"""

import sqlite3
import json
import os
import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import difflib

from app.utils.logger import get_logger
from .embedding import EmbeddingService, cosine_sim

logger = get_logger(__name__)


class AgentMemory:
    """智能体记忆系统"""
    
    def __init__(self, agent_name: str, db_path: Optional[str] = None):
        """
        初始化记忆系统
        
        Args:
            agent_name: 智能体名称
            db_path: 数据库路径（可选）
        """
        self.agent_name = agent_name
        
        if db_path is None:
            # 默认数据库路径
            db_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'memory')
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, f'{agent_name}_memory.db')
        
        self.db_path = db_path
        self.embedder = EmbeddingService()
        self.enable_vector = os.getenv("AGENT_MEMORY_ENABLE_VECTOR", "true").lower() == "true"
        self.candidate_limit = int(os.getenv("AGENT_MEMORY_CANDIDATE_LIMIT", "500") or 500)
        self.half_life_days = float(os.getenv("AGENT_MEMORY_HALF_LIFE_DAYS", "30") or 30)
        self.w_sim = float(os.getenv("AGENT_MEMORY_W_SIM", "0.75") or 0.75)
        self.w_recency = float(os.getenv("AGENT_MEMORY_W_RECENCY", "0.20") or 0.20)
        self.w_returns = float(os.getenv("AGENT_MEMORY_W_RETURNS", "0.05") or 0.05)
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    situation TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    result TEXT,
                    returns REAL,
                    market TEXT,
                    symbol TEXT,
                    timeframe TEXT,
                    features_json TEXT,
                    embedding BLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Best-effort migration for older DBs
            # NOTE: For existing tables, we must add missing columns BEFORE creating indexes
            # that reference them (otherwise we'll hit: "no such column: market").
            cursor.execute("PRAGMA table_info(memories)")
            existing_cols = {row[1] for row in cursor.fetchall() or []}
            for col, ddl in {
                "market": "TEXT",
                "symbol": "TEXT",
                "timeframe": "TEXT",
                "features_json": "TEXT",
                "embedding": "BLOB",
            }.items():
                if col not in existing_cols:
                    cursor.execute(f"ALTER TABLE memories ADD COLUMN {col} {ddl}")

            # 创建索引（放在迁移之后，兼容旧库）
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at ON memories(created_at)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_market_symbol ON memories(market, symbol)
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"初始化记忆数据库失败: {e}")

    def _now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def _parse_ts(self, ts_val: Any) -> Optional[datetime]:
        if ts_val is None:
            return None
        if isinstance(ts_val, datetime):
            return ts_val
        s = str(ts_val)
        try:
            return datetime.fromisoformat(s.replace("Z", ""))
        except Exception:
            return None

    def _recency_score(self, created_at: Any) -> float:
        dt = self._parse_ts(created_at)
        if not dt:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (self._now_utc() - dt).total_seconds() / 86400.0)
        hl = max(0.1, float(self.half_life_days or 30.0))
        return float(math.exp(-math.log(2.0) * (age_days / hl)))

    def _returns_score(self, returns: Any) -> float:
        try:
            r = float(returns)
        except Exception:
            return 0.0
        return float(math.tanh(r / 10.0))

    def _build_embed_text(self, situation: str, recommendation: str, result: Optional[str], features_json: Optional[str]) -> str:
        return "\n".join([
            f"situation: {situation or ''}",
            f"recommendation: {recommendation or ''}",
            f"result: {result or ''}",
            f"features: {features_json or ''}",
        ])

    def add_memory(
        self,
        situation: str,
        recommendation: str,
        result: Optional[str] = None,
        returns: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        添加记忆
        
        Args:
            situation: 情况描述
            recommendation: 建议/决策
            result: 结果描述（可选）
            returns: 收益（可选）
            metadata: Optional structured metadata (market/symbol/timeframe/features...)
        """
        try:
            meta = metadata or {}
            market = (meta.get("market") or "").strip() or None
            symbol = (meta.get("symbol") or "").strip() or None
            timeframe = (meta.get("timeframe") or "").strip() or None
            features = meta.get("features") if isinstance(meta, dict) else None
            try:
                features_json = json.dumps(features, ensure_ascii=False) if features is not None else None
            except Exception:
                features_json = None

            embedding_blob = None
            if self.enable_vector:
                text = self._build_embed_text(situation, recommendation, result, features_json)
                vec = self.embedder.embed(text)
                embedding_blob = self.embedder.to_bytes(vec)

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO memories (situation, recommendation, result, returns, market, symbol, timeframe, features_json, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (situation, recommendation, result, returns, market, symbol, timeframe, features_json, embedding_blob))
            
            conn.commit()
            conn.close()
            logger.info(f"{self.agent_name} 添加新记忆")
        except Exception as e:
            logger.error(f"添加记忆失败: {e}")
    
    def get_memories(self, current_situation: str, n_matches: int = 5, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        检索相似记忆
        
        Args:
            current_situation: 当前情况描述
            n_matches: 返回的匹配数量
            
        Returns:
            匹配的记忆列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 获取所有记忆
            cursor.execute('''
                SELECT id, situation, recommendation, result, returns, created_at, market, symbol, timeframe, features_json, embedding
                FROM memories
                ORDER BY created_at DESC
                LIMIT ?
            ''', (int(self.candidate_limit),))
            
            all_memories = cursor.fetchall()
            conn.close()
            
            if not all_memories:
                return []
            
            meta = metadata or {}
            tf = (meta.get("timeframe") or "").strip()
            features = meta.get("features") if isinstance(meta, dict) else None
            try:
                q_features_json = json.dumps(features, ensure_ascii=False) if features is not None else None
            except Exception:
                q_features_json = None

            query_vec = []
            if self.enable_vector:
                query_text = self._build_embed_text(current_situation, "", "", q_features_json)
                query_vec = self.embedder.embed(query_text)

            ranked = []
            for row in all_memories:
                (
                    mem_id,
                    situation,
                    recommendation,
                    result,
                    returns,
                    created_at,
                    market,
                    symbol,
                    timeframe,
                    features_json,
                    embedding_blob,
                ) = row

                sim = 0.0
                if self.enable_vector and embedding_blob:
                    try:
                        mem_vec = self.embedder.from_bytes(embedding_blob)
                        sim = cosine_sim(query_vec, mem_vec)
                    except Exception:
                        sim = 0.0
                else:
                    sim = difflib.SequenceMatcher(None, (current_situation or "").lower(), (situation or "").lower()).ratio()

                rec = self._recency_score(created_at)
                ret = self._returns_score(returns)

                score = (self.w_sim * sim) + (self.w_recency * rec) + (self.w_returns * ret)

                if tf and timeframe and str(timeframe).strip() != tf:
                    score -= 0.15

                ranked.append({
                    'id': mem_id,
                    'matched_situation': situation,
                    'recommendation': recommendation,
                    'result': result,
                    'returns': returns,
                    'created_at': created_at,
                    'market': market,
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'features_json': features_json,
                    'score': float(score),
                    'sim': float(sim),
                    'recency': float(rec),
                })

            ranked.sort(key=lambda x: x.get('score', 0.0), reverse=True)
            return ranked[: max(0, int(n_matches or 0))]
            
        except Exception as e:
            logger.error(f"检索记忆失败: {e}")
            return []
    
    def update_memory_result(self, memory_id: int, result: str, returns: Optional[float] = None):
        """
        更新记忆的结果
        
        Args:
            memory_id: 记忆ID
            result: 结果描述
            returns: 收益
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE memories
                SET result = ?, returns = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (result, returns, memory_id))
            
            conn.commit()
            conn.close()
            logger.info(f"{self.agent_name} 更新记忆 {memory_id}")
        except Exception as e:
            logger.error(f"更新记忆失败: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取记忆统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM memories')
            total = cursor.fetchone()[0]
            
            cursor.execute('SELECT AVG(returns) FROM memories WHERE returns IS NOT NULL')
            avg_returns = cursor.fetchone()[0] or 0
            
            cursor.execute('SELECT COUNT(*) FROM memories WHERE returns > 0')
            positive = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'total_memories': total,
                'average_returns': round(avg_returns, 2),
                'positive_decisions': positive,
                'success_rate': round(positive / total * 100, 2) if total > 0 else 0
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}
