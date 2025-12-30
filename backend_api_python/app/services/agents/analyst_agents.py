"""
Analyst agents.
Includes: market/technical, fundamental, news, sentiment, risk analysts.
"""
import json
from typing import Dict, Any
from .base_agent import BaseAgent
from .tools import AgentTools
from app.services.llm import LLMService

logger = __import__('app.utils.logger', fromlist=['get_logger']).get_logger(__name__)


class MarketAnalyst(BaseAgent):
    """Market / technical analyst."""
    
    def __init__(self, memory=None):
        super().__init__("MarketAnalyst", memory)
        self.tools = AgentTools()
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run technical analysis."""
        market = context.get('market')
        symbol = context.get('symbol')
        language = context.get('language', 'zh-CN')
        model = context.get('model')
        base_data = context.get('base_data', {})
        
        # Kline + current price
        kline_data = base_data.get('kline_data') or self.tools.get_stock_data(market, symbol, days=30)
        current_price = base_data.get('current_price') or self.tools.get_current_price(market, symbol)
        
        # Technical indicators
        indicators = {}
        if kline_data:
            indicators = self.tools.calculate_technical_indicators(kline_data)
        
        # Prompts
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a professional technical analyst. Please analyze the technical trends of the stock or cryptocurrency, including:
{lang_instruction}
1. Technical Indicator Signals (MACD signals, RSI range, trend strength, important MA directions)
2. Technical Score (0-100). Be objective. Do not default to 75. 
   - 0-40: Bearish/Weak
   - 41-60: Neutral
   - 61-100: Bullish/Strong
3. Technical Analysis Report (about 300 words)

Please strictly return the result in JSON format as follows:
{{
  "score": 75,
  "indicators": {{
    "MACD": "Golden Cross/Death Cross or Flat",
    "RSI(14)": "75 (Overbought)",
    "MA20": "Upward/Downward/Flat",
    "Support/Resistance": "Support: 150.00, Resistance: 165.50"
  }},
  "report": "Technical analysis report content..."
}}"""

        user_prompt = f"""Please perform technical analysis for {symbol} in {market} market.

**Current Price:**
{json.dumps(current_price, ensure_ascii=False, indent=2) if current_price else 'No Data'}

**Kline Data (Last 30 days):**
{json.dumps(kline_data[-10:] if kline_data else [], ensure_ascii=False, indent=2) if kline_data else 'No Data'}

**Calculated Technical Indicators:**
{json.dumps(indicators, ensure_ascii=False, indent=2) if indicators else 'No Data'}

Please analyze the short-term and medium-term trends based on the above Kline data and price movements."""

        # LLM call
        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {"score": 50, "indicators": {}, "report": "Failed to parse technical analysis"},
            model=model
        )
        
        return {
            "type": "technical",
            "data": result,
            "indicators": indicators
        }
    
    def _get_language_instruction(self, language: str) -> str:
        """Return an English language instruction string for the LLM prompt."""
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


class FundamentalAnalyst(BaseAgent):
    """Fundamental analyst."""
    
    def __init__(self, memory=None):
        super().__init__("FundamentalAnalyst", memory)
        self.tools = AgentTools()
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run fundamental analysis."""
        market = context.get('market')
        symbol = context.get('symbol')
        language = context.get('language', 'zh-CN')
        model = context.get('model')
        base_data = context.get('base_data', {})
        
        # Fundamental data
        fundamental_data = base_data.get('fundamental_data') or self.tools.get_fundamental_data(market, symbol)
        company_data = base_data.get('company_data') or self.tools.get_company_data(market, symbol, language=language)
        
        # Memory
        situation = f"{market}:{symbol} fundamental analysis"
        memory_meta = {
            "market": market,
            "symbol": symbol,
            "timeframe": context.get("timeframe"),
            "features": context.get("memory_features") or {},
        }
        memories = self.get_memories(situation, n_matches=None, metadata=memory_meta)
        memory_prompt = self.format_memories_for_prompt(memories)
        
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a fundamental analyst. Please analyze the financial status and industry position of the stock, including:
{lang_instruction}
1. Financial Indicators (Select key P/E, P/B, ROE, Revenue Growth)
2. Fundamental Score (0-100). Be objective. Do not default to 80.
   - 0-40: Poor/Overvalued
   - 41-60: Fair/Neutral
   - 61-100: Good/Undervalued
3. Fundamental Analysis Report (about 300 words)

{memory_prompt}

Please strictly return the result in JSON format as follows:
{{
  "score": 80,
  "financials": {{
    "P/E": "25.3",
    "P/B": "4.2",
    "ROE": "18.5%",
    "Market Cap": "1200.5 B"
  }},
  "report": "Fundamental analysis report content..."
}}"""

        user_prompt = f"""Please perform fundamental analysis for {symbol} in {market} market.

**Basic Company Info:**
{json.dumps(company_data, ensure_ascii=False, indent=2) if company_data else 'No Data'}

**Raw Fundamental Indicators:**
{json.dumps(fundamental_data, ensure_ascii=False, indent=2) if fundamental_data else 'No Data'}

Please analyze based on the above data."""

        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {"score": 50, "financials": {}, "report": "Failed to parse fundamental analysis"},
            model=model
        )
        
        return {
            "type": "fundamental",
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


class NewsAnalyst(BaseAgent):
    """News analyst."""
    
    def __init__(self, memory=None):
        super().__init__("NewsAnalyst", memory)
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run news analysis."""
        market = context.get('market')
        symbol = context.get('symbol')
        language = context.get('language', 'zh-CN')
        model = context.get('model')
        base_data = context.get('base_data', {})
        
        company_data = base_data.get('company_data', {})
        news_data = base_data.get('news_data', [])
        
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a professional news intelligence analyst. Your task is to extract key intelligence that has a major impact on stock prices from massive market information.

Analysis Requirements:
{lang_instruction}
1. **Filter Noise**: News data may contain internet results from search engines. Please carefully discriminate and ignore ads, duplicate content, or irrelevant noise. Prioritize authoritative financial media and official announcements.
2. **Timeliness**: Focus on breaking news within the last 48 hours. For old news, lower its weight unless there are new developments.
3. **Deep Interpretation**: Do not just repeat news titles. Analyze the logic behind the event and its specific impact on company fundamentals or market sentiment (e.g., Earnings Beat -> Profit Improvement -> Valuation Increase).
4. **Scoring**: News Score (0-100).
   - 0-40: Major Negative (e.g., financial fraud, regulatory crackdown, core business damage)
   - 41-59: Neutral or minor impact
   - 60-100: Positive (e.g., strong earnings, major partnership, policy support)
   - Higher scores indicate more positive news.

Please strictly return the result in JSON format as follows:
{{
  "score": 70,
  "events": [
    {{
      "title": "Event Title",
      "impact": "Positive/Negative/Neutral",
      "summary": "Event summary and deep impact analysis...",
      "date": "2023-10-27"
    }}
  ],
  "report": "Comprehensive news analysis report, including overall judgment on recent market public opinion..."
}}"""

        user_prompt = f"""Please perform in-depth news intelligence analysis for {symbol} in {market} market.

**Company Background:**
{json.dumps(company_data, ensure_ascii=False, indent=2) if company_data else 'No Data'}

**Latest Intelligence Sources (Contains professional financial news and web search results, please discriminate):**
{json.dumps(news_data, ensure_ascii=False, indent=2) if news_data else 'No directly related news'}

Please analyze based on the above intelligence. If the provided "Latest Intelligence Sources" contain no substantive content or only irrelevant noise, please explicitly state "No valid news available" and deduce logically based on the industry trends and macro market environment of the stock."""

        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {"score": 50, "events": [], "report": "Failed to parse news analysis"},
            model=model
        )
        
        return {
            "type": "news",
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


class SentimentAnalyst(BaseAgent):
    """Sentiment analyst."""
    
    def __init__(self, memory=None):
        super().__init__("SentimentAnalyst", memory)
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run sentiment analysis."""
        market = context.get('market')
        symbol = context.get('symbol')
        language = context.get('language', 'zh-CN')
        model = context.get('model')
        base_data = context.get('base_data', {})
        
        current_price = base_data.get('current_price', {})
        kline_data = base_data.get('kline_data', [])
        
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a market sentiment analyst. Please analyze the market sentiment and popularity of the stock, including:
{lang_instruction}
1. Sentiment Heat Indicators (e.g., analyst ratings, social media discussion volume, put/call ratio)
2. Sentiment Score (0-100, higher means more optimistic). Be objective. Do not default to 65.
   - 0-40: Bearish/Fearful
   - 41-60: Neutral
   - 61-100: Bullish/Greedy
3. Sentiment Analysis Report (about 300 words)

Please strictly return the result in JSON format as follows:
{{
  "score": 65,
  "scores": {{
    "Analyst Rating": 90,
    "Social Media Heat": 85,
    "Market Sentiment Index": 70
  }},
  "report": "Sentiment analysis report content..."
}}
Note: All values in the 'scores' dictionary must be integers between 0-100 (pure numbers), representing optimism or heat, without any text or percentage signs."""

        user_prompt = f"""Please perform sentiment analysis for {symbol} in {market} market.
Based on the current Kline trends and price fluctuations, combined with your existing knowledge, evaluate whether the market sentiment for this stock is bullish, bearish, or neutral.

**Current Price:**
{json.dumps(current_price, ensure_ascii=False, indent=2) if current_price else 'No Data'}

**Kline Data (Recent Trends):**
{json.dumps(kline_data[-5:] if kline_data else [], ensure_ascii=False, indent=2) if kline_data else 'No Data'}

Please evaluate market sentiment."""

        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {"score": 50, "scores": {"Analyst Rating": 50, "Social Media Heat": 50, "Market Sentiment Index": 50}, "report": "Failed to parse sentiment analysis"},
            model=model
        )
        
        return {
            "type": "sentiment",
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


class RiskAnalyst(BaseAgent):
    """Risk analyst."""
    
    def __init__(self, memory=None):
        super().__init__("RiskAnalyst", memory)
        self.llm_service = LLMService()
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run risk assessment."""
        market = context.get('market')
        symbol = context.get('symbol')
        language = context.get('language', 'zh-CN')
        model = context.get('model')
        base_data = context.get('base_data', {})
        
        current_price = base_data.get('current_price', {})
        kline_data = base_data.get('kline_data', [])
        fundamental_data = base_data.get('fundamental_data', {})
        
        lang_instruction = self._get_language_instruction(language)
        system_prompt = f"""You are a risk management analyst. Please evaluate the investment risks of the stock, including:
{lang_instruction}
1. Risk Indicators (Volatility, Liquidity, Concentration Risk, Systemic Risk Exposure)
2. Risk Score (0-100, higher score means lower risk/safer). Be objective. Do not default to 60.
   - 0-40: High Risk (Dangerous)
   - 41-60: Moderate Risk
   - 61-100: Low Risk (Safe)
3. Risk Assessment Report (about 300 words)

Please strictly return the result in JSON format as follows:
{{
  "score": 60,
  "metrics": {{
    "Volatility (Beta)": "1.2 (Higher than market)",
    "Liquidity": "Good",
    "Concentration Risk": "Low (Diversified business)"
  }},
  "report": "Risk assessment report content..."
}}"""

        user_prompt = f"""Please perform risk assessment for {symbol} in {market} market.

**Current Price:**
{json.dumps(current_price, ensure_ascii=False, indent=2) if current_price else 'No Data'}

**Kline Data (Volatility Analysis):**
{json.dumps(kline_data, ensure_ascii=False, indent=2) if kline_data else 'No Data'}

**Fundamental Data (Debt Risk):**
{json.dumps(fundamental_data, ensure_ascii=False, indent=2) if fundamental_data else 'No Data'}

Please evaluate investment risks based on price volatility, fundamental data, etc."""

        result = self.llm_service.safe_call_llm(
            system_prompt,
            user_prompt,
            {"score": 50, "metrics": {}, "report": "Failed to parse risk assessment"},
            model=model
        )
        
        return {
            "type": "risk",
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
