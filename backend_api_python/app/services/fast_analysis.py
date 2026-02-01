"""
Fast Analysis Service 3.0
系统性重构版本 - 使用统一的数据采集器

核心改进：
1. 数据源统一 - 使用 MarketDataCollector，与K线模块、自选列表完全一致
2. 宏观数据 - 新增美元指数、VIX、利率等宏观经济指标
3. 多维新闻 - 使用结构化API，无需深度阅读
4. 单次LLM调用 - 强约束prompt，输出结构化分析
"""
import json
import time
from typing import Dict, Any, Optional, List
from decimal import Decimal, ROUND_HALF_UP

from app.utils.logger import get_logger
from app.services.llm import LLMService
from app.services.market_data_collector import get_market_data_collector

logger = get_logger(__name__)


class FastAnalysisService:
    """
    快速分析服务 3.0
    
    架构：
    1. 数据采集层 - MarketDataCollector (统一数据源)
    2. 分析层 - 单次LLM调用 (强约束prompt)
    3. 记忆层 - 分析历史存储和检索
    """
    
    def __init__(self):
        self.llm_service = LLMService()
        self.data_collector = get_market_data_collector()
        self._memory_db = None  # Lazy init
    
    # ==================== Data Collection Layer ====================
    
    def _collect_market_data(self, market: str, symbol: str, timeframe: str = "1D") -> Dict[str, Any]:
        """
        使用统一的数据采集器收集市场数据
        
        数据层次：
        1. 核心数据: 价格、K线、技术指标
        2. 基本面: 公司信息、财务数据
        3. 宏观数据: DXY、VIX、TNX、黄金等
        4. 情绪数据: 新闻、市场情绪
        """
        return self.data_collector.collect_all(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            include_macro=True,
            include_news=True,
            timeout=30
        )
    
    def _calculate_indicators(self, kline_data: List[Dict]) -> Dict[str, Any]:
        """
        Calculate technical indicators using rules (no LLM).
        Returns actionable signals, not raw numbers.
        """
        if not kline_data or len(kline_data) < 5:
            return {"error": "Insufficient data"}
        
        try:
            # Use tools' built-in calculation
            raw_indicators = self.tools.calculate_technical_indicators(kline_data)
            
            # Extract key values
            closes = [float(k.get("close", 0)) for k in kline_data if k.get("close")]
            if not closes:
                return {"error": "No close prices"}
            
            current_price = closes[-1]
            
            # RSI interpretation
            rsi = raw_indicators.get("RSI", 50)
            if rsi < 30:
                rsi_signal = "oversold"
                rsi_action = "potential_buy"
            elif rsi > 70:
                rsi_signal = "overbought"
                rsi_action = "potential_sell"
            else:
                rsi_signal = "neutral"
                rsi_action = "hold"
            
            # MACD interpretation
            macd = raw_indicators.get("MACD", 0)
            macd_signal_line = raw_indicators.get("MACD_Signal", 0)
            macd_hist = raw_indicators.get("MACD_Hist", 0)
            
            if macd > macd_signal_line and macd_hist > 0:
                macd_signal = "bullish"
                macd_trend = "golden_cross" if macd_hist > 0 and len(kline_data) > 1 else "bullish"
            elif macd < macd_signal_line and macd_hist < 0:
                macd_signal = "bearish"
                macd_trend = "death_cross" if macd_hist < 0 and len(kline_data) > 1 else "bearish"
            else:
                macd_signal = "neutral"
                macd_trend = "consolidating"
            
            # Moving averages
            ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else current_price
            ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else current_price
            ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else current_price
            
            if current_price > ma5 > ma10 > ma20:
                ma_trend = "strong_uptrend"
            elif current_price > ma20:
                ma_trend = "uptrend"
            elif current_price < ma5 < ma10 < ma20:
                ma_trend = "strong_downtrend"
            elif current_price < ma20:
                ma_trend = "downtrend"
            else:
                ma_trend = "sideways"
            
            # Support/Resistance (simple: recent highs/lows)
            recent_highs = [float(k.get("high", 0)) for k in kline_data[-14:] if k.get("high")]
            recent_lows = [float(k.get("low", 0)) for k in kline_data[-14:] if k.get("low")]
            
            resistance = max(recent_highs) if recent_highs else current_price * 1.05
            support = min(recent_lows) if recent_lows else current_price * 0.95
            
            # Volatility (ATR-like)
            if len(kline_data) >= 14:
                ranges = []
                for k in kline_data[-14:]:
                    h = float(k.get("high", 0))
                    l = float(k.get("low", 0))
                    if h > 0 and l > 0:
                        ranges.append(h - l)
                atr = sum(ranges) / len(ranges) if ranges else 0
                volatility_pct = (atr / current_price * 100) if current_price > 0 else 0
                
                if volatility_pct > 5:
                    volatility = "high"
                elif volatility_pct > 2:
                    volatility = "medium"
                else:
                    volatility = "low"
            else:
                volatility = "unknown"
                volatility_pct = 0
            
            return {
                "current_price": round(current_price, 6),
                "rsi": {
                    "value": round(rsi, 2),
                    "signal": rsi_signal,
                    "action": rsi_action,
                },
                "macd": {
                    "value": round(macd, 6),
                    "signal_line": round(macd_signal_line, 6),
                    "histogram": round(macd_hist, 6),
                    "signal": macd_signal,
                    "trend": macd_trend,
                },
                "moving_averages": {
                    "ma5": round(ma5, 6),
                    "ma10": round(ma10, 6),
                    "ma20": round(ma20, 6),
                    "trend": ma_trend,
                },
                "levels": {
                    "support": round(support, 6),
                    "resistance": round(resistance, 6),
                },
                "volatility": {
                    "level": volatility,
                    "pct": round(volatility_pct, 2),
                },
                "raw": raw_indicators,
            }
        except Exception as e:
            logger.error(f"Indicator calculation failed: {e}")
            return {"error": str(e)}
    
    def _format_news_summary(self, news_data: List[Dict], max_items: int = 5) -> str:
        """Format news into a concise summary for the prompt."""
        if not news_data:
            return "No recent news available."
        
        summaries = []
        for item in news_data[:max_items]:
            title = item.get("title", item.get("headline", ""))
            sentiment = item.get("sentiment", "neutral")
            date = item.get("date", item.get("datetime", ""))[:10] if item.get("date") or item.get("datetime") else ""
            
            if title:
                summaries.append(f"- [{sentiment}] {title} ({date})")
        
        return "\n".join(summaries) if summaries else "No recent news available."
    
    # ==================== Memory Layer ====================
    
    def _get_memory_context(self, market: str, symbol: str, current_indicators: Dict) -> str:
        """
        Retrieve relevant historical analysis for similar market conditions.
        """
        try:
            from app.services.analysis_memory import get_analysis_memory
            memory = get_analysis_memory()
            
            # Get similar patterns
            patterns = memory.get_similar_patterns(market, symbol, current_indicators, limit=3)
            
            if not patterns:
                return "No similar historical patterns found in memory."
            
            context_lines = ["Historical patterns with similar conditions:"]
            for p in patterns:
                outcome = ""
                if p.get("was_correct") is not None:
                    outcome = f" (Outcome: {'Correct' if p['was_correct'] else 'Incorrect'}"
                    if p.get("actual_return_pct"):
                        outcome += f", Return: {p['actual_return_pct']:.2f}%"
                    outcome += ")"
                
                context_lines.append(
                    f"- Decision: {p['decision']} at ${p.get('price', 'N/A')}{outcome}"
                )
            
            return "\n".join(context_lines)
            
        except Exception as e:
            logger.warning(f"Memory retrieval failed: {e}")
            return "Memory retrieval failed."
    
    # ==================== Prompt Engineering ====================
    
    def _build_analysis_prompt(self, data: Dict[str, Any], language: str) -> tuple:
        """
        Build the single, comprehensive analysis prompt.
        Key: Strong constraints to prevent absurd recommendations.
        """
        price_data = data.get("price") or {}
        current_price = price_data.get("price", 0) if price_data else 0
        change_24h = price_data.get("changePercent", 0) if price_data else 0
        
        # Ensure all data fields have safe defaults (may be None from failed fetches)
        indicators = data.get("indicators") or {}
        fundamental = data.get("fundamental") or {}
        company = data.get("company") or {}
        news_summary = self._format_news_summary(data.get("news") or [])
        
        # Language instruction - MUST be enforced strictly
        lang_map = {
            'zh-CN': '⚠️ 重要：你必须用简体中文回答所有内容，包括summary、key_reasons、risks等所有文本字段。不要使用英文。',
            'zh-TW': '⚠️ 重要：你必須用繁體中文回答所有內容，包括summary、key_reasons、risks等所有文本字段。不要使用英文。',
            'en-US': '⚠️ IMPORTANT: You MUST answer ALL content in English, including summary, key_reasons, risks, and all text fields. Do NOT use Chinese.',
            'ja-JP': '⚠️ 重要：すべての内容を日本語で回答してください。summary、key_reasons、risksなど、すべてのテキストフィールドを日本語で記述してください。',
        }
        lang_instruction = lang_map.get(language, '⚠️ IMPORTANT: Answer ALL content in English.')
        
        # Get pre-calculated trading levels from technical analysis
        levels = indicators.get("levels", {})
        trading_levels = indicators.get("trading_levels", {})
        volatility = indicators.get("volatility", {})
        
        support = levels.get("support", current_price * 0.95)
        resistance = levels.get("resistance", current_price * 1.05)
        pivot = levels.get("pivot", current_price)
        
        # Use ATR-based suggestions if available, otherwise use percentage
        atr = volatility.get("atr", current_price * 0.02)
        suggested_stop_loss = trading_levels.get("suggested_stop_loss", current_price - 2 * atr)
        suggested_take_profit = trading_levels.get("suggested_take_profit", current_price + 3 * atr)
        risk_reward_ratio = trading_levels.get("risk_reward_ratio", 1.5)
        
        # Price bounds (still enforce max 10% deviation)
        if current_price > 0:
            price_lower_bound = round(max(suggested_stop_loss, current_price * 0.90), 6)
            price_upper_bound = round(min(suggested_take_profit, current_price * 1.10), 6)
            entry_range_low = round(current_price * 0.98, 6)
            entry_range_high = round(current_price * 1.02, 6)
        else:
            price_lower_bound = price_upper_bound = entry_range_low = entry_range_high = 0
        
        system_prompt = f"""You are QuantDinger's Senior Financial Analyst with 20+ years of experience. 
Provide professional, detailed analysis like a Wall Street analyst report.

{lang_instruction}

📐 TECHNICAL LEVELS (Pre-calculated from chart data):
- Support: ${support} | Resistance: ${resistance} | Pivot: ${pivot}
- ATR (14-day): ${atr:.4f} ({volatility.get('pct', 0)}% volatility)
- Suggested Stop Loss: ${suggested_stop_loss:.4f} (based on 2x ATR below support)
- Suggested Take Profit: ${suggested_take_profit:.4f} (based on 3x ATR above resistance)
- Risk/Reward Ratio: {risk_reward_ratio}

⚠️ CRITICAL PRICE RULES:
1. Current price: ${current_price}
2. Your stop_loss MUST be near ${suggested_stop_loss:.4f} (range: ${price_lower_bound:.4f} ~ ${current_price})
3. Your take_profit MUST be near ${suggested_take_profit:.4f} (range: ${current_price} ~ ${price_upper_bound:.4f})
4. Entry price: ${entry_range_low:.4f} ~ ${entry_range_high:.4f}
5. These levels are based on ATR and support/resistance analysis - use them as reference!

📊 YOUR ANALYSIS MUST INCLUDE:
1. **Technical Analysis**: Interpret the indicators, explain why support/resistance levels matter
2. **Fundamental Analysis**: Evaluate valuation, growth if data available
3. **Sentiment Analysis**: Assess market mood, news impact, macro factors
4. **Risk Assessment**: Explain why the stop loss level is appropriate
5. **Clear Recommendation**: BUY/SELL/HOLD with entry, stop loss (near suggested), take profit (near suggested)

Output ONLY valid JSON (do NOT include word counts or format hints in your actual response):
{{
  "decision": "BUY" | "SELL" | "HOLD",
  "confidence": 0-100,
  "summary": "Executive summary in 2-3 sentences",
  "analysis": {{
    "technical": "Your detailed technical analysis here - interpret RSI, MACD, MA, support/resistance",
    "fundamental": "Your fundamental assessment here - valuation, growth, competitive position",
    "sentiment": "Your market sentiment analysis here - news impact, macro factors, mood"
  }},
  "entry_price": number,
  "stop_loss": number,
  "take_profit": number,
  "position_size_pct": 1-100,
  "timeframe": "short" | "medium" | "long",
  "key_reasons": ["First key reason for this decision", "Second key reason", "Third key reason"],
  "risks": ["Primary risk with potential impact", "Secondary risk"],
  "technical_score": 0-100,
  "fundamental_score": 0-100,
  "sentiment_score": 0-100
}}

⚠️ IMPORTANT: The analysis fields should contain your ACTUAL analysis text, NOT the format description above."""

        # Format indicator data for prompt (ensure safe defaults)
        rsi_data = indicators.get("rsi") or {}
        macd_data = indicators.get("macd") or {}
        ma_data = indicators.get("moving_averages") or {}
        vol_data = indicators.get("volatility") or {}
        levels = indicators.get("levels") or {}
        
        # Format macro data
        macro = data.get("macro") or {}
        macro_summary = self._format_macro_summary(macro, data.get("market", ""))
        
        user_prompt = f"""Analyze {data['symbol']} in {data['market']} market.

📊 REAL-TIME DATA:
- Current Price: ${current_price}
- 24h Change: {change_24h}%
- Support: ${support}
- Resistance: ${resistance}

📈 TECHNICAL INDICATORS:
- RSI(14): {rsi_data.get('value', 'N/A')} ({rsi_data.get('signal', 'N/A')})
- MACD: {macd_data.get('signal', 'N/A')} ({macd_data.get('trend', 'N/A')})
- MA Trend: {ma_data.get('trend', 'N/A')}
- Volatility: {vol_data.get('level', 'N/A')} ({vol_data.get('pct', 0)}%)
- Trend: {indicators.get('trend', 'N/A')}
- Price Position (20d): {indicators.get('price_position', 'N/A')}%

🌐 MACRO ENVIRONMENT:
{macro_summary}

📰 MARKET NEWS ({len(data.get('news') or [])} items):
{news_summary}

💼 FUNDAMENTALS:
- Company: {company.get('name', data['symbol'])}
- Industry: {company.get('industry', 'N/A')}
- P/E Ratio: {fundamental.get('pe_ratio', 'N/A')}
- P/B Ratio: {fundamental.get('pb_ratio', 'N/A')}
- Market Cap: {fundamental.get('market_cap', 'N/A')}
- 52W High/Low: {fundamental.get('52w_high', 'N/A')} / {fundamental.get('52w_low', 'N/A')}
- ROE: {fundamental.get('roe', 'N/A')}

IMPORTANT: Consider the macro environment (especially DXY, VIX, rates) when making your recommendation.
Provide your analysis now. Remember: all prices must be within 10% of ${current_price}."""

        return system_prompt, user_prompt
    
    def _format_macro_summary(self, macro: Dict[str, Any], market: str) -> str:
        """格式化宏观数据摘要"""
        if not macro:
            return "宏观数据暂不可用"
        
        lines = []
        
        # 美元指数
        if 'DXY' in macro:
            dxy = macro['DXY']
            direction = "↑" if dxy.get('change', 0) > 0 else "↓"
            lines.append(f"- {dxy.get('name', 'USD Index')}: {dxy.get('price', 'N/A')} ({direction}{abs(dxy.get('changePercent', 0)):.2f}%)")
            # 美元强弱对不同资产的影响
            if market == 'Crypto':
                impact = "利空加密货币" if dxy.get('change', 0) > 0 else "利好加密货币"
                lines.append(f"  ⚠️ 美元{direction} {impact}")
            elif market == 'Forex':
                lines.append(f"  ⚠️ 美元{direction} 直接影响外汇走势")
        
        # VIX恐慌指数
        if 'VIX' in macro:
            vix = macro['VIX']
            vix_value = vix.get('price', 0)
            if vix_value > 30:
                level = "极度恐慌 (>30)"
            elif vix_value > 20:
                level = "较高恐慌 (20-30)"
            elif vix_value > 15:
                level = "正常 (15-20)"
            else:
                level = "低波动 (<15)"
            lines.append(f"- {vix.get('name', 'VIX')}: {vix_value:.2f} - {level}")
        
        # 美债收益率
        if 'TNX' in macro:
            tnx = macro['TNX']
            direction = "↑" if tnx.get('change', 0) > 0 else "↓"
            lines.append(f"- {tnx.get('name', '10Y Treasury')}: {tnx.get('price', 'N/A'):.3f}% ({direction})")
            if tnx.get('price', 0) > 4.5:
                lines.append("  ⚠️ 高利率环境，对估值不利")
        
        # 黄金
        if 'GOLD' in macro:
            gold = macro['GOLD']
            direction = "↑" if gold.get('change', 0) > 0 else "↓"
            lines.append(f"- {gold.get('name', 'Gold')}: ${gold.get('price', 'N/A'):.2f} ({direction}{abs(gold.get('changePercent', 0)):.2f}%)")
        
        # 标普500
        if 'SPY' in macro:
            spy = macro['SPY']
            direction = "↑" if spy.get('change', 0) > 0 else "↓"
            lines.append(f"- {spy.get('name', 'S&P 500')}: ${spy.get('price', 'N/A'):.2f} ({direction}{abs(spy.get('changePercent', 0)):.2f}%)")
        
        # 比特币 (作为风险指标)
        if 'BTC' in macro and market != 'Crypto':
            btc = macro['BTC']
            direction = "↑" if btc.get('change', 0) > 0 else "↓"
            lines.append(f"- {btc.get('name', 'BTC')}: ${btc.get('price', 'N/A'):,.0f} ({direction}{abs(btc.get('changePercent', 0)):.2f}%) [风险偏好指标]")
        
        return "\n".join(lines) if lines else "宏观数据暂不可用"
    
    # ==================== Main Analysis ====================
    
    def analyze(self, market: str, symbol: str, language: str = 'en-US', 
                model: str = None, timeframe: str = "1D", user_id: int = None) -> Dict[str, Any]:
        """
        Run fast single-call analysis.
        
        Args:
            market: Market type (Crypto, USStock, etc.)
            symbol: Trading pair or stock symbol
            language: Response language (zh-CN or en-US)
            model: LLM model to use
            timeframe: Analysis timeframe (1D, 4H, etc.)
            user_id: User ID for storing analysis history
        
        Returns:
            Complete analysis result with actionable recommendations.
        """
        start_time = time.time()
        
        result = {
            "market": market,
            "symbol": symbol,
            "language": language,
            "timeframe": timeframe,
            "analysis_time_ms": 0,
            "error": None,
        }
        
        try:
            # Phase 1: Data collection (parallel)
            logger.info(f"Fast analysis starting: {market}:{symbol}")
            data = self._collect_market_data(market, symbol, timeframe)
            
            # Validate we have essential data - with fallback to indicators
            current_price = None
            
            # 优先从 price 数据获取
            if data.get("price") and data["price"].get("price"):
                current_price = data["price"]["price"]
            
            # Fallback: 从 indicators 获取 (如果 K 线成功计算了)
            if not current_price and data.get("indicators"):
                current_price = data["indicators"].get("current_price")
                if current_price:
                    logger.info(f"Using price from indicators: ${current_price}")
                    # 构建简化的 price 数据
                    data["price"] = {
                        "price": current_price,
                        "change": 0,
                        "changePercent": 0,
                        "source": "indicators_fallback"
                    }
            
            # Fallback: 从 kline 最后一根获取
            if not current_price and data.get("kline"):
                klines = data["kline"]
                if klines and len(klines) > 0:
                    current_price = float(klines[-1].get("close", 0))
                    if current_price > 0:
                        logger.info(f"Using price from kline: ${current_price}")
                        prev_close = float(klines[-2].get("close", current_price)) if len(klines) > 1 else current_price
                        change = current_price - prev_close
                        change_pct = (change / prev_close * 100) if prev_close > 0 else 0
                        data["price"] = {
                            "price": current_price,
                            "change": round(change, 6),
                            "changePercent": round(change_pct, 2),
                            "source": "kline_fallback"
                        }
            
            if not current_price or current_price <= 0:
                result["error"] = "Failed to fetch current price from all sources"
                logger.error(f"Price fetch failed for {market}:{symbol}, all sources exhausted")
                return result
            
            # Phase 2: Build prompt
            system_prompt, user_prompt = self._build_analysis_prompt(data, language)
            
            # Phase 3: Single LLM call
            logger.info(f"Calling LLM for analysis...")
            llm_start = time.time()
            
            analysis = self.llm_service.safe_call_llm(
                system_prompt,
                user_prompt,
                default_structure={
                    "decision": "HOLD",
                    "confidence": 50,
                    "summary": "Analysis failed",
                    "entry_price": current_price,
                    "stop_loss": current_price * 0.95,
                    "take_profit": current_price * 1.05,
                    "position_size_pct": 10,
                    "timeframe": "medium",
                    "key_reasons": ["Unable to analyze"],
                    "risks": ["Analysis error"],
                    "technical_score": 50,
                    "fundamental_score": 50,
                    "sentiment_score": 50,
                },
                model=model
            )
            
            llm_time = int((time.time() - llm_start) * 1000)
            logger.info(f"LLM call completed in {llm_time}ms")
            
            # Phase 4: Validate and constrain output
            analysis = self._validate_and_constrain(analysis, current_price)
            
            # Build final result
            total_time = int((time.time() - start_time) * 1000)
            
            # Extract detailed analysis sections
            detailed_analysis = analysis.get("analysis", {})
            if isinstance(detailed_analysis, str):
                # If AI returned a string instead of dict, use it as technical analysis
                detailed_analysis = {"technical": detailed_analysis, "fundamental": "", "sentiment": ""}
            
            result.update({
                "decision": analysis.get("decision", "HOLD"),
                "confidence": analysis.get("confidence", 50),
                "summary": analysis.get("summary", ""),
                "detailed_analysis": {
                    "technical": detailed_analysis.get("technical", ""),
                    "fundamental": detailed_analysis.get("fundamental", ""),
                    "sentiment": detailed_analysis.get("sentiment", ""),
                },
                "trading_plan": {
                    "entry_price": analysis.get("entry_price"),
                    "stop_loss": analysis.get("stop_loss"),
                    "take_profit": analysis.get("take_profit"),
                    "position_size_pct": analysis.get("position_size_pct", 10),
                    "timeframe": analysis.get("timeframe", "medium"),
                },
                "reasons": analysis.get("key_reasons", []),
                "risks": analysis.get("risks", []),
                "scores": {
                    "technical": analysis.get("technical_score", 50),
                    "fundamental": analysis.get("fundamental_score", 50),
                    "sentiment": analysis.get("sentiment_score", 50),
                    "overall": self._calculate_overall_score(analysis),
                },
                "market_data": {
                    "current_price": current_price,
                    "change_24h": data["price"].get("changePercent", 0),
                    "support": data["indicators"].get("levels", {}).get("support"),
                    "resistance": data["indicators"].get("levels", {}).get("resistance"),
                },
                "indicators": data.get("indicators", {}),
                "analysis_time_ms": total_time,
                "llm_time_ms": llm_time,
                "data_collection_time_ms": data.get("collection_time_ms", 0),
            })
            
            # Store in memory for future retrieval and get memory_id for feedback
            memory_id = self._store_analysis_memory(result, user_id=user_id)
            if memory_id:
                result["memory_id"] = memory_id
            
            logger.info(f"Fast analysis completed in {total_time}ms: {market}:{symbol} -> {result['decision']} (memory_id={memory_id}, user_id={user_id})")
            
        except Exception as e:
            logger.error(f"Fast analysis failed: {e}", exc_info=True)
            result["error"] = str(e)
        
        return result
    
    def _validate_and_constrain(self, analysis: Dict, current_price: float) -> Dict:
        """
        Validate LLM output and constrain prices to reasonable ranges.
        This prevents absurd recommendations like "BTC at 95000, buy at 75000".
        """
        if not current_price or current_price <= 0:
            return analysis
        
        # Price bounds
        min_price = current_price * 0.90
        max_price = current_price * 1.10
        
        # Constrain entry price
        entry = analysis.get("entry_price", current_price)
        if entry and (entry < min_price or entry > max_price):
            logger.warning(f"Entry price {entry} out of bounds, constraining to current price {current_price}")
            analysis["entry_price"] = round(current_price, 6)
        
        # Constrain stop loss
        stop_loss = analysis.get("stop_loss", current_price * 0.95)
        if stop_loss and (stop_loss < min_price or stop_loss > current_price):
            analysis["stop_loss"] = round(current_price * 0.95, 6)
        
        # Constrain take profit
        take_profit = analysis.get("take_profit", current_price * 1.05)
        if take_profit and (take_profit < current_price or take_profit > max_price):
            analysis["take_profit"] = round(current_price * 1.05, 6)
        
        # Constrain confidence
        confidence = analysis.get("confidence", 50)
        analysis["confidence"] = max(0, min(100, int(confidence)))
        
        # Constrain scores
        for score_key in ["technical_score", "fundamental_score", "sentiment_score"]:
            score = analysis.get(score_key, 50)
            analysis[score_key] = max(0, min(100, int(score)))
        
        # Validate decision
        decision = str(analysis.get("decision", "HOLD")).upper()
        if decision not in ["BUY", "SELL", "HOLD"]:
            analysis["decision"] = "HOLD"
        else:
            analysis["decision"] = decision
        
        return analysis
    
    def _calculate_overall_score(self, analysis: Dict) -> int:
        """Calculate weighted overall score."""
        tech = analysis.get("technical_score", 50)
        fund = analysis.get("fundamental_score", 50)
        sent = analysis.get("sentiment_score", 50)
        
        # Weights: technical 40%, fundamental 35%, sentiment 25%
        overall = tech * 0.40 + fund * 0.35 + sent * 0.25
        
        # Adjust based on decision
        decision = analysis.get("decision", "HOLD")
        confidence = analysis.get("confidence", 50)
        
        if decision == "BUY":
            overall = overall * 0.6 + (50 + confidence * 0.5) * 0.4
        elif decision == "SELL":
            overall = overall * 0.6 + (50 - confidence * 0.5) * 0.4
        
        return max(0, min(100, int(overall)))
    
    def _store_analysis_memory(self, result: Dict, user_id: int = None) -> Optional[int]:
        """Store analysis result for future learning. Returns memory_id."""
        try:
            from app.services.analysis_memory import get_analysis_memory
            memory = get_analysis_memory()
            memory_id = memory.store(result, user_id=user_id)
            return memory_id
        except Exception as e:
            logger.warning(f"Memory storage failed: {e}")
            return None
    
    # ==================== Backward Compatibility ====================
    
    def analyze_legacy_format(self, market: str, symbol: str, language: str = 'en-US',
                              model: str = None, timeframe: str = "1D") -> Dict[str, Any]:
        """
        Returns analysis in legacy multi-agent format for backward compatibility.
        """
        fast_result = self.analyze(market, symbol, language, model, timeframe)
        
        if fast_result.get("error"):
            return {
                "overview": {"report": f"Analysis failed: {fast_result['error']}"},
                "fundamental": {"report": "N/A"},
                "technical": {"report": "N/A"},
                "news": {"report": "N/A"},
                "sentiment": {"report": "N/A"},
                "risk": {"report": "N/A"},
                "error": fast_result["error"],
            }
        
        # Convert to legacy format
        decision = fast_result.get("decision", "HOLD")
        confidence = fast_result.get("confidence", 50)
        scores = fast_result.get("scores", {})
        
        return {
            "overview": {
                "overallScore": scores.get("overall", 50),
                "recommendation": decision,
                "confidence": confidence,
                "dimensionScores": {
                    "fundamental": scores.get("fundamental", 50),
                    "technical": scores.get("technical", 50),
                    "news": scores.get("sentiment", 50),
                    "sentiment": scores.get("sentiment", 50),
                    "risk": 100 - confidence,  # Inverse of confidence
                },
                "report": fast_result.get("summary", ""),
            },
            "fundamental": {
                "score": scores.get("fundamental", 50),
                "report": f"Fundamental score: {scores.get('fundamental', 50)}/100",
            },
            "technical": {
                "score": scores.get("technical", 50),
                "report": f"Technical score: {scores.get('technical', 50)}/100",
                "indicators": fast_result.get("indicators", {}),
            },
            "news": {
                "score": scores.get("sentiment", 50),
                "report": "See sentiment analysis",
            },
            "sentiment": {
                "score": scores.get("sentiment", 50),
                "report": f"Sentiment score: {scores.get('sentiment', 50)}/100",
            },
            "risk": {
                "score": 100 - confidence,
                "report": "\n".join(fast_result.get("risks", [])),
            },
            "debate": {
                "bull": {"confidence": confidence if decision == "BUY" else 50},
                "bear": {"confidence": confidence if decision == "SELL" else 50},
                "research_decision": fast_result.get("summary", ""),
            },
            "trader_decision": {
                "decision": decision,
                "confidence": confidence,
                "reasoning": fast_result.get("summary", ""),
                "trading_plan": fast_result.get("trading_plan", {}),
                "report": "\n".join(fast_result.get("reasons", [])),
            },
            "risk_debate": {
                "risky": {"recommendation": ""},
                "neutral": {"recommendation": fast_result.get("summary", "")},
                "safe": {"recommendation": ""},
            },
            "final_decision": {
                "decision": decision,
                "confidence": confidence,
                "reasoning": fast_result.get("summary", ""),
                "risk_summary": {
                    "risks": fast_result.get("risks", []),
                },
                "recommendation": "\n".join(fast_result.get("reasons", [])),
            },
            "fast_analysis": fast_result,  # Include new format for gradual migration
            "error": None,
        }


# Singleton instance
_fast_analysis_service = None

def get_fast_analysis_service() -> FastAnalysisService:
    """Get singleton FastAnalysisService instance."""
    global _fast_analysis_service
    if _fast_analysis_service is None:
        _fast_analysis_service = FastAnalysisService()
    return _fast_analysis_service


def fast_analyze(market: str, symbol: str, language: str = 'en-US', 
                 model: str = None, timeframe: str = "1D") -> Dict[str, Any]:
    """Convenience function for fast analysis."""
    service = get_fast_analysis_service()
    return service.analyze(market, symbol, language, model, timeframe)
