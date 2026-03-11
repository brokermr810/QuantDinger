# QuantDinger Backend API Dockerfile
FROM python:3.12-slim-bookworm

# Set working directory
WORKDIR /app

# Use HTTPS mirror and install minimal runtime dependencies.
# Keep image lean to avoid long downloads of full compiler toolchains.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/*.sources 2>/dev/null || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends --fix-missing \
    curl \
    # Build deps (needed for some pyproject-based packages like ed25519-blake2b)
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --prefer-binary --timeout 120 -r requirements.txt \
    # Remove build deps to keep image small
    && apt-get purge -y --auto-remove build-essential python3-dev libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY . .

# Copy and set up entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create log and data directories
RUN mkdir -p logs data/memory

# Expose port
EXPOSE 5000

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHON_API_HOST=0.0.0.0
ENV PYTHON_API_PORT=5000

# Use entrypoint script to check SECRET_KEY before starting
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Start command
CMD ["python", "run.py"]
