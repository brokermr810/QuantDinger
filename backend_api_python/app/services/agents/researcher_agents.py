"""
Researcher agents.
Includes: bull researcher and bear researcher.
"""
import json
from typing import Dict, Any
from .base_agent import BaseAgent
from app.services.llm import LLMService

logger = __import__('app.utils.logger', fromlist=['get_logger']).get_logger(__name__)


class BullResearcher(BaseAgent):
    """Bullish researcher."""
    
    def __init__(self, memory=None):
        super().__init__("BullResearcher", memory)
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Construct the bull case."""
        market = context.get('market')
        symbol = context.get('symbol')
        language = context.get('language', 'zh-CN')
        model = context.get('model')
        
        # Inputs
        market_report = context.get('market_report', {})
        fundamental_report = context.get('fundamental_report', {})
        news_report = context.get('news_report', {})
        sentiment_report = context.get('sentiment_report', {})
        
        # Memory
        situation = f"{market}:{symbol} bull case"
        memory_meta = {
            "market": market,
            "symbol": symbol,
            "timeframe": context.get("timeframe"),
            "features": context.get("memory_features") or {},
        }
        memories = self.get_memories(situation, n_matches=None, metadata=memory_meta)
        memory_prompt = self.format_memories_for_prompt(memories)
        
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a Bullish Analyst, constructing a bullish argument for an investment decision. Your tasks are:
{lang_instruction}
1. Highlight growth potential, competitive advantages, and positive market indicators.
2. Use the provided research and data to build a strong argument.
3. Effectively address/counter bearish viewpoints.
4. Learn from historical experience: {memory_prompt}
5. **Confidence Score**: Evaluate your confidence in the bullish case (0-100). Be realistic. If the data is mixed or weak, lower your confidence. Do NOT default to 75.

Please return in JSON format as follows:
{{
  "argument": "Detailed bullish argument...",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "confidence": 75
}}"""

        user_prompt = f"""Based on the following analysis reports, construct a bullish argument for {symbol} in {market} market:

**Market Technical Analysis:**
{json.dumps(market_report.get('data', {}), ensure_ascii=False, indent=2) if market_report else 'No Data'}

**Fundamental Analysis:**
{json.dumps(fundamental_report.get('data', {}), ensure_ascii=False, indent=2) if fundamental_report else 'No Data'}

**News Analysis:**
{json.dumps(news_report.get('data', {}), ensure_ascii=False, indent=2) if news_report else 'No Data'}

**Sentiment Analysis:**
{json.dumps(sentiment_report.get('data', {}), ensure_ascii=False, indent=2) if sentiment_report else 'No Data'}

Please construct a strong bullish argument, emphasizing growth potential, competitive advantages, and positive indicators."""

        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {"argument": "", "key_points": [], "confidence": 50},
            model=model
        )
        
        return {
            "type": "bull",
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


class BearResearcher(BaseAgent):
    """Bearish researcher."""
    
    def __init__(self, memory=None):
        super().__init__("BearResearcher", memory)
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Construct the bear case."""
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
        
        # Bull argument (if present)
        bull_argument = context.get('bull_argument', '')
        
        # Memory
        situation = f"{market}:{symbol} bear case"
        memory_meta = {
            "market": market,
            "symbol": symbol,
            "timeframe": context.get("timeframe"),
            "features": context.get("memory_features") or {},
        }
        memories = self.get_memories(situation, n_matches=None, metadata=memory_meta)
        memory_prompt = self.format_memories_for_prompt(memories)
        
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a Bearish Analyst, constructing a bearish argument for an investment decision. Your tasks are:
{lang_instruction}
1. Identify risks, challenges, and negative indicators.
2. Use the provided research and data to build a strong argument.
3. Effectively address/counter bullish viewpoints.
4. Learn from historical experience: {memory_prompt}
5. **Confidence Score**: Evaluate your confidence in the bearish case (0-100). Be realistic. If the data is mixed or weak, lower your confidence. Do NOT default to 75.

Please return in JSON format as follows:
{{
  "argument": "Detailed bearish argument...",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "confidence": 75
}}"""

        # Bull argument section (avoid backslashes in f-string expression)
        bull_argument_section = f"**Bullish Argument (Needs Rebuttal):**\n{bull_argument}" if bull_argument else ""
        
        user_prompt = f"""Based on the following analysis reports, construct a bearish argument for {symbol} in {market} market:

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

{bull_argument_section}

Please construct a strong bearish argument, emphasizing risks, challenges, and negative indicators."""

        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {"argument": "", "key_points": [], "confidence": 50},
            model=model
        )
        
        return {
            "type": "bear",
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
