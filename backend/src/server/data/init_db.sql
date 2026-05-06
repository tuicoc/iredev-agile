-- =============================================================================
-- iReDev / CARA — PostgreSQL Schema  (idempotent)
-- =============================================================================
-- Safe to run multiple times:
--   • Tables / indexes are created only if they do not exist yet.
--   • Seed rows are inserted only if the email is not already present.
--   • No DROP statements — existing data is never touched.
-- =============================================================================

-- ── Extensions ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- =============================================================================
-- users
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id          TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name        TEXT        NOT NULL,
    email       TEXT        NOT NULL UNIQUE,
    password    TEXT        NOT NULL,   -- SHA-256 hex digest
    plan        TEXT        NOT NULL DEFAULT 'free',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

-- =============================================================================
-- projects
-- =============================================================================
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id     TEXT        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects (user_id);

-- =============================================================================
-- chats
-- =============================================================================
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id     TEXT        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id  TEXT        REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT        NOT NULL DEFAULT 'New conversation',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chats_user_id    ON chats (user_id);
CREATE INDEX IF NOT EXISTS idx_chats_project_id ON chats (project_id);

-- =============================================================================
-- messages
-- =============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id           TEXT        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chat_id      TEXT        NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    sub_chat_id  INTEGER     NOT NULL DEFAULT 0,
    role         TEXT        NOT NULL CHECK (role IN ('user', 'assistant', 'interviewer', 'enduser')),
    content      TEXT        NOT NULL DEFAULT '',
    artifact     JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id     ON messages (chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_sub_chat_id ON messages (chat_id, sub_chat_id);

-- =============================================================================
-- Seed demo users — inserted only once (ON CONFLICT DO NOTHING)
-- demo@example.com  / password123
-- admin@example.com / admin123
-- =============================================================================
INSERT INTO users (id, name, email, password, plan) VALUES
    ('u001', 'Demo User', 'demo@example.com',
     encode(digest('password123', 'sha256'), 'hex'), 'free'),
    ('u002', 'Admin',     'admin@example.com',
     encode(digest('admin123',    'sha256'), 'hex'), 'pro')
ON CONFLICT (email) DO NOTHING;