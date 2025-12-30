"""
Trader agent.
Synthesizes all analysis outputs and produces a final trading decision.
"""
import json
from typing import Dict, Any
from .base_agent import BaseAgent
from app.services.llm import LLMService

logger = __import__('app.utils.logger', fromlist=['get_logger']).get_logger(__name__)


class TraderAgent(BaseAgent):
    """Trader agent."""
    
    def __init__(self, memory=None):
        super().__init__("TraderAgent", memory)
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Make a final trading decision."""
        market = context.get('market')
        symbol = context.get('symbol')
        language = context.get('language', 'zh-CN')
        model = context.get('model')
        
        # Inputs
        market_report = context.get('market_report', {})
        fundamental_report = context.get('fundamental_report', {})
        news_report = context.get('news_report', {})
        sentiment_report = context.get('sentiment_report', {})
        risk_report = context.get('risk_report', {})
        
        # Debate outputs
        bull_argument = context.get('bull_argument', {})
        bear_argument = context.get('bear_argument', {})
        research_decision = context.get('research_decision', '')
        
        # Memory
        situation = f"{market}:{symbol} trading decision"
        memory_meta = {
            "market": market,
            "symbol": symbol,
            "timeframe": context.get("timeframe"),
            "features": context.get("memory_features") or {},
        }
        memories = self.get_memories(situation, n_matches=None, metadata=memory_meta)
        memory_prompt = self.format_memories_for_prompt(memories)
        
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a Trader, needing to make a final trading decision based on all analysis results.
{lang_instruction}

Your tasks:
1. Synthesize analysis results from all dimensions.
2. Consider both bullish and bearish arguments.
3. Make a clear trading decision: BUY, SELL, or HOLD.
4. Provide a detailed trading plan.
5. Learn from historical experience: {memory_prompt}
6. **Confidence Score**: Evaluate your confidence in the decision (0-100). Be realistic. If the signals are mixed, confidence should be lower (e.g., 40-60). Only use high confidence (>80) for very clear strong signals. Do NOT default to 85.

Please return in JSON format as follows:
{{
  "decision": "BUY/SELL/HOLD",
  "confidence": 85,
  "reasoning": "Reason for decision...",
  "trading_plan": {{
    "entry_price": "Suggested entry price",
    "stop_loss": "Stop loss price",
    "take_profit": "Take profit price",
    "position_size": "Suggested position size"
  }},
  "report": "Detailed trading plan report..."
}}"""

        user_prompt = f"""Based on all the following analyses, make a trading decision for {symbol} in {market} market:

**Market Technical Analysis:**
{json.dumps(market_report.get('data', {}), ensure_ascii=False, indent=2) if market_report else 'No Data'}

**Fundamental Analysis:**
{json.dumps(fundamental_report.get('data', {}), ensure_ascii=False, indent=2) if fundamental_report else 'No Data'}

**News Analysis:**
{json.dumps(news_report.get('data', {}), ensure_ascii=False, indent=2) if news_report else 'No Data'}

**Sentiment Analysis:**
{json.dumps(sentiment_report.get('data', {}), ensure_ascii=False, indent=2) if sentiment_report else 'No Data'}

**Risk Analysis:**
{json.dumps(risk_report.get('data', {}), ensure_ascii=False, indent=2) if risk_report else 'No Data'}

**Bullish Argument:**
{json.dumps(bull_argument.get('data', {}), ensure_ascii=False, indent=2) if bull_argument else 'No Data'}

**Bearish Argument:**
{json.dumps(bear_argument.get('data', {}), ensure_ascii=False, indent=2) if bear_argument else 'No Data'}

**Research Manager Decision:**
{research_decision if research_decision else 'No Data'}

Please make a clear trading decision (BUY/SELL/HOLD) and provide a detailed trading plan."""

        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {
                "decision": "HOLD",
                "confidence": 50,
                "reasoning": "",
                "trading_plan": {},
                "report": "Failed to parse trader decision"
            },
            model=model
        )
        
        return {
            "type": "trader",
            "data": result
        }
    
    def _get_language_instruction(self, language: str) -> str:
        language_map = {
            'zh-CN': 'Answer in Simplified Chinese.',
            'zh-TW': 'Answer in Traditional Chinese.',
            'en-US': 'Answer in English.',
            'ja-JP': 'Answer in Japanese.',
            'ko-KR': 'Answer in Korean.',
            'vi-VN': 'Answer in Vietnamese.',
            'th-TH': 'Answer in Thai.',
            'ar-SA': 'Answer in Arabic.',
            'fr-FR': 'Answer in French.',
            'de-DE': 'Answer in German.'
        }
        return language_map.get(language, 'Answer in English.')
