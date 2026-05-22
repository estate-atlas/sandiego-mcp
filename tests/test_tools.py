"""Unit tests with mocked DB + embeddings.

These do not hit Postgres or Voyage AI — they pin the response shape and
the _meta envelope contract every tool must honor.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_meta(resp: dict) -> bool:
    meta = resp.get("_meta")
    if not isinstance(meta, dict):
        return False
    required = {"source", "mcp_server", "license"}
    return required.issubset(meta.keys())


# ---------------------------------------------------------------------------
# search_municipal_code
# ---------------------------------------------------------------------------

def test_search_empty_query_returns_empty_results():
    from sandiego_mcp.tools.search import search_municipal_code
    resp = search_municipal_code("")
    assert resp["results"] == []
    assert _has_meta(resp)


def test_search_returns_shaped_results():
    from sandiego_mcp.tools import search as search_mod

    fake_rows = [{
        "doc_id": "abc",
        "chunk_id": 1,
        "chunk_md": "Fence height shall not exceed 6 feet.",
        "section_number": "142.0310",
        "title": "Land Development Code — Fences",
        "doc_type": "code",
        "chapter": "14",
        "section": "142",
        "source_url": "https://docs.sandiego.gov/142",
        "source_pdf_url": "https://docs.sandiego.gov/142.pdf",
        "effective_date": date(2024, 1, 1),
        "revised_date": date(2025, 6, 1),
        "similarity": 0.91,
    }]

    with patch.object(search_mod, "embed", return_value=[0.0] * 1024), \
         patch.object(search_mod, "fetch_all", return_value=fake_rows):
        resp = search_mod.search_municipal_code("fence height", limit=3)

    assert resp["query"] == "fence height"
    assert len(resp["results"]) == 1
    r = resp["results"][0]
    assert r["section_number"] == "142.0310"
    assert r["similarity"] == 0.91
    assert r["effective_date"] == "2024-01-01"
    assert _has_meta(resp)
    assert resp["_meta"]["freshness_sla"] == "monthly"
    assert resp["_meta"]["citations"]


def test_search_rejects_invalid_doc_type():
    from sandiego_mcp.tools.search import search_municipal_code
    resp = search_municipal_code("fence", doc_types=["pirate-treaty"])
    assert "error" in resp
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# get_code_section
# ---------------------------------------------------------------------------

def test_get_code_section_not_found():
    from sandiego_mcp.tools import code as code_mod
    with patch.object(code_mod, "fetch_all", return_value=[]):
        resp = code_mod.get_code_section("999.9999")
    assert resp["found"] is False
    assert _has_meta(resp)


def test_get_code_section_returns_full_text_and_diagrams():
    from sandiego_mcp.tools import code as code_mod

    chunks = [{
        "doc_id": "doc-1",
        "chunk_id": 1,
        "chunk_md": "Buildings shall conform to § 142.0610.",
        "section_number": "142.0610",
        "parent_context": "Chapter 14",
        "title": "Setbacks",
        "chapter": "14",
        "section": "142",
        "source_url": "https://docs.sandiego.gov/142.0610",
        "source_pdf_url": "https://docs.sandiego.gov/142.pdf",
        "effective_date": date(2024, 1, 1),
        "revised_date": date(2025, 6, 1),
    }]
    diagrams = [{
        "figure_label": "Table 142-05F",
        "image_url": "https://cdn/img.png",
        "page_number": 7,
        "extracted_text": None,
        "structured_data": {},
    }]

    with patch.object(code_mod, "fetch_all", side_effect=[chunks, diagrams]):
        resp = code_mod.get_code_section("142.0610")

    assert resp["found"] is True
    assert "142.0610" in resp["cross_references"]
    assert resp["diagrams"][0]["pdf_anchor"].endswith("#page=7")
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# bulletins
# ---------------------------------------------------------------------------

def test_get_bulletin_normalizes_ib_number():
    from sandiego_mcp.tools import bulletins as bul_mod

    row = {
        "ib_number": "IB-121",
        "title": "ADU Submittal",
        "project_types": ["ADU"],
        "required_forms": ["DS-3032"],
        "checklist_items": None,
        "reference_codes": ["141.0302"],
        "pdf_url": "https://docs/IB-121.pdf",
        "text_content": "...",
        "effective_date": date(2024, 1, 1),
        "last_updated": date(2025, 3, 1),
    }
    with patch.object(bul_mod, "fetch_one", return_value=row):
        resp = bul_mod.get_bulletin("121")
    assert resp["ib_number"] == "IB-121"
    assert resp["found"] is True
    assert _has_meta(resp)


def test_list_bulletins_filters_by_project_type():
    from sandiego_mcp.tools import bulletins as bul_mod
    with patch.object(bul_mod, "fetch_all", return_value=[]):
        resp = bul_mod.list_bulletins(project_type="ADU")
    assert resp["project_type_filter"] == "ADU"
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# parcels
# ---------------------------------------------------------------------------

def test_lookup_parcel_requires_input():
    from sandiego_mcp.tools.parcels import lookup_parcel
    resp = lookup_parcel()
    assert "error" in resp
    assert _has_meta(resp)


def test_lookup_parcel_returns_merged_record():
    from sandiego_mcp.tools import parcels as p

    parcel = {"apn": "123-456-78-00", "address": "100 Main St",
              "normalized_address": "100 MAIN ST", "lot_size_sqft": 5000,
              "legal_description": "Lot 1"}
    zoning = [{"zone_name": "RS-1-7", "overlay_zones": ["Coastal"],
               "imp_date": date(2020, 1, 1), "ordnum": "O-1234"}]
    assessor = {"year_built": 1955, "existing_sqft": 1200,
                "property_type": "Single Family", "assessed_value": 750000,
                "last_scraped": date(2025, 4, 1)}

    with patch.object(p, "fetch_one", side_effect=[parcel, assessor]), \
         patch.object(p, "fetch_all", return_value=zoning):
        resp = p.lookup_parcel(apn="123-456-78-00")

    assert resp["found"] is True
    assert resp["zoning"][0]["zone_name"] == "RS-1-7"
    assert resp["assessor"]["year_built"] == 1955
    assert _has_meta(resp)


def test_get_permits_for_parcel_status_filter():
    from sandiego_mcp.tools import parcels as p
    with patch.object(p, "fetch_all", return_value=[]):
        resp = p.get_permits_for_parcel("123-456-78-00", status="Active")
    assert resp["apn"] == "123-456-78-00"
    assert resp["status_filter"] == "Active"
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# get_table_of_contents — chapter type fix
# ---------------------------------------------------------------------------

def test_get_table_of_contents_integer_chapter_returns_results():
    """Passing chapter as int must not raise type error or return empty.

    Root cause: docs.chapter is TEXT; psycopg3 raises 'operator does not
    exist: text = smallint' when an int is passed, silently returning [].
    Fix: cast chapter to str before the SQL query.
    """
    from sandiego_mcp.tools import code as code_mod

    fake_rows = [
        {
            "chapter": "14",
            "section": "14 Art1 Div1",
            "title": "General Rules for Separately Regulated Uses",
            "source_url": "http://docs.sandiego.gov/municode/MuniCodeChapter14/Ch14Art01Division01.pdf",
            "effective_date": None,
        }
    ]

    with patch.object(code_mod, "fetch_all", return_value=fake_rows) as mock_fetch:
        resp = code_mod.get_table_of_contents(chapter=14)

    # Must call fetch_all with string '14', not integer 14
    call_args = mock_fetch.call_args
    params_passed = call_args[0][1]  # positional: (sql, params)
    assert params_passed == ("14",), (
        f"Expected ('14',) but got {params_passed!r} — chapter must be cast to str"
    )
    assert resp["chapter_filter"] == "14"
    assert resp["chapter_count"] == 1
    assert len(resp["chapters"]) == 1
    assert resp["chapters"][0]["chapter"] == "14"
    assert _has_meta(resp)


def test_get_table_of_contents_string_chapter_still_works():
    """String chapter path must still work after the int-cast fix."""
    from sandiego_mcp.tools import code as code_mod

    fake_rows = [
        {
            "chapter": "11",
            "section": "11.1",
            "title": "Subdivision Regulations",
            "source_url": None,
            "effective_date": None,
        }
    ]

    with patch.object(code_mod, "fetch_all", return_value=fake_rows):
        resp = code_mod.get_table_of_contents(chapter="11")

    assert resp["chapter_filter"] == "11"
    assert resp["chapter_count"] == 1
    assert _has_meta(resp)


def test_get_table_of_contents_numeric_sort_order():
    """Chapters should sort numerically (1,2,...,9,10,11) not lexicographically."""
    from sandiego_mcp.tools import code as code_mod

    fake_rows = [
        {"chapter": ch, "section": None, "title": f"Chapter {ch}", "source_url": None, "effective_date": None}
        for ch in ["10", "2", "14", "1", "9"]
    ]

    with patch.object(code_mod, "fetch_all", return_value=fake_rows):
        resp = code_mod.get_table_of_contents()

    chapter_order = [c["chapter"] for c in resp["chapters"]]
    assert chapter_order == ["1", "2", "9", "10", "14"], (
        f"Expected numeric order but got {chapter_order}"
    )


def test_get_table_of_contents_none_chapter_returns_all():
    """No chapter filter returns all chapters, no SQL error."""
    from sandiego_mcp.tools import code as code_mod

    with patch.object(code_mod, "fetch_all", return_value=[]) as mock_fetch:
        resp = code_mod.get_table_of_contents()

    call_args = mock_fetch.call_args
    params_passed = call_args[0][1]
    assert params_passed == (), f"Expected () but got {params_passed!r}"
    assert resp["chapter_count"] == 0
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# get_zoning_for_apn (parcel_zoning table path)
# ---------------------------------------------------------------------------

def test_get_zoning_for_apn_requires_input():
    from sandiego_mcp.tools.zoning import get_zoning_for_apn
    resp = get_zoning_for_apn("")
    assert "error" in resp
    assert _has_meta(resp)


def test_get_zoning_for_apn_reads_parcel_zoning_table():
    """get_zoning_for_apn uses parcel_zoning (fast path) when rows exist."""
    from sandiego_mcp.tools import zoning as z

    fake_rows = [
        {
            "zone_name": "RS-1-7",
            "is_primary": True,
            "overlay_zones": ["Coastal"],
            "imp_date": date(2020, 6, 1),
            "ordnum": "O-20855",
        }
    ]

    with patch.object(z, "fetch_all", return_value=fake_rows):
        resp = z.get_zoning_for_apn("535-095-05-00")

    assert resp["found"] is True
    assert resp["source"] == "parcel_zoning_table"
    assert resp["zones"][0]["zone_name"] == "RS-1-7"
    assert resp["zones"][0]["is_primary"] is True
    assert _has_meta(resp)


def test_get_zoning_for_apn_fallback_when_not_in_table():
    """Falls back to spatial-join DB function when parcel_zoning returns empty."""
    from sandiego_mcp.tools import zoning as z

    fallback_rows = [
        {
            "zone_name": "CC-1-3",
            "overlay_zones": [],
            "imp_date": date(2019, 1, 1),
            "ordnum": "O-19001",
        }
    ]

    # First call (parcel_zoning table) returns empty; second (DB function) returns data
    with patch.object(z, "fetch_all", side_effect=[[], fallback_rows]):
        resp = z.get_zoning_for_apn("999-999-99-00")

    assert resp["found"] is True
    assert resp["source"] == "spatial_join_fallback"
    assert resp["zones"][0]["zone_name"] == "CC-1-3"
    assert _has_meta(resp)


def test_get_zoning_for_apn_not_found():
    """Returns found=False when both paths return empty."""
    from sandiego_mcp.tools import zoning as z

    with patch.object(z, "fetch_all", return_value=[]):
        resp = z.get_zoning_for_apn("000-000-00-00")

    assert resp["found"] is False
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# zoning
# ---------------------------------------------------------------------------

def test_get_setbacks_for_zone_not_found():
    from sandiego_mcp.tools import zoning as z
    with patch.object(z, "fetch_one", return_value=None):
        resp = z.get_setbacks_for_zone("XX-99")
    assert resp["found"] is False
    assert _has_meta(resp)


def test_get_setbacks_for_zone_returns_envelope():
    from sandiego_mcp.tools import zoning as z

    row = {
        "zone_code": "RS-1-7", "zone_name": "Residential SFH",
        "zone_category": "residential",
        "front_setback_ft": 15, "side_setback_ft": 4,
        "street_side_setback_ft": 5, "rear_setback_ft": 13,
        "min_lot_area_sqft": 5000, "min_lot_width_ft": 50,
        "min_lot_depth_ft": 100, "min_street_frontage_ft": 50,
        "max_lot_coverage_pct": None, "max_floor_area_ratio": 0.70,
        "max_height_ft": 30, "max_density_du_per_acre": None,
        "corner_lot_rules": {}, "hillside_rules": {},
        "coastal_overlay_rules": {}, "accessory_structure_rules": {},
        "source_table": "Table 131-04D", "source_section": "131.0443",
        "ordinance_number": "O-1234", "effective_date": date(2020, 1, 1),
        "notes": None,
    }
    with patch.object(z, "fetch_one", return_value=row):
        resp = z.get_setbacks_for_zone("RS-1-7")
    assert resp["found"] is True
    assert resp["setbacks_ft"]["front"] == 15.0
    assert resp["setbacks_ft"]["street_side"] == 5.0  # audited: was 10, now 5
    # Without lot_area_sqft, returns scalar FAR maximum
    assert resp["envelope_limits"]["max_floor_area_ratio"] == 0.70
    assert resp["envelope_limits"]["far_basis"] == "scalar maximum from zone_setbacks"
    assert _has_meta(resp)


def test_get_setbacks_for_zone_far_bracket_lookup():
    """When lot_area_sqft is provided, FAR comes from zone_far_brackets (Table 131-04J).

    A 5,000 sf RS-1-7 lot should return FAR=0.60, not the scalar max of 0.70.
    """
    from sandiego_mcp.tools import zoning as z

    setbacks_row = {
        "zone_code": "RS-1-7", "zone_name": "Residential SFH",
        "zone_category": "residential",
        "front_setback_ft": 15, "side_setback_ft": 4,
        "street_side_setback_ft": 5, "rear_setback_ft": 13,
        "min_lot_area_sqft": 5000, "min_lot_width_ft": 50,
        "min_lot_depth_ft": 100, "min_street_frontage_ft": 50,
        "max_lot_coverage_pct": None, "max_floor_area_ratio": 0.70,
        "max_height_ft": 30, "max_density_du_per_acre": None,
        "corner_lot_rules": {}, "hillside_rules": {},
        "coastal_overlay_rules": {}, "accessory_structure_rules": {},
        "source_table": "Table 131-04D", "source_section": "131.0443",
        "ordinance_number": "O-1234", "effective_date": date(2020, 1, 1),
        "notes": None,
    }
    bracket_row = {
        "far_value": 0.60,
        "note": "SDMC Table 131-04J — 4,001–5,000 sf bracket",
        "source_table": "Table 131-04J",
    }

    with patch.object(z, "fetch_one", side_effect=[setbacks_row, bracket_row]):
        resp = z.get_setbacks_for_zone("RS-1-7", lot_area_sqft=5000)

    assert resp["found"] is True
    assert resp["envelope_limits"]["max_floor_area_ratio"] == 0.60
    assert resp["envelope_limits"]["max_floor_area_ratio_scalar"] == 0.70
    assert "5,000" in resp["envelope_limits"]["far_basis"]
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------

def test_data_freshness_aggregates_sources():
    from sandiego_mcp.tools import freshness as f

    def fake_fetch_one(_sql):
        return {"cnt": 100, "latest": date(2025, 5, 1)}

    with patch.object(f, "fetch_one", side_effect=fake_fetch_one):
        resp = f.data_freshness()
    assert resp["jurisdiction"].startswith("City of San Diego")
    assert len(resp["sources"]) >= 5
    assert all("freshness_sla" in s for s in resp["sources"])
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# overlays
# ---------------------------------------------------------------------------

def test_get_overlays_for_apn_requires_apn():
    from sandiego_mcp.tools.overlays import get_overlays_for_apn
    resp = get_overlays_for_apn("")
    assert "error" in resp
    assert _has_meta(resp)


def test_get_overlays_for_apn_not_found():
    from sandiego_mcp.tools import overlays as o
    with patch.object(o, "fetch_one", return_value=None):
        resp = o.get_overlays_for_apn("999-999-99-00")
    assert resp["found"] is False
    assert _has_meta(resp)


def test_get_overlays_for_apn_returns_sda_tpa_and_env():
    from sandiego_mcp.tools import overlays as o

    parcel_centroid = {"apn": "660-152-21-00", "lat": 32.7157, "lon": -117.1611}
    sda_rows = [{
        "feature_name": "Sustainable Development Area",
        "ordinance_ref": "O-21618",
        "source_url": "https://example/sda",
        "effective_date": date(2024, 1, 1),
    }]
    env_rows = [{
        "overlay_type": "cpioz",
        "overlay_name": "Mission Valley CPIOZ-A",
        "zone_code": "CPIOZ-A",
        "ordinance_number": "O-22222",
        "community_plan": "Mission Valley",
        "district_type": "CPIOZ-A",
        "hazard_level": None,
        "flood_zone": None, "flood_bfe": None, "flood_sfha": None,
        "fire_hazard_class": None, "fire_responsibility": None,
        "coastal_zone": None, "airport_name": None, "permit_jurisdiction": None,
        "source": "City of San Diego",
        "source_url": "https://example/cpioz",
        "effective_date": date(2023, 6, 1),
        "notes": None,
    }]
    tpa_row = {
        "stop_id": "MTS-555",
        "stop_name": "Hazard Center Trolley",
        "route_types": [0],
        "distance_m": 312.5,
        "source_url": "https://mts/gtfs",
    }

    # First fetch_one is the parcel centroid; second is the TPA query.
    # fetch_all is called twice: SDA then environmental overlays.
    with patch.object(o, "fetch_one", side_effect=[parcel_centroid, tpa_row]), \
         patch.object(o, "fetch_all", side_effect=[sda_rows, env_rows]):
        resp = o.get_overlays_for_apn("660-152-21-00")

    assert resp["found"] is True
    assert resp["apn"] == "660-152-21-00"
    assert resp["parcel_centroid"]["lat"] == 32.7157
    types = {o["type"] for o in resp["overlays"]}
    assert "SDA" in types
    assert "CPIOZ" in types
    assert "TPA" in types
    tpa = next(x for x in resp["overlays"] if x["type"] == "TPA")
    assert tpa["attributes"]["distance_m"] == 312.5
    assert "AB 2097" in tpa["citation"]["statute"]
    assert _has_meta(resp)
    assert resp["_meta"]["freshness_sla"] == "quarterly"


def test_get_overlays_for_point_validates_range():
    from sandiego_mcp.tools.overlays import get_overlays_for_point
    resp = get_overlays_for_point(999.0, 0.0)
    assert "error" in resp
    assert _has_meta(resp)


def test_get_overlays_for_point_rejects_non_numeric():
    from sandiego_mcp.tools.overlays import get_overlays_for_point
    resp = get_overlays_for_point("not-a-lat", "not-a-lon")  # type: ignore[arg-type]
    assert "error" in resp
    assert _has_meta(resp)


def test_get_overlays_for_point_empty_result_still_shaped():
    from sandiego_mcp.tools import overlays as o
    # SDA empty, env empty, no nearby major stop
    with patch.object(o, "fetch_one", return_value=None), \
         patch.object(o, "fetch_all", side_effect=[[], []]):
        resp = o.get_overlays_for_point(33.0, -117.0)
    assert resp["found"] is True
    assert resp["overlay_count"] == 0
    assert resp["overlays"] == []
    assert resp["point"] == {"lat": 33.0, "lon": -117.0}
    assert _has_meta(resp)


# ---------------------------------------------------------------------------
# rulings stub
# ---------------------------------------------------------------------------

def test_get_case_rulings_is_stub():
    from sandiego_mcp.tools.rulings import get_case_rulings
    resp = get_case_rulings("CEQA challenges in San Diego")
    assert resp["available"] is False
    assert resp["coverage"] == "pending"
    assert resp["planned_at"] == "2026-07-15"
    assert "pipeline" in resp
    assert _has_meta(resp)
