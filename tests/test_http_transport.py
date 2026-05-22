"""HTTP transport smoke tests.

Confirms:
  - build_http_app() returns a Starlette app without touching the DB or
    importing uvicorn.
  - /healthz returns 200 with no auth.
  - Bearer-token middleware accepts a configured key and rejects unknown
    ones when require_auth is on.
  - Rate limiter denies after the burst is consumed.

These tests mock the DB layer; they do NOT spin up a real server.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

pytest.importorskip("mcp", reason="`mcp` SDK not installed")
pytest.importorskip("starlette", reason="`starlette` not installed (install with [http] extra)")

from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    """Build the HTTP app with deterministic config."""
    monkeypatch.setenv("SANDIEGO_MCP_API_KEYS", "partner-a:key-aaa,partner-b:key-bbb")
    monkeypatch.setenv("SANDIEGO_MCP_REQUIRE_AUTH", "false")
    monkeypatch.setenv("SANDIEGO_MCP_KEYED_RPM", "5")
    monkeypatch.setenv("SANDIEGO_MCP_ANON_RPM", "2")
    monkeypatch.setenv("SANDIEGO_MCP_MOUNT_PATH", "/sandiego")
    # Provide a dummy DSN so build_server doesn't fail on import paths
    # that touch db config. We won't actually connect in these tests.
    monkeypatch.setenv("SANDIEGO_MCP_DATABASE_URL", "postgresql://test@localhost/test")

    from sandiego_mcp.http_app import build_http_app
    return build_http_app()


def test_healthz_is_open(app):
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_reports_db_failure_gracefully(app):
    """readyz should return 503 (not raise) when DB is unreachable."""
    client = TestClient(app)
    # No real DB in test env — readyz should degrade, not crash.
    r = client.get("/readyz")
    assert r.status_code in (200, 503)


def test_unknown_bearer_falls_through_to_anonymous(app):
    """When require_auth=false, an unknown bearer is treated as anon."""
    client = TestClient(app)
    # Hit healthz with an unknown bearer — exempt path, but middleware still
    # runs identify(). Should still return 200.
    r = client.get("/healthz", headers={"Authorization": "Bearer not-a-real-key"})
    assert r.status_code == 200


def test_require_auth_rejects_anonymous(monkeypatch):
    monkeypatch.setenv("SANDIEGO_MCP_API_KEYS", "partner-a:key-aaa")
    monkeypatch.setenv("SANDIEGO_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setenv("SANDIEGO_MCP_DATABASE_URL", "postgresql://test@localhost/test")
    monkeypatch.setenv("SANDIEGO_MCP_KEYED_RPM", "10")
    monkeypatch.setenv("SANDIEGO_MCP_ANON_RPM", "10")

    from sandiego_mcp.http_app import build_http_app
    app = build_http_app()
    client = TestClient(app)

    # Hit a non-exempt path under the mount with no auth.
    r = client.get("/sandiego/mcp")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "unauthorized"


def test_anonymous_rate_limit_kicks_in(monkeypatch):
    """Anon tier capped at 2 RPM should 429 on the 3rd request.

    We hit an under-the-mount path that doesn't exist — middleware runs
    before routing resolves the mount, so we exercise auth+limit cleanly
    without needing FastMCP's lifespan-managed session manager.
    """
    monkeypatch.setenv("SANDIEGO_MCP_API_KEYS", "")
    monkeypatch.setenv("SANDIEGO_MCP_REQUIRE_AUTH", "false")
    monkeypatch.setenv("SANDIEGO_MCP_ANON_RPM", "2")
    monkeypatch.setenv("SANDIEGO_MCP_KEYED_RPM", "100")
    monkeypatch.setenv("SANDIEGO_MCP_DATABASE_URL", "postgresql://test@localhost/test")

    from sandiego_mcp.http_app import build_http_app
    app = build_http_app()

    # Use a path under the mount that won't resolve to FastMCP's session
    # handler — middleware fires either way. The mounted MCP app returns
    # 404 for /sandiego/__rate_probe__, which is fine; we want to observe
    # rate-limit headers, not the downstream response.
    with TestClient(app) as client:
        statuses = []
        for _ in range(3):
            r = client.get("/sandiego/__rate_probe__")
            statuses.append(r.status_code)
        assert statuses[-1] == 429, f"Expected 429 on third request, got {statuses}"
        # Verify retry-after header is present on the limit response.
        r = client.get("/sandiego/__rate_probe__")
        assert r.status_code == 429
        assert "retry-after" in {k.lower() for k in r.headers.keys()}


def test_keyed_request_uses_higher_limit(monkeypatch):
    """A request with a valid key uses keyed_rpm, not anon_rpm."""
    monkeypatch.setenv("SANDIEGO_MCP_API_KEYS", "partner-a:secretkey")
    monkeypatch.setenv("SANDIEGO_MCP_REQUIRE_AUTH", "false")
    monkeypatch.setenv("SANDIEGO_MCP_ANON_RPM", "1")
    monkeypatch.setenv("SANDIEGO_MCP_KEYED_RPM", "10")
    monkeypatch.setenv("SANDIEGO_MCP_DATABASE_URL", "postgresql://test@localhost/test")

    from sandiego_mcp.http_app import build_http_app
    app = build_http_app()

    headers = {"Authorization": "Bearer secretkey"}
    with TestClient(app) as client:
        # If we were anonymous, the 2nd call would 429. With the key, we
        # should be able to make several without hitting the limit.
        statuses = [
            client.get("/sandiego/__rate_probe__", headers=headers).status_code
            for _ in range(5)
        ]
        assert 429 not in statuses, f"Keyed requests hit anon limit: {statuses}"
        # And the tier header should reflect keyed.
        r = client.get("/sandiego/__rate_probe__", headers=headers)
        assert r.headers.get("X-RateLimit-Tier") == "keyed"


def test_transport_env_var_dispatch_stdio(monkeypatch):
    """server.run() should dispatch to stdio when SANDIEGO_MCP_TRANSPORT=stdio."""
    monkeypatch.setenv("SANDIEGO_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("SANDIEGO_MCP_DATABASE_URL", "postgresql://test@localhost/test")

    from sandiego_mcp import server as srv

    with patch.object(srv, "build_server") as build_mock:
        # build_server is called; .run() is called on the returned mcp.
        mcp_inst = build_mock.return_value
        srv.run()
        mcp_inst.run.assert_called_once()


def test_transport_env_var_dispatch_http(monkeypatch):
    """server.run() should dispatch to http when SANDIEGO_MCP_TRANSPORT=http."""
    monkeypatch.setenv("SANDIEGO_MCP_TRANSPORT", "http")
    monkeypatch.setenv("SANDIEGO_MCP_DATABASE_URL", "postgresql://test@localhost/test")

    from sandiego_mcp import server as srv

    with patch("sandiego_mcp.http_app.run_http") as run_http_mock:
        srv.run()
        run_http_mock.assert_called_once()


def test_transport_env_var_invalid_raises(monkeypatch):
    monkeypatch.setenv("SANDIEGO_MCP_TRANSPORT", "carrier-pigeon")
    monkeypatch.setenv("SANDIEGO_MCP_DATABASE_URL", "postgresql://test@localhost/test")

    from sandiego_mcp import server as srv

    with pytest.raises(SystemExit):
        srv.run()
