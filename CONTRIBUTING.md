# Contributing

Thanks for considering a contribution. This is the official MCP server for the
City of San Diego municipal code, bulletins, permits, and parcel data.

## Quick start

```bash
git clone https://github.com/estate-atlas/sandiego-mcp
cd sandiego-mcp
uv venv --python 3.11
uv pip install -e ".[dev]"
uv run pytest
```

## Running locally

You need:
- A Postgres connection to a database with the SD-MCP schema (see
  `manifest.json` for required tables). Estate Atlas runs a hosted read-only
  endpoint — email `hello@estateatlas.ai` for beta access.
- A [Voyage AI](https://www.voyageai.com) API key for query embeddings.

Set:

```bash
export SANDIEGO_MCP_DATABASE_URL="postgresql://readonly@host/db"
export SANDIEGO_MCP_VOYAGE_API_KEY="pa-..."
.venv/bin/sandiego-municipal-code-mcp
```

## Issue reports

Open an issue with:

- What tool you called (e.g. `search_municipal_code`)
- The exact query / arguments
- Expected vs. actual response (paste the `_meta` block — it carries source,
  data_as_of, and citations)
- MCP client version (Claude Desktop / Cursor / etc.)

## Pull requests

- Small, focused PRs welcome.
- Tests required for new tool surfaces or changes to the `_meta` envelope.
- Don't break the `_meta` contract — every tool returns `source`,
  `data_as_of`, `freshness_sla`, `citations`, `license`.
- Multi-jurisdiction additions should follow the v0.3 roadmap shape (see
  README) — open an issue first to align before coding.

## Code style

- Python 3.10+
- Run `uv run pytest` before pushing.
- Format with the project's existing conventions.

## Security

If you find a security issue (e.g. a way to bypass the read-only role,
exfiltrate non-public data, or hit unbounded compute), please email
`hello@estateatlas.ai` rather than filing a public issue.
