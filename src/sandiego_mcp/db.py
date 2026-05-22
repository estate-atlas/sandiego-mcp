"""Database access helpers.

Single Postgres connection pool used by all tool implementations.
Read-only DSN expected — the MCP never writes.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


def get_dsn() -> str:
    dsn = (
        os.getenv("SANDIEGO_MCP_DATABASE_URL")
        or os.getenv("VECTOR_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )
    if not dsn:
        raise RuntimeError(
            "Set SANDIEGO_MCP_DATABASE_URL (or DATABASE_URL) to a Postgres "
            "connection string pointing at the San Diego municipal data warehouse."
        )
    if dsn.startswith("postgresql+psycopg://"):
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
    return dsn


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Yield a Postgres connection. Caller manages cursor lifecycle."""
    conn = psycopg.connect(get_dsn(), row_factory=dict_row, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(sql: str, params: tuple | list | None = None) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def fetch_one(sql: str, params: tuple | list | None = None) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()
