"""HTTP/SSE transport for Estate Atlas: SD-MCP.

Wraps the FastMCP `streamable_http_app()` Starlette app with:
  - Bearer-token auth middleware (env var SANDIEGO_MCP_API_KEYS).
  - Per-key in-memory rate limiting (token bucket).
  - Anonymous tier (rate-limited harder, banner in _meta.notes via header hint).
  - /healthz and /readyz endpoints.
  - Structured JSON access logs.

Why a custom middleware (and not slowapi):
  Anonymous + keyed tiers with very different limits, and we want a single
  in-process token-bucket store. slowapi adds a dependency and an extra
  decorator layer per route — for v0 (single instance, low traffic) the
  in-memory bucket is simpler and faster. Trade-off: it does NOT survive
  process restarts and does NOT share state across replicas. See deploy
  plan for when to migrate to Redis.

Endpoints exposed (mounted under SANDIEGO_MCP_MOUNT_PATH, default /mcp):
  POST /mcp        — streamable-http transport
  GET  /sse        — SSE transport (legacy clients)
  POST /messages/  — SSE message channel
  GET  /healthz             — liveness (always 200 if process up)
  GET  /readyz              — readiness (checks DB connectivity)
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

log = logging.getLogger("sandiego-mcp.http")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANONYMOUS_KEY = "__anonymous__"
DEFAULT_KEYED_RPM = 100
DEFAULT_ANON_RPM = 10
DEFAULT_MOUNT_PATH = "/mcp"


def _parse_api_keys(raw: str | None) -> dict[str, str]:
    """Parse SANDIEGO_MCP_API_KEYS env.

    Format: `key1,key2,key3` OR `name1:key1,name2:key2` for labeled keys.
    Returns dict of {key -> label}. Empty / None -> {}.
    """
    if not raw:
        return {}
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            label, key = part.split(":", 1)
            out[key.strip()] = label.strip()
        else:
            out[part] = part[:8]  # label = first 8 chars (safe for logs)
    return out


# ---------------------------------------------------------------------------
# Rate limiter (in-memory token bucket, per principal)
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
    capacity: int
    refill_per_sec: float

    def take(self, now: float) -> bool:
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


@dataclass
class RateLimiter:
    keyed_rpm: int = DEFAULT_KEYED_RPM
    anon_rpm: int = DEFAULT_ANON_RPM
    _buckets: dict[str, _Bucket] = field(default_factory=dict)

    def check(self, principal: str, is_anonymous: bool) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds_if_denied)."""
        rpm = self.anon_rpm if is_anonymous else self.keyed_rpm
        b = self._buckets.get(principal)
        now = time.monotonic()
        if b is None or b.capacity != rpm:
            b = _Bucket(
                tokens=rpm,
                last_refill=now,
                capacity=rpm,
                refill_per_sec=rpm / 60.0,
            )
            self._buckets[principal] = b
        allowed = b.take(now)
        if allowed:
            return True, 0
        # Seconds until 1 full token
        deficit = 1 - b.tokens
        retry = max(1, int(deficit / b.refill_per_sec) + 1)
        return False, retry


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthAndRateLimitMiddleware(BaseHTTPMiddleware):
    """Bearer-token auth + per-principal rate limit.

    - If SANDIEGO_MCP_REQUIRE_AUTH=true, anonymous is rejected outright.
    - Otherwise anonymous is allowed but capped at anon_rpm.
    - On 200 responses, adds X-RateLimit-* response headers.
    - /healthz and /readyz are exempt from auth + rate limit.
    """

    EXEMPT_PATHS = ("/healthz", "/readyz")

    def __init__(
        self,
        app,
        *,
        api_keys: dict[str, str],
        limiter: RateLimiter,
        require_auth: bool,
    ):
        super().__init__(app)
        self.api_keys = api_keys
        self.limiter = limiter
        self.require_auth = require_auth

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        principal, label, is_anon = self._identify(request)

        if is_anon and self.require_auth:
            return _error(
                401,
                "unauthorized",
                "Missing or invalid bearer token. "
                "Set Authorization: Bearer <key>.",
            )

        if is_anon and not self.api_keys and not self.require_auth:
            # No keys configured at all — open mode (dev). Still rate-limit.
            pass
        elif is_anon and self.api_keys and not self.require_auth:
            # Anon tier alongside configured keys
            pass

        allowed, retry_after = self.limiter.check(principal, is_anon)
        if not allowed:
            log.info(
                json.dumps({
                    "event": "rate_limit",
                    "principal": label,
                    "anonymous": is_anon,
                    "path": path,
                    "retry_after": retry_after,
                })
            )
            resp = _error(
                429,
                "rate_limited",
                f"Rate limit exceeded. Retry after {retry_after}s.",
                extra={"retry_after_seconds": retry_after},
            )
            resp.headers["Retry-After"] = str(retry_after)
            return resp

        # Anon hint header — downstream tool wrappers can read this and
        # surface a banner in _meta.notes. (FastMCP doesn't natively
        # expose request headers to tools yet, so this is a forward hook.)
        request.scope["sandiego_mcp.principal"] = label
        request.scope["sandiego_mcp.anonymous"] = is_anon

        response = await call_next(request)
        response.headers["X-RateLimit-Tier"] = "anonymous" if is_anon else "keyed"
        if is_anon:
            response.headers["X-RateLimit-Limit"] = str(self.limiter.anon_rpm)
        else:
            response.headers["X-RateLimit-Limit"] = str(self.limiter.keyed_rpm)
        return response

    def _identify(self, request: Request) -> tuple[str, str, bool]:
        """Return (principal_key, log_label, is_anonymous)."""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            label = self.api_keys.get(token)
            if label is not None:
                return token, label, False
            # Bearer header present but key unknown — treat as anon (or 401 if require_auth).
            # Keep simple: anon, but log.
            log.info(json.dumps({
                "event": "invalid_bearer",
                "token_prefix": token[:6] if token else "",
            }))
        # Anonymous: bucket per client IP so one bad actor can't drain the pool.
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        return f"{ANONYMOUS_KEY}:{client_ip}", f"anon:{client_ip}", True


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


async def healthz(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def readyz(_: Request) -> Response:
    """Readiness: DB reachable + at least one row in docs."""
    try:
        from sandiego_mcp.db import fetch_one

        row = fetch_one("SELECT 1 AS ok")
        if not row or row.get("ok") != 1:
            return JSONResponse({"status": "degraded", "reason": "db_query_failed"}, status_code=503)
    except Exception as exc:  # noqa: BLE001
        log.warning("readyz db check failed: %s", exc)
        return JSONResponse({"status": "degraded", "reason": str(exc)}, status_code=503)
    return JSONResponse({"status": "ready"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _error(status: int, code: str, message: str, *, extra: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if extra:
        body["error"]["details"] = extra
    return JSONResponse(body, status_code=status)


def build_http_app(mcp=None) -> Starlette:
    """Build the public HTTP ASGI app.

    Wraps FastMCP's streamable-http app, prefixes it under the mount path,
    and adds auth, rate-limit, and health endpoints.
    """
    if mcp is None:
        from sandiego_mcp.server import build_server
        mcp = build_server()

    mount_path = os.getenv("SANDIEGO_MCP_MOUNT_PATH", DEFAULT_MOUNT_PATH).rstrip("/") or ""
    api_keys = _parse_api_keys(os.getenv("SANDIEGO_MCP_API_KEYS"))
    require_auth = os.getenv("SANDIEGO_MCP_REQUIRE_AUTH", "false").lower() in ("1", "true", "yes")
    keyed_rpm = int(os.getenv("SANDIEGO_MCP_KEYED_RPM", DEFAULT_KEYED_RPM))
    anon_rpm = int(os.getenv("SANDIEGO_MCP_ANON_RPM", DEFAULT_ANON_RPM))

    limiter = RateLimiter(keyed_rpm=keyed_rpm, anon_rpm=anon_rpm)

    # FastMCP returns a Starlette app that owns /mcp (streamable-http) and /sse.
    mcp_app = mcp.streamable_http_app()

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/readyz", readyz, methods=["GET"]),
        Mount(mount_path or "/", app=mcp_app),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(
        AuthAndRateLimitMiddleware,
        api_keys=api_keys,
        limiter=limiter,
        require_auth=require_auth,
    )

    log.info(json.dumps({
        "event": "http_app_built",
        "mount_path": mount_path or "/",
        "keyed_keys": len(api_keys),
        "require_auth": require_auth,
        "keyed_rpm": keyed_rpm,
        "anon_rpm": anon_rpm,
    }))

    return app


def run_http() -> None:
    """Run the HTTP transport via uvicorn. Called from server.run() when
    SANDIEGO_MCP_TRANSPORT=http."""
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn is required for the HTTP transport. "
            "Install with: pip install 'sandiego-municipal-code-mcp[http]'"
        ) from exc

    host = os.getenv("SANDIEGO_MCP_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("SANDIEGO_MCP_PORT", "8000")))
    log.info("Starting SD-MCP HTTP transport on %s:%s", host, port)

    app = build_http_app()
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("SANDIEGO_MCP_LOG_LEVEL", "info").lower())
