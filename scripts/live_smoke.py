"""Live smoke test: hits the real Supabase DB and Voyage AI (embeddings).

Reads <estate-atlas-municipal>/.env, exercises each tool,
prints a short summary. Run from the mcp-server/ directory:

    .venv/bin/python scripts/live_smoke.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load the david repo .env (parent of mcp-server/)
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sandiego_mcp.tools.bulletins import get_bulletin, list_bulletins  # noqa: E402
from sandiego_mcp.tools.code import get_code_section, get_table_of_contents  # noqa: E402
from sandiego_mcp.tools.freshness import data_freshness  # noqa: E402
from sandiego_mcp.tools.parcels import (  # noqa: E402
    get_permits_for_parcel,
    get_violations_for_parcel,
    lookup_parcel,
)
from sandiego_mcp.tools.rulings import get_case_rulings  # noqa: E402
from sandiego_mcp.tools.search import search_municipal_code  # noqa: E402
from sandiego_mcp.tools.zoning import get_setbacks_for_zone, get_zone_info  # noqa: E402


def step(name: str, fn, *args, **kwargs) -> None:
    print(f"\n── {name} ──")
    try:
        result = fn(*args, **kwargs)
        summary = _summarize(result)
        print(json.dumps(summary, indent=2, default=str)[:1200])
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ {type(exc).__name__}: {exc}")


def _summarize(result: dict) -> dict:
    """Shrink a tool response down to its shape — full payloads are huge."""
    keys_to_show = {
        "results", "found", "section_number", "title", "ib_number",
        "apn", "address", "zoning", "assessor", "count", "bulletins",
        "permits", "violations", "zone_code", "zone_name", "setbacks_ft",
        "envelope_limits", "jurisdiction", "sources", "status",
        "chapters", "chapter_count", "error",
    }
    out = {}
    for k, v in result.items():
        if k not in keys_to_show:
            continue
        if isinstance(v, list) and v:
            out[f"{k}_count"] = len(v)
            out[f"{k}_first"] = v[0] if len(str(v[0])) < 400 else f"<{type(v[0]).__name__}>"
        elif isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        else:
            out[k] = v
    if "_meta" in result and isinstance(result["_meta"], dict):
        meta = result["_meta"]
        out["_meta"] = {
            "data_as_of": meta.get("data_as_of"),
            "freshness_sla": meta.get("freshness_sla"),
            "citations_count": len(meta.get("citations") or []),
            "notes": meta.get("notes"),
        }
    return out


def main() -> int:
    print("=" * 60)
    print("San Diego Municipal Code MCP — LIVE SMOKE TEST")
    print("=" * 60)

    step("1. data_freshness", data_freshness)
    step("2. get_table_of_contents (chapter=14)", get_table_of_contents, chapter="14")
    step("3. search_municipal_code('fence height')", search_municipal_code, "fence height residential", limit=3)
    step("4. get_code_section (pick a real section)", get_code_section, "142.0310")
    step("5. list_bulletins (project_type=ADU)", list_bulletins, project_type="ADU", limit=5)
    step("6. get_bulletin (IB-120)", get_bulletin, "120")
    step("7. lookup_parcel (by address)", lookup_parcel, address="600 5th Ave")
    step("8. lookup_parcel (no input → error case)", lookup_parcel)
    step("9. get_setbacks_for_zone (RS-1-7)", get_setbacks_for_zone, "RS-1-7")
    step("10. get_zone_info (RM-1-1)", get_zone_info, "RM-1-1")
    step("11. get_case_rulings (stub)", get_case_rulings, "CEQA")

    print("\n" + "=" * 60)
    print("LIVE SMOKE TEST COMPLETE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
