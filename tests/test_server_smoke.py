"""Smoke test: build the server and confirm every expected tool is registered."""
from __future__ import annotations

import pytest

EXPECTED_TOOLS = {
    "search_municipal_code",
    "get_code_section",
    "get_table_of_contents",
    "list_bulletins",
    "get_bulletin",
    "lookup_parcel",
    "get_permits_for_parcel",
    "get_violations_for_parcel",
    "get_setbacks_for_zone",
    "get_zone_info",
    "data_freshness",
    "get_case_rulings",
}


def test_server_registers_every_tool():
    pytest.importorskip("mcp", reason="`mcp` SDK not installed in this environment")

    from sandiego_mcp.server import build_server

    mcp = build_server()
    # FastMCP exposes the tool registry on _tool_manager._tools (current SDK)
    # Fall back to a few candidate attrs in case the SDK API moves.
    registered = _extract_tool_names(mcp)
    missing = EXPECTED_TOOLS - registered
    assert not missing, f"Missing tools: {sorted(missing)}"


def _extract_tool_names(mcp) -> set[str]:
    candidates = [
        getattr(mcp, "_tool_manager", None),
        getattr(mcp, "tool_manager", None),
        getattr(mcp, "tools", None),
        mcp,
    ]
    for c in candidates:
        if c is None:
            continue
        tools = getattr(c, "_tools", None) or getattr(c, "tools", None)
        if isinstance(tools, dict):
            return set(tools.keys())
        if isinstance(tools, list):
            return {getattr(t, "name", str(t)) for t in tools}
    # Last resort: list_tools()
    try:
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(mcp.list_tools())
        return {t.name for t in result}
    except Exception:
        return set()
