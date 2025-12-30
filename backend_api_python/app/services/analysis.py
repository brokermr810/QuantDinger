"""
Multi-dimensional analysis service.
Uses OpenRouter via the internal LLMService and the multi-agent coordinator.
Local-only: this project does not implement any paid/credit system itself.
"""
import json
import traceback
from typing import Dict, Any, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class AnalysisService:
    """Multi-dimensional analyzer powered by agent coordinator."""
    
    # Class-level guard to avoid circular-init recursion
    _initializing = False

    def __init__(self, use_multi_agent: bool = None):
        """
        Args:
            use_multi_agent: Deprecated; kept for frontend compatibility
        """
        # Avoid circular-init recursion
        if AnalysisService._initializing:
            logger.warning("AnalysisService is initializing; skipping duplicate initialization")
            self.coordinator = None
            return
        
        self.coordinator = None
        
        try:
            # Mark initializing
            AnalysisService._initializing = True
            
            # Lazy import to avoid circular imports
            from app.services.agents.coordinator import AgentCoordinator
            import os
            enable_memory = os.getenv("ENABLE_AGENT_MEMORY", "true").lower() == "true"
            self.coordinator = AgentCoordinator(
                enable_memory=enable_memory,
                max_debate_rounds=2
            )
            logger.info("Multi-agent coordinator initialized")
            
        except Exception as e:
            logger.error(f"Coordinator init failed: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            self.coordinator = None
        finally:
            AnalysisService._initializing = False

    def analyze(self, market: str, symbol: str, language: str = 'en-US', model: str = None, timeframe: str = "1D") -> Dict[str, Any]:
        """
        Args:
            market: Market (AShare, USStock, HShare, Crypto, Forex, Futures)
            symbol: Symbol
            language: Output language tag (e.g. en-US, zh-CN, zh-TW)
            model: Optional OpenRouter model id
        Returns:
            Result dict
        """
        logger.info(f"Starting analysis {market}:{symbol}, language={language}, mode=multi-agent")

        # Default result structure (keeps frontend compatible even when coordinator fails).
        result = {
            "overview": {"report": "Initializing..."},
            "fundamental": {"report": "Initializing..."},
            "technical": {"report": "Initializing..."},
            "news": {"report": "Initializing..."},
            "sentiment": {"report": "Initializing..."},
            "risk": {"report": "Initializing..."},
            "error": None
        }

        if not self.coordinator:
            result["error"] = "Analysis service is not ready (coordinator init failed)"
            return result

        try:
            logger.info(f"Run coordinator: {market}:{symbol}")
            agent_result = self.coordinator.run_analysis(market, symbol, language, model=model, timeframe=timeframe)
            
            logger.info(f"Coordinator result keys: {list(agent_result.keys())}")
            
            # Validate expected keys (defensive)
            debate = agent_result.get("debate", {})
            trader_decision = agent_result.get("trader_decision", {})
            risk_debate = agent_result.get("risk_debate", {})
            final_decision = agent_result.get("final_decision", {})
            
            # Keep frontend-compatible shape and fill defaults if empty
            if "debate" in agent_result and "trader_decision" in agent_result and "risk_debate" in agent_result and "final_decision" in agent_result:
                if not debate or (isinstance(debate, dict) and len(debate) == 0):
                    logger.warning("debate is empty; using defaults")
                    agent_result["debate"] = {"bull": {}, "bear": {}, "research_decision": "Analyzing..."}
                if not trader_decision or (isinstance(trader_decision, dict) and len(trader_decision) == 0):
                    logger.warning("trader_decision is empty; using defaults")
                    agent_result["trader_decision"] = {"decision": "HOLD", "confidence": 50, "reasoning": "Analyzing..."}
                if not risk_debate or (isinstance(risk_debate, dict) and len(risk_debate) == 0):
                    logger.warning("risk_debate is empty; using defaults")
                    agent_result["risk_debate"] = {"risky": {}, "neutral": {}, "safe": {}}
                if not final_decision or (isinstance(final_decision, dict) and len(final_decision) == 0):
                    logger.warning("final_decision is empty; using defaults")
                    agent_result["final_decision"] = {"decision": "HOLD", "confidence": 50, "reasoning": "Analyzing..."}
                
                return agent_result
            else:
                logger.warning("Coordinator result format is incomplete; filling defaults")
                return {
                    "overview": agent_result.get("overview", {"report": "Analyzing..."}),
                    "fundamental": agent_result.get("fundamental", {"report": "Analyzing..."}),
                    "technical": agent_result.get("technical", {"report": "Analyzing..."}),
                    "news": agent_result.get("news", {"report": "Analyzing..."}),
                    "sentiment": agent_result.get("sentiment", {"report": "Analyzing..."}),
                    "risk": agent_result.get("risk", {"report": "Analyzing..."}),
                    "debate": agent_result.get("debate", {"bull": {}, "bear": {}, "research_decision": "Analyzing..."}),
                    "trader_decision": agent_result.get("trader_decision", {"decision": "HOLD", "confidence": 50, "reasoning": "Analyzing..."}),
                    "risk_debate": agent_result.get("risk_debate", {"risky": {}, "neutral": {}, "safe": {}}),
                    "final_decision": agent_result.get("final_decision", {"decision": "HOLD", "confidence": 50, "reasoning": "Analyzing..."}),
                    "error": agent_result.get("error")
                }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Analysis failed {market}:{symbol} - {error_msg}")
            
            # If OpenRouter returns 402, it's an upstream billing/credit issue (not a QuantDinger fee).
            if "402" in error_msg or "Payment Required" in error_msg:
                result["error"] = f"OpenRouter returned 402 (billing/credits). Please check your OpenRouter account. Details: {error_msg}"
            else:
                result["error"] = f"Analysis failed: {error_msg}"
                
            return result


def multi_analysis(market: str, symbol: str, language: str = 'en-US', use_multi_agent: bool = None) -> Dict[str, Any]:
    """
    Convenience entrypoint for multi-dimensional analysis.

    Args:
        market: Market (AShare, USStock, HShare, Crypto, Forex, Futures)
        symbol: Symbol
        language: Output language tag
        use_multi_agent: Deprecated; kept for compatibility
    """
    analyzer = AnalysisService()
    return analyzer.analyze(market, symbol, language)


def reflect_analysis(market: str, symbol: str, decision: str, returns: float = None, result: str = None):
    """
    Reflection hook: learn from post-trade outcomes (local-only).

    Args:
        market: Market
        symbol: Symbol
        decision: Decision (BUY/SELL/HOLD)
        returns: Return percentage
        result: Free-text outcome
    """
    try:
        analyzer = AnalysisService()
        if analyzer.coordinator:
            analyzer.coordinator.reflect_and_learn(market, symbol, decision, returns, result)
            logger.info(f"Reflection completed: {market}:{symbol}")
    except Exception as e:
        logger.error(f"Reflection failed: {e}")
