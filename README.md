# Estate Atlas: SD-MCP

The first and only **Model Context Protocol server** for the San Diego Municipal Code — built so any AI agent (Claude, Cursor, custom) can query SD's regulatory data with citations, freshness guarantees, and machine-readable structure that no government source publishes.

> **Status:** v0.1 — pilot. Read-only. STDIO transport.
> Maintained by [Estate Atlas](https://estateatlas.ai). Powered by the same fresh data pipelines used by our property-intelligence product.
> Embeddings: [Voyage AI](https://www.voyageai.com) `voyage-4-large` — Anthropic's embedding partner.

---

## What you can ask it

```text
> "What are the fence height rules for an RS-1-7 lot?"
> "Show me all the active permits on APN 535-095-05-00."
> "What's the rear setback for RM-1-1?"
> "Find bulletins about ADUs."
> "When was the municipal code last updated?"
```

## Tools

| Tool | Purpose |
|------|---------|
| `search_municipal_code` | Semantic search across SDMC, bulletins, ordinances |
| `get_code_section` | Fetch a specific section by number (e.g. `142.0610`) |
| `get_table_of_contents` | Browse the code structure |
| `list_bulletins` | Discover DSD information bulletins |
| `get_bulletin` | Fetch a specific IB by number |
| `lookup_parcel` | Address or APN → zoning, overlays, lot, assessor |
| `get_permits_for_parcel` | Permit history for a parcel |
| `get_violations_for_parcel` | Code-enforcement cases for a parcel |
| `get_setbacks_for_zone` | Setbacks, FAR, height limits by zone code |
| `get_zone_info` | Higher-level zone summary |
| `data_freshness` | Per-source last-update + SLA cadence |
| `get_case_rulings` | (Stub — v2) Court rulings affecting SD land use |

**Every response includes a `_meta` envelope with `source`, `data_as_of`, `freshness_sla`, `citations` (with PDF page anchors where available), and `license`.** This is the differentiator — no government source publishes machine-readable freshness or citations.

---

## Install

### Claude Desktop

Edit your Claude Desktop config at `~/Library/Application Support/Claude/claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "sandiego-municipal-code": {
      "command": "uvx",
      "args": ["sandiego-municipal-code-mcp"],
      "env": {
        "SANDIEGO_MCP_DATABASE_URL": "postgresql://readonly@db.estateatlas.ai/sandiego_public",
        "SANDIEGO_MCP_VOYAGE_API_KEY": "pa-..."
      }
    }
  }
}
```

Restart Claude Desktop. You should see "sandiego-municipal-code" in the MCP indicator.

### Claude Code

In `~/.claude/settings.json` or a project `.mcp.json`:

```jsonc
{
  "mcpServers": {
    "sandiego-municipal-code": {
      "command": "uvx",
      "args": ["sandiego-municipal-code-mcp"],
      "env": {
        "SANDIEGO_MCP_DATABASE_URL": "postgresql://...",
        "SANDIEGO_MCP_VOYAGE_API_KEY": "pa-..."
      }
    }
  }
}
```

### Cursor / Continue / Other MCP-aware tools

Use the same JSON above; check your editor's MCP docs for the config path.

### From source (development)

```bash
git clone https://github.com/estate-atlas/sandiego-mcp
cd sandiego-mcp
uv venv --python 3.11
uv pip install -e ".[dev]"
.venv/bin/sandiego-municipal-code-mcp  # runs server over STDIO
```

---

## Environment variables

| Var | Required | Default | Purpose |
|-----|----------|---------|---------|
| `SANDIEGO_MCP_DATABASE_URL` | yes | — | Postgres connection string (read-only role). Falls back to `DATABASE_URL`. |
| `SANDIEGO_MCP_VOYAGE_API_KEY` | yes | — | Voyage AI key for query embeddings (`voyage-4-large`). Falls back to `VOYAGE_API_KEY`. Get one free at [voyageai.com](https://www.voyageai.com). |
| `SANDIEGO_MCP_EMBEDDING_MODEL` | no | `voyage-4-large` | Override the embedding model (must match the model the DB was re-indexed with). |
| `SANDIEGO_MCP_EMBEDDING_DIM` | no | `1024` | Override the embedding dimension. |
| `SANDIEGO_MCP_LOG_LEVEL` | no | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. Logs go to stderr (stdout is the MCP transport). |

---

## Public read-only database (coming soon)

The hosted endpoint `db.estateatlas.ai/sandiego_public` will provide free, rate-limited access to all the data this MCP server exposes. Until that ships, you can:

1. Run your own Supabase replica with the schemas under `david/backend/db/`
2. Email `hello@estateatlas.ai` for a private beta credential

---

## Data sources + refresh cadence

| Source | Records | Refresh |
|--------|---------|---------|
| San Diego Municipal Code | 1,966 docs / 27k chunks | Monthly |
| Information Bulletins | 456 docs | Monthly |
| Building Permits | 240k | Weekly (Accela API) |
| Code Enforcement | 17.4k | Weekly |
| Parcels | 1.09M | Quarterly |
| Zoning Parcels | varies | Quarterly |
| Zone Setbacks | 21 zones | On ordinance change |

Refresh is automated via GitHub Actions in the upstream Estate Atlas data repo. The MCP server source code lives at [estate-atlas/sandiego-mcp](https://github.com/estate-atlas/sandiego-mcp).

---

## Roadmap

- **v0.1** (now) — STDIO transport, 11 tools, read-only, BYO DB credentials
- **v0.2** — Public read-only hosted endpoint (free tier + rate limit)
- **v0.3** — Court rulings ingestion (CourtListener integration)
- **v1.0** — Hosted HTTP/SSE transport, bearer-token auth, billing tiers
- **v1.x** — San Diego County → other CA cities → other states

---

## License

MIT. Municipal data is public-domain (City of San Diego). The MCP envelope, citations layer, and freshness SLA are © Estate Atlas.

## Citing

If your agent's output is consumed for any regulatory or legal decision, the `_meta.citations[]` field gives you the verifiable source. We recommend always surfacing `source_pdf_url` to the human consumer.
