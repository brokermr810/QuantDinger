"""
智能体基类
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import os
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BaseAgent(ABC):
    """智能体基类，所有分析智能体都继承此类"""
    
    def __init__(self, name: str, memory: Optional[Any] = None):
        """
        初始化智能体
        
        Args:
            name: 智能体名称
            memory: 记忆系统实例（可选）
        """
        self.name = name
        self.memory = memory
        self.logger = get_logger(f"{__name__}.{name}")
    
    @abstractmethod
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行分析任务
        
        Args:
            context: 分析上下文，包含市场、代码、基础数据等
            
        Returns:
            分析结果字典
        """
        pass
    
    def get_memories(self, situation: str, n_matches: Optional[int] = None, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        从记忆中检索相似情况
        
        Args:
            situation: 当前情况描述
            n_matches: 返回的匹配数量
            
        Returns:
            匹配的历史记录列表
        """
        if n_matches is None:
            try:
                n_matches = int(os.getenv("AGENT_MEMORY_TOP_K", "5") or 5)
            except Exception:
                n_matches = 5
        if self.memory:
            # New memory API supports metadata; older implementations will ignore extra args.
            try:
                return self.memory.get_memories(situation, n_matches=n_matches, metadata=metadata)
            except TypeError:
                return self.memory.get_memories(situation, n_matches=n_matches)
        return []
    
    def format_memories_for_prompt(self, memories: List[Dict[str, Any]]) -> str:
        """
        格式化记忆为提示词
        
        Args:
            memories: 记忆列表
            
        Returns:
            格式化的字符串
        """
        if not memories:
            return "No prior experience available."

        lines = ["Prior experience (most relevant first):"]
        for i, mem in enumerate(memories, 1):
            rec = mem.get("recommendation") or "N/A"
            res = mem.get("result") or ""
            ret = mem.get("returns")
            created_at = mem.get("created_at")
            # Keep created_at as-is (SQLite string), but include it for traceability.
            meta_bits = []
            if created_at:
                meta_bits.append(f"at {created_at}")
            if ret is not None and ret != "":
                meta_bits.append(f"returns={ret}%")
            meta_s = f" ({', '.join(meta_bits)})" if meta_bits else ""

            if res:
                lines.append(f"{i}. {rec}{meta_s}\n   outcome: {res}")
            else:
                lines.append(f"{i}. {rec}{meta_s}")

        return "\n".join(lines)
