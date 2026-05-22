"""Information bulletin lookups (DSD procedural guides).

Bulletins live in the `docs` table with doc_type='bulletin'. Two title
formats exist in the wild:

    "IB-120 \"Project Inspections\""
    "INFORMATION BULLETIN115"

The `information_bulletins` table was spec'd but never populated.

Bulletins are also duplicated in the `docs` table (multiple rows per
bulletin), so every query DISTINCTs on extracted IB number.
"""
from __future__ import annotations

import re
from typing import Any

from sandiego_mcp.db import fetch_all, fetch_one
from sandiego_mcp.meta import build_meta

# Match: "IB-120 ..." | "INFORMATION BULLETIN 120" | "INFORMATION BULLETIN120"
_IB_NUM_RE = re.compile(
    r"(?:IB[-\s]*|INFORMATION\s*BULLETIN\s*)0*(\d+)", re.IGNORECASE
)


def list_bulletins(project_type: str | None = None, limit: int = 20) -> dict[str, Any]:
    """List information bulletins, optionally filtered by topic keyword.

    Args:
        project_type: Optional keyword filter — matches title OR full
            bulletin text (e.g. 'ADU', 'fence', 'pool').
        limit: Max bulletins to return after de-duplication (1-200).
    """
    limit = max(1, min(int(limit), 200))

    if project_type:
        # Match on title OR full text content
        rows = fetch_all(
            """
            SELECT DISTINCT ON (extracted_num)
                REGEXP_REPLACE(title, '^.*?(\\d+).*$', '\\1') AS extracted_num,
                title, source_pdf_url, source_url, effective_date, revised_date,
                updated_at, topic
            FROM docs
            WHERE doc_type = 'bulletin'
              AND (
                title ILIKE %s
                OR text_md ILIKE %s
                OR %s = ANY(topic)
              )
            ORDER BY extracted_num, updated_at DESC
            LIMIT %s
            """,
            (f"%{project_type}%", f"%{project_type}%", project_type, limit),
        )
    else:
        rows = fetch_all(
            """
            SELECT DISTINCT ON (extracted_num)
                REGEXP_REPLACE(title, '^.*?(\\d+).*$', '\\1') AS extracted_num,
                title, source_pdf_url, source_url, effective_date, revised_date,
                updated_at, topic
            FROM docs
            WHERE doc_type = 'bulletin'
            ORDER BY extracted_num, updated_at DESC
            LIMIT %s
            """,
            (limit,),
        )

    return {
        "project_type_filter": project_type,
        "count": len(rows),
        "bulletins": [_shape(r) for r in rows],
        "_meta": build_meta(freshness_sla="monthly"),
    }


def get_bulletin(ib_number: str) -> dict[str, Any]:
    """Fetch a single information bulletin by IB number.

    Accepts '120', 'IB-120', 'IB 120', 'INFORMATION BULLETIN 120'.
    """
    if not ib_number:
        return {"error": "ib_number required", "_meta": build_meta()}

    digits_match = re.search(r"\d+", ib_number)
    if not digits_match:
        return {
            "error": f"Could not parse IB number from '{ib_number}'",
            "_meta": build_meta(),
        }
    num = digits_match.group(0)
    num_padded = num.zfill(3)

    row = fetch_one(
        """
        SELECT id::text AS doc_id, title, text_md, source_pdf_url, source_url,
               effective_date, revised_date, updated_at, topic, chapter, section
        FROM docs
        WHERE doc_type = 'bulletin'
          AND (
            title ILIKE %s
            OR title ILIKE %s
            OR title ILIKE %s
          )
        ORDER BY LENGTH(COALESCE(text_md, '')) DESC NULLS LAST
        LIMIT 1
        """,
        (
            f"IB-{num}%",
            f"IB-{num_padded}%",
            f"%BULLETIN{num}%",
        ),
    )

    if not row:
        return {
            "ib_number": f"IB-{num}",
            "found": False,
            "_meta": build_meta(notes="Bulletin not found. Try list_bulletins to discover IB numbers."),
        }

    return {
        "ib_number": f"IB-{num}",
        "found": True,
        "title": row["title"],
        "topic": row.get("topic") or [],
        "chapter": row.get("chapter"),
        "section": row.get("section"),
        "text_md": row.get("text_md"),
        "pdf_url": row.get("source_pdf_url"),
        "source_url": row.get("source_url"),
        "effective_date": _isofmt(row.get("effective_date")),
        "revised_date": _isofmt(row.get("revised_date")),
        "_meta": build_meta(
            data_as_of=_isofmt(
                row.get("revised_date") or row.get("effective_date") or row.get("updated_at")
            ),
            freshness_sla="monthly",
            citations=[{
                "title": row["title"],
                "ib_number": f"IB-{num}",
                "pdf_url": row.get("source_pdf_url"),
                "url": row.get("source_url"),
            }],
        ),
    }


def _shape(r: dict) -> dict:
    title = r.get("title") or ""
    m = _IB_NUM_RE.search(title)
    ib_num = f"IB-{m.group(1)}" if m else None
    return {
        "ib_number": ib_num,
        "title": title,
        "topic": r.get("topic") or [],
        "pdf_url": r.get("source_pdf_url"),
        "source_url": r.get("source_url"),
        "effective_date": _isofmt(r.get("effective_date")),
        "revised_date": _isofmt(r.get("revised_date")),
        "updated_at": _isofmt(r.get("updated_at")),
    }


def _isofmt(d) -> str | None:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)
