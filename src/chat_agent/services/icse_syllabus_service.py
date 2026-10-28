"""ICSE Grade 5 subject-wise syllabus store backed by Turso/libSQL with local SQLite fallback."""
from __future__ import annotations

import difflib
import logging
import os
import sqlite3
import threading
import time
from typing import Any

from chat_agent.config import settings

logger = logging.getLogger(__name__)

SYLLABUS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS icse_syllabus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    term TEXT NOT NULL DEFAULT 'full_year',
    chapter TEXT NOT NULL,
    subtopics TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(subject, term, chapter)
);

CREATE INDEX IF NOT EXISTS idx_icse_syllabus_subject ON icse_syllabus(subject, term);
"""


class IcseSyllabusService:
    """Stores and queries the ICSE Grade 5 syllabus, one row per subject chapter."""

    def __init__(
        self,
        db_path: str | None = None,
        database_url: str | None = None,
        auth_token: str | None = None,
        sync_url: str | None = None,
    ) -> None:
        self.db_path: str = db_path if db_path is not None else str(settings.resolved_turso_db_path)
        raw_url = (
            database_url
            if database_url is not None
            else (
                sync_url
                if sync_url is not None
                else (os.getenv("ARYHANT_TURSO_DATABASE_URL") or settings.ARYHANT_TURSO_DATABASE_URL)
            )
        )
        url = (raw_url or "").strip().strip("'").strip('"')
        if url.startswith("turso://"):
            url = f"libsql://{url[len('turso://'):]}"
        elif url and not (url.startswith("libsql://") or url.startswith("https://") or url.startswith("http://")):
            url = f"libsql://{url}"
        self.database_url: str = url
        raw_token = (
            auth_token
            if auth_token is not None
            else (os.getenv("ARYHANT_TURSO_AUTH_TOKEN") or settings.ARYHANT_TURSO_AUTH_TOKEN)
        )
        self.auth_token: str = (raw_token or "").strip().strip("'").strip('"')
        self._write_lock = threading.Lock()
        logger.info(
            "IcseSyllabusService initialized: database_url=%s, db_path=%s",
            f"{self.database_url[:30]}..." if self.database_url else "NONE (local test SQLite)",
            self.db_path,
        )

    def _get_connection(self) -> Any:
        """Connect to remote Turso when configured, else local SQLite (tests / offline)."""
        if self.database_url:
            import libsql

            conn = libsql.connect(self.database_url, auth_token=self.auth_token, isolation_level=None)
            logger.info("Connected to remote Turso database for syllabus access.")
            return conn

        logger.info("Using local SQLite database for syllabus access: %s", self.db_path)
        return sqlite3.connect(self.db_path, isolation_level=None)

    def _ensure_table(self, cursor: Any) -> None:
        """Create the icse_syllabus table if it does not exist yet (idempotent)."""
        for statement in SYLLABUS_SCHEMA_SQL.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt)

    def upsert_syllabus_entries(self, entries: list[dict[str, Any]]) -> int:
        """Insert or update ICSE Grade 5 syllabus rows (subject-wise chapters)."""
        if not entries:
            return 0
        now_ms = int(time.time() * 1000)
        rows = [
            (
                str(e["subject"]).strip(),
                str(e.get("term", "full_year")).strip() or "full_year",
                str(e["chapter"]).strip(),
                (str(e["subtopics"]).strip() if e.get("subtopics") else None),
                now_ms,
                now_ms,
            )
            for e in entries
        ]
        rows = [r for r in rows if r[0] and r[2]]
        with self._write_lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("BEGIN IMMEDIATE;")
                self._ensure_table(cursor)
                cursor.executemany(
                    """
                    INSERT INTO icse_syllabus (subject, term, chapter, subtopics, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(subject, term, chapter) DO UPDATE SET
                        subtopics = excluded.subtopics,
                        updated_at = excluded.updated_at;
                    """,
                    rows,
                )
                conn.commit()
                logger.info("Upserted %d ICSE syllabus entries.", len(rows))
                return len(rows)
            except Exception as e:
                logger.warning("Error upserting ICSE syllabus entries: %s", e)
                try:
                    conn.rollback()
                except Exception as e_rb:
                    logger.warning("Rollback error during syllabus upsert: %s", e_rb)
                return 0
            finally:
                conn.close()

    def get_syllabus(self, subject: str | None = None) -> list[dict[str, Any]]:
        """Fetch syllabus rows, optionally filtered by subject (case-insensitive)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if subject:
                cursor.execute(
                    """
                    SELECT id, subject, term, chapter, subtopics
                    FROM icse_syllabus
                    WHERE LOWER(subject) = LOWER(?)
                    ORDER BY id;
                    """,
                    (subject,),
                )
            else:
                cursor.execute(
                    "SELECT id, subject, term, chapter, subtopics FROM icse_syllabus ORDER BY subject, id;"
                )
            return [
                {"id": r[0], "subject": r[1], "term": r[2], "chapter": r[3], "subtopics": r[4]}
                for r in cursor.fetchall()
            ]
        except Exception as e:
            logger.warning("Error fetching syllabus (subject=%s): %s", subject, e)
            return []
        finally:
            conn.close()

    def list_syllabus_subjects(self) -> list[str]:
        """Return the distinct subjects present in the ICSE syllabus table."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT subject FROM icse_syllabus ORDER BY subject;")
            return [r[0] for r in cursor.fetchall()]
        except Exception as e:
            logger.warning("Error listing syllabus subjects: %s", e)
            return []
        finally:
            conn.close()

    def get_syllabus_context(self, subject: str) -> str:
        """Format one subject's chapters and subtopics for prompt injection."""
        rows = self.get_syllabus(subject)
        if not rows:
            return ""
        lines = [f"ICSE Grade 5 {rows[0]['subject']} syllabus:"]
        for r in rows:
            line = f"- {r['chapter']}"
            if r["subtopics"]:
                line += f": {r['subtopics']}"
            lines.append(line)
        return "\n".join(lines)

    def resolve_subject(self, query: str) -> str:
        """
        Resolve a fuzzy subject query (e.g. 'math', 'social science', 'computer')
        to the stored subject name; empty string when nothing matches.
        """
        cleaned = (query or "").strip().lower()
        if not cleaned:
            return ""
        subjects = self.list_syllabus_subjects()
        lowered = {s.lower(): s for s in subjects}
        # 1. Exact (case-insensitive)
        if cleaned in lowered:
            return lowered[cleaned]
        # 2. Containment either way ('math' in 'mathematics', 'computer' in 'computer studies')
        for low, orig in lowered.items():
            if cleaned in low or low in cleaned:
                return orig
        # 3. Word overlap ('social science' shares 'social' with 'social studies')
        for low, orig in lowered.items():
            if set(cleaned.replace("-", " ").split()) & set(low.replace("-", " ").split()):
                return orig
        # 4. Typo tolerance ('matematics' -> 'mathematics')
        close = difflib.get_close_matches(cleaned, list(lowered), n=1, cutoff=0.6)
        return lowered[close[0]] if close else ""
