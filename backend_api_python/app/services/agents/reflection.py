"""
自动反思与验证服务
用于记录分析预测，并在未来自动验证结果，实现闭环学习
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from app.utils.logger import get_logger
from .memory import AgentMemory
from .tools import AgentTools

logger = get_logger(__name__)

class ReflectionService:
    """反思服务：管理分析记录的存储和验证"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # 默认数据库路径
            db_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'memory')
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, 'reflection_records.db')
        
        self.db_path = db_path
        self.tools = AgentTools()
        self._init_database()
        
    def _init_database(self):
        """初始化数据库表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 创建分析记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    initial_price REAL,
                    decision TEXT,
                    confidence INTEGER,
                    reasoning TEXT,
                    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    target_check_date TIMESTAMP,
                    status TEXT DEFAULT 'PENDING',  -- PENDING, COMPLETED, FAILED
                    final_price REAL,
                    actual_return REAL,
                    check_result TEXT
                )
            ''')
            
            # 创建索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_status_date ON analysis_records(status, target_check_date)
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"初始化反思数据库失败: {e}")

    def record_analysis(self, market: str, symbol: str, price: float, 
                       decision: str, confidence: int, reasoning: str,
                       check_days: int = 7):
        """
        记录一次分析，以便未来验证
        
        Args:
            market: 市场
            symbol: 代码
            price: 当前价格
            decision: 决策 (BUY/SELL/HOLD)
            confidence: 置信度
            reasoning: 理由
            check_days: 几天后验证 (默认7天)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            target_date = datetime.now() + timedelta(days=check_days)
            
            cursor.execute('''
                INSERT INTO analysis_records 
                (market, symbol, initial_price, decision, confidence, reasoning, target_check_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (market, symbol, price, decision, confidence, reasoning, target_date))
            
            conn.commit()
            conn.close()
            logger.info(f"Recorded analysis for reflection: {market}:{symbol}, will verify after {check_days} day(s)")
        except Exception as e:
            logger.error(f"记录分析失败: {e}")

    def run_verification_cycle(self):
        """
        执行验证周期：检查到期的记录，验证结果，并写入记忆
        """
        logger.info("开始执行自动反思验证周期...")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. 查找所有已到期且未处理的记录
            cursor.execute('''
                SELECT id, market, symbol, initial_price, decision, confidence, reasoning, analysis_date 
                FROM analysis_records 
                WHERE status = 'PENDING' AND target_check_date <= CURRENT_TIMESTAMP
            ''')
            
            records = cursor.fetchall()
            
            if not records:
                logger.info("没有需要验证的记录")
                conn.close()
                return
            
            logger.info(f"发现 {len(records)} 条待验证记录")
            
            # 初始化记忆系统（用于写入验证结果）
            trader_memory = AgentMemory('trader_agent')
            
            for record in records:
                record_id, market, symbol, initial_price, decision, confidence, reasoning, analysis_date = record
                
                try:
                    # 2. 获取当前最新价格
                    current_price_data = self.tools.get_current_price(market, symbol)
                    current_price = current_price_data.get('price')
                    
                    if not current_price:
                        logger.warning(f"无法获取 {market}:{symbol} 的当前价格，跳过")
                        continue
                        
                    # 3. 计算收益和结果
                    if not initial_price or initial_price == 0:
                        actual_return = 0.0
                    else:
                        actual_return = (current_price - initial_price) / initial_price * 100
                    
                    # 评估结果
                    result_desc = ""
                    is_good_prediction = False
                    
                    if decision == "BUY":
                        if actual_return > 2.0:
                            result_desc = "Correct: price rose after BUY"
                            is_good_prediction = True
                        elif actual_return < -2.0:
                            result_desc = "Wrong: price fell after BUY"
                        else:
                            result_desc = "Neutral: limited price movement"
                    elif decision == "SELL":
                        if actual_return < -2.0:
                            result_desc = "Correct: price fell after SELL"
                            is_good_prediction = True
                        elif actual_return > 2.0:
                            result_desc = "Wrong: price rose after SELL"
                        else:
                            result_desc = "Neutral: limited price movement"
                    else: # HOLD
                        if -2.0 <= actual_return <= 2.0:
                            result_desc = "Correct: limited movement during HOLD"
                            is_good_prediction = True
                        else:
                            result_desc = f"Deviated: large movement during HOLD ({actual_return:.2f}%)"

                    # 4. 写入记忆系统 (Let the agent learn)
                    memory_situation = f"{market}:{symbol} auto-verified (analysis_date: {analysis_date})"
                    memory_recommendation = f"Decision: {decision} (confidence {confidence}), reasoning: {(reasoning or '')[:120]}"
                    memory_result = f"Verification: {result_desc}; return={actual_return:.2f}% (initial {initial_price} -> final {current_price})"
                    
                    trader_memory.add_memory(
                        memory_situation,
                        memory_recommendation,
                        memory_result,
                        actual_return,
                        metadata={
                            "market": market,
                            "symbol": symbol,
                            "timeframe": "1D",
                            "features": {
                                "source": "auto_verify",
                                "decision": decision,
                                "confidence": confidence,
                                "initial_price": initial_price,
                                "final_price": current_price,
                                "analysis_date": str(analysis_date),
                                "result_desc": result_desc,
                                "is_good_prediction": bool(is_good_prediction),
                            },
                        }
                    )
                    
                    # 5. 更新记录状态
                    cursor.execute('''
                        UPDATE analysis_records 
                        SET status = 'COMPLETED', final_price = ?, actual_return = ?, check_result = ?
                        WHERE id = ?
                    ''', (current_price, actual_return, result_desc, record_id))
                    
                    conn.commit()
                    logger.info(f"验证完成 {market}:{symbol}: {result_desc}")
                    
                except Exception as inner_e:
                    logger.error(f"处理记录 {record_id} 失败: {inner_e}")
                    # 标记为失败，避免重复处理
                    # cursor.execute("UPDATE analysis_records SET status = 'FAILED' WHERE id = ?", (record_id,))
                    # conn.commit()
            
            conn.close()
            logger.info("反思验证周期结束")
            
        except Exception as e:
            logger.error(f"执行验证周期失败: {e}")

