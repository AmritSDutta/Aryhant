"""Standalone migration script to initialize Turso / libSQL schema and indexes for Aryhant."""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Ensure src is on sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from chat_agent.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("init_turso_db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    real_name TEXT NOT NULL,
    email TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('preference', 'fact', 'pattern', 'skill')),
    text TEXT NOT NULL,
    keywords TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL CHECK(source IN ('request', 'interest', 'wake', 'manual')),
    category TEXT,
    request_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_user_kind ON memories(user_id, kind);
CREATE INDEX IF NOT EXISTS idx_memories_user_weight ON memories(user_id, weight DESC, last_seen_at DESC);
"""


def get_db_connection() -> Any:
    """Obtain connection to Turso (libsql) or fallback to local SQLite."""
    url = settings.turso_database_url
    token = settings.turso_auth_token
    local_path = str(settings.resolved_turso_db_path)

    if url and (url.startswith("libsql://") or url.startswith("https://") or url.startswith("http://")):
        try:
            import libsql
        except ImportError as err:
            logger.error("ARYHANT_TURSO_DATABASE_URL is set (%s), but 'libsql' is not installed.", url)
            raise RuntimeError(
                "ARYHANT_TURSO_DATABASE_URL is set but 'libsql' package is not installed. "
                "Install it with `pip install libsql`."
            ) from err

        try:
            logger.info("Connecting to Turso remote database (%s) with replica (%s)...", url, local_path)
            conn = libsql.connect(local_path, sync_url=url, auth_token=token)
            try:
                conn.sync()
                logger.info("Turso remote sync completed successfully.")
            except Exception as sync_err:
                logger.warning("Turso sync warning (%s). Continuing with local replica.", sync_err)
            return conn
        except Exception as exc:
            logger.warning("Failed to connect to Turso remote (%s). Falling back to local sqlite3.", exc)

    logger.info("Using local SQLite database: %s", local_path)
    return sqlite3.connect(local_path)


def init_database() -> bool:
    """Execute DDL statements and verify table creation."""
    conn = get_db_connection()
    try:
        logger.info("Enabling foreign keys and executing schema migration...")
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        for statement in SCHEMA_SQL.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt)
        conn.commit()

        # Try to sync back to Turso if supported
        if hasattr(conn, "sync"):
            try:
                conn.sync()
            except Exception as sync_err:
                logger.warning("Post-migration Turso sync notice: %s", sync_err)

        # Verify tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('user_profiles', 'memories');")
        rows = cursor.fetchall()
        table_names = [r[0] for r in rows]
        logger.info("Migration successful. Verified active tables: %s", table_names)
        return len(table_names) == 2
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)
