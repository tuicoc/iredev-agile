# backend/src/server/data/connection.py
# =============================================================================
# PostgreSQL connection pool — single source of truth for DB access.
#
# All other modules do:
#   from ..data.connection import get_conn
#   with get_conn() as conn:
#       with conn.cursor() as cur:
#           cur.execute(...)
#
# Call init_db() once at app startup (done inside app.py) to run schema.sql
# idempotently — creates tables/indexes/seed data only if not already present.
#
# Environment variables (add to .env):
#   IREDEV_PG_CONNECTION  — full DSN, e.g.
#       postgresql://user:pass@localhost:5432/iredev
#   DB_MIN_CONN   — pool minimum (default 1)
#   DB_MAX_CONN   — pool maximum (default 10)
# =============================================================================

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

# ── Read config ───────────────────────────────────────────────────────────────
_DATABASE_URL = os.getenv("IREDEV_PG_CONNECTION")
_MIN_CONN = int(os.getenv("DB_MIN_CONN", "1"))
_MAX_CONN = int(os.getenv("DB_MAX_CONN", "10"))

# init_db.sql lives in the same directory as this file
_SCHEMA_PATH = Path(__file__).parent / "init_db.sql"

# ── Pool (initialised lazily on first use) ────────────────────────────────────
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not _DATABASE_URL:
            raise RuntimeError(
                "IREDEV_PG_CONNECTION environment variable is not set."
            )
        masked = _DATABASE_URL.split("@")[-1] if "@" in _DATABASE_URL else _DATABASE_URL
        log.info("[DB] Creating connection pool  dsn=%s", masked)
        dsn = _DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=_MIN_CONN,
            max_size=_MAX_CONN,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        log.info("[DB] Pool ready  min=%d  max=%d", _MIN_CONN, _MAX_CONN)
    return _pool


@contextmanager
def get_conn():
    """
    Yield a psycopg v3 connection from the pool.
    The connection is returned to the pool when the `with` block exits.
    Rolls back automatically on exception.

    Usage:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


def dict_cursor(conn):
    """
    Return a cursor that yields rows as plain dicts.

    psycopg v3: the row_factory is set at pool level (dict_row), so every
    cursor on pooled connections already returns dicts.  This helper is kept
    for API compatibility with callers that do `with dict_cursor(conn) as cur`.
    """
    return conn.cursor()


# =============================================================================
# init_db — called once at app startup
# =============================================================================

def init_db(schema_path: Path | str | None = None) -> None:
    """
    Run init_db.sql against the database.

    The SQL file is fully idempotent:
      • CREATE TABLE IF NOT EXISTS  — skips existing tables
      • CREATE INDEX IF NOT EXISTS  — skips existing indexes
      • INSERT … ON CONFLICT DO NOTHING — skips existing seed rows

    Safe to call every time the app starts; nothing is dropped or overwritten.

    Args:
        schema_path: override the default path to init_db.sql.
    """
    path = Path(schema_path) if schema_path else _SCHEMA_PATH

    if not path.exists():
        log.error(
            "[DB] init_db: schema file not found at %s — skipping.", path
        )
        return

    sql = path.read_text(encoding="utf-8")
    log.info("[DB] Running schema from %s …", path)

    with get_conn() as conn:
        conn.execute(sql)
        conn.commit()

    log.info("[DB] Schema applied successfully (tables / indexes / seed data up to date).")