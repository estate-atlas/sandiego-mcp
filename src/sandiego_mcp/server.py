"""Estate Atlas: SD-MCP — server entrypoint.

Registers all tools with the FastMCP server and runs over the transport
selected by SANDIEGO_MCP_TRANSPORT (`stdio` default, or `http`).

- stdio: classic local transport (Claude Desktop / Code).
- http:  streamable-HTTP + SSE for the hosted endpoint at
         sandiego.estateatlas.ai/mcp. Requires the `http` extra.
"""
from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

# Load .env if present — useful for local dev. In production (Claude Desktop / Code)
# the env is provided via the mcp config block.
load_dotenv()

logging.basicConfig(
    level=os.getenv("SANDIEGO_MCP_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,  # MUST be stderr — stdout is the MCP transport
)
log = logging.getLogger("sandiego-mcp")


def build_server():
    """Build and return the FastMCP server with all tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The `mcp` Python package is required. "
            "Install with: pip install 'mcp>=1.0,<2'"
        ) from exc

    from sandiego_mcp import __version__
    from sandiego_mcp.tools.bulletins import get_bulletin, list_bulletins
    from sandiego_mcp.tools.code import get_code_section, get_table_of_contents
    from sandiego_mcp.tools.freshness import data_freshness
    from sandiego_mcp.tools.overlays import (
        get_overlays_for_apn,
        get_overlays_for_point,
    )
    from sandiego_mcp.tools.parcels import (
        get_permits_for_parcel,
        get_violations_for_parcel,
        lookup_parcel,
    )
    from sandiego_mcp.tools.rulings import get_case_rulings
    from sandiego_mcp.tools.search import search_municipal_code
    from sandiego_mcp.tools.zoning import get_setbacks_for_zone, get_zone_info

    mcp = FastMCP(
        name="estate-atlas-sd-mcp",
        instructions=(
            "Estate Atlas: SD-MCP — authoritative Model Context Protocol server "
            "for City of San Diego land-use intelligence. Covers municipal code, "
            "information bulletins, permits, zoning, parcels, and (planned) court "
            "rulings. Every response includes a _meta envelope with data freshness, "
            "citations, and source links. Read-only. "
            f"Server version: {__version__}."
        ),
    )

    # --- Search & code ---------------------------------------------------
    mcp.tool(
        name="search_municipal_code",
        description=(
            "Semantic search across San Diego Municipal Code, information "
            "bulletins, and ordinances. Returns top-matching chunks with "
            "section numbers, source URLs, and PDF anchors. Use for "
            "open-ended questions like 'what are fence height rules' or "
            "'when do I need historical review'."
        ),
    )(search_municipal_code)

    mcp.tool(
        name="get_code_section",
        description=(
            "Fetch the full text of a specific SDMC section by section "
            "number (e.g. '142.0610'). Includes diagrams, cross-references, "
            "and source PDF link. Prefer this over search when you already "
            "know the section."
        ),
    )(get_code_section)

    mcp.tool(
        name="get_table_of_contents",
        description=(
            "Return a hierarchical table of contents for the Municipal "
            "Code, optionally filtered to a single chapter. Use to "
            "discover what's available before searching."
        ),
    )(get_table_of_contents)

    # --- Bulletins -------------------------------------------------------
    mcp.tool(
        name="list_bulletins",
        description=(
            "List Development Services Department information bulletins, "
            "optionally filtered by project type (e.g. 'ADU', "
            "'New Construction'). Bulletins are the procedural guides "
            "that tell applicants what forms + checklists are required."
        ),
    )(list_bulletins)

    mcp.tool(
        name="get_bulletin",
        description=(
            "Fetch the full content of a specific information bulletin "
            "by IB number (e.g. 'IB-121' or '121'). Returns checklist, "
            "required forms, and reference code sections."
        ),
    )(get_bulletin)

    # --- Parcels ---------------------------------------------------------
    mcp.tool(
        name="lookup_parcel",
        description=(
            "Look up a parcel by street address OR APN. Returns zoning, "
            "overlays, lot size, assessor data (year built, sqft, type). "
            "The killer query — most public sources require visiting "
            "4+ websites to assemble this picture."
        ),
    )(lookup_parcel)

    mcp.tool(
        name="get_permits_for_parcel",
        description=(
            "Fetch building permits for a parcel by APN. Filter by status "
            "('Active', 'Completed', 'Expired', 'Revoked', 'Pending', "
            "or 'all'). Returns permit number, type, dates, contractor, "
            "and project value."
        ),
    )(get_permits_for_parcel)

    mcp.tool(
        name="get_violations_for_parcel",
        description=(
            "Fetch code-enforcement cases for a parcel by APN. Filter by "
            "status ('Open', 'Closed', 'Resolved', 'Pending', or 'all'). "
            "Returns case number, violation type, dates, and resolution."
        ),
    )(get_violations_for_parcel)

    # --- Overlays --------------------------------------------------------
    mcp.tool(
        name="get_overlays_for_apn",
        description=(
            "Return every regulatory overlay that applies to a parcel "
            "by APN: SDA (Sustainable Development Area, drives state ADU "
            "density bonus eligibility), TPA (Transit Priority Area for "
            "AB 2097 parking elimination), CPIOZ, Coastal Overlay, Prop D "
            "Coastal Height Limit, MSCP, flood, fire, seismic, airport, "
            "and historic-district overlays. The #1 multifamily-developer "
            "question — overlays gate ADU bonus and parking workflows."
        ),
    )(get_overlays_for_apn)

    mcp.tool(
        name="get_overlays_for_point",
        description=(
            "Same overlay lookup as get_overlays_for_apn but keyed by a "
            "WGS84 lat/lon. Use when you have a project-site coordinate "
            "but no APN (map click, geocode result, etc.)."
        ),
    )(get_overlays_for_point)

    # --- Zoning ----------------------------------------------------------
    mcp.tool(
        name="get_setbacks_for_zone",
        description=(
            "Return setbacks, lot dimension minima, FAR, height limits, "
            "and special-overlay rules for a San Diego zone code "
            "(e.g. 'RS-1-7', 'RM-1-1'). Sourced from SDMC tables."
        ),
    )(get_setbacks_for_zone)

    mcp.tool(
        name="get_zone_info",
        description=(
            "Higher-level zone summary. Returns setbacks + envelope "
            "limits + pointer back into SDMC for permitted-use detail. "
            "Combine with search_municipal_code for narrative regs."
        ),
    )(get_zone_info)

    # --- Freshness -------------------------------------------------------
    mcp.tool(
        name="data_freshness",
        description=(
            "Per-source data freshness: last-update timestamp, record "
            "count, and SLA cadence for every data source the MCP "
            "exposes. Call this when you need to assess whether the "
            "answer to a regulatory question is up-to-date."
        ),
    )(data_freshness)

    # --- Case rulings (stub — first data 2026-07-15) --------------------
    mcp.tool(
        name="get_case_rulings",
        description=(
            "PENDING (v0.1): Federal and California appellate court rulings "
            "affecting San Diego land use, zoning, CEQA, and Coastal Act. "
            "Pipeline scaffolded 2026-05-15 via CourtListener API. "
            "Returns coverage:pending with a planned_at date and fallback "
            "CourtListener search URL until live data ships (ETA 2026-07-15)."
        ),
    )(get_case_rulings)

    return mcp


def run():
    """Console-script entrypoint. Dispatches by SANDIEGO_MCP_TRANSPORT."""
    transport = os.getenv("SANDIEGO_MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        log.info("Starting Estate Atlas: SD-MCP (STDIO transport)")
        mcp = build_server()
        mcp.run()
    elif transport in ("http", "streamable-http", "sse"):
        log.info("Starting Estate Atlas: SD-MCP (HTTP transport)")
        from sandiego_mcp.http_app import run_http
        run_http()
    else:
        raise SystemExit(
            f"Unknown SANDIEGO_MCP_TRANSPORT={transport!r}. "
            "Use 'stdio' or 'http'."
        )


if __name__ == "__main__":
    run()
