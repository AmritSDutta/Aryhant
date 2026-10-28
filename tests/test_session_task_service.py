"""Hermetic unit tests for SessionTaskService, metrics aggregation, and 15-day retention purging."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from chat_agent.services.session_task_service import SessionTaskService
from scripts.init_turso_db import SCHEMA_SQL


@pytest.fixture
def task_service(tmp_path: Path) -> SessionTaskService:
    """Provide an isolated SessionTaskService instance backed by temporary SQLite DB."""
    db_file = tmp_path / "test_session_tasks.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    for statement in SCHEMA_SQL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            cursor.execute(stmt)
    conn.commit()
    conn.close()

    return SessionTaskService(db_path=str(db_file), sync_url="", auth_token="")


def test_create_chat_task_start_only(task_service: SessionTaskService) -> None:
    """Verify chat turn registers at start with initial identity and no completion fields."""
    tid = task_service.create_task(
        session_id="slack:C123:170000.00",
        user_id="slack:U98765",
        task_type="chat",
        provider="gemini",
    )
    assert tid.startswith("task_")

    task = task_service.get_task(tid)
    assert task is not None
    assert task["session_id"] == "slack:C123:170000.00"
    assert task["user_id"] == "slack:U98765"
    assert task["task_type"] == "chat"
    assert task["provider"] == "gemini"
    assert task["status"] == "created"
    assert task["completed_at"] is None
    assert task["prompt_tokens"] == 0


def test_complete_task_lifecycle(task_service: SessionTaskService) -> None:
    """Verify two-phase task registration for non-chat jobs."""
    job_id = "job_res_test_123"
    task_service.create_task(
        session_id=job_id,
        user_id="slack:U11111",
        task_type="research",
        provider="nebius",
        task_id=job_id,
        status="in_progress",
    )

    # Complete the task
    ok = task_service.complete_task(
        task_id=job_id,
        status="completed",
        prompt_tokens=450,
        completion_tokens=550,
        total_tokens=1000,
        duration_ms=3500,
        model_name="nvidia/Nemotron-3.5-Super-VL",
        metadata={"topic": "Quantum Computing", "word_count": 2500},
    )
    assert ok is True

    task = task_service.get_task(job_id)
    assert task is not None
    assert task["status"] == "completed"
    assert task["prompt_tokens"] == 450
    assert task["completion_tokens"] == 550
    assert task["total_tokens"] == 1000
    assert task["duration_ms"] == 3500
    assert task["model_name"] == "nvidia/Nemotron-3.5-Super-VL"
    assert task["metadata"]["word_count"] == 2500
    assert task["completed_at"] is not None


def test_table_metrics_and_failed_tasks(task_service: SessionTaskService) -> None:
    """Verify operational telemetry calculation and failed task retrieval."""
    t1 = task_service.create_task("sess1", "user1", "chat", "gemini")
    task_service.complete_task(t1, "completed", prompt_tokens=100, completion_tokens=200, total_tokens=300, duration_ms=500)

    t2 = task_service.create_task("sess2", "user2", "research", "nebius")
    task_service.complete_task(t2, "failed", prompt_tokens=50, completion_tokens=0, duration_ms=200, error_message="Rate limit 429")

    metrics = task_service.get_table_metrics(days=15)
    assert metrics["total_tasks"] == 2
    assert metrics["status_breakdown"].get("completed") == 1
    assert metrics["status_breakdown"].get("failed") == 1
    assert metrics["prompt_tokens_sum"] == 150
    assert metrics["completion_tokens_sum"] == 200
    assert metrics["total_tokens_sum"] == 350
    assert metrics["failure_count"] == 1

    failed = task_service.get_failed_tasks(days=15)
    assert len(failed) == 1
    assert failed[0]["error_message"] == "Rate limit 429"


def test_delete_records_older_than_15_days(task_service: SessionTaskService) -> None:
    """Verify retention cleanup deletes records older than 15 days and preserves newer ones."""
    now_ms = int(time.time() * 1000)
    day_ms = 86400 * 1000

    # Insert 20-day-old record directly
    conn = task_service._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO session_tasks (id, session_id, user_id, task_type, provider, status, created_at)
        VALUES ('old_task_1', 'old_session', 'user_old', 'chat', 'gemini', 'completed', ?);
        """,
        (now_ms - 20 * day_ms,),
    )
    # Insert 16-day-old record
    cursor.execute(
        """
        INSERT INTO session_tasks (id, session_id, user_id, task_type, provider, status, created_at)
        VALUES ('old_task_2', 'old_session_2', 'user_old', 'research', 'nebius', 'completed', ?);
        """,
        (now_ms - 16 * day_ms,),
    )
    # Insert 10-day-old record
    cursor.execute(
        """
        INSERT INTO session_tasks (id, session_id, user_id, task_type, provider, status, created_at)
        VALUES ('new_task_1', 'new_session', 'user_new', 'chat', 'gemini', 'completed', ?);
        """,
        (now_ms - 10 * day_ms,),
    )
    conn.commit()
    conn.close()

    deleted = task_service.delete_records_older_than(days=15)
    assert deleted == 2

    # Verify old_task_1 and old_task_2 deleted, new_task_1 preserved
    assert task_service.get_task("old_task_1") is None
    assert task_service.get_task("old_task_2") is None
    assert task_service.get_task("new_task_1") is not None

@pytest.mark.asyncio
async def test_aget_task_async_twin(task_service: SessionTaskService) -> None:
    """Verify async twin aget_task returns matching record without blocking."""
    tid = task_service.create_task("async_sess", "async_user", "chat", "gemini")
    task = await task_service.aget_task(tid)
    assert task is not None
    assert task["id"] == tid
    assert task["session_id"] == "async_sess"


def test_get_task_db_exception_resilience(task_service: SessionTaskService) -> None:
    """Verify get_task catches DB exceptions and returns None gracefully."""
    from unittest.mock import patch
    with patch.object(task_service, "_get_connection", side_effect=sqlite3.OperationalError("disk I/O error")):
        res = task_service.get_task("some_task_id")
        assert res is None

def test_complete_task_fallback_insert_when_uncreated(task_service: SessionTaskService) -> None:
    """Verify complete_task directly inserts record if initial start record was missed."""
    orphan_id = "orphan_task_999"
    ok = task_service.complete_task(
        task_id=orphan_id,
        status="completed",
        prompt_tokens=120,
        completion_tokens=240,
        total_tokens=360,
        duration_ms=1500,
        model_name="test-model",
        metadata={"note": "fallback-test"},
    )
    assert ok is True

    record = task_service.get_task(orphan_id)
    assert record is not None
    assert record["id"] == orphan_id
    assert record["status"] == "completed"
    assert record["total_tokens"] == 360
    assert record["duration_ms"] == 1500
    assert record["metadata"] == {"note": "fallback-test"}

