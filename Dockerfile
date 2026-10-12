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
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
