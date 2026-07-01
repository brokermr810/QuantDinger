#!/bin/sh
set -eu

mkdir -p logs

echo "Starting QuantDinger Python API on ${PYTHON_API_HOST:-0.0.0.0}:${PYTHON_API_PORT:-5000}"

if [ "${FLASK_DEV_SERVER:-false}" = "true" ]; then
  echo "FLASK_DEV_SERVER=true, using Flask development server."
  exec python run.py
fi

exec gunicorn -c gunicorn_config.py "run:app"
