"""
数据源配置
"""
import os

class MetaDataSourceConfig(type):
    @property
    def DEFAULT_TIMEOUT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('data_source', {}).get('timeout')
        return int(val) if val is not None else int(os.getenv('DATA_SOURCE_TIMEOUT', 30))

    @property
    def RETRY_COUNT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('data_source', {}).get('retry_count')
        return int(val) if val is not None else int(os.getenv('DATA_SOURCE_RETRY', 3))

    @property
    def RETRY_BACKOFF(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('data_source', {}).get('retry_backoff')
        return float(val) if val is not None else float(os.getenv('DATA_SOURCE_RETRY_BACKOFF', 0.5))


class DataSourceConfig(metaclass=MetaDataSourceConfig):
    """数据源通用配置"""
    pass


class MetaFinnhubConfig(type):
    @property
    def BASE_URL(cls):
        return "https://finnhub.io/api/v1"

    @property
    def TIMEOUT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('finnhub', {}).get('timeout')
        return int(val) if val is not None else int(os.getenv('FINNHUB_TIMEOUT', 10))

    @property
    def RATE_LIMIT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('finnhub', {}).get('rate_limit')
        return int(val) if val is not None else int(os.getenv('FINNHUB_RATE_LIMIT', 60))

    @property
    def RATE_LIMIT_PERIOD(cls):
        return 60


class FinnhubConfig(metaclass=MetaFinnhubConfig):
    """Finnhub 数据源配置"""
    pass


class MetaTiingoConfig(type):
    @property
    def BASE_URL(cls):
        return "https://api.tiingo.com/tiingo"

    @property
    def TIMEOUT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('tiingo', {}).get('timeout')
        return int(val) if val is not None else int(os.getenv('TIINGO_TIMEOUT', 10))


class TiingoConfig(metaclass=MetaTiingoConfig):
    """Tiingo 数据源配置"""
    pass


class MetaYFinanceConfig(type):
    @property
    def TIMEOUT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('yfinance', {}).get('timeout')
        return int(val) if val is not None else int(os.getenv('YFINANCE_TIMEOUT', 30))
    
    @property
    def INTERVAL_MAP(cls):
        return {
            '1m': '1m',
            '3m': '3m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1H': '1h',
            '4H': '4h',
            '1D': '1d',
            '1W': '1wk'
        }


class YFinanceConfig(metaclass=MetaYFinanceConfig):
    """Yahoo Finance 数据源配置"""
    pass


class MetaCCXTConfig(type):
    @property
    def DEFAULT_EXCHANGE(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('ccxt', {}).get('default_exchange')
        return val if val else os.getenv('CCXT_DEFAULT_EXCHANGE', 'binance')

    @property
    def TIMEOUT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('ccxt', {}).get('timeout')
        return int(val) if val is not None else int(os.getenv('CCXT_TIMEOUT', 10000))

    @property
    def ENABLE_RATE_LIMIT(cls):
        return True

    @property
    def TIMEFRAME_MAP(cls):
        return {
            '1m': '1m',
            '3m': '3m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1H': '1h',
            '4H': '4h',
            '1D': '1d',
            '1W': '1w'
        }

    @property
    def PROXY(cls):
        # 1) Local proxy helpers from backend_api_python/.env
        # PROXY_URL has the highest priority if provided.
        proxy_url = (os.getenv('PROXY_URL') or '').strip()
        if proxy_url:
            return proxy_url

        # 2) Standard proxy envs (fallback)
        for key in ['HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY']:
            v = (os.getenv(key) or '').strip()
            if v:
                return v

        return ''


class CCXTConfig(metaclass=MetaCCXTConfig):
    """CCXT 加密货币数据源配置"""
    pass


class MetaAkshareConfig(type):
    @property
    def TIMEOUT(cls):
        from app.utils.config_loader import load_addon_config
        val = load_addon_config().get('akshare', {}).get('timeout')
        return int(val) if val is not None else int(os.getenv('AKSHARE_TIMEOUT', 30))

    @property
    def PERIOD_MAP(cls):
        return {
            '1D': 'daily',
            '1W': 'weekly'
        }


class AkshareConfig(metaclass=MetaAkshareConfig):
    """Akshare 数据源配置"""
    pass
