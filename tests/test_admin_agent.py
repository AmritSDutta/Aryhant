"""Hermetic unit tests for the Administrative Agent, tool isolation, and multi-provider maintenance."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from chat_agent.agents.admin_agent import (
    ADMIN_SYSTEM_PROMPT,
    ADMIN_TOOLS,
    ADMIN_TOOLS_OPENAI,
    GEMINI_ADMIN_MODEL,
    NEBIUS_ADMIN_MODEL,
    AdminAgent,
    get_admin_agent,
)
from chat_agent.agents.nebius_model_runner import _TOOLS
from chat_agent.services.session_task_service import SessionTaskService, get_session_task_service
from scripts.init_turso_db import SCHEMA_SQL


@pytest.fixture
def mock_db_service(tmp_path: Path) -> SessionTaskService:
    """Provide an isolated SessionTaskService instance with initialized schema."""
    db_file = tmp_path / "test_admin_tasks.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    for statement in SCHEMA_SQL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            cursor.execute(stmt)
    conn.commit()
    conn.close()

    service = SessionTaskService(db_path=str(db_file), sync_url="", auth_token="")
    with patch("chat_agent.services.session_task_service._service_singleton", service):
        yield service


def test_tool_isolation_not_leaked_to_general_agents() -> None:
    """Verify that private admin tools are strictly isolated and not present in standard model runners."""
    general_tool_names = [fn.__name__ for fn in _TOOLS]
    admin_tool_names = [t["function"]["name"] for t in ADMIN_TOOLS]

    assert "search_context7" in admin_tool_names
    assert "search_web" in admin_tool_names

    # Pruning and metrics read are executed deterministically in python prior to LLM call
    assert "delete_old_session_tasks" not in admin_tool_names
    assert "read_session_tasks_metrics" not in admin_tool_names
    assert "search_context7" not in general_tool_names


@pytest.mark.asyncio
async def test_admin_agent_nebius_maintenance_flow(mock_db_service: SessionTaskService) -> None:
    """Verify AdminAgent execution using Nebius Nemotron-3-Nano-30B."""
    # Seed mock tasks: one old (>15 days), one recent
    now_ms = int(time.time() * 1000)
    day_ms = 86400 * 1000

    conn = mock_db_service._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO session_tasks (id, session_id, user_id, task_type, provider, status, created_at)
        VALUES ('task_20d', 'sess_old', 'user1', 'chat', 'gemini', 'completed', ?);
        """,
        (now_ms - 20 * day_ms,),
    )
    cursor.execute(
        """
        INSERT INTO session_tasks (id, session_id, user_id, task_type, provider, status, created_at)
        VALUES ('task_5d', 'sess_new', 'user2', 'research', 'nebius', 'completed', ?);
        """,
        (now_ms - 5 * day_ms,),
    )
    conn.commit()
    conn.close()

    agent = AdminAgent()
    agent.task_service = mock_db_service

    mock_report = "# Admin Health Report\n\nPruned 1 record. System operational."
    mock_tokens = {"prompt": 120, "completion": 80, "total": 200}

    with patch.object(agent, "_execute_nebius_report", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = (mock_report, mock_tokens)

        res = await agent.run_maintenance(days=15, provider="nebius")

        assert res["status"] == "success"
        assert res["deleted_count"] == 1
        assert "Admin Health Report" in res["report"]
        assert mock_db_service.get_task("task_20d") is None
        assert mock_db_service.get_task("task_5d") is not None

        # Verify admin task itself was logged in session_tasks
        admin_job_id = res["job_id"]
        admin_rec = mock_db_service.get_task(admin_job_id)
        assert admin_rec is not None
        assert admin_rec["task_type"] == "admin"
        assert admin_rec["provider"] == "nebius"
        assert admin_rec["status"] == "completed"
        assert admin_rec["total_tokens"] == 200


@pytest.mark.asyncio
async def test_admin_agent_gemini_maintenance_flow(mock_db_service: SessionTaskService) -> None:
    """Verify AdminAgent execution using Gemini gemini-flash-lite-latest."""
    agent = AdminAgent()
    agent.task_service = mock_db_service

    mock_report = "# Gemini Admin Report\n\nAll systems nominal."
    mock_tokens = {"prompt": 90, "completion": 60, "total": 150}

    with patch.object(agent, "_execute_gemini_report", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = (mock_report, mock_tokens)

        res = await agent.run_maintenance(days=15, provider="gemini")

        assert res["status"] == "success"
        assert "Gemini Admin Report" in res["report"]

        admin_job_id = res["job_id"]
        admin_rec = mock_db_service.get_task(admin_job_id)
        assert admin_rec is not None
        assert admin_rec["task_type"] == "admin"
        assert admin_rec["provider"] == "gemini"
        assert admin_rec["model_name"] == GEMINI_ADMIN_MODEL

@pytest.mark.asyncio
async def test_telemetry_sanitization_and_privacy(mock_db_service: SessionTaskService) -> None:
    """Verify that raw session IDs, task IDs, file paths, emails, and tokens are scrubbed from LLM payloads."""
    import json

    conn = mock_db_service._get_connection()
    cursor = conn.cursor()
    now_ms = int(time.time() * 1000)
    raw_error = "Traceback (most recent call last):\n  File 'C:\\codebase\\Aryhant\\bad.py', line 12\nValueError: token 9a8b7c6d5e4f3a2b1c0d9e8f for user john.doe@example.com failed"
    cursor.execute(
        """
        INSERT INTO session_tasks (id, session_id, user_id, task_type, provider, status, error_message, created_at)
        VALUES ('private_task_id_999', 'slack:C123:private_sess', 'slack:U999', 'research', 'nebius', 'failed', ?, ?);
        """,
        (raw_error, now_ms),
    )
    conn.commit()
    conn.close()

    agent = AdminAgent()
    agent.task_service = mock_db_service

    captured_prompt: list[str] = []

    async def mock_exec(messages: list[dict[str, str]], model: str = "") -> tuple[str, dict[str, int]]:
        for m in messages:
            captured_prompt.append(m.get("content", ""))
        return ("# Report\n\nOk", {"prompt": 10, "completion": 10, "total": 20})

    with patch.object(agent, "_execute_nebius_report", side_effect=mock_exec):
        res = await agent.run_maintenance(days=15, provider="nebius")
        assert res["status"] == "success"

    full_payload_text = "\n".join(captured_prompt)

    # Raw IDs and sensitive information MUST NOT appear in the prompt sent to LLM
    assert "private_task_id_999" not in full_payload_text
    assert "slack:C123:private_sess" not in full_payload_text
    assert "C:\\codebase" not in full_payload_text
    assert "john.doe@example.com" not in full_payload_text
    assert "9a8b7c6d5e4f3a2b1c0d9e8f" not in full_payload_text

    # Extract JSON telemetry payload to check structure
    start_idx = full_payload_text.find("```json\n") + 8
    end_idx = full_payload_text.find("\n```", start_idx)
    telemetry = json.loads(full_payload_text[start_idx:end_idx])

    assert len(telemetry["recent_failures"]) == 1
    sanitized_failure = telemetry["recent_failures"][0]
    assert "session_id" not in sanitized_failure
    assert "id" not in sanitized_failure
    assert "[path]" in sanitized_failure["error_summary"]
    assert "[email]" in sanitized_failure["error_summary"]


def test_dynamic_fallback_report_status() -> None:
    """Verify fallback report indicates ATTENTION REQUIRED when failures exist, and HEALTHY when 0."""
    agent = AdminAgent()

    healthy_msg = [{'content': '{"failure_count": 0}'}]
    healthy_report = agent._build_deterministic_report(healthy_msg)
    assert "HEALTHY - All telemetry metrics within nominal bounds" in healthy_report
    assert "✅ Administrative & Operations Audit" in healthy_report

    failing_msg = [{'content': '{"failure_count": 4}'}]
    failing_report = agent._build_deterministic_report(failing_msg)
    assert "ATTENTION REQUIRED - 4 failures detected" in failing_report

@pytest.mark.asyncio
async def test_admin_agent_nebius_tool_dispatch_loop(mock_db_service: SessionTaskService) -> None:
    """Verify that the Nebius tool dispatch loop executes search_context7 and incorporates tool response."""
    from unittest.mock import MagicMock

    agent = AdminAgent()
    agent.task_service = mock_db_service

    # Round 1: Model requests search_context7
    tool_call_mock = MagicMock()
    tool_call_mock.id = "call_abc123"
    tool_call_mock.function.name = "search_context7"
    tool_call_mock.function.arguments = json.dumps({"query": "database connection error"})

    msg1 = MagicMock()
    msg1.content = None
    msg1.tool_calls = [tool_call_mock]
    msg1.model_dump.return_value = {
        "role": "assistant",
        "tool_calls": [{"id": "call_abc123", "type": "function", "function": {"name": "search_context7", "arguments": '{"query": "database connection error"}'}}],
    }

    resp1 = MagicMock()
    resp1.choices = [MagicMock(message=msg1)]
    resp1.usage = MagicMock(prompt_tokens=40, completion_tokens=15, total_tokens=55)

    # Round 2: Model returns final synthesized report with recommendations
    msg2 = MagicMock()
    msg2.content = "# Admin Health Report\n\n### Suggestions\nContext7 reference applied."
    msg2.tool_calls = None

    resp2 = MagicMock()
    resp2.choices = [MagicMock(message=msg2)]
    resp2.usage = MagicMock(prompt_tokens=60, completion_tokens=30, total_tokens=90)

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

    with patch("openai.AsyncOpenAI", return_value=mock_client), patch(
        "chat_agent.agents.admin_agent.search_context7",
        new_callable=AsyncMock,
        return_value={"code_snippets": [{"title": "Turso DB Guide", "code": "conn.close()"}]},
    ):
        report, tokens = await agent._execute_nebius_report(
            messages=[{"role": "user", "content": "Run audit"}],
            model="test-model",
        )

        assert "Admin Health Report" in report
        assert "Context7 reference applied" in report
        assert tokens["total"] == 145  # 55 + 90
        assert mock_client.chat.completions.create.call_count == 2

