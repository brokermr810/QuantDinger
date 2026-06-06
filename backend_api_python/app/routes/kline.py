"""
K线数据 API 路由
"""
from flask import Blueprint, request, jsonify
from datetime import datetime
import traceback

from app.services.kline import KlineService
from app.utils.logger import get_logger

logger = get_logger(__name__)

kline_bp = Blueprint('kline', __name__)
kline_service = KlineService()


@kline_bp.route('/kline', methods=['GET'])
def get_kline():
    """
    获取K线数据
    
    参数:
        market: 市场类型 (Crypto, USStock, Forex, Futures)
        symbol: 交易对/股票代码
        timeframe: 时间周期 (1m, 5m, 15m, 30m, 1H, 4H, 1D, 1W)
        limit: 数据条数 (默认300)
        before_time: 获取此时间之前的数据 (可选，Unix时间戳)
    """
    try:
        # 强制 GET, 使用 request.args
        market = request.args.get('market', 'USStock')
        symbol = request.args.get('symbol', '')
        timeframe = request.args.get('timeframe', '1D')
        limit = int(request.args.get('limit', 300))
        before_time = request.args.get('before_time') or request.args.get('beforeTime')
        
        if before_time:
            before_time = int(before_time)
        
        if not symbol:
            return jsonify({
                'code': 0,
                'msg': 'Missing symbol parameter',
                'data': None
            }), 400
        
        logger.info(f"Requesting K-lines: {market}:{symbol}, timeframe={timeframe}, limit={limit}")
        
        klines = kline_service.get_kline(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            before_time=before_time
        )
        
        resolved_symbol = symbol
        if market == 'Crypto' and klines:
            try:
                from app.data_sources import DataSourceFactory
                from app.data_sources.crypto import CryptoDataSource
                source = DataSourceFactory.get_source(market)
                if isinstance(source, CryptoDataSource):
                    resolved_symbol = source._symbol_for_scoped_market(symbol)
            except Exception as ex:
                logger.warning(f"Failed to resolve symbol for frontend: {ex}")
        
        if not klines:
            # 针对特定情况给出更详细的提示
            msg = 'No data found'
            if market == 'Forex' and timeframe == '1m':
                msg = 'Forex 1-minute data requires Tiingo paid subscription'
            elif market == 'Forex' and timeframe in ('1W', '1M'):
                msg = 'No weekly/monthly data available for this period'
            return jsonify({
                'code': 0,
                'msg': msg,
                'data': [],
                'hint': 'tiingo_subscription' if (market == 'Forex' and timeframe == '1m') else None
            })
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': klines,
            'symbol': resolved_symbol
        })
        
    except Exception as e:
        logger.error(f"Failed to fetch K-lines: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'code': 0,
            'msg': f'Failed to fetch kline data: {str(e)}',
            'data': None
        }), 500


@kline_bp.route('/price', methods=['GET'])
def get_price():
    """获取最新价格"""
    try:
        market = request.args.get('market', 'USStock')
        symbol = request.args.get('symbol', '')
        
        if not symbol:
            return jsonify({
                'code': 0,
                'msg': 'Missing symbol parameter',
                'data': None
            }), 400
        
        price_data = kline_service.get_latest_price(market, symbol)
        
        if not price_data:
            return jsonify({
                'code': 0,
                'msg': 'No price data found',
                'data': None
            })
        
        return jsonify({
            'code': 1,
            'msg': 'success',
            'data': price_data
        })
        
    except Exception as e:
        logger.error(f"Failed to fetch price: {str(e)}")
        return jsonify({
            'code': 0,
            'msg': f'Failed to fetch price: {str(e)}',
            'data': None
        }), 500

