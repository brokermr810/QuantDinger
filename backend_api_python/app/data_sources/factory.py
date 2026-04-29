"""
数据源工厂
根据市场类型返回对应的数据源
"""
from typing import Dict, List, Any, Optional

from app.data_sources.base import BaseDataSource
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 小写 / 别名 -> 与 _create_source 一致的 PascalCase key
_MARKET_ALIASES: Dict[str, str] = {
    "crypto": "Crypto",
    "cryptocurrency": "Crypto",
    "forex": "Forex",
    "fx": "Forex",
    "usstock": "USStock",
    "us_stocks": "USStock",
    "stock": "USStock",
    "cnstock": "CNStock",
    "hkstock": "HKStock",
    "futures": "Futures",
    "moex": "MOEX",
    "rustock": "MOEX",
    "rustocks": "MOEX",
    "russianstock": "MOEX",
    "russia": "MOEX",
}


class DataSourceFactory:
    """
    数据源工厂。
    K 线 / 报价 使用哪个接口完全由调用方传入的 market（与自选分类一致）决定，不做根据 symbol 字符串的推断。
    """
    
    _sources: Dict[str, BaseDataSource] = {}
    
    @classmethod
    def normalize_market(cls, market: str) -> str:
        """统一市场枚举大小写与别名，供路由与数据源入口使用。"""
        if not market:
            return "Crypto"
        raw = str(market).strip()
        if raw in ("Crypto", "Forex", "Futures", "USStock", "CNStock", "HKStock", "MOEX"):
            return raw
        key = raw.lower().replace(" ", "").replace("-", "_")
        return _MARKET_ALIASES.get(key, raw)

    @classmethod
    def get_source(cls, market: str) -> BaseDataSource:
        """
        获取指定市场的数据源
        
        Args:
            market: 市场类型 (Crypto, USStock, Forex, Futures)
            
        Returns:
            数据源实例
        """
        market = cls.normalize_market(market or "")
        if market not in cls._sources:
            cls._sources[market] = cls._create_source(market)
        return cls._sources[market]

    @classmethod
    def get_data_source(cls, name: str) -> BaseDataSource:
        """
        Backward compatible alias used by older code paths.

        Some modules historically called `get_data_source("binance")` to fetch a crypto data source.
        In the localized Python backend we primarily use `get_source("Crypto")`.
        """
        key = (name or "").strip().lower()
        if key in ("crypto", "binance", "okx", "bybit", "bitget", "kucoin", "gate", "mexc", "kraken", "coinbase"):
            return cls.get_source("Crypto")
        if key in ("futures",):
            return cls.get_source("Futures")
        if key in ("forex", "fx"):
            return cls.get_source("Forex")
        # Default to Crypto for safety (most callers want a ticker for crypto pairs).
        return cls.get_source("Crypto")
    
    @classmethod
    def _create_source(cls, market: str) -> BaseDataSource:
        """创建数据源实例"""
        if market == 'Crypto':
            from app.data_sources.crypto import CryptoDataSource
            return CryptoDataSource()
        elif market == 'CNStock':
            from app.data_sources.cn_stock import CNStockDataSource
            return CNStockDataSource()
        elif market == 'HKStock':
            from app.data_sources.hk_stock import HKStockDataSource
            return HKStockDataSource()
        elif market == 'USStock':
            from app.data_sources.us_stock import USStockDataSource
            return USStockDataSource()
        elif market == 'Forex':
            from app.data_sources.forex import ForexDataSource
            return ForexDataSource()
        elif market == 'Futures':
            from app.data_sources.futures import FuturesDataSource
            return FuturesDataSource()
        elif market == 'MOEX':
            from app.data_sources.moex import MOEXDataSource
            return MOEXDataSource()
        else:
            raise ValueError(f"不支持的市场类型: {market}")
    
    @classmethod
    def get_kline(
        cls,
        market: str,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取K线数据的便捷方法
        
        Args:
            market: 市场类型
            symbol: 交易对/股票代码
            timeframe: 时间周期
            limit: 数据条数
            before_time: 获取此时间之前的数据
            after_time: 可选，Unix 秒，K 线 time 需 >= 此值（回测左边界）
            
        Returns:
            K线数据列表
        """
        try:
            m = cls.normalize_market(market or "")
            source = cls.get_source(m)
            klines = source.get_kline(symbol, timeframe, limit, before_time, after_time)
            
            # 确保数据按时间排序
            klines.sort(key=lambda x: x['time'])
            
            return klines
        except Exception as e:
            logger.error(f"Failed to fetch K-lines {market}:{symbol} (normalized={cls.normalize_market(market or '')}) - {str(e)}")
            return []
    
    @classmethod
    def get_ticker(cls, market: str, symbol: str) -> Dict[str, Any]:
        """
        获取实时报价的便捷方法
        
        Args:
            market: 市场类型
            symbol: 交易对/股票代码
            
        Returns:
            实时报价数据: {
                'last': 最新价,
                'change': 涨跌额,
                'changePercent': 涨跌幅,
                ...
            }
        """
        try:
            m = cls.normalize_market(market or "")
            source = cls.get_source(m)
            return source.get_ticker(symbol)
        except NotImplementedError:
            logger.warning(f"get_ticker not implemented for market: {market}")
            return {'last': 0, 'symbol': symbol}
        except Exception as e:
            logger.error(f"Failed to fetch ticker {market}:{symbol} - {str(e)}")
            return {'last': 0, 'symbol': symbol}

