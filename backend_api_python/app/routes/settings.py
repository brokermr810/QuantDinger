"""
Settings API - 读取和保存 .env 配置
"""
import os
import re
from flask import Blueprint, request, jsonify
from app.utils.logger import get_logger
from app.utils.config_loader import clear_config_cache

logger = get_logger(__name__)

settings_bp = Blueprint('settings', __name__)

# .env 文件路径
ENV_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')

# 配置项定义（分组）- 完整对照 env.example
CONFIG_SCHEMA = {
    'auth': {
        'title': '认证配置',
        'items': [
            {'key': 'SECRET_KEY', 'label': 'Secret Key', 'type': 'password', 'default': 'quantdinger-secret-key-change-me'},
            {'key': 'ADMIN_USER', 'label': '管理员用户名', 'type': 'text', 'default': 'quantdinger'},
            {'key': 'ADMIN_PASSWORD', 'label': '管理员密码', 'type': 'password', 'default': '123456'},
        ]
    },
    'server': {
        'title': '服务器配置',
        'items': [
            {'key': 'PYTHON_API_HOST', 'label': '监听地址', 'type': 'text', 'default': '0.0.0.0'},
            {'key': 'PYTHON_API_PORT', 'label': '端口', 'type': 'number', 'default': '5000'},
            {'key': 'PYTHON_API_DEBUG', 'label': '调试模式', 'type': 'boolean', 'default': 'False'},
        ]
    },
    'worker': {
        'title': '订单处理配置',
        'items': [
            {'key': 'ENABLE_PENDING_ORDER_WORKER', 'label': '启用订单处理Worker', 'type': 'boolean', 'default': 'True'},
            {'key': 'PENDING_ORDER_STALE_SEC', 'label': '订单超时时间(秒)', 'type': 'number', 'default': '90'},
        ]
    },
    'notification': {
        'title': '信号通知配置',
        'items': [
            {'key': 'SIGNAL_WEBHOOK_URL', 'label': 'Webhook URL', 'type': 'text', 'required': False},
            {'key': 'SIGNAL_WEBHOOK_TOKEN', 'label': 'Webhook Token', 'type': 'password', 'required': False},
            {'key': 'SIGNAL_NOTIFY_TIMEOUT_SEC', 'label': '通知超时(秒)', 'type': 'number', 'default': '6'},
            {'key': 'TELEGRAM_BOT_TOKEN', 'label': 'Telegram Bot Token', 'type': 'password', 'required': False, 'link': 'https://t.me/BotFather', 'link_text': 'settings.link.createBot'},
        ]
    },
    'smtp': {
        'title': '邮件SMTP配置',
        'items': [
            {'key': 'SMTP_HOST', 'label': 'SMTP服务器', 'type': 'text', 'required': False},
            {'key': 'SMTP_PORT', 'label': 'SMTP端口', 'type': 'number', 'default': '587'},
            {'key': 'SMTP_USER', 'label': 'SMTP用户名', 'type': 'text', 'required': False},
            {'key': 'SMTP_PASSWORD', 'label': 'SMTP密码', 'type': 'password', 'required': False},
            {'key': 'SMTP_FROM', 'label': '发件人地址', 'type': 'text', 'required': False},
            {'key': 'SMTP_USE_TLS', 'label': '使用TLS', 'type': 'boolean', 'default': 'True'},
            {'key': 'SMTP_USE_SSL', 'label': '使用SSL', 'type': 'boolean', 'default': 'False'},
        ]
    },
    'twilio': {
        'title': 'Twilio短信配置',
        'items': [
            {'key': 'TWILIO_ACCOUNT_SID', 'label': 'Account SID', 'type': 'password', 'required': False, 'link': 'https://console.twilio.com/', 'link_text': 'settings.link.getApi'},
            {'key': 'TWILIO_AUTH_TOKEN', 'label': 'Auth Token', 'type': 'password', 'required': False},
            {'key': 'TWILIO_FROM_NUMBER', 'label': '发送号码', 'type': 'text', 'required': False},
        ]
    },
    'strategy': {
        'title': '策略执行配置',
        'items': [
            {'key': 'DISABLE_RESTORE_RUNNING_STRATEGIES', 'label': '禁用自动恢复策略', 'type': 'boolean', 'default': 'False'},
            {'key': 'STRATEGY_TICK_INTERVAL_SEC', 'label': '策略Tick间隔(秒)', 'type': 'number', 'default': '10'},
            {'key': 'PRICE_CACHE_TTL_SEC', 'label': '价格缓存TTL(秒)', 'type': 'number', 'default': '10'},
        ]
    },
    'proxy': {
        'title': '代理配置',
        'items': [
            {'key': 'PROXY_PORT', 'label': '代理端口', 'type': 'text', 'required': False},
            {'key': 'PROXY_HOST', 'label': '代理主机', 'type': 'text', 'default': '127.0.0.1'},
            {'key': 'PROXY_SCHEME', 'label': '代理协议', 'type': 'select', 'options': ['socks5h', 'socks5', 'http', 'https'], 'default': 'socks5h'},
            {'key': 'PROXY_URL', 'label': '完整代理URL', 'type': 'text', 'required': False},
        ]
    },
    'app': {
        'title': '应用配置',
        'items': [
            {'key': 'CORS_ORIGINS', 'label': 'CORS来源', 'type': 'text', 'default': '*'},
            {'key': 'RATE_LIMIT', 'label': '速率限制(每分钟)', 'type': 'number', 'default': '100'},
            {'key': 'ENABLE_CACHE', 'label': '启用缓存', 'type': 'boolean', 'default': 'False'},
            {'key': 'ENABLE_REQUEST_LOG', 'label': '启用请求日志', 'type': 'boolean', 'default': 'True'},
            {'key': 'ENABLE_AI_ANALYSIS', 'label': '启用AI分析', 'type': 'boolean', 'default': 'True'},
        ]
    },
    'ai': {
        'title': 'AI/LLM配置',
        'items': [
            {'key': 'OPENROUTER_API_KEY', 'label': 'OpenRouter API Key', 'type': 'password', 'required': False, 'link': 'https://openrouter.ai/keys', 'link_text': 'settings.link.getApiKey'},
            {'key': 'OPENROUTER_API_URL', 'label': 'OpenRouter API URL', 'type': 'text', 'default': 'https://openrouter.ai/api/v1/chat/completions'},
            {'key': 'OPENROUTER_MODEL', 'label': '默认模型', 'type': 'text', 'default': 'openai/gpt-4o', 'link': 'https://openrouter.ai/models', 'link_text': 'settings.link.viewModels'},
            {'key': 'OPENROUTER_TEMPERATURE', 'label': 'Temperature', 'type': 'number', 'default': '0.7'},
            {'key': 'OPENROUTER_MAX_TOKENS', 'label': 'Max Tokens', 'type': 'number', 'default': '4000'},
            {'key': 'OPENROUTER_TIMEOUT', 'label': '超时时间(秒)', 'type': 'number', 'default': '300'},
            {'key': 'OPENROUTER_CONNECT_TIMEOUT', 'label': '连接超时(秒)', 'type': 'number', 'default': '30'},
            {'key': 'AI_MODELS_JSON', 'label': '模型列表(JSON)', 'type': 'text', 'default': '{}', 'required': False},
        ]
    },
    'market': {
        'title': '市场预设',
        'items': [
            {'key': 'MARKET_TYPES_JSON', 'label': '市场类型(JSON)', 'type': 'text', 'default': '[]', 'required': False},
            {'key': 'TRADING_SUPPORTED_SYMBOLS_JSON', 'label': '支持的交易对(JSON)', 'type': 'text', 'default': '[]', 'required': False},
        ]
    },
    'data_source': {
        'title': '数据源配置',
        'items': [
            {'key': 'DATA_SOURCE_TIMEOUT', 'label': '数据源超时(秒)', 'type': 'number', 'default': '30'},
            {'key': 'DATA_SOURCE_RETRY', 'label': '重试次数', 'type': 'number', 'default': '3'},
            {'key': 'DATA_SOURCE_RETRY_BACKOFF', 'label': '重试退避(秒)', 'type': 'number', 'default': '0.5'},
            {'key': 'FINNHUB_API_KEY', 'label': 'Finnhub API Key', 'type': 'password', 'required': False, 'link': 'https://finnhub.io/register', 'link_text': 'settings.link.freeRegister'},
            {'key': 'FINNHUB_TIMEOUT', 'label': 'Finnhub超时(秒)', 'type': 'number', 'default': '10'},
            {'key': 'FINNHUB_RATE_LIMIT', 'label': 'Finnhub速率限制', 'type': 'number', 'default': '60'},
            {'key': 'CCXT_DEFAULT_EXCHANGE', 'label': 'CCXT默认交易所', 'type': 'text', 'default': 'coinbase', 'link': 'https://github.com/ccxt/ccxt#supported-cryptocurrency-exchange-markets', 'link_text': 'settings.link.supportedExchanges'},
            {'key': 'CCXT_TIMEOUT', 'label': 'CCXT超时(ms)', 'type': 'number', 'default': '10000'},
            {'key': 'CCXT_PROXY', 'label': 'CCXT代理', 'type': 'text', 'required': False},
            {'key': 'AKSHARE_TIMEOUT', 'label': 'Akshare超时(秒)', 'type': 'number', 'default': '30'},
            {'key': 'YFINANCE_TIMEOUT', 'label': 'YFinance超时(秒)', 'type': 'number', 'default': '30'},
            {'key': 'TIINGO_API_KEY', 'label': 'Tiingo API Key', 'type': 'password', 'required': False, 'link': 'https://www.tiingo.com/account/api/token', 'link_text': 'settings.link.getToken'},
            {'key': 'TIINGO_TIMEOUT', 'label': 'Tiingo超时(秒)', 'type': 'number', 'default': '10'},
        ]
    },
    'search': {
        'title': '搜索配置',
        'items': [
            {'key': 'SEARCH_PROVIDER', 'label': '搜索提供商', 'type': 'select', 'options': ['google', 'bing', 'none'], 'default': 'google'},
            {'key': 'SEARCH_MAX_RESULTS', 'label': '最大结果数', 'type': 'number', 'default': '10'},
            {'key': 'SEARCH_GOOGLE_API_KEY', 'label': 'Google API Key', 'type': 'password', 'required': False, 'link': 'https://developers.google.com/custom-search/v1/introduction', 'link_text': 'settings.link.applyApi'},
            {'key': 'SEARCH_GOOGLE_CX', 'label': 'Google CX', 'type': 'text', 'required': False, 'link': 'https://programmablesearchengine.google.com/controlpanel/all', 'link_text': 'settings.link.createSearchEngine'},
            {'key': 'SEARCH_BING_API_KEY', 'label': 'Bing API Key', 'type': 'password', 'required': False, 'link': 'https://www.microsoft.com/en-us/bing/apis/bing-web-search-api', 'link_text': 'settings.link.applyApi'},
            {'key': 'INTERNAL_API_KEY', 'label': '内部API Key', 'type': 'password', 'required': False},
        ]
    },
}


def read_env_file():
    """读取 .env 文件"""
    env_values = {}
    
    if not os.path.exists(ENV_FILE_PATH):
        logger.warning(f".env file not found at {ENV_FILE_PATH}")
        return env_values
    
    try:
        with open(ENV_FILE_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                # 解析 KEY=VALUE
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # 移除引号
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    env_values[key] = value
    except Exception as e:
        logger.error(f"Failed to read .env file: {e}")
    
    return env_values


def write_env_file(env_values):
    """写入 .env 文件，保留注释和格式"""
    lines = []
    existing_keys = set()
    
    # 读取原文件保留格式
    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    original_line = line
                    stripped = line.strip()
                    
                    # 保留空行和注释
                    if not stripped or stripped.startswith('#'):
                        lines.append(original_line)
                        continue
                    
                    # 更新已存在的键
                    if '=' in stripped:
                        key = stripped.split('=', 1)[0].strip()
                        if key in env_values:
                            existing_keys.add(key)
                            value = env_values[key]
                            # 如果值包含特殊字符，用引号包裹
                            if ' ' in str(value) or '"' in str(value) or "'" in str(value):
                                lines.append(f'{key}="{value}"\n')
                            else:
                                lines.append(f'{key}={value}\n')
                        else:
                            lines.append(original_line)
                    else:
                        lines.append(original_line)
        except Exception as e:
            logger.error(f"Failed to read .env file for update: {e}")
    
    # 添加新的键
    new_keys = set(env_values.keys()) - existing_keys
    if new_keys:
        if lines and not lines[-1].endswith('\n'):
            lines.append('\n')
        lines.append('\n# Added by Settings UI\n')
        for key in sorted(new_keys):
            value = env_values[key]
            if ' ' in str(value) or '"' in str(value) or "'" in str(value):
                lines.append(f'{key}="{value}"\n')
            else:
                lines.append(f'{key}={value}\n')
    
    # 写入文件
    try:
        with open(ENV_FILE_PATH, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return True
    except Exception as e:
        logger.error(f"Failed to write .env file: {e}")
        return False


@settings_bp.route('/schema', methods=['GET'])
def get_settings_schema():
    """获取配置项定义"""
    return jsonify({
        'code': 1,
        'msg': 'success',
        'data': CONFIG_SCHEMA
    })


@settings_bp.route('/values', methods=['GET'])
def get_settings_values():
    """获取当前配置值 - 包括敏感信息（真实值）"""
    env_values = read_env_file()
    
    # 构建返回数据，返回真实值
    result = {}
    for group_key, group in CONFIG_SCHEMA.items():
        result[group_key] = {}
        for item in group['items']:
            key = item['key']
            value = env_values.get(key, item.get('default', ''))
            result[group_key][key] = value
            # 标记密码类型是否已配置
            if item['type'] == 'password':
                result[group_key][f'{key}_configured'] = bool(value)
    
    return jsonify({
        'code': 1,
        'msg': 'success',
        'data': result
    })


@settings_bp.route('/save', methods=['POST'])
def save_settings():
    """保存配置"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'code': 0, 'msg': '无效的请求数据'})
        
        # 读取当前配置
        current_env = read_env_file()
        
        # 更新配置
        updates = {}
        for group_key, group_values in data.items():
            if group_key not in CONFIG_SCHEMA:
                continue
            
            for item in CONFIG_SCHEMA[group_key]['items']:
                key = item['key']
                if key in group_values:
                    new_value = group_values[key]
                    
                    # 空值处理
                    if new_value is None or new_value == '':
                        if not item.get('required', True):
                            updates[key] = ''
                    else:
                        updates[key] = str(new_value)
        
        # 合并更新
        current_env.update(updates)
        
        # 写入文件
        if write_env_file(current_env):
            # 清除配置缓存
            clear_config_cache()
            
            return jsonify({
                'code': 1,
                'msg': '配置保存成功',
                'data': {
                    'updated_keys': list(updates.keys()),
                    'requires_restart': True  # 标记需要重启
                }
            })
        else:
            return jsonify({'code': 0, 'msg': '保存配置失败'})
    
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")
        return jsonify({'code': 0, 'msg': f'保存失败: {str(e)}'})


@settings_bp.route('/test-connection', methods=['POST'])
def test_connection():
    """测试API连接"""
    try:
        data = request.get_json()
        service = data.get('service')
        
        if service == 'openrouter':
            # 测试 OpenRouter 连接
            from app.services.llm import LLMService
            llm = LLMService()
            result = llm.test_connection()
            if result:
                return jsonify({'code': 1, 'msg': 'OpenRouter连接成功'})
            else:
                return jsonify({'code': 0, 'msg': 'OpenRouter连接失败'})
        
        elif service == 'finnhub':
            # 测试 Finnhub 连接
            import requests
            api_key = data.get('api_key') or os.getenv('FINNHUB_API_KEY')
            if not api_key:
                return jsonify({'code': 0, 'msg': 'API Key未配置'})
            resp = requests.get(
                f'https://finnhub.io/api/v1/quote?symbol=AAPL&token={api_key}',
                timeout=10
            )
            if resp.status_code == 200:
                return jsonify({'code': 1, 'msg': 'Finnhub连接成功'})
            else:
                return jsonify({'code': 0, 'msg': f'Finnhub连接失败: {resp.status_code}'})
        
        return jsonify({'code': 0, 'msg': '未知服务'})
    
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return jsonify({'code': 0, 'msg': f'测试失败: {str(e)}'})
