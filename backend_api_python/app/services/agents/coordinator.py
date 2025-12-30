"""
Multi-agent coordinator.
Orchestrates agents and the overall analysis workflow.
"""
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from .analyst_agents import (
    MarketAnalyst, FundamentalAnalyst, NewsAnalyst,
    SentimentAnalyst, RiskAnalyst
)
from .researcher_agents import BullResearcher, BearResearcher
from .trader_agent import TraderAgent
from .risk_agents import RiskyAnalyst, NeutralAnalyst, SafeAnalyst
from .memory import AgentMemory
from .reflection import ReflectionService
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AgentCoordinator:
    """Multi-agent coordinator."""

    @staticmethod
    def _is_zh(language: str) -> bool:
        return str(language or "").lower().startswith("zh")

    @classmethod
    def _t(cls, language: str, en: str, zh: str) -> str:
        """Pick a localized string for user-facing fields (not logs)."""
        return zh if cls._is_zh(language) else en
    
    def __init__(self, enable_memory: bool = True, max_debate_rounds: int = 2):
        """
        Args:
            enable_memory: Enable memory/reflection
            max_debate_rounds: Max debate rounds
        """
        self.enable_memory = enable_memory
        self.max_debate_rounds = max_debate_rounds
        
        # Reflection service
        self.reflection_service = ReflectionService() if enable_memory else None
        
        # Memory stores
        if enable_memory:
            self.memories = {
                'market': AgentMemory('market_analyst'),
                'fundamental': AgentMemory('fundamental_analyst'),
                'news': AgentMemory('news_analyst'),
                'sentiment': AgentMemory('sentiment_analyst'),
                'risk': AgentMemory('risk_analyst'),
                'bull': AgentMemory('bull_researcher'),
                'bear': AgentMemory('bear_researcher'),
                'trader': AgentMemory('trader_agent'),
            }
        else:
            self.memories = {}
        
        # Initialize agents
        self._init_agents()
    
    def _init_agents(self):
        """Initialize all agents."""
        # Analyst agents
        self.market_analyst = MarketAnalyst(
            memory=self.memories.get('market')
        )
        self.fundamental_analyst = FundamentalAnalyst(
            memory=self.memories.get('fundamental')
        )
        self.news_analyst = NewsAnalyst(
            memory=self.memories.get('news')
        )
        self.sentiment_analyst = SentimentAnalyst(
            memory=self.memories.get('sentiment')
        )
        self.risk_analyst = RiskAnalyst(
            memory=self.memories.get('risk')
        )
        
        # Researcher agents
        self.bull_researcher = BullResearcher(
            memory=self.memories.get('bull')
        )
        self.bear_researcher = BearResearcher(
            memory=self.memories.get('bear')
        )
        
        # Trader agent
        self.trader_agent = TraderAgent(
            memory=self.memories.get('trader')
        )
        
        # Risk debate agents
        self.risky_analyst = RiskyAnalyst()
        self.neutral_analyst = NeutralAnalyst()
        self.safe_analyst = SafeAnalyst()
    
    def run_analysis(self, market: str, symbol: str, language: str = 'zh-CN', model: str = None, timeframe: str = "1D") -> Dict[str, Any]:
        """
        Run the full multi-agent analysis workflow.
        """
        logger.info(f"Multi-agent analysis start: {market}:{symbol}, model={model}, language={language}")
        
        # Build base context
        from .tools import AgentTools
        tools = AgentTools()
        
        # 1) Base data
        current_price = tools.get_current_price(market, symbol)
        company_data = tools.get_company_data(market, symbol, language=language)
        
        # Normalize timeframe
        tf = (timeframe or "1D").strip()

        # 2) Kline + fundamentals
        kline_data = tools.get_stock_data(market, symbol, days=30, timeframe=tf)
        fundamental_data = tools.get_fundamental_data(market, symbol)
        indicators = tools.calculate_technical_indicators(kline_data or [])
        
        # 3) News (Finnhub + web search)
        company_name = company_data.get('name', symbol) if company_data else symbol
        news_data = tools.get_news(market, symbol, days=7, company_name=company_name)
        
        base_data = {
            "market": market,
            "symbol": symbol,
            "current_price": current_price,
            "kline_data": kline_data,
            "fundamental_data": fundamental_data,
            "company_data": company_data,
            "news_data": news_data,
            "indicators": indicators,
        }
        
        context = {
            "market": market,
            "symbol": symbol,
            "language": language,
            "model": model,
            "timeframe": tf,
            # Compact structured features for memory retrieval.
            "memory_features": {
                "timeframe": tf,
                "price": (current_price or {}).get("price"),
                "changePercent": (current_price or {}).get("changePercent"),
                "indicators": indicators,
            },
            "base_data": base_data
        }
        
        # Phase 1: Analysts (parallel)
        logger.info("Phase 1: Analyst team (parallel)")
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_market = executor.submit(self.market_analyst.analyze, context)
            future_fundamental = executor.submit(self.fundamental_analyst.analyze, context)
            future_news = executor.submit(self.news_analyst.analyze, context)
            future_sentiment = executor.submit(self.sentiment_analyst.analyze, context)
            future_risk = executor.submit(self.risk_analyst.analyze, context)
            
            market_report = future_market.result()
            fundamental_report = future_fundamental.result()
            news_report = future_news.result()
            sentiment_report = future_sentiment.result()
            risk_report = future_risk.result()
        
        # Update context with analyst outputs
        context.update({
            "market_report": market_report,
            "fundamental_report": fundamental_report,
            "news_report": news_report,
            "sentiment_report": sentiment_report,
            "risk_report": risk_report,
        })
        
        # Phase 2: Bull/Bear debate (parallel)
        logger.info("Phase 2: Research debate (parallel)")
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_bull = executor.submit(self.bull_researcher.analyze, context)
            future_bear = executor.submit(self.bear_researcher.analyze, context)
            
            bull_argument = future_bull.result()
            bear_argument = future_bear.result()
        
        context["bull_argument"] = bull_argument
        context["bear_argument"] = bear_argument
        
        # Research manager decision (lightweight, based on debate)
        research_decision = self._make_research_decision(
            bull_argument, bear_argument, context
        )
        context["research_decision"] = research_decision
        
        # Phase 3: Trader decision
        logger.info("Phase 3: Trader decision")
        trader_result = self.trader_agent.analyze(context)
        trader_plan = trader_result.get('data', {}).get('trading_plan', {})
        context["trader_plan"] = trader_plan
        
        # Phase 4: Risk debate (parallel)
        logger.info("Phase 4: Risk debate (parallel)")
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_risky = executor.submit(self.risky_analyst.analyze, context)
            future_neutral = executor.submit(self.neutral_analyst.analyze, context)
            future_safe = executor.submit(self.safe_analyst.analyze, context)
            
            risky_result = future_risky.result()
            neutral_result = future_neutral.result()
            safe_result = future_safe.result()
        
        # Risk manager final decision
        final_decision = self._make_risk_decision(
            risky_result, neutral_result, safe_result,
            trader_result, context
        )
        
        # Record analysis result for later reflection/validation
        if self.reflection_service and final_decision.get('decision') in ['BUY', 'SELL', 'HOLD']:
            try:
                self.reflection_service.record_analysis(
                    market=market,
                    symbol=symbol,
                    price=base_data.get('current_price', {}).get('price'),
                    decision=final_decision.get('decision'),
                    confidence=final_decision.get('confidence', 50),
                    reasoning=final_decision.get('reasoning', ''),
                    check_days=7  # Validate after 7 days by default
                )
            except Exception as e:
                logger.warning(f"Record reflection failed: {e}")
        
        # Build final result (defensive defaults to keep frontend stable)
        debate_data = {
            "bull": bull_argument.get('data', {}) if bull_argument.get('data') else {},
            "bear": bear_argument.get('data', {}) if bear_argument.get('data') else {},
            "research_decision": research_decision if research_decision else "Analyzing..."
        }
        
        trader_decision_data = trader_result.get('data', {}) if trader_result.get('data') else {
            "decision": "HOLD",
            "confidence": 50,
            "reasoning": "Analyzing...",
            "trading_plan": {},
            "report": "Analyzing..."
        }
        
        risk_debate_data = {
            "risky": risky_result.get('data', {}) if risky_result.get('data') else {},
            "neutral": neutral_result.get('data', {}) if neutral_result.get('data') else {},
            "safe": safe_result.get('data', {}) if safe_result.get('data') else {}
        }
        
        # Ensure final_decision is present
        if not final_decision or (isinstance(final_decision, dict) and len(final_decision) == 0):
            final_decision = {
                "decision": "HOLD",
                "confidence": 50,
                "reasoning": "Analyzing...",
                "risk_summary": {},
                "recommendation": "Analyzing..."
            }
        
        result = {
            "overview": self._generate_overview(context, final_decision),
            "fundamental": fundamental_report.get('data', {}),
            "technical": market_report.get('data', {}),
            "news": news_report.get('data', {}),
            "sentiment": sentiment_report.get('data', {}),
            "risk": risk_report.get('data', {}),
            "debate": debate_data,
            "trader_decision": trader_decision_data,
            "risk_debate": risk_debate_data,
            "final_decision": final_decision,
            "error": None
        }
        
        logger.info(f"Multi-agent analysis completed: {market}:{symbol}")
        logger.info(
            "Result fields - debate=%s, trader_decision=%s, risk_debate=%s, final_decision=%s",
            bool(result.get('debate')),
            bool(result.get('trader_decision')),
            bool(result.get('risk_debate')),
            bool(result.get('final_decision')),
        )
        return result
    
    def _make_research_decision(self, bull: Dict, bear: Dict, context: Dict) -> str:
        """Research manager decision (rule-based, lightweight)."""
        try:
            language = context.get("language", "en-US")
            bull_confidence = bull.get('data', {}).get('confidence', 50)
            bear_confidence = bear.get('data', {}).get('confidence', 50)
            
            # Tie-breaker when scores are close (<= 10)
            score_diff = bull_confidence - bear_confidence
            
            if abs(score_diff) <= 10:
                # Use technical + sentiment as a bias signal
                market_score = context.get('market_report', {}).get('data', {}).get('score', 50)
                sentiment_score = context.get('sentiment_report', {}).get('data', {}).get('score', 50)
                
                market_bias = (market_score + sentiment_score) / 2
                
                if market_bias > 60:
                    return self._t(
                        language,
                        en=(
                            f"Research decision: bull and bear cases are close (bull {bull_confidence}% vs bear {bear_confidence}%), "
                            f"but technical/sentiment are optimistic (avg {market_bias:.1f}), slightly leaning bullish."
                        ),
                        zh=(
                            f"研究经理决策：多空论据势均力敌（看涨 {bull_confidence}% vs 看跌 {bear_confidence}%），"
                            f"但鉴于技术面和市场情绪偏乐观（平均分 {market_bias:.1f}），稍微倾向于看涨。"
                        ),
                    )
                elif market_bias < 40:
                    return self._t(
                        language,
                        en=(
                            f"Research decision: bull and bear cases are close (bull {bull_confidence}% vs bear {bear_confidence}%), "
                            f"but technical/sentiment are pessimistic (avg {market_bias:.1f}), slightly leaning bearish."
                        ),
                        zh=(
                            f"研究经理决策：多空论据势均力敌（看涨 {bull_confidence}% vs 看跌 {bear_confidence}%），"
                            f"但鉴于技术面和市场情绪偏悲观（平均分 {market_bias:.1f}），稍微倾向于看跌。"
                        ),
                    )
                else:
                    return self._t(
                        language,
                        en=(
                            f"Research decision: bull and bear cases are close (bull {bull_confidence}% vs bear {bear_confidence}%), "
                            "and market bias is unclear. Prefer neutral / wait-and-see."
                        ),
                        zh=(
                            f"研究经理决策：多空论据势均力敌（看涨 {bull_confidence}% vs 看跌 {bear_confidence}%），"
                            "且市场情绪不明朗，建议保持中立/观望。"
                        ),
                    )
            
            elif score_diff > 10:
                return self._t(
                    language,
                    en=(
                        f"Research decision: bullish case (confidence {bull_confidence}%) is clearly stronger than bearish "
                        f"(confidence {bear_confidence}%). Lean bullish."
                    ),
                    zh=(
                        f"研究经理决策：基于看涨论据（置信度 {bull_confidence}%）明显强于看跌论据（置信度 {bear_confidence}%），明确倾向于看涨。"
                    ),
                )
            else: # score_diff < -10
                return self._t(
                    language,
                    en=(
                        f"Research decision: bearish case (confidence {bear_confidence}%) is clearly stronger than bullish "
                        f"(confidence {bull_confidence}%). Lean bearish."
                    ),
                    zh=(
                        f"研究经理决策：基于看跌论据（置信度 {bear_confidence}%）明显强于看涨论据（置信度 {bull_confidence}%），明确倾向于看跌。"
                    ),
                )
                
        except Exception as e:
            logger.error(f"Research decision failed: {e}")
            language = context.get("language", "en-US") if isinstance(context, dict) else "en-US"
            return self._t(language, en="Research decision: unable to reach a clear conclusion.", zh="研究经理决策：无法做出明确判断。")
    
    def _make_risk_decision(self, risky: Dict, neutral: Dict, safe: Dict,
                           trader: Dict, context: Dict) -> Dict[str, Any]:
        """Risk manager final decision (lightweight)."""
        try:
            language = context.get("language", "en-US")
            trader_decision = trader.get('data', {}).get('decision', 'HOLD')
            trader_confidence = trader.get('data', {}).get('confidence', 50)
            
            # Risk debate summary
            risk_summary = {
                "risky_view": risky.get('data', {}).get('recommendation', ''),
                "neutral_view": neutral.get('data', {}).get('recommendation', ''),
                "safe_view": safe.get('data', {}).get('recommendation', ''),
            }
            
            # Final decision (use trader decision + risk debate context)
            final_decision = {
                "decision": trader_decision,
                "confidence": trader_confidence,
                "reasoning": self._t(
                    language,
                    en=f"Final decision is based on trader analysis ({trader_decision}, confidence {trader_confidence}%) and the risk debate.",
                    zh=f"基于交易员分析（{trader_decision}，置信度 {trader_confidence}%）和风险辩论，做出最终决策。",
                ),
                "risk_summary": risk_summary,
                "recommendation": trader.get('data', {}).get('report', '')
            }
            
            return final_decision
        except Exception as e:
            logger.error(f"Risk decision failed: {e}")
            language = context.get("language", "en-US") if isinstance(context, dict) else "en-US"
            return {
                "decision": "HOLD",
                "confidence": 50,
                "reasoning": self._t(language, en="Risk decision failed", zh="风险决策失败"),
                "risk_summary": {},
                "recommendation": ""
            }
    
    def _generate_overview(self, context: Dict, final_decision: Dict) -> Dict[str, Any]:
        """Generate overview section (lightweight, deterministic)."""
        try:
            language = context.get("language", "en-US")
            # Extract dimension scores
            technical_data = context.get('market_report', {}).get('data', {})
            fundamental_data = context.get('fundamental_report', {}).get('data', {})
            news_data = context.get('news_report', {}).get('data', {})
            sentiment_data = context.get('sentiment_report', {}).get('data', {})
            risk_data = context.get('risk_report', {}).get('data', {})

            technical_score = technical_data.get('score', 50)
            fundamental_score = fundamental_data.get('score', 50)
            news_score = news_data.get('score', 50)
            sentiment_score = sentiment_data.get('score', 50)
            risk_score = risk_data.get('score', 50)
            
            # Generate an overall score using weighted dimensions + decision/confidence adjustment
            decision = final_decision.get('decision', 'HOLD')
            confidence = final_decision.get('confidence', 50)
            
            # 1) Base score: weighted average (tech 30%, fundamental 25%, news 15%, sentiment 15%, risk 15%)
            weighted_score = (
                technical_score * 0.3 +
                fundamental_score * 0.25 +
                news_score * 0.15 +
                sentiment_score * 0.15 +
                risk_score * 0.15
            )
            
            # 2) Decision adjustment: BUY pushes toward 60-100, SELL toward 0-40, HOLD toward 50
            if decision == 'BUY':
                target_score = 60 + (confidence / 100 * 40)  # Map to 60-100
                overall_score = (weighted_score * 0.4) + (target_score * 0.6)
            elif decision == 'SELL':
                target_score = 40 - (confidence / 100 * 40)  # Map to 0-40
                overall_score = (weighted_score * 0.4) + (target_score * 0.6)
            else:
                overall_score = (weighted_score * 0.6) + (50 * 0.4)
            
            # Clamp to 0..100
            overall_score = max(0, min(100, int(overall_score)))
            
            return {
                "overallScore": overall_score,
                "recommendation": decision,
                "confidence": confidence,
                "dimensionScores": {
                    "fundamental": fundamental_score,
                    "technical": technical_score,
                    "news": news_score,
                    "sentiment": sentiment_score,
                    "risk": risk_score
                },
                "report": final_decision.get(
                    'reasoning',
                    self._t(language, en="Overview generated.", zh="综合分析完成"),
                )
            }
        except Exception as e:
            logger.error(f"Generate overview failed: {e}")
            language = context.get("language", "en-US") if isinstance(context, dict) else "en-US"
            return {
                "overallScore": 50,
                "recommendation": "HOLD",
                "confidence": 50,
                "dimensionScores": {
                    "fundamental": 50,
                    "technical": 50,
                    "news": 50,
                    "sentiment": 50,
                    "risk": 50
                },
                "report": self._t(language, en="Failed to generate overview.", zh="综合分析生成失败")
            }
    
    def reflect_and_learn(self, market: str, symbol: str, decision: str,
                          returns: Optional[float] = None, result: Optional[str] = None):
        """
        Reflection hook: store post-trade outcomes into memory (local-only).

        Args:
            market: Market
            symbol: Symbol
            decision: BUY/SELL/HOLD
            returns: Return percentage
            result: Free-text outcome
        """
        if not self.enable_memory:
            return
        
        try:
            situation = f"{market}:{symbol} trading decision"
            recommendation = f"Decision: {decision}, returns: {returns if returns is not None else 'N/A'}"
            
            # Update trader memory
            if 'trader' in self.memories:
                self.memories['trader'].add_memory(
                    situation,
                    recommendation,
                    result,
                    returns,
                    metadata={
                        "market": market,
                        "symbol": symbol,
                        "timeframe": None,
                        "features": {
                            "source": "manual_reflect",
                        }
                    },
                )
            
            logger.info(f"Reflection completed: {market}:{symbol}, decision={decision}, returns={returns}")
        except Exception as e:
            logger.error(f"Reflection failed: {e}")
