#!/bin/sh
# QuantDinger Docker Entrypoint Script
# Checks and validates SECRET_KEY before starting the application

set -e

echo "============================================"
echo "  QuantDinger Backend - Starting..."
echo "============================================"

# Check if .env file exists
if [ ! -f /app/.env ]; then
    echo "[WARNING] .env file not found at /app/.env"
    echo "Creating .env from env.example..."
    if [ -f /app/env.example ]; then
        if cp /app/env.example /app/.env 2>/tmp/quantdinger-env-copy.err; then
            echo "[INFO] Created .env from env.example"
            echo "[IMPORTANT] Please edit /app/.env and set a secure SECRET_KEY before restarting!"
        else
            echo "[WARNING] Cannot create /app/.env: $(cat /tmp/quantdinger-env-copy.err)"
            echo "[WARNING] Continuing with container environment variables only."
            echo "[TIP] Create the host env file before starting Docker:"
            echo "      cp backend_api_python/env.example backend_api_python/.env"
            rm -f /tmp/quantdinger-env-copy.err
        fi
    else
        echo "[WARNING] env.example not found. Continuing with container environment variables only."
    fi
fi

# Check SECRET_KEY configuration
DEFAULT_SECRET="quantdinger-secret-key-change-me"
CURRENT_SECRET=$(grep -E "^SECRET_KEY=" /app/.env 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs || true)
CURRENT_SECRET=${CURRENT_SECRET:-${SECRET_KEY:-}}

if [ -z "$CURRENT_SECRET" ]; then
    NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    if [ -f /app/.env ] && [ -w /app/.env ]; then
        echo "SECRET_KEY=${NEW_SECRET}" >> /app/.env
        echo "[AUTO] Generated random SECRET_KEY (was missing)."
    else
        export SECRET_KEY="$NEW_SECRET"
        echo "[AUTO] Generated random in-memory SECRET_KEY (no writable .env)."
        echo "[TIP]  Set a persistent SECRET_KEY in backend_api_python/.env for production."
    fi
    CURRENT_SECRET="$NEW_SECRET"
fi

# Auto-generate SECRET_KEY if using default (zero-config experience)
if [ "$CURRENT_SECRET" = "$DEFAULT_SECRET" ]; then
    NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    # Use a temp file + write-back instead of `sed -i`. When /app/.env is a
    # Docker bind-mount from the host (zero-repo GHCR deploy), `sed -i` fails
    # with "Device or resource busy" because it tries to rename(2) the inode
    # over a mount target. Truncate+write through the mount works fine and
    # propagates the new key back to the host file.
    if [ -f /app/.env ] && [ -w /app/.env ]; then
        TMP=$(mktemp)
        sed "s|SECRET_KEY=.*|SECRET_KEY=${NEW_SECRET}|" /app/.env > "$TMP"
        cat "$TMP" > /app/.env
        rm -f "$TMP"
        echo "[AUTO] Generated random SECRET_KEY (was default)."
        echo "[TIP]  For production, set a persistent SECRET_KEY in backend_api_python/.env"
    else
        export SECRET_KEY="$NEW_SECRET"
        echo "[AUTO] Generated random in-memory SECRET_KEY (default value, no writable .env)."
        echo "[TIP]  Set a persistent SECRET_KEY in backend_api_python/.env for production."
    fi
    CURRENT_SECRET="$NEW_SECRET"
fi

echo "[OK] SECRET_KEY is configured"
SECRET_LEN=$(printf '%s' "$CURRENT_SECRET" | wc -c | tr -d ' ')
if [ "$SECRET_LEN" -lt 32 ]; then
    echo "[WARNING] SECRET_KEY is only ${SECRET_LEN} bytes; RFC 7518 recommends >= 32 for HS256."
    echo "          Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
    echo "          After updating .env, restart the stack; users must sign in again."
fi
echo ""

# Start the application
exec "$@"
