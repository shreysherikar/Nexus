# Production Dockerfile for NEXUS FastAPI Backend
FROM python:3.11-slim

# System configuration and curl for health probes
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Set environment flags
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Create non-root user and application directory
RUN groupadd -g 1000 nexus && \
    useradd -u 1000 -g nexus -s /bin/bash -m nexus && \
    mkdir -p /app && \
    chown -R nexus:nexus /app

WORKDIR /app

# Install Python dependencies first for caching
COPY --chown=nexus:nexus pyproject.toml alembic.ini ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy application source code and migrations
COPY --chown=nexus:nexus src/ ./src/
COPY --chown=nexus:nexus migrations/ ./migrations/
COPY --chown=nexus:nexus docker-entrypoint.sh ./

RUN chmod +x /app/docker-entrypoint.sh

# Switch to unprivileged user
USER nexus

# Expose FastAPI HTTP server port
EXPOSE 8000

# Health check probe against /ready endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/ready || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "nexus.main:app", "--host", "0.0.0.0", "--port", "8000"]
