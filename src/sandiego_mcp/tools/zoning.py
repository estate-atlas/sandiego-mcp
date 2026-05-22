"""Zone-code lookups: setbacks, lot dimensions, FAR, height limits."""
from __future__ import annotations

from typing import Any

from sandiego_mcp.db import fetch_all, fetch_one
from sandiego_mcp.meta import build_meta


def get_zoning_for_apn(apn: str) -> dict[str, Any]:
    """Return the zone name(s) for a parcel APN.

    Reads from parcel_zoning (migration 057 reverse spatial join covering all 1M+
    parcels) first. Falls back to the DB function get_zoning_for_apn() which does
    a live spatial join for parcels not yet in the lookup table.
    """
    if not apn:
        return {"error": "apn required (e.g. '535-095-05-00').", "_meta": build_meta()}

    apn_clean = apn.strip()

    # Fast path: parcel_zoning lookup table (covers ~90%+ of parcels after migration 057)
    rows = fetch_all(
        """
        SELECT pz.zone_name, pz.is_primary,
               zp.overlay_zones, zp.imp_date, zp.ordnum
        FROM parcel_zoning pz
        LEFT JOIN zoning_parcels zp
            ON zp.zone_name = pz.zone_name
           AND zp.apn = pz.apn
        WHERE pz.apn = %s
        ORDER BY pz.is_primary DESC, zp.imp_date DESC NULLS LAST
        """,
        (apn_clean,),
    )

    if not rows:
        # Fallback: DB-side function that does a live spatial join
        rows = fetch_all(
            "SELECT zone_name, overlay_zones, imp_date, ordnum FROM get_zoning_for_apn(%s)",
            (apn_clean,),
        )
        source = "spatial_join_fallback"
    else:
        source = "parcel_zoning_table"

    if not rows:
        return {
            "apn": apn_clean,
            "found": False,
            "_meta": build_meta(
                notes="No zoning found for this APN. Parcel may be outside city boundaries."
            ),
        }

    return {
        "apn": apn_clean,
        "found": True,
        "source": source,
        "zones": [
            {
                "zone_name": r["zone_name"],
                "is_primary": r.get("is_primary", True),
                "overlay_zones": r.get("overlay_zones") or [],
                "implementation_date": _isofmt(r.get("imp_date")),
                "ordinance_number": r.get("ordnum"),
            }
            for r in rows
        ],
        "_meta": build_meta(
            freshness_sla="quarterly",
            notes="Call get_setbacks_for_zone with zone_name for dimensional rules.",
        ),
    }


def get_setbacks_for_zone(
    zone_code: str,
    lot_area_sqft: float | None = None,
    dwelling_units: int | None = None,
) -> dict[str, Any]:
    """Return setbacks + lot rules + envelope limits for a zone.

    Args:
        zone_code: Base zone designator, e.g. "RS-1-7" or "CC-1-3".
        lot_area_sqft: Actual lot area in square feet. When provided for RS zones
            (RS-1-2 through RS-1-7, RS-1-9 through RS-1-14), the FAR is looked up
            from the zone_far_brackets table (SDMC Table 131-04J sliding scale)
            rather than returned as the scalar maximum.
        dwelling_units: Proposed or existing DU count. When provided for RM-1-x and
            RM-2-x zones, returns the tier-appropriate FAR from zone_far_brackets.
    """
    if not zone_code:
        return {"error": "zone_code required (e.g. 'RS-1-7').", "_meta": build_meta()}

    zone_clean = zone_code.strip().upper()

    row = fetch_one(
        """
        SELECT zone_code, zone_name, zone_category,
               front_setback_ft, side_setback_ft, street_side_setback_ft, rear_setback_ft,
               min_lot_area_sqft, min_lot_width_ft, min_lot_depth_ft, min_street_frontage_ft,
               max_lot_coverage_pct, max_floor_area_ratio, max_height_ft, max_density_du_per_acre,
               corner_lot_rules, hillside_rules, coastal_overlay_rules, accessory_structure_rules,
               source_table, source_section, ordinance_number, effective_date, notes
        FROM zone_setbacks
        WHERE zone_code = %s AND is_active = TRUE
        """,
        (zone_clean,),
    )

    if not row:
        return {
            "zone_code": zone_code,
            "found": False,
            "_meta": build_meta(notes="Zone code not found. Check spelling (e.g. 'RS-1-7')."),
        }

    # FAR: prefer bracket lookup when caller supplies lot_area_sqft or dwelling_units
    scalar_far = _num(row.get("max_floor_area_ratio"))
    applied_far = scalar_far
    far_basis: str | None = None

    if lot_area_sqft is not None or dwelling_units is not None:
        bracket_row = _lookup_far_bracket(zone_clean, lot_area_sqft, dwelling_units)
        if bracket_row is not None:
            applied_far = float(bracket_row["far_value"])
            far_basis = (
                f"Table 131-04J bracket for {int(lot_area_sqft):,} sf lot"
                if lot_area_sqft is not None
                else f"Table 131-04G tier for {dwelling_units} DU"
            )

    result = {
        "zone_code": row["zone_code"],
        "found": True,
        "zone_name": row.get("zone_name"),
        "zone_category": row.get("zone_category"),
        "setbacks_ft": {
            "front": _num(row.get("front_setback_ft")),
            "side": _num(row.get("side_setback_ft")),
            "street_side": _num(row.get("street_side_setback_ft")),
            "rear": _num(row.get("rear_setback_ft")),
        },
        "lot_requirements": {
            "min_area_sqft": _num(row.get("min_lot_area_sqft")),
            "min_width_ft": _num(row.get("min_lot_width_ft")),
            "min_depth_ft": _num(row.get("min_lot_depth_ft")),
            "min_street_frontage_ft": _num(row.get("min_street_frontage_ft")),
        },
        "envelope_limits": {
            "max_lot_coverage_pct": _num(row.get("max_lot_coverage_pct")),
            "max_floor_area_ratio": applied_far,
            "max_floor_area_ratio_scalar": scalar_far,
            "far_basis": far_basis or "scalar maximum from zone_setbacks",
            "max_height_ft": _num(row.get("max_height_ft")),
            "max_density_du_per_acre": _num(row.get("max_density_du_per_acre")),
        },
        "special_rules": {
            "corner_lot": row.get("corner_lot_rules") or {},
            "hillside": row.get("hillside_rules") or {},
            "coastal_overlay": row.get("coastal_overlay_rules") or {},
            "accessory_structure": row.get("accessory_structure_rules") or {},
        },
        "source": {
            "table": row.get("source_table"),
            "section": row.get("source_section"),
            "ordinance_number": row.get("ordinance_number"),
            "effective_date": _isofmt(row.get("effective_date")),
        },
        "notes": row.get("notes"),
        "_meta": build_meta(
            data_as_of=_isofmt(row.get("effective_date")),
            freshness_sla="on-ordinance-change",
            citations=[{
                "section": row.get("source_section"),
                "table": row.get("source_table"),
            }],
        ),
    }
    return result


def get_zone_info(
    zone_code: str,
    lot_area_sqft: float | None = None,
    dwelling_units: int | None = None,
) -> dict[str, Any]:
    """Higher-level zone summary: combines setbacks + a pointer back into SDMC chunks.

    Args:
        zone_code: Base zone designator, e.g. "RS-1-7" or "CC-1-3".
        lot_area_sqft: Lot area in square feet. Used to look up sliding-scale FAR
            for RS zones (SDMC Table 131-04J). Example: a 5,000 sf RS-1-7 lot
            has FAR 0.60, not the scalar maximum of 0.70.
        dwelling_units: Proposed DU count. Used to look up tier-based FAR for
            RM zones (SDMC Table 131-04G).
    """
    base = get_setbacks_for_zone(zone_code, lot_area_sqft=lot_area_sqft,
                                 dwelling_units=dwelling_units)
    base["next_steps"] = [
        f"Call search_municipal_code with query='{zone_code} permitted uses' for use regulations.",
        f"Call search_municipal_code with query='{zone_code} development regulations' for narrative regs.",
    ]
    return base


def _lookup_far_bracket(
    zone_code: str,
    lot_area_sqft: float | None,
    dwelling_units: int | None,
) -> dict[str, Any] | None:
    """Return a zone_far_brackets row matching the given lot area or DU count."""
    if lot_area_sqft is not None:
        return fetch_one(
            """
            SELECT far_value, note, source_table
            FROM zone_far_brackets
            WHERE zone_code = %s
              AND bracket_type = 'lot_area'
              AND (range_min IS NULL OR %s >= range_min)
              AND (range_max IS NULL OR %s <= range_max)
            LIMIT 1
            """,
            (zone_code, lot_area_sqft, lot_area_sqft),
        )

    if dwelling_units is not None:
        return fetch_one(
            """
            SELECT far_value, note, source_table
            FROM zone_far_brackets
            WHERE zone_code = %s
              AND bracket_type = 'dwelling_units'
              AND (range_min IS NULL OR %s >= range_min)
              AND (range_max IS NULL OR %s <= range_max)
            LIMIT 1
            """,
            (zone_code, dwelling_units, dwelling_units),
        )

    return None


def _num(v):
    return float(v) if v is not None else None


def _isofmt(d) -> str | None:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)
