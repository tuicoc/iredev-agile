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
#   DATABASE_URL  — full DSN, e.g.
#       postgresql://user:pass@localhost:5432/iredev
#   DB_MIN_CONN   — pool minimum (default 1)
#   DB_MAX_CONN   — pool maximum (default 10)
# =============================================================================

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)

# ── Read config ───────────────────────────────────────────────────────────────
_DATABASE_URL = os.getenv(
    "IREDEV_PG_CONNECTION",
    # "postgresql://postgres:postgres@localhost:5432/iredev",
)
_MIN_CONN = int(os.getenv("DB_MIN_CONN", "1"))
_MAX_CONN = int(os.getenv("DB_MAX_CONN", "10"))

# init_db.sql lives at the project root (two levels up from this file:
#   backend/src/server/data/connection.py → project root)
_SCHEMA_PATH = Path(__file__).parent / "init_db.sql"

# ── Pool (initialised lazily on first use) ────────────────────────────────────
_pool: pg_pool.ThreadedConnectionPool | None = None


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        log.info(_DATABASE_URL)
        log.info("[DB] Creating connection pool  dsn=%s", _DATABASE_URL.split("@")[-1])
        _pool = pg_pool.ThreadedConnectionPool(
            _MIN_CONN,
            _MAX_CONN,
            dsn=_DATABASE_URL,
        )
        log.info("[DB] Pool ready  min=%d  max=%d", _MIN_CONN, _MAX_CONN)
    return _pool


@contextmanager
def get_conn():
    """
    Yield a psycopg2 connection from the pool.
    The connection is returned to the pool when the `with` block exits.
    Rolls back automatically on exception.

    Usage:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    p    = _get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


def dict_cursor(conn):
    """Return a cursor that yields rows as plain dicts."""
    return conn.cursor(cursor_factory=RealDictCursor)


# =============================================================================
# init_db — called once at app startup
# =============================================================================

def init_db(schema_path: Path | str | None = None) -> None:
    """
    Run schema.sql against the database.

    The SQL file is fully idempotent:
      • CREATE TABLE IF NOT EXISTS  — skips existing tables
      • CREATE INDEX IF NOT EXISTS  — skips existing indexes
      • INSERT … ON CONFLICT DO NOTHING — skips existing seed rows

    Safe to call every time the app starts; nothing is dropped or overwritten.

    Args:
        schema_path: override the default path to schema.sql.
                     Defaults to <project_root>/schema.sql.
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
        with conn.cursor() as cur:
            cur.execute(sql)

    log.info("[DB] Schema applied successfully (tables / indexes / seed data up to date).")