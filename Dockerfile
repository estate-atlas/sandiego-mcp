# Estate Atlas: SD-MCP — HTTP transport image.
#
# Minimal Python 3.11 image. Installs the package with the [http] extra
# and runs the HTTP transport on $PORT (default 8000).
#
# Local test:
#   docker build -t sd-mcp .
#   docker run --rm -p 8000:8000 \
#     -e SANDIEGO_MCP_TRANSPORT=http \
#     -e SANDIEGO_MCP_DATABASE_URL="$DATABASE_URL" \
#     -e VOYAGE_API_KEY="$VOYAGE_API_KEY" \
#     sd-mcp
#   curl http://localhost:8000/healthz

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg[binary] needs no system libs, but libpq is good to have for diag.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching).
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --upgrade pip \
    && pip install ".[http]"

# Non-root for safety.
RUN useradd --create-home --uid 1001 mcp \
    && chown -R mcp:mcp /app
USER mcp

# Default runtime config (overridable at deploy time).
ENV SANDIEGO_MCP_TRANSPORT=http \
    SANDIEGO_MCP_HOST=0.0.0.0 \
    PORT=8000 \
    SANDIEGO_MCP_MOUNT_PATH=/sandiego \
    SANDIEGO_MCP_LOG_LEVEL=INFO

EXPOSE 8000

# Cheap built-in healthcheck — hits /healthz which is exempt from auth.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

CMD ["sandiego-municipal-code-mcp"]
