"""Direct code-section lookups + table of contents."""
from __future__ import annotations

import re
from typing import Any

from sandiego_mcp.db import fetch_all, fetch_one
from sandiego_mcp.meta import build_meta

_SECTION_RE = re.compile(r"^\d{2,3}\.\d{3,4}[A-Za-z]?$")


def get_code_section(section_number: str) -> dict[str, Any]:
    """Fetch the full text of a single SDMC section, plus diagrams + cross-refs."""
    if not section_number:
        return {"error": "section_number required", "_meta": build_meta()}

    section = section_number.strip()
    if not _SECTION_RE.match(section):
        # Soft-validate: allow but flag
        notes = (
            f"Section '{section}' does not match expected SDMC format "
            "(e.g. '142.0610'). Searching anyway."
        )
    else:
        notes = None

    chunks = fetch_all(
        """
        SELECT
            e.doc_id::text AS doc_id,
            e.chunk_id,
            e.chunk_md,
            e.section_number,
            e.parent_context,
            d.title,
            d.chapter,
            d.section,
            d.source_url,
            d.source_pdf_url,
            d.effective_date,
            d.revised_date
        FROM embeddings e
        JOIN docs d ON e.doc_id = d.id
        WHERE e.section_number = %s
        ORDER BY e.chunk_id
        """,
        (section,),
    )

    if not chunks:
        return {
            "section_number": section,
            "found": False,
            "_meta": build_meta(notes="Section not found. Try search_municipal_code instead."),
        }

    doc_id = chunks[0]["doc_id"]
    diagrams = fetch_all(
        """
        SELECT
            figure_label,
            image_url,
            page_number,
            extracted_text,
            structured_data
        FROM diagrams
        WHERE doc_id = %s
        ORDER BY page_number, image_index
        """,
        (doc_id,),
    )

    full_text = "\n\n".join(c["chunk_md"] for c in chunks)
    cross_refs = sorted(set(_find_cross_refs(full_text)))

    return {
        "section_number": section,
        "found": True,
        "title": chunks[0]["title"],
        "chapter": chunks[0]["chapter"],
        "section_label": chunks[0]["section"],
        "text_md": full_text,
        "chunks": [
            {
                "chunk_id": c["chunk_id"],
                "parent_context": c.get("parent_context"),
                "text_md": c["chunk_md"],
            }
            for c in chunks
        ],
        "diagrams": [
            {
                "figure_label": d.get("figure_label"),
                "image_url": d.get("image_url"),
                "page_number": d.get("page_number"),
                "pdf_anchor": (
                    f"{chunks[0].get('source_pdf_url')}#page={d.get('page_number')}"
                    if chunks[0].get("source_pdf_url") and d.get("page_number")
                    else None
                ),
                "extracted_text": d.get("extracted_text"),
                "structured_data": d.get("structured_data"),
            }
            for d in diagrams
        ],
        "cross_references": cross_refs,
        "source_url": chunks[0].get("source_url"),
        "source_pdf_url": chunks[0].get("source_pdf_url"),
        "_meta": build_meta(
            data_as_of=_isofmt(chunks[0].get("revised_date") or chunks[0].get("effective_date")),
            freshness_sla="monthly",
            citations=[{
                "title": chunks[0]["title"],
                "section": section,
                "url": chunks[0].get("source_url"),
                "pdf_url": chunks[0].get("source_pdf_url"),
            }],
            notes=notes,
        ),
    }


def get_table_of_contents(chapter: str | int | None = None) -> dict[str, Any]:
    """Return a hierarchical TOC of the municipal code.

    Args:
        chapter: Optional chapter filter (e.g. '14' or 14 for Land Development Code).
                 Accepts int or str — the column is text so we always cast to str.
    """
    # Normalise: MCP callers may pass an integer (e.g. chapter=14).
    # docs.chapter is TEXT; psycopg3 would raise "operator does not exist: text = smallint"
    # if we pass an int directly, causing empty results for all numeric chapters.
    chapter_str: str | None = str(chapter).strip() if chapter is not None else None

    sql = """
        SELECT DISTINCT chapter, section, title, source_url, effective_date
        FROM docs
        WHERE doc_type = 'code'
          AND chapter IS NOT NULL
          {chapter_filter}
        ORDER BY chapter, section, title
    """
    params: tuple = ()
    if chapter_str:
        sql = sql.format(chapter_filter="AND chapter = %s")
        params = (chapter_str,)
    else:
        sql = sql.format(chapter_filter="")

    rows = fetch_all(sql, params)

    # Group by chapter
    toc: dict[str, list[dict]] = {}
    for row in rows:
        ch = row["chapter"] or "unknown"
        toc.setdefault(ch, []).append({
            "section": row.get("section"),
            "title": row["title"],
            "source_url": row.get("source_url"),
        })

    # Sort numerically where possible ('1','2',...,'14') so chapter ordering
    # is intuitive rather than lexicographic ('1','10','11',...,'2').
    def _chapter_sort_key(ch: str):
        try:
            return (0, int(ch), ch)
        except (ValueError, TypeError):
            return (1, 0, ch)

    return {
        "chapter_filter": chapter_str,
        "chapter_count": len(toc),
        "chapters": [
            {"chapter": ch, "entries": entries}
            for ch, entries in sorted(toc.items(), key=lambda kv: _chapter_sort_key(kv[0]))
        ],
        "_meta": build_meta(freshness_sla="monthly"),
    }


_CROSS_REF_PATTERN = re.compile(r"§?\s*(\d{2,3}\.\d{3,4}[A-Za-z]?)")


def _find_cross_refs(text: str) -> list[str]:
    return _CROSS_REF_PATTERN.findall(text or "")


def _isofmt(d) -> str | None:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)
