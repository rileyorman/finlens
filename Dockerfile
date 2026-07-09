# FinLens container image.
# Python 3.11 to match the authoritative CI version (CLAUDE.md: "CI Python
# Version is Authoritative" — 3.11 has real syntax differences from local 3.13).
FROM python:3.11-slim

# - PYTHONUNBUFFERED: logs stream to `docker logs` immediately.
# - FINLENS_DATA_DIR: canonical app-data root (config.py). Points at the
#   mounted /data volume so the filing library, caches, and integrity log
#   persist across container restarts instead of living in the container layer.
# - HOME: a writable home so Streamlit can write ~/.streamlit for a non-root user.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FINLENS_DATA_DIR=/data \
    HOME=/home/appuser \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true

# curl is used only by the container HEALTHCHECK below.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first so this layer caches across app-code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as an unprivileged user; give it ownership of the app dir and /data.
RUN useradd --create-home --home-dir /home/appuser --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data /home/appuser

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8501
VOLUME ["/data"]

# Streamlit's built-in health endpoint (available in 1.35+).
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# --server.address=0.0.0.0 overrides .streamlit/config.toml's "localhost"
# bind (which would make the app unreachable from outside the container).
# Host exposure is still restricted to loopback by the compose port mapping.
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
