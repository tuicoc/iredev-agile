# backend/src/server/data/database.py
# =============================================================================
# Database layer — PostgreSQL implementation.
#
# Public API is identical to the previous in-memory mock so every caller
# (auth routes, chat routes, ws_handler, etc.) works without changes.
#
# Tables used:
#   users    — accounts
#   projects — project folders
#   chats    — conversation sessions (optionally inside a project)
#   messages — individual messages, with optional JSONB artifact column
#
# Helper conventions
# ──────────────────
#   _row(row)   — convert a RealDictRow to a plain dict (or None-safe)
#   _now()      — UTC ISO timestamp string (kept for API response compat)
#   _hash(pw)   — SHA-256 hex digest, identical to the original mock
# =============================================================================

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .connection import dict_cursor, get_conn

log = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row) -> dict | None:
    """Convert a RealDictRow (or None) to a plain dict."""
    return dict(row) if row is not None else None


def _fmt(row: dict | None) -> dict | None:
    """
    Normalise a DB row for API consumers:
      - created_at / updated_at → camelCase strings
      - snake_case → camelCase for foreign keys
    """
    if row is None:
        return None
    out = {}
    for k, v in row.items():
        # Timestamp columns → ISO string
        if isinstance(v, datetime):
            v = v.isoformat()

        # snake_case → camelCase mapping for keys the frontend expects
        camel = {
            "user_id":     "userId",
            "project_id":  "projectId",
            "chat_id":     "chatId",
            "sub_chat_id": "subChatId",
            "created_at":  "createdAt",
            "updated_at":  "updatedAt",
        }.get(k, k)

        out[camel] = v
    return out


# =============================================================================
# USERS
# =============================================================================

def find_user_by_email(email: str) -> dict | None:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                "SELECT * FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                (email,),
            )
            return _row(cur.fetchone())


def find_user_by_id(uid: str) -> dict | None:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s LIMIT 1", (uid,))
            return _row(cur.fetchone())


def create_user(name: str, email: str, password: str) -> dict:
    if find_user_by_email(email):
        raise ValueError("Email already registered.")
    uid = _new_id()
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO users (id, name, email, password, plan)
                VALUES (%s, %s, %s, %s, 'free')
                RETURNING *
                """,
                (uid, name.strip(), email.strip().lower(), _hash(password)),
            )
            return _row(cur.fetchone())


def check_password(user: dict, plain: str) -> bool:
    return user.get("password") == _hash(plain)


def safe_user(user: dict) -> dict:
    """Return user dict without the password field."""
    return {k: v for k, v in user.items() if k != "password"}


# =============================================================================
# PROJECTS
# =============================================================================

def get_projects_for_user(user_id: str) -> list[dict]:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                SELECT * FROM projects
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return [_fmt(_row(r)) for r in cur.fetchall()]


def get_project(project_id: str) -> dict | None:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("SELECT * FROM projects WHERE id = %s LIMIT 1", (project_id,))
            return _fmt(_row(cur.fetchone()))


def create_project(user_id: str, name: str, description: str = "") -> dict:
    pid = _new_id()
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO projects (id, user_id, name, description)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (pid, user_id, name.strip(), description.strip()),
            )
            return _fmt(_row(cur.fetchone()))


def update_project(
    project_id: str,
    name: str | None = None,
    description: str | None = None,
) -> dict | None:
    # Build SET clause dynamically
    sets, vals = [], []
    if name is not None:
        sets.append("name = %s")
        vals.append(name.strip())
    if description is not None:
        sets.append("description = %s")
        vals.append(description.strip())
    if not sets:
        return get_project(project_id)

    sets.append("updated_at = NOW()")
    vals.append(project_id)

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id = %s RETURNING *",
                vals,
            )
            return _fmt(_row(cur.fetchone()))


def delete_project(project_id: str) -> bool:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                "DELETE FROM projects WHERE id = %s RETURNING id",
                (project_id,),
            )
            return cur.fetchone() is not None


# =============================================================================
# CHATS
# =============================================================================

def get_chats_for_user(user_id: str) -> list[dict]:
    """Return top-level chats (no project) for a user, newest first."""
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                SELECT * FROM chats
                WHERE user_id = %s AND project_id IS NULL
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            return [_fmt(_row(r)) for r in cur.fetchall()]


def get_chats_for_project(project_id: str) -> list[dict]:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                SELECT * FROM chats
                WHERE project_id = %s
                ORDER BY created_at DESC
                """,
                (project_id,),
            )
            return [_fmt(_row(r)) for r in cur.fetchall()]


def get_chat(chat_id: str) -> dict | None:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute("SELECT * FROM chats WHERE id = %s LIMIT 1", (chat_id,))
            return _fmt(_row(cur.fetchone()))


def create_chat(
    user_id: str,
    title: str,
    project_id: str | None = None,
) -> dict:
    cid = _new_id()
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO chats (id, user_id, project_id, title)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (cid, user_id, project_id or None, title or "New conversation"),
            )
            row = _fmt(_row(cur.fetchone()))

    # Touch project updatedAt
    if project_id:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE projects SET updated_at = NOW() WHERE id = %s",
                    (project_id,),
                )
    return row


def delete_chat(chat_id: str) -> bool:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                "DELETE FROM chats WHERE id = %s RETURNING id",
                (chat_id,),
            )
            return cur.fetchone() is not None


# =============================================================================
# MESSAGES
# =============================================================================

def get_messages(chat_id: str, sub_chat_id: Any) -> list[dict]:
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                SELECT * FROM messages
                WHERE chat_id = %s AND sub_chat_id = %s
                ORDER BY created_at ASC
                """,
                (chat_id, int(sub_chat_id)),
            )
            return [_fmt(_row(r)) for r in cur.fetchall()]


def add_message(
    chat_id: str,
    role: str,
    content: str,
    artifact: dict | None = None,
    messID: str | None = None,
    subChatID: int = 0,
) -> dict:
    import json as _json

    mid = messID or _new_id()
    artifact_json = _json.dumps(artifact) if artifact else None

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                INSERT INTO messages (id, chat_id, sub_chat_id, role, content, artifact)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING *
                """,
                (mid, chat_id, int(subChatID) if subChatID not in (None, "null", "") else 0, role, content, artifact_json),
            )
            row = _fmt(_row(cur.fetchone()))

    # Touch chat & project timestamps
    _touch_chat(chat_id)
    return row


def update_message_artifact(message_id: str, artifact: dict) -> bool:
    """Update the artifact JSONB on an existing message (accept / reject flow)."""
    import json as _json

    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                UPDATE messages
                SET artifact = %s::jsonb
                WHERE id = %s
                RETURNING id
                """,
                (_json.dumps(artifact), message_id),
            )
            return cur.fetchone() is not None


# =============================================================================
# Internal helpers
# =============================================================================

def _touch_chat(chat_id: str) -> None:
    """Update chat.updated_at and propagate to project."""
    with get_conn() as conn:
        with dict_cursor(conn) as cur:
            cur.execute(
                """
                UPDATE chats SET updated_at = NOW()
                WHERE id = %s
                RETURNING project_id
                """,
                (chat_id,),
            )
            row = cur.fetchone()
            if row and row["project_id"]:
                cur.execute(
                    "UPDATE projects SET updated_at = NOW() WHERE id = %s",
                    (row["project_id"],),
                )