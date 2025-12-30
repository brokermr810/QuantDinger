"""
加密货币数据源
使用 CCXT (Coinbase) 获取数据
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import ccxt

from app.data_sources.base import BaseDataSource, TIMEFRAME_SECONDS
from app.utils.logger import get_logger
from app.config import CCXTConfig, APIKeys

logger = get_logger(__name__)


class CryptoDataSource(BaseDataSource):
    """加密货币数据源"""
    
    name = "Crypto/CCXT"
    
    # 时间周期映射
    TIMEFRAME_MAP = CCXTConfig.TIMEFRAME_MAP
    
    def __init__(self):
        config = {
            'timeout': CCXTConfig.TIMEOUT,
            'enableRateLimit': CCXTConfig.ENABLE_RATE_LIMIT
        }
        
        # 如果配置了代理
        if CCXTConfig.PROXY:
            config['proxies'] = {
                'http': CCXTConfig.PROXY,
                'https': CCXTConfig.PROXY
            }
        
        exchange_id = CCXTConfig.DEFAULT_EXCHANGE
        
        # 动态加载交易所类
        if not hasattr(ccxt, exchange_id):
            logger.warning(f"CCXT exchange '{exchange_id}' not found, falling back to 'coinbase'")
            exchange_id = 'coinbase'
            
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class(config)

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Get latest ticker for a crypto symbol via CCXT.

        Accepts common formats:
        - BTC/USDT
        - BTCUSDT
        - BTC/USDT:USDT (swap-style suffix, will be normalized)
        """
        sym = (symbol or "").strip()
        if ":" in sym:
            sym = sym.split(":", 1)[0]
        sym = sym.upper()
        if "/" not in sym:
            # Coinbase often uses USD, check if we need to adapt
            if sym.endswith("USDT") and len(sym) > 4:
                sym = f"{sym[:-4]}/USDT"
            elif sym.endswith("USD") and len(sym) > 3:
                sym = f"{sym[:-3]}/USD"
        return self.exchange.fetch_ticker(sym)
    
    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取加密货币K线数据"""
        klines = []
        
        try:
            ccxt_timeframe = self.TIMEFRAME_MAP.get(timeframe, '1d')
            
            # 构建交易对符号
            if not symbol.endswith('USDT') and not symbol.endswith('USD'):
                symbol_pair = f'{symbol}/USDT'
            else:
                symbol_pair = symbol
            
            # logger.info(f"获取加密货币K线: {symbol_pair}, 周期: {ccxt_timeframe}, 条数: {limit}")
            
            ohlcv = self._fetch_ohlcv(symbol_pair, ccxt_timeframe, limit, before_time, timeframe)
            
            if not ohlcv:
                logger.warning(f"CCXT returned no K-lines: {symbol_pair}")
                return []
            
            # 转换数据格式
            for candle in ohlcv:
                if len(candle) < 6:
                    continue
                klines.append(self.format_kline(
                    timestamp=int(candle[0] / 1000),  # 毫秒转秒
                    open_price=candle[1],
                    high=candle[2],
                    low=candle[3],
                    close=candle[4],
                    volume=candle[5]
                ))
            
            # 过滤和限制
            klines = self.filter_and_limit(klines, limit, before_time)
            
            # 记录结果
            self.log_result(symbol, klines, timeframe)
            
        except Exception as e:
            logger.error(f"Failed to fetch crypto K-lines {symbol}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        
        return klines
    
    def _fetch_ohlcv(
        self,
        symbol_pair: str,
        ccxt_timeframe: str,
        limit: int,
        before_time: Optional[int],
        timeframe: str
    ) -> List:
        """获取OHLCV数据（支持分页获取完整数据）"""
        try:
            if before_time:
                # 计算时间范围
                total_seconds = self.calculate_time_range(timeframe, limit)
                end_time = datetime.fromtimestamp(before_time)
                start_time = end_time - timedelta(seconds=total_seconds)
                since = int(start_time.timestamp() * 1000)
                end_ms = before_time * 1000
                
                # logger.info(f"历史数据请求: since={since//1000}, end={before_time}, 时间跨度={total_seconds/86400:.1f}天")
                
                # 分页获取数据，直到覆盖完整时间范围
                all_ohlcv = []
                batch_limit = 300  # Coinbase limit is often 300, safer than 1000
                current_since = since
                
                while current_since < end_ms:
                    batch = self.exchange.fetch_ohlcv(
                        symbol_pair, 
                        ccxt_timeframe, 
                        since=current_since, 
                        limit=batch_limit
                    )
                    
                    if not batch:
                        break
                    
                    all_ohlcv.extend(batch)
                    
                    # 获取最后一条数据的时间，作为下次请求的起始时间
                    last_timestamp = batch[-1][0]
                    
                    # 如果最后一条数据时间超过了结束时间，或者返回数据少于请求量，说明已经获取完毕
                    if last_timestamp >= end_ms or len(batch) < batch_limit:
                        break
                    
                    # 下次从最后一条的下一个时间点开始
                    timeframe_ms = TIMEFRAME_SECONDS.get(timeframe, 86400) * 1000
                    current_since = last_timestamp + timeframe_ms
                    
                    # logger.info(f"分页获取中: 已获取 {len(all_ohlcv)} 条, 继续从 {datetime.fromtimestamp(current_since/1000)}")
                
                ohlcv = all_ohlcv
            else:
                ohlcv = self.exchange.fetch_ohlcv(symbol_pair, ccxt_timeframe, limit=limit)
            
            # logger.info(f"CCXT 返回 {len(ohlcv) if ohlcv else 0} 条数据")
            return ohlcv
            
        except Exception as e:
            logger.warning(f"CCXT fetch_ohlcv failed: {str(e)}; trying fallback")
            return self._fetch_ohlcv_fallback(symbol_pair, ccxt_timeframe, limit, before_time, timeframe)
    
    def _fetch_ohlcv_fallback(
        self,
        symbol_pair: str,
        ccxt_timeframe: str,
        limit: int,
        before_time: Optional[int],
        timeframe: str
    ) -> List:
        """备用获取方法"""
        try:
            total_seconds = self.calculate_time_range(timeframe, limit)
            
            if before_time:
                end_time = datetime.fromtimestamp(before_time)
                start_time = end_time - timedelta(seconds=total_seconds)
                since = int(start_time.timestamp() * 1000)
            else:
                since = int((datetime.now() - timedelta(seconds=total_seconds)).timestamp() * 1000)
            
            ohlcv = self.exchange.fetch_ohlcv(symbol_pair, ccxt_timeframe, since=since, limit=limit)
            # logger.info(f"CCXT 备用方法返回 {len(ohlcv) if ohlcv else 0} 条数据")
            return ohlcv
        except Exception as e:
            logger.error(f"CCXT fallback method also failed: {str(e)}")
            return []

