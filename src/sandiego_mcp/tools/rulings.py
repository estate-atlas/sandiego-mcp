"""Estate Atlas: SD-MCP — Court case rulings tool.

v0.1 stub: returns a structured 'coverage: pending' response so agents can
plan around the data gap while ingestion is being built.

Ingestion plan:  mcp-server/docs/2026-05-15-case-rulings-pipeline-PLAN.md
Pipeline scaffold: pipelines/scripts/ingestion/fetch_court_rulings.py

Source: CourtListener REST API v4 (Free Law Project)
Scope: Federal district (S.D. Cal.), Cal. Court of Appeal (4th Dist.),
       Cal. Supreme Court — opinions relevant to SD land-use, zoning,
       CEQA, and Coastal Act matters.

Planned first-data date: 2026-07-15 (Phase 3 per pipeline plan)
"""
from __future__ import annotations

from typing import Any

from sandiego_mcp.meta import build_meta


def get_case_rulings(query: str | None = None) -> dict[str, Any]:
    """Return court rulings affecting San Diego land use, zoning, and planning.

    Currently a stub. First live data expected 2026-07-15.

    Args:
        query: Optional search query (e.g. 'CEQA coastal setback variance').
               Accepted now so callers can be written ahead of data availability.
    """
    return {
        "coverage": "pending",
        "query": query,
        "available": False,
        "planned_at": "2026-07-15",   # ISO date — Phase 3 per pipeline plan
        "pipeline": {
            "source": "CourtListener REST API v4 (Free Law Project)",
            "courts": [
                "casd — U.S. District Court, S.D. Cal.",
                "calctapp4d — Cal. Court of Appeal, 4th District",
                "cal — California Supreme Court",
                "scotus — U.S. Supreme Court (land-use precedent)",
            ],
            "scope": (
                "Federal + CA appellate decisions referencing City of San Diego "
                "or County of San Diego in land-use, zoning, CEQA, and Coastal Act matters."
            ),
            "plan_doc": "mcp-server/docs/2026-05-15-case-rulings-pipeline-PLAN.md",
            "pipeline_scaffold": "pipelines/scripts/ingestion/fetch_court_rulings.py",
        },
        "fallback": (
            "For ordinance text: use search_municipal_code or get_code_section. "
            "For case law now: query CourtListener directly at "
            "https://www.courtlistener.com/opinion/?q=City+of+San+Diego+zoning&type=o"
            "&court=casd&court=calctapp4d&stat_Precedential=on"
        ),
        "_meta": build_meta(
            freshness_sla="not-yet-available",
            notes=(
                "Stub v0.1 — CourtListener ingestion pipeline scaffolded 2026-05-15. "
                "Commercial-use license with Free Law Project must be resolved before "
                "production deployment. See Open Questions in pipeline plan."
            ),
        ),
    }
