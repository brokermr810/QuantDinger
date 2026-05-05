"""
美股数据源
使用 yfinance 和 finnhub 获取数据
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

import yfinance as yf

from app.data_sources.base import BaseDataSource
from app.utils.logger import get_logger
from app.config import APIKeys, YFinanceConfig

logger = get_logger(__name__)


class USStockDataSource(BaseDataSource):
    """美股数据源"""
    
    name = "USStock/yfinance"
    
    # yfinance 时间周期映射
    INTERVAL_MAP = {
        '1m': '1m',
        '3m': '1m',
        '5m': '5m',
        '15m': '15m',
        '30m': '30m',
        '1H': '1h',
        '4H': '4h',
        '1D': '1d',
        '1W': '1wk'
    }
    
    # 不同周期获取数据的天数范围
    # 美股每日约6.5交易小时，交易日/日历日 ≈ 5/7；乘1.5留余量
    DAYS_MAP = {
        '1m': lambda limit: min(7, max(1, (limit // 390) + 2)),
        '3m': lambda limit: min(7, max(1, (limit // 130) + 2)),
        '5m': lambda limit: min(60, max(1, (limit // 78) + 2)),
        '15m': lambda limit: min(60, max(2, (limit // 26) + 3)),
        '30m': lambda limit: min(60, max(2, (limit // 13) + 3)),
        '1H': lambda limit: min(730, max(5, int(limit / 6.5 * 7 / 5 * 1.5) + 5)),
        '4H': lambda limit: min(730, max(10, int(limit / 1.625 * 7 / 5 * 1.5) + 5)),
        '1D': lambda limit: min(3650, limit + 1),
        '1W': lambda limit: min(3650, (limit * 7) + 7)
    }

    MERGE_FACTOR_MAP = {
        '3m': 3,
    }
    
    def __init__(self):
        # 初始化 finnhub 作为备选
        self.finnhub_client = None
        try:
            import finnhub
            if APIKeys.is_configured('FINNHUB_API_KEY'):
                self.finnhub_client = finnhub.Client(api_key=APIKeys.FINNHUB_API_KEY)
                logger.info("Finnhub client initialized")
        except Exception as e:
            logger.warning(f"Finnhub init failed: {e}")
    
    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        获取美股实时报价
        
        优先使用 Finnhub（更实时），降级使用 yfinance fast_info
        
        Returns:
            dict: {
                'last': 当前价格,
                'change': 涨跌额,
                'changePercent': 涨跌幅,
                'high': 最高价,
                'low': 最低价,
                'open': 开盘价,
                'previousClose': 昨收价
            }
        """
        symbol = (symbol or '').strip().upper()
        
        # 优先使用 Finnhub（实时数据）
        if self.finnhub_client:
            try:
                quote = self.finnhub_client.quote(symbol)
                if quote and quote.get('c'):
                    return {
                        'last': quote.get('c', 0),           # 当前价格
                        'change': quote.get('d', 0),         # 涨跌额
                        'changePercent': quote.get('dp', 0), # 涨跌幅
                        'high': quote.get('h', 0),           # 日内最高
                        'low': quote.get('l', 0),            # 日内最低
                        'open': quote.get('o', 0),           # 开盘价
                        'previousClose': quote.get('pc', 0)  # 昨收价
                    }
            except Exception as e:
                msg = str(e).lower()
                if "403" in str(e) or "don't have access" in msg or "no access" in msg:
                    logger.debug(f"Finnhub quote skipped (no access): {symbol}: {e}")
                else:
                    logger.warning(f"Finnhub quote failed for {symbol}: {e}")
        
        # 降级使用 yfinance
        try:
            ticker = yf.Ticker(symbol)
            
            # 尝试 fast_info（更快）
            try:
                fast_info = ticker.fast_info
                last_price = fast_info.get('lastPrice') or fast_info.get('last_price')
                prev_close = fast_info.get('previousClose') or fast_info.get('previous_close') or fast_info.get('regularMarketPreviousClose')
                
                if last_price:
                    change = (last_price - prev_close) if prev_close else 0
                    change_pct = (change / prev_close * 100) if prev_close else 0
                    return {
                        'last': float(last_price),
                        'change': round(change, 4),
                        'changePercent': round(change_pct, 2),
                        'high': float(fast_info.get('dayHigh') or fast_info.get('day_high') or last_price),
                        'low': float(fast_info.get('dayLow') or fast_info.get('day_low') or last_price),
                        'open': float(fast_info.get('open') or fast_info.get('regularMarketOpen') or last_price),
                        'previousClose': float(prev_close) if prev_close else 0
                    }
            except Exception as e:
                logger.debug(f"yfinance fast_info failed for {symbol}: {e}")
            
            # 降级使用 info（较慢但数据更全）
            try:
                info = ticker.info
                last_price = info.get('regularMarketPrice') or info.get('currentPrice')
                prev_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
                
                if last_price:
                    change = (last_price - prev_close) if prev_close else 0
                    change_pct = (change / prev_close * 100) if prev_close else 0
                    return {
                        'last': float(last_price),
                        'change': round(change, 4),
                        'changePercent': round(change_pct, 2),
                        'high': float(info.get('regularMarketDayHigh') or info.get('dayHigh') or last_price),
                        'low': float(info.get('regularMarketDayLow') or info.get('dayLow') or last_price),
                        'open': float(info.get('regularMarketOpen') or info.get('open') or last_price),
                        'previousClose': float(prev_close) if prev_close else 0
                    }
            except Exception as e:
                logger.debug(f"yfinance info failed for {symbol}: {e}")
            
            # 最后降级：使用最近的 1 分钟 K 线
            try:
                hist = ticker.history(period='1d', interval='1m')
                if hist is not None and not hist.empty:
                    last_row = hist.iloc[-1]
                    first_row = hist.iloc[0]
                    last_price = float(last_row['Close'])
                    open_price = float(first_row['Open'])
                    
                    return {
                        'last': last_price,
                        'change': round(last_price - open_price, 4),
                        'changePercent': round((last_price - open_price) / open_price * 100, 2) if open_price else 0,
                        'high': float(hist['High'].max()),
                        'low': float(hist['Low'].min()),
                        'open': open_price,
                        'previousClose': open_price  # 近似
                    }
            except Exception as e:
                logger.debug(f"yfinance history fallback failed for {symbol}: {e}")
                
        except Exception as e:
            logger.error(f"Failed to get ticker for {symbol}: {e}")
        
        return {'last': 0, 'symbol': symbol}
    
    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """获取美股K线数据"""
        klines = []
        
        try:
            interval = self.INTERVAL_MAP.get(timeframe, '1d')
            days_func = self.DAYS_MAP.get(timeframe, lambda x: x + 1)
            merge_factor = self.MERGE_FACTOR_MAP.get(timeframe, 1)
            effective_limit = limit * merge_factor
            days = days_func(effective_limit)
            
            # 计算日期范围
            if before_time:
                end_date = datetime.fromtimestamp(before_time)
                start_date = end_date - timedelta(days=days)
            else:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
            if after_time is not None:
                floor = datetime.fromtimestamp(after_time)
                start_date = min(start_date, floor)
            
            # logger.info(f"使用 yfinance 获取 {symbol}, 周期: {interval}, 日期: {start_date.date()} ~ {end_date.date()}")
            
            # 尝试 yfinance
            df = self._fetch_yfinance(symbol, interval, start_date, end_date)
            
            if df is None or df.empty:
                # 尝试 finnhub
                if self.finnhub_client and timeframe == '1D':
                    klines = self._fetch_finnhub(symbol, start_date, end_date, limit)
                    if klines:
                        return self.filter_and_limit(
                            klines,
                            limit,
                            before_time,
                            after_time,
                            truncate=(after_time is None),
                        )
            else:
                klines = self._convert_dataframe(df, effective_limit)
                if merge_factor > 1:
                    klines = self._merge_every_n_sorted_bars(klines, merge_factor)
            
            # 过滤和限制
            klines = self.filter_and_limit(
                klines,
                limit,
                before_time,
                after_time,
                truncate=(after_time is None),
            )
            
            # 记录结果
            self.log_result(symbol, klines, timeframe)
            
        except Exception as e:
            logger.error(f"Failed to fetch US stock K-lines {symbol}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
        return klines
    
    def _fetch_yfinance(self, symbol: str, interval: str, start_date: datetime, end_date: datetime):
        """使用 yfinance 获取数据"""
        try:
            ticker = yf.Ticker(symbol)
            
            # yfinance 的 end 参数是不包含的（exclusive），所以需要加一天才能包含 end_date 当天的数据
            # 例如：end="2026-01-12" 实际只返回到 2026-01-11 的数据
            end_date_inclusive = end_date + timedelta(days=1)
            
            df = ticker.history(
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date_inclusive.strftime('%Y-%m-%d'),
                interval=interval
            )
            # logger.info(f"yfinance 返回 {len(df) if df is not None and not df.empty else 0} 条数据")
            return df
        except Exception as e:
            logger.warning(f"yfinance fetch failed: {e}")
            return None

    def _merge_every_n_sorted_bars(self, bars: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        if n <= 1 or len(bars) < n:
            return bars
        bars = sorted(bars, key=lambda x: x['time'])
        out = []
        for i in range(0, len(bars) - len(bars) % n, n):
            chunk = bars[i:i + n]
            out.append({
                'time': chunk[0]['time'],
                'open': chunk[0]['open'],
                'high': max(b['high'] for b in chunk),
                'low': min(b['low'] for b in chunk),
                'close': chunk[-1]['close'],
                'volume': round(sum(b['volume'] for b in chunk), 2),
            })
        return out

    def _fetch_finnhub(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        limit: int
    ) -> List[Dict[str, Any]]:
        """使用 finnhub 获取日线数据"""
        klines = []
        try:
            start_ts = int(start_date.timestamp())
            end_ts = int(end_date.timestamp())
            
            # logger.info(f"使用 Finnhub 获取 {symbol} 日线数据")
            candles = self.finnhub_client.stock_candles(symbol, 'D', start_ts, end_ts)
            
            if candles and candles.get('s') == 'ok':
                for i in range(len(candles['t'])):
                    klines.append(self.format_kline(
                        timestamp=candles['t'][i],
                        open_price=candles['o'][i],
                        high=candles['h'][i],
                        low=candles['l'][i],
                        close=candles['c'][i],
                        volume=candles['v'][i]
                    ))
                # logger.info(f"Finnhub 返回 {len(klines)} 条数据")
        except Exception as e:
            msg = str(e).lower()
            # Free tier / plan: 403 "You don't have access to this resource" is common; avoid ERROR spam.
            if "403" in str(e) or "don't have access" in msg or "no access" in msg:
                logger.debug(f"Finnhub candles skipped (no access): {symbol}: {e}")
            else:
                logger.warning(f"Finnhub fetch failed: {e}")
        
        return klines
    
    def _convert_dataframe(self, df, limit: int) -> List[Dict[str, Any]]:
        """转换 DataFrame 为K线列表"""
        klines = []
        df = df.tail(limit).reset_index()
        
        # 确定时间列名（日线是 Date，分钟级是 Datetime）
        time_col = None
        if 'Datetime' in df.columns:
            time_col = 'Datetime'
        elif 'Date' in df.columns:
            time_col = 'Date'
        elif 'index' in df.columns:
            time_col = 'index'
        
        if time_col is None:
            logger.warning(f"Unable to determine time column; available columns: {df.columns.tolist()}")
            return klines
        
        for _, row in df.iterrows():
            try:
                # 处理时间戳
                time_value = row[time_col]
                if hasattr(time_value, 'timestamp'):
                    ts = int(time_value.timestamp())
                else:
                    continue
                
                klines.append(self.format_kline(
                    timestamp=ts,
                    open_price=row['Open'],
                    high=row['High'],
                    low=row['Low'],
                    close=row['Close'],
                    volume=row['Volume']
                ))
            except Exception as e:
                logger.debug(f"Failed to parse row data: {e}")
                continue
        
        return klines

