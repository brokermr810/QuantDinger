"""
QuantDinger Python API entrypoint.
"""
import os
import sys

# Ensure UTF-8 console output on Windows to avoid UnicodeEncodeError in logs.
# (PowerShell default encoding may be GBK/CP936.)
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Load local .env early so config classes can read from os.environ.
# This keeps local deployment simple: edit one file and run.
try:
    from dotenv import load_dotenv

    this_dir = os.path.dirname(os.path.abspath(__file__))
    # Primary: backend_api_python/.env (same dir as run.py)
    load_dotenv(os.path.join(this_dir, ".env"), override=False)
    # Fallback: repo-root/.env (one level up) for users who place .env at workspace root.
    parent_dir = os.path.dirname(this_dir)
    load_dotenv(os.path.join(parent_dir, ".env"), override=False)
except Exception:
    # python-dotenv is optional; environment variables can still be provided by the OS.
    pass

# Optional: disable tqdm progress bars (some data providers like akshare may emit them),
# keeping console logs clean in local mode.
os.environ.setdefault("TQDM_DISABLE", "1")

# Optional: normalize outbound proxy settings for the whole process.
# This makes requests/yfinance/finnhub/tiingo/GoogleSearch etc work behind a local proxy.
#
# Chinese domestic data sources (AkShare → Eastmoney/Sina/etc.) should bypass the proxy
# to avoid unnecessary round-trips through overseas proxies.
_CN_FINANCIAL_DOMAINS = ",".join([
    ".eastmoney.com",
    ".sina.com.cn",
    ".sinajs.cn",
    ".10jqka.com.cn",
    ".ssec.com.cn",
    ".szse.cn",
    ".hexun.com",
    ".cninfo.com.cn",
    ".gtimg.cn",
    ".qq.com",
    ".tencent.com",
    ".mairui.club",
    ".akshare.xyz",
    ".baostock.com",
    ".stcn.com",
    ".p5w.net",
    ".finance.sina.com.cn",
])


def _apply_proxy_env():
    def _set_if_blank(key: str, value: str) -> None:
        """
        Set env var if it is missing OR present but empty.
        (`os.environ.setdefault` does not override empty strings.)
        """
        cur = os.getenv(key)
        if cur is None or str(cur).strip() == "":
            os.environ[key] = value

    # If user provided explicit proxy URL, honor it.
    proxy_url = (os.getenv('PROXY_URL') or '').strip()

    if not proxy_url:
        return

    # Standard env vars used by requests and many libraries.
    _set_if_blank('ALL_PROXY', proxy_url)
    _set_if_blank('HTTP_PROXY', proxy_url)
    _set_if_blank('HTTPS_PROXY', proxy_url)

    # Bypass proxy for Chinese domestic financial data sources.
    # AkShare calls Eastmoney/Sina/etc. which should go direct, not through overseas proxy.
    existing_no_proxy = (os.getenv('NO_PROXY') or '').strip()
    if existing_no_proxy:
        merged = existing_no_proxy + "," + _CN_FINANCIAL_DOMAINS
    else:
        merged = _CN_FINANCIAL_DOMAINS
    os.environ['NO_PROXY'] = merged
    os.environ['no_proxy'] = merged


_apply_proxy_env()

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config.settings import Config

# Create app instance (for gunicorn use)
# gunicorn -c gunicorn_config.py "run:app"
app = create_app()


def main():
    """启动应用"""
    # Keep startup messages ASCII-only and short.
    print("QuantDinger Python API v2.2.2")

    # ========== Critical Security Check for SECRET_KEY ==========
    # In production (DEBUG=False), the SECRET_KEY MUST NOT use the default example value.
    # This prevents attackers from forging JWT tokens with admin privileges.
    default_secret = "quantdinger-secret-key-change-me"
    current_secret = Config.SECRET_KEY
    if not Config.DEBUG and current_secret == default_secret:
        import secrets as _secrets
        new_key = _secrets.token_hex(32)
        os.environ["SECRET_KEY"] = new_key
        print("[AUTO] SECRET_KEY was default; generated random key for this session.")
        print("[TIP]  Set a persistent SECRET_KEY in backend_api_python/.env for production.")

    print(f"Service starting at: http://{Config.HOST}:{Config.PORT}")

    # Flask dev server is for local development only.
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        threaded=True
    )


if __name__ == '__main__':
    main()
