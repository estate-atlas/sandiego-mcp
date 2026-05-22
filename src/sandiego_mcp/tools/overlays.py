"""Overlay-zone lookups: SDA, TPA, Coastal, CPIOZ, height, MSCP, flood, fire, etc.

This is the #1 multifamily-developer question — overlays drive ADU density bonus
eligibility (SDA), AB 2097 parking elimination (TPA = ½-mile of major transit),
Coastal Commission review, Prop D height limits, etc.

Two entrypoints:
  - get_overlays_for_apn(apn): resolves parcel centroid then runs PIP.
  - get_overlays_for_point(lat, lon): direct point-in-polygon.

Geometry contract: all three source tables (`parcels`, `sda_boundaries`,
`environmental_overlays`, `transit_stops`) live in SRID 4326. Distances are
computed in meters via ST_DWithin on the geography cast — see DDIA ch. 3
on choosing the right index type; PostGIS GIST indexes handle the geometry
predicates here.
"""
from __future__ import annotations

from typing import Any

from sandiego_mcp.db import fetch_all, fetch_one
from sandiego_mcp.meta import build_meta

# AB 2097 / TPA threshold: a parcel within ~½ mile (805m) of a major transit
# stop is in a Transit Priority Area for state parking-elimination purposes.
# Treated as a conservative approximation — the official TPA layer is an
# MTS-published polygon, but until that's ingested this radius-from-major-stop
# proxy matches the statutory definition (Gov Code 65915(o)) closely enough.
TPA_RADIUS_METERS = 805.0  # 0.5 mi

# How human-readable labels map for the structured `overlay_type` column.
ENV_OVERLAY_LABELS = {
    "cpioz": "CPIOZ (Community Plan Implementation Overlay Zone)",
    "height": "Coastal Height Limit (Prop D)",
    "coastal": "Coastal Overlay Zone",
    "airport": "Airport Influence Area",
    "historic": "Historical District",
    "flood": "FEMA Flood Zone",
    "fire": "Very High Fire Hazard Severity Zone",
    "seismic": "Seismic Hazard / Fault Zone",
    "mscp": "Multiple Species Conservation Program",
    "contamination": "Contaminated Site / Brownfield",
    "community_plan": "Community Plan Area",
    "mobile_home": "Mobile Home Park Overlay",
    "design": "Design Review Overlay",
    "lighting": "Outdoor Lighting Zone",
    "parking": "Parking Standards Overlay",
    "tandem_parking": "Tandem Parking Overlay",
    "urban_village": "Urban Village Overlay",
    "transit": "Transit Area Overlay",
}

# overlay_type values we report by default. Excludes contamination (mostly
# historical site records, not regulatory); callers can pass include_all=True.
DEFAULT_ENV_TYPES = (
    "cpioz", "height", "coastal", "airport", "historic", "flood", "fire",
    "seismic", "mscp", "community_plan", "mobile_home", "design", "lighting",
    "parking", "tandem_parking", "urban_village", "transit",
)


def get_overlays_for_apn(apn: str, include_all: bool = False) -> dict[str, Any]:
    """Return every overlay that applies to a parcel.

    Resolves parcel centroid by APN, then runs point-in-polygon against
    SDA, environmental overlays, and a radius search against major transit
    stops for TPA inference.
    """
    if not apn:
        return {"error": "apn required (e.g. '660-152-21-00').", "_meta": build_meta()}

    row = fetch_one(
        """
        SELECT apn,
               ST_Y(ST_Centroid(geometry)) AS lat,
               ST_X(ST_Centroid(geometry)) AS lon
        FROM parcels
        WHERE apn = %s AND geometry IS NOT NULL
        """,
        (apn.strip(),),
    )
    if not row:
        return {
            "apn": apn,
            "found": False,
            "_meta": build_meta(notes="No parcel geometry for that APN."),
        }

    payload = _overlays_at_point(row["lat"], row["lon"], include_all=include_all)
    payload["apn"] = apn
    payload["found"] = True
    payload["parcel_centroid"] = {"lat": row["lat"], "lon": row["lon"]}
    return payload


def get_overlays_for_point(
    lat: float,
    lon: float,
    include_all: bool = False,
) -> dict[str, Any]:
    """Return overlays applying to an arbitrary WGS84 point.

    Useful when the caller has a coordinate but not an APN — e.g. from a
    map click, an address geocode, or a project-site centroid.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return {"error": "lat and lon must be numeric (WGS84).", "_meta": build_meta()}

    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lon_f <= 180.0):
        return {"error": "lat/lon out of WGS84 range.", "_meta": build_meta()}

    payload = _overlays_at_point(lat_f, lon_f, include_all=include_all)
    payload["found"] = True
    payload["point"] = {"lat": lat_f, "lon": lon_f}
    return payload


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _overlays_at_point(lat: float, lon: float, *, include_all: bool) -> dict[str, Any]:
    overlays: list[dict[str, Any]] = []

    # --- SDA --------------------------------------------------------------
    # Multiple boundary records share the same name (10K rows = many polygons
    # tiled together). De-dupe by feature_name + ordinance_ref in app code.
    sda_rows = fetch_all(
        """
        SELECT DISTINCT feature_name, ordinance_ref, source_url,
               effective_date
        FROM sda_boundaries
        WHERE ST_Intersects(
            geometry,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        )
        """,
        (lon, lat),
    )
    for r in sda_rows:
        overlays.append({
            "type": "SDA",
            "name": r.get("feature_name") or "Sustainable Development Area",
            "applies": True,
            "regulatory_effect": (
                "Eligible for state ADU density bonus + streamlined CEQA "
                "review. SDA designation supports SB 9 / SB 10 paths."
            ),
            "citation": {
                "ordinance": r.get("ordinance_ref"),
                "source_url": r.get("source_url"),
                "effective_date": _isofmt(r.get("effective_date")),
            },
        })

    # --- Environmental overlays (CPIOZ, height, coastal, etc.) ------------
    env_filter = "" if include_all else "AND overlay_type = ANY(%s)"
    env_params: list = [lon, lat]
    if not include_all:
        env_params.append(list(DEFAULT_ENV_TYPES))

    env_rows = fetch_all(
        f"""
        SELECT overlay_type, overlay_name, zone_code, ordinance_number,
               community_plan, district_type, hazard_level,
               flood_zone, flood_bfe, flood_sfha,
               fire_hazard_class, fire_responsibility,
               coastal_zone, airport_name, permit_jurisdiction,
               source, source_url, effective_date, notes
        FROM environmental_overlays
        WHERE ST_Intersects(
            geometry,
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        )
          {env_filter}
        """,
        env_params,
    )
    for r in env_rows:
        otype = r.get("overlay_type") or "unknown"
        overlays.append({
            "type": otype.upper(),
            "name": r.get("overlay_name") or ENV_OVERLAY_LABELS.get(otype, otype),
            "applies": True,
            "regulatory_effect": _effect_for(otype, r),
            "attributes": _attrs_for(otype, r),
            "citation": {
                "ordinance": r.get("ordinance_number"),
                "source": r.get("source"),
                "source_url": r.get("source_url"),
                "effective_date": _isofmt(r.get("effective_date")),
                "notes": r.get("notes"),
            },
        })

    # --- TPA (AB 2097) — radius search around major transit stops ---------
    # ST_DWithin on the geography cast — meters everywhere. The major stop
    # filter (`is_major_stop`) was set in the MTS GTFS ingester; non-major
    # stops do not trigger TPA under state definition.
    tpa_row = fetch_one(
        """
        SELECT stop_id, stop_name, route_types,
               ST_Distance(
                   geometry::geography,
                   ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
               )::numeric(10, 1) AS distance_m,
               source_url
        FROM transit_stops
        WHERE is_major_stop = TRUE
          AND ST_DWithin(
              geometry::geography,
              ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
              %s
          )
        ORDER BY ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography <-> geometry::geography
        LIMIT 1
        """,
        (lon, lat, lon, lat, TPA_RADIUS_METERS, lon, lat),
    )
    if tpa_row:
        overlays.append({
            "type": "TPA",
            "name": "Transit Priority Area (AB 2097)",
            "applies": True,
            "regulatory_effect": (
                "Within 0.5 mile of a major transit stop. State law (AB 2097, "
                "Gov Code 65863.2) eliminates minimum parking requirements. "
                "ADU bonus densities + reduced setbacks may apply."
            ),
            "attributes": {
                "nearest_stop": tpa_row.get("stop_name"),
                "stop_id": tpa_row.get("stop_id"),
                "distance_m": float(tpa_row["distance_m"]) if tpa_row.get("distance_m") is not None else None,
                "route_types": tpa_row.get("route_types"),
            },
            "citation": {
                "statute": "California Gov Code 65863.2 (AB 2097, 2022)",
                "source_url": tpa_row.get("source_url"),
                "notes": (
                    "TPA computed as 0.5 mi (805m) of an MTS-flagged major "
                    "transit stop. Authoritative TPA polygon ingestion is "
                    "planned; this radius proxy follows the statutory test."
                ),
            },
        })

    # Citations roll up into the _meta envelope for one-glance provenance.
    citations = [o["citation"] for o in overlays if o.get("citation")]
    return {
        "overlays": overlays,
        "overlay_count": len(overlays),
        "_meta": build_meta(
            freshness_sla="quarterly",
            citations=citations,
            notes=(
                "Geometry source SRID 4326. SDA/CPIOZ/Coastal authoritative; "
                "TPA derived from MTS GTFS major-stop radius (proxy for the "
                "official polygon)."
            ),
        ),
    }


def _effect_for(overlay_type: str, r: dict) -> str:
    t = overlay_type.lower()
    if t == "cpioz":
        return (
            "Community Plan Implementation Overlay Zone. Triggers additional "
            "discretionary review (CPIOZ-A or CPIOZ-B). Check SDMC § 132.14."
        )
    if t == "height":
        return (
            "Coastal Height Limit Overlay (Prop D). 30 ft / 2-story max in "
            "the coastal zone west of I-5 (with exceptions). SDMC § 132.0505."
        )
    if t == "coastal":
        return (
            "Coastal Overlay Zone. May require Coastal Development Permit "
            "from City or Coastal Commission. SDMC § 126.0701 et seq."
        )
    if t == "airport":
        airport = r.get("airport_name") or "an airport"
        return f"Airport Influence Area for {airport}. ALUC review required for new development."
    if t == "historic":
        return "Historical District / Resource. HRB review may be required prior to permit issuance."
    if t == "flood":
        sfha = r.get("flood_sfha")
        zone = r.get("flood_zone")
        if sfha:
            return f"FEMA Special Flood Hazard Area (Zone {zone}). FEMA elevation certificate + flood insurance required."
        return f"FEMA flood zone {zone}. Lower-risk; check local floodplain regs."
    if t == "fire":
        cls = r.get("fire_hazard_class") or "Very High"
        return f"Fire Hazard Severity Zone ({cls}). Chapter 7A construction + defensible space required."
    if t == "seismic":
        return "Seismic / Alquist-Priolo zone. Geotechnical study required for habitable structures."
    if t == "mscp":
        return "MSCP preserve / Multi-Habitat Planning Area. Habitat impact + biological review may apply."
    if t == "community_plan":
        cp = r.get("community_plan") or "a community plan area"
        return f"Within {cp}. Community-plan-specific FAR, height, and design standards apply."
    return r.get("notes") or "Overlay applies — see citation for details."


def _attrs_for(overlay_type: str, r: dict) -> dict[str, Any]:
    """Surface only the columns that are relevant to each overlay flavor."""
    t = overlay_type.lower()
    if t == "flood":
        return {
            "flood_zone": r.get("flood_zone"),
            "flood_bfe": _num(r.get("flood_bfe")),
            "flood_sfha": r.get("flood_sfha"),
        }
    if t == "fire":
        return {
            "fire_hazard_class": r.get("fire_hazard_class"),
            "fire_responsibility": r.get("fire_responsibility"),
        }
    if t == "height":
        return {
            "hazard_level": r.get("hazard_level"),
            "zone_code": r.get("zone_code"),
        }
    if t == "coastal":
        return {
            "coastal_zone": r.get("coastal_zone"),
            "permit_jurisdiction": r.get("permit_jurisdiction"),
        }
    if t == "airport":
        return {"airport_name": r.get("airport_name")}
    if t == "community_plan":
        return {"community_plan": r.get("community_plan")}
    if t == "cpioz":
        return {
            "zone_code": r.get("zone_code"),
            "district_type": r.get("district_type"),
        }
    # generic fallback
    out = {
        "zone_code": r.get("zone_code"),
        "district_type": r.get("district_type"),
        "community_plan": r.get("community_plan"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _num(v):
    return float(v) if v is not None else None


def _isofmt(d) -> str | None:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)
