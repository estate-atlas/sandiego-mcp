"""Provenance + freshness metadata attached to every tool response.

This _meta envelope is the competitive moat — it gives every response
a machine-readable source, data freshness timestamp, and citation list
that no government source publishes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sandiego_mcp import __version__, __mcp_server__, __source__

DEFAULT_FRESHNESS_SLA = {
    "code": "monthly",
    "bulletin": "monthly",
    "ordinance": "monthly",
    "permit": "weekly",
    "code_enforcement": "weekly",
    "parcel": "quarterly",
    "zoning": "quarterly",
    "assessor": "quarterly",
}


def build_meta(
    *,
    data_as_of: datetime | str | None = None,
    freshness_sla: str | None = None,
    citations: list[dict] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    if isinstance(data_as_of, datetime):
        data_as_of = data_as_of.astimezone(timezone.utc).isoformat()
    return {
        "source": __source__,
        "data_as_of": data_as_of,
        "freshness_sla": freshness_sla,
        "mcp_server": f"{__mcp_server__} v{__version__}",
        "citations": citations or [],
        "notes": notes,
        "license": "Public-domain municipal data, MCP envelope © Estate Atlas",
    }
