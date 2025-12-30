<div align="center">
  <a href="https://github.com/brokermr810/QuantDinger">
    <img src="https://ai.quantdinger.com/img/logo.e0f510a8.png" alt="QuantDinger Logo" width="160" height="160">
  </a>

  <h1 align="center">QuantDinger</h1>

  <div align="center">
    <a href="README.md">🇺🇸 English</a> |
    <a href="README_CN.md">🇨🇳 简体中文</a> |
    <a href="README_TW.md">🇹🇼 繁體中文</a> |
    <a href="README_JA.md">🇯🇵 日本語</a> |
    <a href="README_KO.md">🇰🇷 한국어</a>
  </div>
  <br/>

  <p align="center">
    <strong>🤖 AI-Native · 🔒 Privacy-First · 🚀 All-in-One Quant Workspace</strong>
  </p>
  <p align="center">
    <i>The Next-Gen Local Quant Platform: Multi-Market Data, AI Research, Visual Backtesting, and Automated Trading.</i>
  </p>

  <p align="center">
    <a href="https://www.quantdinger.com"><strong>Website</strong></a> ·
    <a href="https://ai.quantdinger.com"><strong>Live Demo</strong></a> ·
    <a href="https://github.com/brokermr810/QuantDinger/issues"><strong>Report Bug</strong></a> ·
    <a href="https://github.com/brokermr810/QuantDinger/discussions"><strong>Discussions</strong></a>
  </p>

  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square&logo=apache" alt="License"></a>
    <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/Vue.js-2.x-4FC08D?style=flat-square&logo=vue.js&logoColor=white" alt="Vue">
    <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
    <img src="https://img.shields.io/github/stars/brokermr810/QuantDinger?style=flat-square&logo=github" alt="Stars">
  </p>

  <p align="center">
    <a href="https://t.me/worldinbroker"><img src="https://img.shields.io/badge/Telegram-Join%20Chat-26A5E4?style=for-the-badge&logo=telegram" alt="Telegram"></a>
    <a href="https://discord.gg/cn6HVE2KC"><img src="https://img.shields.io/badge/Discord-Join%20Server-5865F2?style=for-the-badge&logo=discord" alt="Discord"></a>
    <a href="https://x.com/HenryCryption"><img src="https://img.shields.io/badge/X-Follow%20Us-000000?style=for-the-badge&logo=x" alt="X"></a>
  </p>
</div>

---

## 📖 Introduction

**QuantDinger** is a **Local-First** quantitative trading workspace designed for traders, researchers, and geeks.

Unlike expensive SaaS platforms, QuantDinger returns **data ownership** to you. It features a built-in **LLM-based Multi-Agent Research Team** that autonomously gathers financial intelligence from the web, combines it with local market data, generates professional analysis reports, and seamlessly integrates with your strategy development, backtesting, and live trading workflows.

### Core Value
- **🛡️ Privacy First**: All strategies, trading logs, and API keys are stored locally in your SQLite database.
- **🧠 AI Empowered**: Not just code completion, but a real AI Research Analyst (powered by OpenRouter/LLM).
- **⚡ Multi-Market**: Native support for **Crypto**, **US Stocks**, **CN/HK Stocks**, **Forex**, and **Futures**.
- **🔌 Out-of-the-Box**: One-click deployment via Docker. No complex environment setup required.

---

## 📚 Documentation
- [Python Strategy Development Guide](docs/STRATEGY_DEV_GUIDE.md)

## 📸 Visual Tour

<div align="center">
  <h3>📊 Professional Quant Dashboard</h3>
  <p>Real-time monitoring of market dynamics, assets, and strategy status.</p>
  <img src="docs/screenshots/dashboard.png" alt="QuantDinger Dashboard" width="100%" style="border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
</div>

<br/>

<table align="center" width="100%">
  <tr>
    <td width="50%" align="center" valign="top">
      <h3>🤖 AI Deep Research</h3>
      <p>Multi-agent collaboration for market sentiment & technical analysis.</p>
      <img src="docs/screenshots/ai_analysis1.png" alt="AI Market Analysis" style="border-radius: 6px;">
    </td>
    <td width="50%" align="center" valign="top">
      <h3>💬 Smart Trading Assistant</h3>
      <p>Natural language interface for instant market insights.</p>
      <img src="docs/screenshots/trading_assistant.png" alt="Trading Assistant" style="border-radius: 6px;">
    </td>
  </tr>
  <tr>
    <td width="50%" align="center" valign="top">
      <h3>📈 Interactive Indicator Analysis</h3>
      <p>Rich library of technical indicators with drag-and-drop analysis.</p>
      <img src="docs/screenshots/indicator_analysis.png" alt="Indicator Analysis" style="border-radius: 6px;">
    </td>
    <td width="50%" align="center" valign="top">
      <h3>🐍 Python Strategy Gen</h3>
      <p>Built-in editor with AI-assisted strategy coding.</p>
      <img src="docs/screenshots/indicator_creat_python_code.png" alt="Code Generation" style="border-radius: 6px;">
    </td>
  </tr>
</table>

---

## ✨ Key Features

### 1. Universal Data Engine
Stop worrying about data APIs. QuantDinger features a powerful Data Source Factory pattern:
- **Crypto**: **Direct API connection** for trading (10+ exchanges) combined with **CCXT** for market data (100+ sources).
- **Stocks**: Integrates Yahoo Finance, Finnhub, Tiingo (US), and AkShare (CN/HK).
- **Futures/Forex**: Supports OANDA and major futures data sources.
- **Proxy Support**: Built-in proxy configuration for restricted network environments.

### 2. AI Multi-Agent Research
Your tireless team of analysts:
- **Coordinator Agent**: Decomposes tasks and manages workflows.
- **Research Agent**: Performs full-web searches (Google/Bing) for macro news.
- **Crypto/Stock Agent**: Specializes in technical and capital flow analysis for specific markets.
- **Report Generation**: Automatically produces structured Daily/Weekly research reports.

### 3. Robust Strategy Runtime
- **Thread-Based Executor**: Independent thread pool management for strategy execution.
- **Auto-Restore**: Automatically resumes running strategies after system restarts.
- **Pending Order Worker**: Reliable background queue ensures precise signal execution and prevents slippage.

### 4. Modern Tech Stack
- **Backend**: Python (Flask) + SQLite + Redis (Optional) — Simple, powerful, extensible.
- **Frontend**: Vue 2 + Ant Design Vue + KlineCharts/ECharts — Responsive and interactive.
- **Deployment**: Docker Compose orchestration.

---

## 🏦 Supported Exchanges & Rebates

QuantDinger supports **direct connection** to major cryptocurrency exchanges for low-latency execution, while using **CCXT** for broad market data coverage.

> 💡 **Exclusive Benefits**: Create accounts through our partner links below to enjoy **reduced trading fees** and **exclusive bonuses**. It helps support the project at no extra cost to you!

| Exchange | Features | Sign Up Bonus |
|:--------:|:---------|:-------------:|
| <img src="https://img.shields.io/badge/Binance-F0B90B?style=for-the-badge&logo=binance&logoColor=white" height="35"/> | 🥇 **World's Largest**<br/>Spot, Futures, Margin | <a href="https://www.bjwebptyiou.com/join/14449926"><img src="https://img.shields.io/badge/💰_Save_20%25_Fees-00C853?style=for-the-badge" height="35"/></a> |
| <img src="https://img.shields.io/badge/OKX-000000?style=for-the-badge&logo=okx&logoColor=white" height="35"/> | 🚀 **Web3 & Derivatives**<br/>Spot, Perpetual, Options | <a href="https://www.bmwweb.ac/referral/earn-together/refer2earn-usdc/claim?hl=zh-CN&ref=GRO_28502_9OSOJ"><img src="https://img.shields.io/badge/🎁_Get_Mystery_Box-00C853?style=for-the-badge" height="35"/></a> |
| <img src="https://img.shields.io/badge/Bitget-00C7B1?style=for-the-badge&logoColor=white" height="35"/> | 👥 **Social Trading**<br/>Copy Trading, Futures | <a href="https://www.bitget.rocks/zh-CN/referral/register?clacCode=91AWLH0U&from=%2Fzh-CN%2Fevents%2Freferral-all-program&source=events&utmSource=PremierInviter"><img src="https://img.shields.io/badge/🔥_Claim_Bonus-00C853?style=for-the-badge" height="35"/></a> |

<br>

**Also Supported (Direct/CCXT):**

| <img src="https://img.shields.io/badge/Bybit-F7931A?style=for-the-badge&logoColor=white"/> | <img src="https://img.shields.io/badge/Gate.io-17E6A1?style=for-the-badge&logoColor=white"/> | <img src="https://img.shields.io/badge/Kraken-5741D9?style=for-the-badge&logo=kraken&logoColor=white"/> | <img src="https://img.shields.io/badge/KuCoin-24AE8F?style=for-the-badge&logoColor=white"/> | <img src="https://img.shields.io/badge/HTX-1A73E8?style=for-the-badge&logoColor=white"/> |
|:---:|:---:|:---:|:---:|:---:|


---

### Multi-Language Support

QuantDinger is built for a global audience with comprehensive internationalization:

<p>
  <img src="https://img.shields.io/badge/🇺🇸_English-Supported-2563EB?style=flat-square" alt="English" />
  <img src="https://img.shields.io/badge/🇨🇳_简体中文-Supported-2563EB?style=flat-square" alt="Simplified Chinese" />
  <img src="https://img.shields.io/badge/🇹🇼_繁體中文-Supported-2563EB?style=flat-square" alt="Traditional Chinese" />
  <img src="https://img.shields.io/badge/🇯🇵_日本語-Supported-2563EB?style=flat-square" alt="Japanese" />
  <img src="https://img.shields.io/badge/🇰🇷_한국어-Supported-2563EB?style=flat-square" alt="Korean" />
  <img src="https://img.shields.io/badge/🇩🇪_Deutsch-Supported-2563EB?style=flat-square" alt="German" />
  <img src="https://img.shields.io/badge/🇫🇷_Français-Supported-2563EB?style=flat-square" alt="French" />
  <img src="https://img.shields.io/badge/🇹🇭_ไทย-Supported-2563EB?style=flat-square" alt="Thai" />
  <img src="https://img.shields.io/badge/🇻🇳_Tiếng_Việt-Supported-2563EB?style=flat-square" alt="Vietnamese" />
  <img src="https://img.shields.io/badge/🇸🇦_العربية-Supported-2563EB?style=flat-square" alt="Arabic" />
</p>

All UI elements, error messages, and documentation are fully translated. Language is auto-detected based on browser settings or can be manually switched in the app.

---

### Supported Markets

| Market Type | Data Sources | Trading |
|-------------|--------------|---------|
| **Cryptocurrency** | Binance, OKX, Bitget, + 100 exchanges | ✅ Full support |
| **US Stocks** | Yahoo Finance, Finnhub, Tiingo | ✅ Via broker API |
| **CN/HK Stocks** | AkShare, East Money | ⚡ Data only |
| **Forex** | Finnhub, OANDA | ✅ Via broker API |
| **Futures** | Exchange APIs, AkShare | ⚡ Data only |

---

### Architecture (Current Repo)

```text
┌─────────────────────────────┐
│      quantdinger_vue         │
│   (Vue 2 + Ant Design Vue)   │
└──────────────┬──────────────┘
               │  HTTP (/api/*)
               ▼
┌─────────────────────────────┐
│     backend_api_python       │
│   (Flask + strategy runtime) │
└──────────────┬──────────────┘
               │
               ├─ SQLite (quantdinger.db)
               ├─ Redis (optional cache)
               └─ Data providers / LLMs / Exchanges
```

---

### Repository Layout

```text
.
├─ backend_api_python/         # Flask API + AI + backtest + strategy runtime
│  ├─ app/
│  ├─ env.example              # Copy to .env for local config
│  ├─ requirements.txt
│  └─ run.py                   # Entrypoint
└─ quantdinger_vue/            # Vue 2 UI (dev server proxies /api -> backend)
```

---

## Quick Start

### Option 1: Docker Deployment (Recommended)

The fastest way to get QuantDinger running.

#### 1. Prepare Configuration

Linux/macOS:

```bash
cp docker.env.example backend_api_python/.env
nano backend_api_python/.env
```

Windows PowerShell:

```powershell
Copy-Item docker.env.example backend_api_python/.env
notepad backend_api_python/.env
```

**Required settings:**
- `SECRET_KEY` - Application secret, use a random string
- `ADMIN_USER` / `ADMIN_PASSWORD` - Login credentials
- `OPENROUTER_API_KEY` - OpenRouter API key (required for AI analysis)

#### 2. Build and Start

```bash
# Build images and start (first run)
docker-compose up -d --build

# Subsequent starts (no rebuild needed)
docker-compose up -d
```

#### 3. Access the Application

- **Frontend UI**: http://localhost
- **Backend API**: http://localhost:5000

#### Docker Commands Reference

```bash
# View running status
docker-compose ps

# View logs
docker-compose logs -f

# View backend logs only
docker-compose logs -f backend

# View frontend logs only
docker-compose logs -f frontend

# Stop services
docker-compose down

# Stop and remove volumes (WARNING: deletes database!)
docker-compose down -v

# Restart services
docker-compose restart

# Rebuild and restart
docker-compose up -d --build

# Enter backend container
docker exec -it quantdinger-backend /bin/bash

# Enter frontend container
docker exec -it quantdinger-frontend /bin/sh
```

#### Docker Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Frontend      │     │    Backend      │
│   (Nginx)       │────▶│   (Python)      │
│   Port: 80      │     │   Port: 5000    │
└─────────────────┘     └─────────────────┘
        │                       │
        └───────────────────────┘
              Docker Network
```

- **Frontend**: Vue.js app served by Nginx, proxies API requests to backend
- **Backend**: Python Flask API service

#### Data Persistence

The following data is mounted to the host and persists across container restarts:

```yaml
volumes:
  - ./backend_api_python/quantdinger.db:/app/quantdinger.db   # Database
  - ./backend_api_python/logs:/app/logs                       # Logs
  - ./backend_api_python/data:/app/data                       # Data directory
  - ./backend_api_python/.env:/app/.env                       # Configuration
```

#### Customization

**Change ports** - Edit `docker-compose.yml`:

```yaml
services:
  frontend:
  ports:
    - "8080:80"  # Change to port 8080
  
  backend:
  ports:
    - "5001:5000"  # Change to port 5001
```

**Configure HTTPS** - Use a reverse proxy (like Caddy/Nginx):

```bash
# Using Caddy (automatic HTTPS)
caddy reverse-proxy --from yourdomain.com --to localhost:80
```

#### Production Recommendations

**Security:**

```bash
# Generate strong SECRET_KEY
openssl rand -hex 32

# Set secure admin password
ADMIN_PASSWORD=your-very-secure-password
```

**Resource limits** - Add to `docker-compose.yml`:

```yaml
services:
  backend:
  deploy:
    resources:
    limits:
      cpus: '2'
      memory: 2G
    reservations:
      cpus: '0.5'
      memory: 512M
```

**Log management:**

```yaml
services:
  backend:
  logging:
    driver: "json-file"
    options:
    max-size: "100m"
    max-file: "3"
```

#### Docker Troubleshooting

**Frontend can't connect to backend:**

```bash
docker-compose logs backend
curl http://localhost:5000/api/health
```

**Database permission issues:**

```bash
chmod 666 backend_api_python/quantdinger.db
```

**Build failures:**

```bash
# Clear Docker cache and rebuild
docker-compose build --no-cache
```

**Out of memory:**

```bash
# Check memory usage
docker stats

# Add swap space (Linux)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

#### Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up -d --build
```

#### Backup

```bash
# Backup database
cp backend_api_python/quantdinger.db backup/quantdinger_$(date +%Y%m%d).db

# Backup configuration
cp backend_api_python/.env backup/.env_$(date +%Y%m%d)
```

---

### Option 2: Local Development

**Prerequisites**

- Python 3.10+ recommended
- Node.js 16+ recommended

#### 1. Start the backend (Flask API)

```bash
cd backend_api_python
pip install -r requirements.txt
cp env.example .env   # Windows: copy env.example .env
python run.py
```

Backend will be available at `http://localhost:5000`.

#### 2. Start the frontend (Vue UI)

```bash
cd quantdinger_vue
npm install
npm run serve
```

Frontend dev server runs at `http://localhost:8000` and proxies `/api/*` to `http://localhost:5000` (see `quantdinger_vue/vue.config.js`).

---

### Configuration (.env)

Use `backend_api_python/env.example` as a template. Common settings include:

- **Auth**: `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD`
- **Server**: `PYTHON_API_HOST`, `PYTHON_API_PORT`, `PYTHON_API_DEBUG`
- **Database**: `SQLITE_DATABASE_FILE` (optional; default is `backend_api_python/quantdinger.db`)
- **AI / LLM**: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, timeouts
- **Web search**: `SEARCH_PROVIDER`, `SEARCH_GOOGLE_*`, `SEARCH_BING_API_KEY`
- **Proxy (optional)**: `PROXY_PORT` or `PROXY_URL`
- **Workers**: `ENABLE_PENDING_ORDER_WORKER`, `DISABLE_RESTORE_RUNNING_STRATEGIES`

---

### API

The backend provides REST endpoints for login, market data, indicators, backtesting, strategies, and AI analysis.

- Health: `GET /health` (also supports `GET /api/health` for deployment probes)
- Auth (frontend-compatible): `POST /api/user/login`, `POST /api/user/logout`, `GET /api/user/info`

For the full route list, see `backend_api_python/app/routes/`.

---

### License

Licensed under the **Apache License 2.0**. See `LICENSE`.

---

## 🤝 Community & Support

Join our global community for strategy sharing and technical support:

- **Telegram (Official)**: [t.me/worldinbroker](https://t.me/worldinbroker)
- **Discord**: [Join Server](https://discord.gg/cn6HVE2KC)
- **YouTube**: [@quantdinger](https://youtube.com/@quantdinger)
- **Email**: [brokermr810@gmail.com](mailto:brokermr810@gmail.com)
- **GitHub Issues**: [Report bugs / Request features](https://github.com/brokermr810/QuantDinger/issues)

---

## ☕ Support the Project

If QuantDinger helps you profit, consider buying the developers a coffee. Your support keeps the project alive!

**ERC-20 / BEP-20 / Polygon / Arbitrum**
```
0x96fa4962181bea077f8c7240efe46afbe73641a7
```
<img src="https://img.shields.io/badge/USDT-Accepted-26A17B?style=flat-square&logo=tether" alt="USDT">
<img src="https://img.shields.io/badge/ETH-Accepted-3C3C3D?style=flat-square&logo=ethereum" alt="ETH">

---

### Commercial Services

We offer professional services to help you get the most out of QuantDinger:

| Service | Description |
|---------|-------------|
| **Deployment & Setup** | One-on-one assistance with server deployment, configuration, and optimization |
| **Custom Strategy Development** | Tailored trading strategies designed for your specific needs and markets |
| **Enterprise Upgrade** | Commercial license, priority support, and advanced features for businesses |
| **Training & Consulting** | Hands-on training sessions and strategic consulting for your trading team |

**Interested?** Contact us via:
- 📧 Email: [brokermr810@gmail.com](mailto:brokermr810@gmail.com)
- 💬 Telegram: [@worldinbroker](https://t.me/worldinbroker)

---

### Acknowledgements

QuantDinger stands on the shoulders of great open-source projects:

| Project | Description | Link |
|---------|-------------|------|
| **Flask** | Lightweight WSGI web framework | [flask.palletsprojects.com](https://flask.palletsprojects.com/) |
| **flask-cors** | Cross-Origin Resource Sharing extension | [GitHub](https://github.com/corydolphin/flask-cors) |
| **Pandas** | Data analysis and manipulation library | [pandas.pydata.org](https://pandas.pydata.org/) |
| **CCXT** | Cryptocurrency exchange trading library | [github.com/ccxt/ccxt](https://github.com/ccxt/ccxt) |
| **yfinance** | Yahoo Finance market data downloader | [github.com/ranaroussi/yfinance](https://github.com/ranaroussi/yfinance) |
| **akshare** | China financial data interface | [github.com/akfamily/akshare](https://github.com/akfamily/akshare) |
| **requests** | HTTP library for Python | [requests.readthedocs.io](https://requests.readthedocs.io/) |
| **Vue.js** | Progressive JavaScript framework | [vuejs.org](https://vuejs.org/) |
| **Ant Design Vue** | Enterprise-class UI components | [antdv.com](https://antdv.com/) |
| **KlineCharts** | Lightweight financial charting library | [github.com/klinecharts/KLineChart](https://github.com/klinecharts/KLineChart) |
| **Lightweight Charts** | TradingView charting library | [github.com/nicepkg/lightweight-charts](https://github.com/nicepkg/lightweight-charts) |
| **ECharts** | Apache data visualization library | [echarts.apache.org](https://echarts.apache.org/) |

Thanks to all maintainers and contributors across these ecosystems! ❤️
