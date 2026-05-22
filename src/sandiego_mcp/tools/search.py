"""Semantic search across SDMC, bulletins, and ordinances."""
from __future__ import annotations

from typing import Any

from sandiego_mcp.db import fetch_all
from sandiego_mcp.embeddings import embed, vector_literal
from sandiego_mcp.meta import build_meta

VALID_DOC_TYPES = {"code", "bulletin", "ordinance", "manual", "policy", "ruling"}


def search_municipal_code(
    query: str,
    limit: int = 5,
    doc_types: list[str] | None = None,
    min_similarity: float = 0.3,
) -> dict[str, Any]:
    """Semantic search over SDMC, info bulletins, and ordinances.

    Args:
        query: Natural-language question or keywords.
        limit: Max chunks to return (1-25).
        doc_types: Optional filter on doc_type column.
        min_similarity: Cosine similarity threshold (0-1). Default 0.3 tuned for voyage-4-large; raise for stricter precision.
    """
    if not query or not query.strip():
        return {"results": [], "_meta": build_meta(notes="Empty query.")}

    limit = max(1, min(int(limit), 25))
    min_similarity = max(0.0, min(float(min_similarity), 1.0))

    doc_type_filter = ""
    params: list = []
    if doc_types:
        bad = [t for t in doc_types if t not in VALID_DOC_TYPES]
        if bad:
            return {
                "error": f"Unknown doc_types: {bad}. Allowed: {sorted(VALID_DOC_TYPES)}",
                "_meta": build_meta(),
            }
        doc_type_filter = "AND d.doc_type = ANY(%s)"
        params.append(doc_types)

    vec = vector_literal(embed(query))

    sql = f"""
        SELECT
            e.doc_id::text AS doc_id,
            e.chunk_id,
            e.chunk_md,
            e.section_number,
            d.title,
            d.doc_type,
            d.chapter,
            d.section,
            d.source_url,
            d.source_pdf_url,
            d.effective_date,
            d.revised_date,
            1 - (e.vector_v2 <=> %s::vector) AS similarity
        FROM embeddings e
        JOIN docs d ON e.doc_id = d.id
        WHERE e.vector_v2 IS NOT NULL
          AND (1 - (e.vector_v2 <=> %s::vector)) >= %s
          {doc_type_filter}
        ORDER BY e.vector_v2 <=> %s::vector
        LIMIT %s
    """
    rows = fetch_all(sql, [vec, vec, min_similarity, *params, vec, limit])

    results = []
    citations = []
    latest_revised = None
    for row in rows:
        result = {
            "section_number": row.get("section_number"),
            "title": row["title"],
            "doc_type": row["doc_type"],
            "chapter": row.get("chapter"),
            "section": row.get("section"),
            "chunk_md": row["chunk_md"],
            "similarity": round(float(row["similarity"]), 4),
            "source_url": row.get("source_url"),
            "source_pdf_url": row.get("source_pdf_url"),
            "effective_date": _isofmt(row.get("effective_date")),
            "revised_date": _isofmt(row.get("revised_date")),
        }
        results.append(result)
        if row.get("source_url") or row.get("source_pdf_url"):
            citations.append({
                "title": row["title"],
                "section": row.get("section_number"),
                "url": row.get("source_url"),
                "pdf_url": row.get("source_pdf_url"),
            })
        rev = row.get("revised_date") or row.get("effective_date")
        if rev and (latest_revised is None or rev > latest_revised):
            latest_revised = rev

    return {
        "query": query,
        "results": results,
        "_meta": build_meta(
            data_as_of=_isofmt(latest_revised),
            freshness_sla="monthly",
            citations=citations,
            notes=f"{len(results)} chunks returned. Lower min_similarity for broader recall.",
        ),
    }


def _isofmt(d) -> str | None:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)
