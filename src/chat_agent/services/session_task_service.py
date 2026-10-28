"""Service for recording session and task execution telemetry in Turso / libSQL."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from chat_agent.config import settings

logger = logging.getLogger(__name__)

_service_singleton: SessionTaskService | None = None
_service_lock = threading.Lock()


class SessionTaskService:
    """Manages persistent execution telemetry and retention in Turso / libSQL."""

    def __init__(
        self,
        db_path: str | None = None,
        sync_url: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        raw_path = db_path if db_path is not None else settings.resolved_turso_db_path
        self.db_path: str = str(Path(raw_path).resolve())
        raw_url = (
            sync_url
            if sync_url is not None
            else (os.getenv("ARYHANT_TURSO_DATABASE_URL") or settings.ARYHANT_TURSO_DATABASE_URL)
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
        self._lock = threading.Lock()

    def _get_connection(self) -> Any:
        """Connect to remote Turso database via libsql or local SQLite for tests."""
        if self.database_url:
            try:
                import libsql
                conn = libsql.connect(
                    self.database_url,
                    auth_token=self.auth_token,
                    isolation_level=None,
                )
                return conn
            except Exception as e:
                logger.error("Remote Turso connection failed (%s), falling back to local SQLite: %s", e, self.db_path)

        conn = sqlite3.connect(self.db_path, isolation_level=None)
        return conn

    def create_task(
        self,
        session_id: str,
        user_id: str | None,
        task_type: str,
        provider: str | None = None,
        task_id: str | None = None,
        status: str = "created",
    ) -> str:
        """Insert initial task record at start of execution."""
        tid = task_id or f"task_{uuid.uuid4().hex[:12]}"
        now_ms = int(time.time() * 1000)
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO session_tasks (
                        id, session_id, user_id, task_type, provider, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (tid, session_id, user_id or "unknown", task_type, provider or "unknown", status, now_ms),
                )
                if hasattr(conn, "commit"):
                    conn.commit()
            except Exception as exc:
                logger.warning("Failed to insert session_task %s: %s", tid, exc)
            finally:
                if conn is not None:
                    conn.close()
        return tid

    async def acreate_task(
        self,
        session_id: str,
        user_id: str | None,
        task_type: str,
        provider: str | None = None,
        task_id: str | None = None,
        status: str = "created",
    ) -> str:
        """Asynchronously insert initial task record."""
        return await asyncio.to_thread(
            self.create_task,
            session_id=session_id,
            user_id=user_id,
            task_type=task_type,
            provider=provider,
            task_id=task_id,
            status=status,
        )

    def complete_task(
        self,
        task_id: str,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: int = 0,
        model_name: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update existing task record with completion status and token metrics."""
        now_ms = int(time.time() * 1000)
        tot = total_tokens if total_tokens > 0 else (prompt_tokens + completion_tokens)
        meta_json = json.dumps(metadata) if metadata else None

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE session_tasks SET
                        status = ?,
                        prompt_tokens = ?,
                        completion_tokens = ?,
                        total_tokens = ?,
                        duration_ms = ?,
                        model_name = COALESCE(?, model_name),
                        error_message = ?,
                        metadata = ?,
                        completed_at = ?
                    WHERE id = ?;
                    """,
                    (
                        status,
                        prompt_tokens,
                        completion_tokens,
                        tot,
                        duration_ms,
                        model_name,
                        error_message,
                        meta_json,
                        now_ms,
                        task_id,
                    ),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        INSERT INTO session_tasks (
                            id, session_id, user_id, task_type, provider, status,
                            model_name, prompt_tokens, completion_tokens, total_tokens,
                            duration_ms, error_message, metadata, created_at, completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            task_id,
                            task_id,
                            "unknown",
                            "task",
                            getattr(settings, "MODEL_PROVIDER", "nebius"),
                            status,
                            model_name,
                            prompt_tokens,
                            completion_tokens,
                            tot,
                            duration_ms,
                            error_message,
                            meta_json,
                            now_ms - duration_ms,
                            now_ms,
                        ),
                    )
                if hasattr(conn, "commit"):
                    conn.commit()
                return True
            except Exception as exc:
                logger.warning("Failed to complete session_task %s: %s", task_id, exc)
                return False
            finally:
                if conn is not None:
                    conn.close()

    async def acomplete_task(
        self,
        task_id: str,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: int = 0,
        model_name: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Asynchronously update task record upon completion."""
        return await asyncio.to_thread(
            self.complete_task,
            task_id=task_id,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            model_name=model_name,
            error_message=error_message,
            metadata=metadata,
        )

    def get_table_metrics(self, days: int = 15) -> dict[str, Any]:
        """Aggregate task volume, status breakdown, and token usage for the given day window."""
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        COUNT(*),
                        COALESCE(SUM(prompt_tokens), 0),
                        COALESCE(SUM(completion_tokens), 0),
                        COALESCE(SUM(total_tokens), 0),
                        COALESCE(AVG(duration_ms), 0)
                    FROM session_tasks
                    WHERE created_at >= ?;
                    """,
                    (cutoff_ms,),
                )
                row = cursor.fetchone() or (0, 0, 0, 0, 0)
                total_tasks, prompt_sum, comp_sum, tot_sum, avg_dur = row

                cursor.execute(
                    "SELECT status, COUNT(*) FROM session_tasks WHERE created_at >= ? GROUP BY status;",
                    (cutoff_ms,),
                )
                status_counts = dict(cursor.fetchall())

                cursor.execute(
                    "SELECT task_type, COUNT(*) FROM session_tasks WHERE created_at >= ? GROUP BY task_type;",
                    (cutoff_ms,),
                )
                type_counts = dict(cursor.fetchall())

                failures = status_counts.get("failed", 0)

                return {
                    "days": days,
                    "total_tasks": total_tasks,
                    "status_breakdown": status_counts,
                    "task_type_breakdown": type_counts,
                    "prompt_tokens_sum": int(prompt_sum),
                    "completion_tokens_sum": int(comp_sum),
                    "total_tokens_sum": int(tot_sum),
                    "avg_duration_ms": round(float(avg_dur), 2),
                    "failure_count": failures,
                }
            except Exception as exc:
                logger.warning("Failed to compute table metrics: %s", exc)
                return {
                    "days": days,
                    "total_tasks": 0,
                    "status_breakdown": {},
                    "task_type_breakdown": {},
                    "prompt_tokens_sum": 0,
                    "completion_tokens_sum": 0,
                    "total_tokens_sum": 0,
                    "avg_duration_ms": 0.0,
                    "failure_count": 0,
                }
            finally:
                if conn is not None:
                    conn.close()

    async def aget_table_metrics(self, days: int = 15) -> dict[str, Any]:
        """Asynchronously compute operational table metrics."""
        return await asyncio.to_thread(self.get_table_metrics, days=days)

    def get_failed_tasks(self, limit: int = 5, days: int = 15) -> list[dict[str, Any]]:
        """Fetch recent failed tasks with error messages for diagnostic debugging."""
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, session_id, task_type, provider, model_name, error_message, duration_ms, created_at
                    FROM session_tasks
                    WHERE status = 'failed' AND created_at >= ?
                    ORDER BY created_at DESC
                    LIMIT ?;
                    """,
                    (cutoff_ms, limit),
                )
                results: list[dict[str, Any]] = []
                for r in cursor.fetchall():
                    results.append({
                        "id": r[0],
                        "session_id": r[1],
                        "task_type": r[2],
                        "provider": r[3],
                        "model_name": r[4],
                        "error_message": r[5],
                        "duration_ms": r[6],
                        "created_at": r[7],
                    })
                return results
            except Exception as exc:
                logger.warning("Failed to query failed tasks: %s", exc)
                return []
            finally:
                if conn is not None:
                    conn.close()

    async def aget_failed_tasks(self, limit: int = 5, days: int = 15) -> list[dict[str, Any]]:
        """Asynchronously fetch recent failed tasks."""
        return await asyncio.to_thread(self.get_failed_tasks, limit=limit, days=days)

    def delete_records_older_than(self, days: int = 15) -> int:
        """Delete records older than specified retention window and return deleted count."""
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM session_tasks WHERE created_at < ?;", (cutoff_ms,))
                row_count = cursor.rowcount if cursor.rowcount >= 0 else 0
                if hasattr(conn, "commit"):
                    conn.commit()
                logger.info("Purged %d session_tasks records older than %d days.", row_count, days)
                return row_count
            except Exception as exc:
                logger.warning("Failed to purge session_tasks older than %d days: %s", days, exc)
                return 0
            finally:
                if conn is not None:
                    conn.close()

    async def adelete_records_older_than(self, days: int = 15) -> int:
        """Asynchronously delete expired records."""
        return await asyncio.to_thread(self.delete_records_older_than, days=days)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Fetch single task record by ID."""
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, session_id, user_id, task_type, provider, status, model_name,
                           prompt_tokens, completion_tokens, total_tokens, duration_ms, error_message,
                           metadata, created_at, completed_at
                    FROM session_tasks WHERE id = ?;
                    """,
                    (task_id,),
                )
                r = cursor.fetchone()
                if not r:
                    return None
                return {
                    "id": r[0],
                    "session_id": r[1],
                    "user_id": r[2],
                    "task_type": r[3],
                    "provider": r[4],
                    "status": r[5],
                    "model_name": r[6],
                    "prompt_tokens": r[7],
                    "completion_tokens": r[8],
                    "total_tokens": r[9],
                    "duration_ms": r[10],
                    "error_message": r[11],
                    "metadata": json.loads(r[12]) if r[12] else {},
                    "created_at": r[13],
                    "completed_at": r[14],
                }
            except Exception as exc:
                logger.warning("Failed to fetch task %s: %s", task_id, exc)
                return None
            finally:
                if conn is not None:
                    conn.close()

    async def aget_task(self, task_id: str) -> dict[str, Any] | None:
        """Asynchronously fetch single task record by ID."""
        return await asyncio.to_thread(self.get_task, task_id=task_id)


def get_session_task_service() -> SessionTaskService:
    """Return singleton SessionTaskService instance."""
    global _service_singleton
    if _service_singleton is None:
        with _service_lock:
            if _service_singleton is None:
                _service_singleton = SessionTaskService()
    return _service_singleton
