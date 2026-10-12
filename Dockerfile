# Multi-stage production Dockerfile for RetroTube
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final runtime image
FROM python:3.11-slim

WORKDIR /app

# Create non-root user for security
RUN useradd -u 1000 -m retro && chown -R retro:retro /app

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/retro/.local

# Copy application source code
COPY --chown=retro:retro . .

USER retro
ENV PATH=/home/retro/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4"]
