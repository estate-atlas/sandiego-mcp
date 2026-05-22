"""Per-source data freshness — our competitive answer to opaque govt sources.

Returns the latest update timestamp + record count per data source, derived
from the actual tables (no separate sync log needed for v1).
"""
from __future__ import annotations

from typing import Any

from sandiego_mcp.db import fetch_one
from sandiego_mcp.meta import build_meta


def data_freshness() -> dict[str, Any]:
    """Return last-update + record-count + SLA per data source."""
    sources = []

    sources.append(_summarize(
        name="Municipal Code",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   GREATEST(
                     MAX(revised_date)::timestamp,
                     MAX(effective_date)::timestamp,
                     MAX(updated_at)
                   )::date AS latest
            FROM docs
            WHERE doc_type = 'code'
        """,
        sla="monthly",
    ))

    sources.append(_summarize(
        name="Information Bulletins",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   GREATEST(
                     MAX(revised_date)::timestamp,
                     MAX(effective_date)::timestamp,
                     MAX(updated_at)
                   )::date AS latest
            FROM docs
            WHERE doc_type = 'bulletin'
        """,
        sla="monthly",
    ))

    sources.append(_summarize(
        name="Building Permits",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   MAX(updated_at)::date AS latest
            FROM permits
        """,
        sla="weekly",
    ))

    sources.append(_summarize(
        name="Code Enforcement",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   MAX(updated_at)::date AS latest
            FROM code_enforcement
        """,
        sla="weekly",
    ))

    sources.append(_summarize(
        name="Parcels",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   MAX(updated_at)::date AS latest
            FROM parcels
        """,
        sla="quarterly",
    ))

    sources.append(_summarize(
        name="Parcel Zoning Lookup",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   NULL::date AS latest
            FROM parcel_zoning
        """,
        sla="quarterly",
    ))

    sources.append(_summarize(
        name="Zoning Polygons",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   MAX(updated_at)::date AS latest
            FROM zoning_parcels
        """,
        sla="quarterly",
    ))

    sources.append(_summarize(
        name="Zone Setbacks",
        sql="""
            SELECT COUNT(*)::int AS cnt,
                   MAX(updated_at)::date AS latest
            FROM zone_setbacks
            WHERE is_active = TRUE
        """,
        sla="on-ordinance-change",
    ))

    return {
        "jurisdiction": "City of San Diego, CA",
        "sources": sources,
        "_meta": build_meta(notes="Freshness derived from table-level timestamps."),
    }


def _summarize(name: str, sql: str, sla: str) -> dict[str, Any]:
    try:
        row = fetch_one(sql) or {}
        return {
            "source": name,
            "record_count": row.get("cnt"),
            "last_updated": str(row.get("latest")) if row.get("latest") else None,
            "freshness_sla": sla,
        }
    except Exception as exc:
        return {"source": name, "error": str(exc), "freshness_sla": sla}
