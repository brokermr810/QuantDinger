"""
Agent tools.

Provides data fetching helpers for the multi-agent analysis pipeline.
All docstrings/log messages in this module are English. Output language of AI reports
is controlled by the `language` value passed through the analysis context.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import os
import time
import pandas as pd
import yfinance as yf
import finnhub
import ccxt
import requests

from app.utils.logger import get_logger
from app.config import APIKeys
from app.services.search import SearchService

logger = get_logger(__name__)


class AgentTools:
    """A thin wrapper around various public data sources used by agents."""
    
    def __init__(self):
        self.search_service = SearchService()
        self.finnhub_client = None
        if APIKeys.is_configured('FINNHUB_API_KEY'):
            try:
                self.finnhub_client = finnhub.Client(api_key=APIKeys.FINNHUB_API_KEY)
            except Exception as e:
                # Safe logging to avoid cascading errors during exception handling
                try:
                    logger.warning(f"Finnhub init failed: {e}")
                except Exception:
                    # Fallback to print if logging fails
                    print(f"Warning: Finnhub init failed: {e}")

        # Optional dependency: akshare (A-share fundamentals/company info)
        try:
            import akshare as ak  # type: ignore
            self._ak = ak
            self._has_akshare = True
        except Exception:
            self._ak = None
            self._has_akshare = False

        # AShare spot cache (avoid fetching the full market list repeatedly)
        self._ashare_spot_cache = None
        self._ashare_spot_cache_ts = 0
        self._ashare_spot_cache_ttl = 300  # seconds

    def _get_ashare_spot_df(self):
        """Cached AShare spot dataframe via akshare (may be heavy on first load)."""
        if not self._akshare_required():
            return None
        now = int(time.time())
        if self._ashare_spot_cache is not None and (now - int(self._ashare_spot_cache_ts)) < int(self._ashare_spot_cache_ttl):
            return self._ashare_spot_cache
        ak = self._ak
        if ak is None or not hasattr(ak, "stock_zh_a_spot_em"):
            return None
        df = ak.stock_zh_a_spot_em()
        self._ashare_spot_cache = df
        self._ashare_spot_cache_ts = now
        return df

    def _ccxt_exchange(self):
        """Create a CCXT exchange client (Binance) with optional proxy support."""
        cfg: Dict[str, Any] = {'timeout': 5000, 'enableRateLimit': True}
        # Keep proxy behavior consistent with data sources (.env PROXY_* is supported)
        from app.config import CCXTConfig
        proxy = (CCXTConfig.PROXY or '').strip()
        if proxy:
            cfg['proxies'] = {'http': proxy, 'https': proxy}
        return ccxt.binance(cfg)

    def _akshare_required(self) -> bool:
        """Whether akshare is available at runtime."""
        return bool(self._has_akshare and self._ak is not None)
    
    def get_stock_data(self, market: str, symbol: str, days: int = 30, timeframe: str = "1d") -> Optional[List[Dict[str, Any]]]:
        """
        Get daily Kline data for recent days (best-effort).
        
        Args:
            market: Market
            symbol: Symbol
            days: Days (for daily) / candle count hint (best-effort for intraday)
            timeframe: Kline timeframe (best-effort). Common values: 1d, 1h, 4h, 1w
            
        Returns:
            List of OHLCV dicts or None
        """
        try:
            klines = []
            tf = (timeframe or "1d").strip().lower()
            # Normalize common UI values
            tf_map = {
                "1d": "1d",
                "1day": "1d",
                "d": "1d",
                "1h": "1h",
                "60m": "1h",
                "4h": "4h",
                "240m": "4h",
                "1w": "1wk",
                "1wk": "1wk",
                "w": "1wk",
            }
            tf_yf = tf_map.get(tf, "1d")
            
            if market == 'USStock':
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=days + 5)).strftime('%Y-%m-%d')
                
                ticker = yf.Ticker(symbol)
                # yfinance supports limited intervals. Fallback to 1d when unsupported.
                interval = tf_yf if tf_yf in ["1d", "1h", "1wk"] else "1d"
                df = ticker.history(start=start_date, end=end_date, interval=interval)
                
                if not df.empty:
                    df = df.tail(days).reset_index()
                    for _, row in df.iterrows():
                        klines.append({
                            "time": row['Date'].strftime('%Y-%m-%d'),
                            "open": round(row['Open'], 4),
                            "high": round(row['High'], 4),
                            "low": round(row['Low'], 4),
                            "close": round(row['Close'], 4),
                            "volume": int(row['Volume'])
                        })
                    return klines
            
            elif market == 'Crypto':
                exchange = self._ccxt_exchange()
                symbol_pair = f'{symbol}/USDT'
                start_time = int((datetime.now() - timedelta(days=days)).timestamp())
                # CCXT timeframes: 1d, 1h, 4h ...
                ccxt_tf = tf if tf in ["1d", "1h", "4h"] else "1d"
                ohlcv = exchange.fetch_ohlcv(symbol_pair, ccxt_tf, since=start_time * 1000, limit=days)
                if ohlcv:
                    for candle in ohlcv:
                        klines.append({
                            "time": datetime.fromtimestamp(candle[0] / 1000).strftime('%Y-%m-%d'),
                            "open": candle[1],
                            "high": candle[2],
                            "low": candle[3],
                            "close": candle[4],
                            "volume": candle[5]
                        })
                    return klines
            
            # CN/HK stocks
            if market in ('AShare', 'HShare'):
                # Prefer akshare for AShare (requested), fall back to yfinance.
                if market == 'AShare' and self._akshare_required():
                    try:
                        ak = self._ak
                        start_date = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')
                        end_date = datetime.now().strftime('%Y%m%d')
                        # akshare returns a dataframe with Chinese column names.
                        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
                        if df is not None and not df.empty:
                            df = df.tail(days)
                            for _, row in df.iterrows():
                                dt = row.get('日期')
                                # dt can be datetime/date/str
                                if hasattr(dt, "strftime"):
                                    t = dt.strftime('%Y-%m-%d')
                                else:
                                    t = str(dt)[:10]
                                klines.append({
                                    "time": t,
                                    "open": float(row.get('开盘', 0) or 0),
                                    "high": float(row.get('最高', 0) or 0),
                                    "low": float(row.get('最低', 0) or 0),
                                    "close": float(row.get('收盘', 0) or 0),
                                    "volume": float(row.get('成交量', 0) or 0),
                                })
                            return klines
                    except Exception as e:
                        logger.warning(f"akshare AShare kline failed ({symbol}): {e}")

                # yfinance fallback (daily)
                if market == 'AShare':
                    yf_symbol = f"{symbol}.SS" if symbol.startswith('6') else f"{symbol}.SZ"
                else:
                    yf_symbol = f"{symbol.zfill(4)}.HK"

                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=days + 5)).strftime('%Y-%m-%d')

                ticker = yf.Ticker(yf_symbol)
                interval = tf_yf if tf_yf in ["1d", "1h", "1wk"] else "1d"
                df = ticker.history(start=start_date, end=end_date, interval=interval)

                if not df.empty:
                    df = df.tail(days).reset_index()
                    for _, row in df.iterrows():
                        klines.append({
                            "time": row['Date'].strftime('%Y-%m-%d'),
                            "open": round(row['Open'], 4),
                            "high": round(row['High'], 4),
                            "low": round(row['Low'], 4),
                            "close": round(row['Close'], 4),
                            "volume": int(row['Volume'])
                        })
                    return klines
                    
        except Exception as e:
            logger.error(f"Failed to fetch kline data {market}:{symbol}: {e}")
        
        return None
    
    def get_current_price(self, market: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current price (best-effort)."""
        try:
            if market == 'USStock' and self.finnhub_client:
                quote = self.finnhub_client.quote(symbol)
                if quote and quote.get('c'):
                    return {
                        "price": quote.get('c', 0),
                        "change": quote.get('d', 0),
                        "changePercent": quote.get('dp', 0),
                        "high": quote.get('h', 0),
                        "low": quote.get('l', 0),
                        "open": quote.get('o', 0),
                        "previousClose": quote.get('pc', 0)
                    }
            elif market == 'Crypto':
                exchange = self._ccxt_exchange()
                symbol_pair = f'{symbol}/USDT'
                ticker = exchange.fetch_ticker(symbol_pair)
                if ticker:
                    return {
                        "price": ticker.get('last', 0),
                        "change": ticker.get('change', 0),
                        "changePercent": ticker.get('percentage', 0),
                        "high": ticker.get('high', 0),
                        "low": ticker.get('low', 0),
                        "open": ticker.get('open', 0),
                        "volume": ticker.get('quoteVolume', 0)
                    }
            
            # CN/HK stocks: prefer akshare for AShare (requested)
            if market in ('AShare', 'HShare'):
                if market == 'AShare' and self._akshare_required():
                    try:
                        ak = self._ak
                        df = self._get_ashare_spot_df()
                        if df is not None and not df.empty:
                            row = df[df['代码'] == symbol].iloc[0]
                            price = float(row.get('最新价', 0) or 0)
                            change = float(row.get('涨跌额', 0) or 0)
                            change_pct = float(row.get('涨跌幅', 0) or 0)
                            high = float(row.get('最高', 0) or 0)
                            low = float(row.get('最低', 0) or 0)
                            open_p = float(row.get('今开', 0) or 0)
                            prev_close = float(row.get('昨收', 0) or 0)
                            return {
                                "price": price,
                                "change": change,
                                "changePercent": change_pct,
                                "high": high,
                                "low": low,
                                "open": open_p,
                                "previousClose": prev_close
                            }
                    except Exception as e:
                        logger.warning(f"akshare AShare spot failed ({symbol}): {e}")

                # Do not use Tencent for AShare by default (requested). If akshare is not available,
                # return None and let the LLM report degrade gracefully.
                if market == 'AShare':
                    if not self._akshare_required():
                        logger.warning("akshare is not installed; AShare spot price is unavailable.")
                    return None

                # HShare fallback: Tencent quote
                symbol_code = f'hk{symbol}'

                url = f"http://qt.gtimg.cn/q={symbol_code}"
                resp = requests.get(url, timeout=10)
                content = resp.content.decode('gbk', errors='ignore')
                if '="' in content:
                    data_str = content.split('="')[1].strip('";\n')
                    if data_str:
                        parts = data_str.split('~')
                        if len(parts) > 32:
                            return {
                                "price": float(parts[3]) if parts[3] else 0,
                                "change": float(parts[31]) if parts[31] else 0,
                                "changePercent": float(parts[32]) if parts[32] else 0,
                                "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                                "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                                "open": float(parts[5]) if len(parts) > 5 and parts[5] else 0,
                                "previousClose": float(parts[4]) if parts[4] else 0
                            }
        except Exception as e:
            logger.error(f"Failed to fetch current price {market}:{symbol}: {e}")
        
        return None
    
    def get_fundamental_data(self, market: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Get fundamental data (best-effort)."""
        try:
            if market == 'USStock' and self.finnhub_client:
                metrics = self.finnhub_client.company_basic_financials(symbol, 'all')
                profile = self.finnhub_client.company_profile2(symbol=symbol)
                
                return {
                    "metrics": metrics.get('metric', {}),
                    "profile_metrics": {
                        "marketCapitalization": profile.get('marketCapitalization', 0),
                        "currency": profile.get('currency', 'USD'),
                        "finnhubIndustry": profile.get('finnhubIndustry', ''),
                    }
                }

            # AShare fundamentals via akshare (requested)
            if market == 'AShare' and self._akshare_required():
                ak = self._ak
                out: Dict[str, Any] = {"metrics": {}, "profile_metrics": {}}

                # 1) Use spot list (fast) for valuation/market cap
                try:
                    df = self._get_ashare_spot_df()
                    if df is not None and not df.empty:
                        row = df[df['代码'] == symbol].iloc[0]
                        out["metrics"].update({
                            "pe_ttm": row.get('市盈率-动态'),
                            "pb": row.get('市净率'),
                            "turnoverRate": row.get('换手率'),
                        })
                        out["profile_metrics"].update({
                            "marketCapitalization": row.get('总市值'),
                            "floatMarketCap": row.get('流通市值'),
                            "currency": "CNY",
                        })
                except Exception as e:
                    logger.debug(f"akshare spot metrics unavailable ({symbol}): {e}")

                # 2) Try akshare indicator endpoints (optional, may be slower / may change)
                try:
                    if hasattr(ak, "stock_a_lg_indicator"):
                        ind_df = ak.stock_a_lg_indicator(symbol=symbol)
                        if ind_df is not None and not ind_df.empty:
                            last = ind_df.iloc[-1].to_dict()
                            out["metrics"].update(last)
                except Exception as e:
                    logger.debug(f"akshare indicator fetch failed ({symbol}): {e}")

                return out
        except Exception as e:
            logger.error(f"Failed to fetch fundamental data {market}:{symbol}: {e}")
        
        return None
    
    def get_company_data(self, market: str, symbol: str, language: str = "en-US") -> Optional[Dict[str, Any]]:
        """Get basic company/project info (best-effort)."""
        try:
            # 1) Finnhub (mainly for US stocks)
            if market == 'USStock' and self.finnhub_client:
                profile = self.finnhub_client.company_profile2(symbol=symbol)
                if profile:
                    return {
                        "name": profile.get('name', symbol),
                        "ticker": profile.get('ticker', symbol),
                        "exchange": profile.get('exchange', ''),
                        "industry": profile.get('finnhubIndustry', ''),
                        "website": profile.get('weburl', ''),
                        "marketCapitalization": profile.get('marketCapitalization', 0),
                        "description": f"Sector: {profile.get('finnhubIndustry', '')}, Country: {profile.get('country', '')}"
                    }
            
            # 2) Basic info for AShare / HShare / Crypto
            elif market in ('AShare', 'HShare', 'Crypto'):
                name = symbol
                if market == 'AShare':
                    # Prefer akshare for AShare (requested)
                    if self._akshare_required():
                        try:
                            ak = self._ak
                            # 1) Individual info (more structured)
                            if hasattr(ak, "stock_individual_info_em"):
                                df = ak.stock_individual_info_em(symbol=symbol)
                                if df is not None and not df.empty and 'item' in df.columns and 'value' in df.columns:
                                    info = {str(r['item']).strip(): r['value'] for _, r in df.iterrows()}
                                    # common keys: 股票简称, 所属行业, 上市时间, 总市值 ...
                                    name = str(info.get('股票简称') or info.get('证券简称') or symbol).strip()
                                    industry = str(info.get('所属行业') or '').strip()
                                    website = str(info.get('公司网址') or '').strip()
                                    market_cap = info.get('总市值') or info.get('总市值(元)') or 0
                                    return {
                                        "name": name or symbol,
                                        "ticker": symbol,
                                        "market": market,
                                        "industry": industry,
                                        "website": website,
                                        "marketCapitalization": market_cap,
                                        "description": f"Industry: {industry}" if industry else ""
                                    }
                            # 2) Spot list for name
                            df2 = ak.stock_zh_a_spot_em()
                            if df2 is not None and not df2.empty:
                                row = df2[df2['代码'] == symbol].iloc[0]
                                name = str(row.get('名称') or symbol).strip()
                        except Exception as e:
                            logger.debug(f"akshare company info failed ({symbol}): {e}")

                    # Do not use Tencent for AShare by default (requested).
                    if not self._akshare_required():
                        logger.warning("akshare is not installed; AShare company info is limited.")
                elif market == 'Crypto':
                    name = f"{symbol} Cryptocurrency"

                # Enrich description via web search (best-effort)
                # Query language should follow UI language when possible.
                if str(language).lower().startswith('zh'):
                    search_query = f"{name} {symbol} 公司 简介" if market != 'Crypto' else f"{symbol} 加密 项目 介绍"
                else:
                    search_query = f"{name} {symbol} company profile" if market != 'Crypto' else f"{symbol} crypto project info"
                search_results = self.search_service.search(search_query, num_results=1)
                description = ""
                if search_results:
                    description = search_results[0].get('snippet', '')

                return {
                    "name": name, 
                    "ticker": symbol, 
                    "market": market,
                    "description": description
                }

        except Exception as e:
            logger.error(f"Failed to fetch company data {market}:{symbol}: {e}")
        
        return None

    def _fetch_page_content(self, url: str) -> str:
        """
        Fetch readable page content via Jina Reader.

        Args:
            url: Target URL

        Returns:
            Extracted content (markdown-ish), truncated
        """
        try:
            jina_url = f"https://r.jina.ai/{url}"
            # Use a slightly longer timeout for content extraction
            response = requests.get(jina_url, timeout=15) 
            if response.status_code == 200:
                content = response.text
                # Truncate to avoid huge prompts
                if len(content) > 3000:
                    content = content[:3000] + "..."
                return content
            return ""
        except Exception as e:
            logger.warning(f"Jina Reader content fetch failed {url}: {e}")
            return ""

    def get_news(self, market: str, symbol: str, days: int = 7, company_name: str = None) -> List[Dict[str, Any]]:
        """
        Get news items (Finnhub + search engine) and optionally enrich via Jina Reader.

        Args:
            market: Market
            symbol: Symbol/pair
            days: Lookback days
            company_name: Optional company/project name to improve search

        Returns:
            List of news items
        """
        news_list = []
        
        # 1) Finnhub news (if available)
        try:
            if self.finnhub_client:
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                
                raw_news = []
                
                if market == 'USStock':
                    raw_news = self.finnhub_client.company_news(symbol, _from=start_date, to=end_date)
                elif market == 'Crypto':
                    crypto_symbol = symbol.split('/')[0] if '/' in symbol else symbol
                    raw_news = self.finnhub_client.crypto_news(crypto_symbol)
                else:
                    raw_news = self.finnhub_client.general_news('general', min_id=0)
                
                if raw_news:
                    for item in raw_news:
                        if not item.get('headline') or not item.get('summary'):
                            continue
                        news_list.append({
                            "id": str(item.get('id', '')),
                            "datetime": datetime.fromtimestamp(item.get('datetime', 0)).strftime('%Y-%m-%d %H:%M'),
                            "headline": item.get('headline', ''),
                            "summary": item.get('summary', ''),
                            "source": f"Finnhub ({item.get('source', '')})",
                            "url": item.get('url', '')
                        })
        except Exception as e:
            logger.warning(f"Finnhub news fetch failed: {e}")

        # 2) Supplement with search engine results (useful for non-US markets or specific events)
        try:
            # Build search query (use company name to improve relevance)
            search_query = ""
            search_name = company_name if company_name else symbol
            
            # Time restriction for Google CSE
            date_restrict = f"d{days}"
            
            if market == 'AShare':
                # AShare CN keywords
                search_query = f'"{search_name}" {symbol} (利好 OR 利空 OR 财报 OR 公告 OR 业绩) after:{datetime.now().year-1}'
            elif market == 'HShare':
                search_query = f'"{search_name}" {symbol} (港股 OR 股价 OR 业绩) after:{datetime.now().year-1}'
            elif market == 'Crypto':
                search_query = f'"{search_name}" {symbol} crypto news analysis'
            else:
                search_query = f'"{search_name}" {symbol} stock news'
            
            logger.info(f"Running news search: {search_query}")
            # Google CSE uses `dateRestrict` as a separate param; SearchService supports it.
            search_results = self.search_service.search(search_query, num_results=10, date_restrict=date_restrict)
            
            for i, item in enumerate(search_results):
                # Default: use snippet as summary
                summary = f"{item.get('snippet', '')} (Source: {item.get('source', '')})"
                
                # Jina Reader: deep-read only first 2 items to avoid slowdowns
                if i < 2 and item.get('link'):
                    logger.info(f"Deep reading: {item.get('title')}")
                    full_content = self._fetch_page_content(item.get('link'))
                    if full_content:
                        summary = f"Deep content:\n{full_content}\n(Source: {item.get('source', '')})"
                
                news_list.append({
                    "id": item.get('link', ''),  # Use link as a stable id
                    "datetime": item.get('published', datetime.now().strftime('%Y-%m-%d')),  # Fallback to today if missing
                    "headline": item.get('title', ''),
                    "summary": summary,
                    "source": f"Search ({item.get('source', '')})",
                    "url": item.get('link', '')
                })
                
        except Exception as e:
            logger.warning(f"Search news failed: {e}")
            
        # Sort by time desc and keep latest items (best-effort; time formats may vary)
        news_list.sort(key=lambda x: x.get('datetime', ''), reverse=True)
        return news_list[:20]
    
    def calculate_technical_indicators(self, kline_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate basic technical indicators from kline data.

        Args:
            kline_data: List of OHLCV dicts

        Returns:
            Indicators dict
        """
        if not kline_data or len(kline_data) < 20:
            return {}
        
        try:
            df = pd.DataFrame(kline_data)
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df['high'] = pd.to_numeric(df['high'], errors='coerce')
            df['low'] = pd.to_numeric(df['low'], errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            
            indicators = {}
            
            # Moving averages
            if len(df) >= 20:
                indicators['MA20'] = round(df['close'].tail(20).mean(), 4)
            if len(df) >= 50:
                indicators['MA50'] = round(df['close'].tail(50).mean(), 4)
            
            # RSI
            if len(df) >= 14:
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                indicators['RSI'] = round(rsi.iloc[-1], 2) if not rsi.empty else None
            
            # MACD
            if len(df) >= 26:
                exp1 = df['close'].ewm(span=12, adjust=False).mean()
                exp2 = df['close'].ewm(span=26, adjust=False).mean()
                macd = exp1 - exp2
                signal = macd.ewm(span=9, adjust=False).mean()
                indicators['MACD'] = round(macd.iloc[-1], 4) if not macd.empty else None
                indicators['MACD_Signal'] = round(signal.iloc[-1], 4) if not signal.empty else None
                indicators['MACD_Histogram'] = round((macd - signal).iloc[-1], 4) if not (macd - signal).empty else None
            
            # Bollinger bands
            if len(df) >= 20:
                sma = df['close'].rolling(window=20).mean()
                std = df['close'].rolling(window=20).std()
                indicators['BB_Upper'] = round((sma + 2 * std).iloc[-1], 4) if not sma.empty else None
                indicators['BB_Middle'] = round(sma.iloc[-1], 4) if not sma.empty else None
                indicators['BB_Lower'] = round((sma - 2 * std).iloc[-1], 4) if not sma.empty else None
            
            return indicators
            
        except Exception as e:
            logger.error(f"Failed to calculate technical indicators: {e}")
            return {}
