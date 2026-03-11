#!/bin/bash
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
        cp /app/env.example /app/.env
        echo "[INFO] Created .env from env.example"
        echo "[IMPORTANT] Please edit /app/.env and set a secure SECRET_KEY before restarting!"
    else
        echo "[ERROR] env.example not found. Cannot create .env automatically."
        exit 1
    fi
fi

# Check SECRET_KEY configuration
DEFAULT_SECRET="quantdinger-secret-key-change-me"
CURRENT_SECRET=$(grep -E "^SECRET_KEY=" /app/.env 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs || echo "")

if [ -z "$CURRENT_SECRET" ]; then
    echo ""
    echo "============================================"
    echo "  [SECURITY WARNING]"
    echo "============================================"
    echo "SECRET_KEY is not set in /app/.env"
    echo ""
    echo "Please set a secure SECRET_KEY before starting:"
    echo ""
    echo "  Option 1: Generate a random key:"
    echo "    docker exec -it quantdinger-backend python -c \"import secrets; print(secrets.token_hex(32))\""
    echo ""
    echo "  Option 2: Edit .env file:"
    echo "    SECRET_KEY=your-generated-secret-key-here"
    echo ""
    echo "Then restart the container:"
    echo "    docker-compose restart backend"
    echo ""
    echo "============================================"
    exit 1
fi

# Check if using default secret key
if [ "$CURRENT_SECRET" = "$DEFAULT_SECRET" ]; then
    echo ""
    echo "============================================"
    echo "  [SECURITY ERROR]"
    echo "============================================"
    echo "SECRET_KEY is using the default example value!"
    echo "This is INSECURE and MUST be changed before running in production."
    echo ""
    echo "Current value: $CURRENT_SECRET"
    echo ""
    echo "To fix this:"
    echo ""
    echo "  1. Generate a secure random key:"
    echo "     docker exec -it quantdinger-backend python -c \"import secrets; print(secrets.token_hex(32))\""
    echo ""
    echo "  2. Edit backend_api_python/.env and replace SECRET_KEY:"
    echo "     SECRET_KEY=<generated-key-here>"
    echo ""
    echo "  3. Restart the container:"
    echo "     docker-compose restart backend"
    echo ""
    echo "Or use this one-liner (Linux/Mac):"
    echo "     sed -i 's|SECRET_KEY=.*|SECRET_KEY='\$(python3 -c \"import secrets; print(secrets.token_hex(32))\")\'|' backend_api_python/.env"
    echo ""
    echo "============================================"
    exit 1
fi

echo "[OK] SECRET_KEY is configured"
echo ""

# Start the application
exec "$@"
