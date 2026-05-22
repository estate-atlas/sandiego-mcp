"""Parcel-level lookups: address/APN -> zoning, assessor, permits, violations."""
from __future__ import annotations

import re
from typing import Any

from sandiego_mcp.db import fetch_all, fetch_one
from sandiego_mcp.meta import build_meta


def lookup_parcel(address: str | None = None, apn: str | None = None) -> dict[str, Any]:
    """Look up parcel by address OR APN. Returns zoning + overlays + assessor + lot.

    This is the highest-value cross-source join — most public sources
    require visiting 4+ websites to assemble this picture.
    """
    if not address and not apn:
        return {"error": "Provide either `address` or `apn`.", "_meta": build_meta()}

    if apn:
        parcel = fetch_one(
            """
            SELECT p.apn,
                   COALESCE(
                       CASE WHEN p.address ~ '^[0-9]+$' THEN NULL ELSE NULLIF(p.address, '0') END,
                       ap.address
                   ) AS address,
                   p.lot_size_sqft, p.legal_description
            FROM parcels p
            LEFT JOIN LATERAL (
                SELECT address FROM address_points WHERE apn = p.apn LIMIT 1
            ) ap ON TRUE
            WHERE p.apn = %s
            """,
            (apn.strip(),),
        )
    else:
        # parcels.address is unreliable (often '0'); search address_points
        # and join back to parcels. City stores street numbers zero-padded
        # to 4 digits ("0600 05TH AVE") and ordinal suffixes attached
        # ("05TH", "21ST"), so try a few variants.
        variants = _address_match_variants(address or "")
        parcel = None
        for v in variants:
            parcel = fetch_one(
                """
                SELECT p.apn,
                       ap.address AS address,
                       p.lot_size_sqft, p.legal_description
                FROM address_points ap
                JOIN parcels p ON p.apn = ap.apn
                WHERE ap.address ILIKE %s
                LIMIT 1
                """,
                (v,),
            )
            if parcel:
                break

    if not parcel:
        return {
            "found": False,
            "address": address,
            "apn": apn,
            "_meta": build_meta(notes="No matching parcel."),
        }

    parcel_apn = parcel["apn"]

    # Use get_zoning_for_apn() which tries indexed APN lookup first,
    # then falls back to spatial join if the APN backfill (migration 054)
    # hasn't populated that row yet.
    zoning = fetch_all(
        "SELECT zone_name, overlay_zones, imp_date, ordnum FROM get_zoning_for_apn(%s)",
        (parcel_apn,),
    )

    assessor = fetch_one(
        """
        SELECT year_built, existing_sqft, property_type, assessed_value, last_scraped
        FROM property_assessor
        WHERE apn = %s
        """,
        (parcel_apn,),
    )

    return {
        "found": True,
        "apn": parcel_apn,
        "address": parcel["address"],
        "lot_size_sqft": parcel.get("lot_size_sqft"),
        "legal_description": parcel.get("legal_description"),
        "zoning": [
            {
                "zone_name": z["zone_name"],
                "overlay_zones": z.get("overlay_zones") or [],
                "implementation_date": _isofmt(z.get("imp_date")),
                "ordinance_number": z.get("ordnum"),
            }
            for z in zoning
        ],
        "assessor": {
            "year_built": assessor.get("year_built") if assessor else None,
            "existing_sqft": assessor.get("existing_sqft") if assessor else None,
            "property_type": assessor.get("property_type") if assessor else None,
            "assessed_value": (
                float(assessor["assessed_value"]) if assessor and assessor.get("assessed_value") else None
            ),
            "last_scraped": _isofmt(assessor.get("last_scraped")) if assessor else None,
        } if assessor else None,
        "_meta": build_meta(
            data_as_of=_isofmt(assessor.get("last_scraped")) if assessor else None,
            freshness_sla="quarterly",
            notes="Call get_permits_for_parcel / get_violations_for_parcel for permit + enforcement detail.",
        ),
    }


def get_permits_for_parcel(
    apn: str,
    status: str = "all",
    limit: int = 20,
) -> dict[str, Any]:
    """Fetch building permits for a parcel."""
    if not apn:
        return {"error": "apn required", "_meta": build_meta()}

    limit = max(1, min(int(limit), 200))
    status_filter = ""
    params: list = [apn.strip()]
    if status and status.lower() != "all":
        status_filter = "AND status = %s"
        params.append(status)
    params.append(limit)

    rows = fetch_all(
        f"""
        SELECT permit_number, permit_type, status, issue_date,
               description, contractor, project_value
        FROM permits
        WHERE apn = %s
          {status_filter}
        ORDER BY issue_date DESC NULLS LAST
        LIMIT %s
        """,
        params,
    )

    return {
        "apn": apn,
        "status_filter": status,
        "count": len(rows),
        "permits": [
            {
                "permit_number": r["permit_number"],
                "permit_type": r.get("permit_type"),
                "status": r["status"],
                "issue_date": _isofmt(r.get("issue_date")),
                "description": r.get("description"),
                "contractor": r.get("contractor"),
                "project_value": float(r["project_value"]) if r.get("project_value") else None,
            }
            for r in rows
        ],
        "_meta": build_meta(freshness_sla="weekly"),
    }


def get_violations_for_parcel(
    apn: str,
    status: str = "all",
    limit: int = 20,
) -> dict[str, Any]:
    """Fetch code-enforcement cases for a parcel."""
    if not apn:
        return {"error": "apn required", "_meta": build_meta()}

    limit = max(1, min(int(limit), 200))
    status_filter = ""
    params: list = [apn.strip()]
    if status and status.lower() != "all":
        status_filter = "AND status = %s"
        params.append(status)
    params.append(limit)

    rows = fetch_all(
        f"""
        SELECT case_number, violation_type, status, open_date, close_date,
               description, resolution
        FROM code_enforcement
        WHERE apn = %s
          {status_filter}
        ORDER BY open_date DESC NULLS LAST
        LIMIT %s
        """,
        params,
    )

    return {
        "apn": apn,
        "status_filter": status,
        "count": len(rows),
        "violations": [
            {
                "case_number": r["case_number"],
                "violation_type": r.get("violation_type"),
                "status": r["status"],
                "open_date": _isofmt(r.get("open_date")),
                "close_date": _isofmt(r.get("close_date")),
                "description": r.get("description"),
                "resolution": r.get("resolution"),
            }
            for r in rows
        ],
        "_meta": build_meta(freshness_sla="weekly"),
    }


def _isofmt(d) -> str | None:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _address_match_variants(addr: str) -> list[str]:
    """Generate ILIKE patterns covering San Diego's zero-padded format.

    City addresses look like "0600 05TH AVE" or "1234 MAIN ST".
    Input "600 5th Ave" should match all of:
      - 0600 05TH AVE
      - 0600 5TH AVE
      - 600 5TH AVE
    """
    s = (addr or "").strip().upper().replace(".", "")
    if not s:
        return []

    parts = s.split()
    variants: list[str] = []

    # Zero-pad street number to 4 digits if it's the first token
    if parts and parts[0].isdigit():
        num = parts[0]
        rest = " ".join(parts[1:])
        # Pad street name ordinal: 5TH -> 05TH if numeric prefix < 10
        rest_padded = re.sub(r"\b(\d)(ST|ND|RD|TH)\b", r"0\1\2", rest)
        for padded_num in {num.zfill(4), num.zfill(3), num}:
            for r in (rest_padded, rest):
                variants.append(f"%{padded_num} {r}%")
    else:
        variants.append(f"%{s}%")

    # Always include a loose substring match as final fallback
    variants.append(f"%{s}%")
    # Dedupe preserving order
    seen, out = set(), []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
