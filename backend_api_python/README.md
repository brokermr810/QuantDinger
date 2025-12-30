# QuantDinger Python API (backend)

Flask-based local-first backend for QuantDinger: market data, indicators, AI analysis, backtesting, and a strategy runtime (with an optional pending-order worker).

This repository is intentionally simple: **no external database is required by default**. Data is stored in a local SQLite file (`quantdinger.db`) created/updated automatically on startup.

## What you get

- **Multi-market data layer**: factory-based providers (crypto / US stocks / CN&HK stocks / futures, etc.)
- **Indicators + backtesting**: persisted runs/history in SQLite
- **AI multi-agent analysis**: optional web search + OpenRouter LLM integration
- **Strategy runtime**: thread-based executor, with optional auto-restore on startup
- **Pending orders worker (optional)**: polls queued orders and dispatches signals (webhook/notifications)
- **Local auth (single-user)**: `/login` with env-configured admin credentials (JWT)

## Project layout

```text
backend_api_python/
├─ app/
│  ├─ __init__.py                 # Flask app factory + startup hooks
│  ├─ config/                     # Settings (env-driven)
│  ├─ data_sources/               # Data sources + factory
│  ├─ routes/                     # REST endpoints
│  ├─ services/                   # Analysis, agents, strategies, search, ...
│  └─ utils/                      # SQLite helpers, config loader, logging, HTTP utils
├─ env.example                    # Copy to .env for local config
├─ requirements.txt
├─ run.py                         # Entrypoint (loads .env, applies proxy env, starts Flask)
├─ gunicorn_config.py             # Optional production config
└─ README.md
```

## Quick start (local development)

### Prerequisites

- Python 3.10+ recommended

### 1) Install dependencies

```bash
cd backend_api_python
pip install -r requirements.txt
```

### 2) Create your local `.env`

Windows (CMD):

```bash
copy env.example .env
```

Windows (PowerShell):

```bash
Copy-Item env.example .env
```

Then edit `.env` and set at least:

- `SECRET_KEY`
- `ADMIN_USER`
- `ADMIN_PASSWORD`

Optional but common:

- `OPENROUTER_API_KEY` (for AI analysis)
- `FINNHUB_API_KEY` / `SEARCH_GOOGLE_*` / `SEARCH_BING_API_KEY` (for richer data/search)
- `PROXY_PORT` or `PROXY_URL` (if your network blocks some providers)

### 3) Start the API server

```bash
python run.py
```

Default address: `http://localhost:5000`

## Database (SQLite)

- Default file: `backend_api_python/data/quantdinger.db` (override via `SQLITE_DATABASE_FILE`)
- Tables are created/updated automatically on startup (see `app/utils/db.py`)
- `qd_addon_config` exists for backward compatibility, but **this backend reads secrets from `.env` / OS env**, not from the database (see `app/utils/config_loader.py`)

## AI memory augmentation (local-only)

This backend includes a lightweight, privacy-first **memory-augmented multi-agent** system:

- Memory DBs (per role): `backend_api_python/data/memory/*_memory.db`
- Reflection DB (optional auto-verify loop): `backend_api_python/data/memory/reflection_records.db`
- API hooks:
  - `POST /api/analysis/multi` (main entry)
  - `POST /api/analysis/reflect` (manual learn from post-trade outcomes)
- Controls: see `.env` / `env.example`:
  - `ENABLE_AGENT_MEMORY`, `AGENT_MEMORY_*`
  - `ENABLE_REFLECTION_WORKER`, `REFLECTION_WORKER_INTERVAL_SEC`

## Frontend integration (Vue dev server)

The Vue dev server proxies `/api/*` to this backend by default:

- Frontend: `http://localhost:8000`
- Backend: `http://localhost:5000`

Proxy config: `quantdinger_vue/vue.config.js`

## Useful endpoints

```text
GET  /health
POST /login
GET  /info
GET  /api/indicator/kline
POST /api/analysis/multi
```

## Production (optional)

Gunicorn example:

```bash
gunicorn -c gunicorn_config.py "run:app"
```

## Troubleshooting

- If outbound data/search requests fail, configure `PROXY_PORT` (or `PROXY_URL`) in `.env`.
- If you don’t want strategies to auto-restore on startup, set `DISABLE_RESTORE_RUNNING_STRATEGIES=true`.
- If you don’t want the pending-order worker, set `ENABLE_PENDING_ORDER_WORKER=false`.

## License

Apache License 2.0. See repository root `LICENSE`.

