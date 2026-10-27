from __future__ import annotations

import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from chat_agent.research.dispatcher import (
    acquire_user_job_slot,
    new_job_id,
    parse_research_trigger,
    release_user_job_slot,
)
from chat_agent.research.models import (
    ModelUsage,
    ResearchJobState,
    ResearchMode,
    TaskStatus,
    TokenEconomics,
)
from chat_agent.research.pdf_builder import (
    build_research_pdf,
    clean_llm_markdown_for_pdf,
    format_human_ist_datetime,
)
from chat_agent.research.research_agent import DualResearchAgent, compute_job_token_economics
from chat_agent.research.todo_tracker import initialize_default_todos, render_slack_todo_board
from chat_agent.services.redis_research_store import (
    RedisResearchStore,
    get_session_token_usage,
    record_session_token_usage,
)
from chat_agent.slack.slack_auth import check_slack_authorization
from chat_agent.tools.context7_tool import search_context7
from chat_agent.tools.sandbox_tool import execute_code_in_sandbox
from chat_agent.tools.serpapi_tool import fetch_google_ai_overview
from chat_agent.tools.tavily_research_tool import run_tavily_mini_research_polling
from chat_agent.tools.tool_factory import _is_allowed_upload_path


@pytest.mark.asyncio
async def test_serpapi_tool_flow():
    """Verify SerpApi Google AI Overview extracts text blocks and resolves page_token."""
    mock_search_json = {
        "ai_overview": {
            "page_token": "token123",
            "text_blocks": [{"type": "paragraph", "snippet": "Initial summary"}],
        }
    }
    mock_overview_json = {
        "ai_overview": {
            "text_blocks": [
                {"type": "paragraph", "snippet": "Resolved deep overview"},
                {"type": "list", "list": [{"title": "Step 1", "snippet": "Execution"}]},
            ],
            "references": [{"title": "Google Source", "link": "https://google.com/test", "snippet": "Ref snippet"}],
        }
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp1 = MagicMock()
        mock_resp1.json.return_value = mock_search_json
        mock_resp1.raise_for_status = MagicMock()

        mock_resp2 = MagicMock()
        mock_resp2.json.return_value = mock_overview_json
        mock_resp2.raise_for_status = MagicMock()

        mock_get.side_effect = [mock_resp1, mock_resp2]

        res = await fetch_google_ai_overview("test query", api_key="dummy_serpapi_key")
        assert res["status"] == "success"
        assert "Resolved deep overview" in res["text"]
        assert "- **Step 1**: Execution" in res["text"]
        assert len(res["references"]) == 1
        assert res["references"][0]["url"] == "https://google.com/test"


@pytest.mark.asyncio
async def test_serpapi_tool_unconfigured():
    """Verify SerpApi tool skips gracefully when key is missing."""
    res = await fetch_google_ai_overview("test query", api_key="")
    assert res["status"] == "skipped"
    assert res["text"] == ""


@pytest.mark.asyncio
async def test_tavily_research_tool_polling():
    """Verify Tavily mini-research polling loop advances to completed."""
    mock_client = MagicMock()
    mock_client.research = AsyncMock(return_value={"request_id": "req_123", "status": "pending"})
    mock_client.get_research = AsyncMock(side_effect=[
        {"status": "processing"},
        {
            "status": "completed",
            "content": "Comprehensive Tavily mini-research synthesis on the topic.",
            "sources": [{"title": "Tavily Doc", "url": "https://tavily.com/doc"}],
        },
    ])

    with patch("tavily.AsyncTavilyClient", return_value=mock_client), patch("asyncio.sleep", new_callable=AsyncMock):
        updates: list[str] = []

        async def _on_status(msg: str) -> None:
            updates.append(msg)

        res = await run_tavily_mini_research_polling(
            query="test query",
            session_id="sess_1",
            human_id="user_1",
            poll_interval=0.1,
            max_poll_seconds=5.0,
            on_status_update=_on_status,
            api_key="dummy_tavily_key",
        )

        assert res["status"] == "completed"
        assert "Comprehensive Tavily" in res["content"]
        assert len(res["sources"]) == 1
        assert res["sources"][0]["url"] == "https://tavily.com/doc"
        assert any("processing" in u for u in updates)


@pytest.mark.asyncio
async def test_context7_tool_search():
    """Verify Context7 tool extracts codeSnippets and infoSnippets."""
    mock_json = {
        "codeSnippets": [
            {
                "libraryId": "fastapi",
                "codeTitle": "Streaming Route",
                "code": "async def stream(): yield b'chunk'",
            }
        ],
        "infoSnippets": [{"libraryId": "fastapi", "content": "FastAPI streaming explanation"}],
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_json
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        res = await search_context7("FastAPI streaming", api_key="dummy_c7_key")
        assert res["status"] == "success"
        assert len(res["code_snippets"]) == 1
        assert res["code_snippets"][0]["title"] == "Streaming Route"
        assert "yield b'chunk'" in res["code_snippets"][0]["code"]


@pytest.mark.asyncio
async def test_sandbox_tool_execution():
    """Verify Nebius sandbox tool executes code and captures stdout."""
    mock_json = {
        "exit_code": 0,
        "stdout": "Hello from microVM sandbox\n",
        "stderr": "",
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_json
        mock_post.return_value = mock_resp

        res = await execute_code_in_sandbox("print('Hello')", api_key="dummy_nebius_key")
        assert res["status"] == "success"
        assert res["exit_code"] == 0
        assert res["reason"] == "exit code 0"
        assert "Hello from microVM" in res["stdout"]


@pytest.mark.asyncio
async def test_sandbox_tool_error_and_skipped_reasons():
    """Verify first-class status and reason reporting on error and unconfigured paths."""
    res_skipped = await execute_code_in_sandbox("print('Hello')", api_key="")
    assert res_skipped["status"] == "skipped"
    assert res_skipped["reason"] == "NEBIUS_API_KEY unconfigured"

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.text = "Bad Gateway"
        mock_post.return_value = mock_resp

        res_err = await execute_code_in_sandbox("print('Hello')", api_key="dummy_key")
        assert res_err["status"] == "error"
        assert res_err["reason"] == "HTTP 502"


@pytest.mark.asyncio
async def test_redis_research_store():
    """Verify RedisResearchStore CRUD operations and in-memory fallback."""
    store = RedisResearchStore(redis_url="")
    todos = initialize_default_todos(ResearchMode.TECHNICAL)

    job = ResearchJobState(
        job_id="test_job_1",
        command="/research",
        topic="Linux eBPF",
        mode=ResearchMode.TECHNICAL,
        todos=todos,
    )

    await store.save_job(job)
    fetched = await store.get_job("test_job_1")
    assert fetched is not None
    assert fetched.topic == "Linux eBPF"
    assert len(fetched.todos) == 5

    updated = await store.update_todo_status("test_job_1", "plan", TaskStatus.COMPLETED, "Done")
    assert updated is not None
    assert updated.todos[0].status == TaskStatus.COMPLETED
    assert updated.todos[0].details == "Done"


def test_todo_board_rendering():
    """Verify Slack Block Kit status board renders for technical and deliberate modes."""
    todos = initialize_default_todos(ResearchMode.TECHNICAL)
    job = ResearchJobState(
        job_id="board_test",
        command="/research",
        topic="PostgreSQL MVCC",
        mode=ResearchMode.TECHNICAL,
        todos=todos,
    )

    blocks = render_slack_todo_board(job)
    assert len(blocks) >= 4
    assert blocks[0]["type"] == "header"
    assert "Technical Research In Progress" in blocks[0]["text"]["text"]

    job.mode = ResearchMode.DELIBERATE
    job.command = "/deliberate"
    job.todos = initialize_default_todos(ResearchMode.DELIBERATE)
    delib_blocks = render_slack_todo_board(job)
    assert "Deliberation & Decision Guide" in delib_blocks[0]["text"]["text"]


def test_clean_llm_markdown_for_pdf():
    """Verify cleaning of LLM markup including outer code fences and raw HTML containers."""
    raw = "```markdown\n# Title\n<div>Content</div>\n```"
    cleaned = clean_llm_markdown_for_pdf(raw)
    assert cleaned.startswith("# Title")
    assert "<div>" not in cleaned
    assert "Content" in cleaned


def test_pdf_builder_compilation_with_token_economics():
    """Verify build_research_pdf compiles valid PDF with sections, tables, and token economics in IST."""
    md_content = (
        "# Executive Summary\n\n"
        "This is an architectural deep dive with a [Reference](https://example.com).\n\n"
        "1. Architectural baseline\n"
        "2. Performance metrics\n"
        "3. Production hardening\n\n"
        "## Core Implementation\n\n"
        "```python\n"
        "def test_func():\n"
        "    return 42\n"
        "```\n\n"
        "| Feature | Status |\n"
        "| --- | --- |\n"
        "| Vectorized Engine | Active |\n"
    )

    econ = TokenEconomics(
        models_used=[
            ModelUsage(
                model_name="gemini-2.5-pro",
                provider="Google GenAI",
                role="Synthesis",
                input_tokens=1000,
                output_tokens=2500,
                total_tokens=3500,
                estimated_cost_usd=0.01375,
            )
        ],
        total_input_tokens=1000,
        total_output_tokens=2500,
        total_tokens=3500,
        total_estimated_cost_usd=0.0138,
    )

    pdf_path = build_research_pdf(
        topic="Vectorized Engines",
        mode=ResearchMode.TECHNICAL,
        markdown_content=md_content,
        word_count=2500,
        token_economics=econ,
    )

    assert os.path.exists(pdf_path)
    with open(pdf_path, "rb") as f:
        header = f.read(5)
        assert header == b"%PDF-"

    ist_str = format_human_ist_datetime()
    assert "IST" in ist_str


def test_allowed_upload_path():
    """Verify aryhant_reports is an allowed upload directory."""
    rep_dir = tempfile.gettempdir()
    test_pdf = os.path.join(rep_dir, "aryhant_reports", "test_report.pdf")
    assert _is_allowed_upload_path(test_pdf)


def test_dispatcher_trigger_parsing():
    """Verify trigger parser accurately extracts commands and ignores prose."""
    assert parse_research_trigger("/research Linux io_uring") == ("/research", "Linux io_uring")
    assert parse_research_trigger("/deliberate Best headphones") == ("/deliberate", "Best headphones")
    assert parse_research_trigger("research: Distributed caches") == ("/research", "Distributed caches")
    assert parse_research_trigger("deliberate: Apple vs Samsung") == ("/deliberate", "Apple vs Samsung")
    assert parse_research_trigger("Hello world, this is a normal message") is None
    assert parse_research_trigger("") is None

    jid = new_job_id("/research")
    assert jid.startswith("res_")


@pytest.mark.asyncio
async def test_user_concurrency_guard():
    """Verify in-flight job concurrency per user."""
    user = "slack:U999"
    assert await acquire_user_job_slot(user) is True
    assert await acquire_user_job_slot(user) is False
    await release_user_job_slot(user)
    assert await acquire_user_job_slot(user) is True
    await release_user_job_slot(user)


@pytest.mark.asyncio
async def test_slack_authorization_check():
    """Verify caller authorization check and denial mechanism."""
    mock_client = AsyncMock()
    mock_client.users_info.return_value = {
        "ok": True,
        "user": {"profile": {"email": "unauthorized@unknown.com", "real_name": "Test"}},
    }
    is_allowed, _, _, email = await check_slack_authorization(mock_client, "U_UNAUTH", notify_on_deny=False)
    assert is_allowed is False
    assert email == "unauthorized@unknown.com"


@pytest.mark.asyncio
async def test_dual_research_agent_flow_and_persistence():
    """Verify DualResearchAgent executes full pipeline, offloads async tasks, and persists state."""
    agent = DualResearchAgent()
    mock_client = AsyncMock()
    mock_client.chat_postMessage.return_value = {"ok": True, "ts": "1234567890.123"}
    mock_client.chat_update.return_value = {"ok": True}

    with patch("chat_agent.research.research_agent.gather_research_intelligence") as mock_gather, \
         patch("chat_agent.research.research_agent.get_model_runner") as mock_runner_factory, \
         patch("chat_agent.research.research_agent._upload_file_to_slack_sync", return_value={"status": "success"}):

        mock_gather.return_value = {
            "dossier": "Mocked research dossier content",
            "sources": [],
            "candidate_code": "",
            "candidate_title": "",
            "c7_snippets": [],
        }

        mock_runner = AsyncMock()
        mock_runner.run.return_value = "# Executive Summary\n\nDeep research report content here.\n\n## Section 2\nDetails."
        mock_runner_factory.return_value = mock_runner

        job_id = "flow_test_persist"
        await record_session_token_usage(
            session_id=f"synth-{job_id}",
            model_name="gemini-2.5-pro",
            provider="Google GenAI",
            prompt_tokens=500,
            completion_tokens=1500,
        )
        await agent.execute_job(
            job_id=job_id,
            command="/research",
            topic="Raft vs Paxos",
            channel_id="C12345",
            thread_ts="",
            user_id="U12345",
            attachments=[],
            client=mock_client,
        )

        assert mock_client.chat_postMessage.call_count >= 2
        assert mock_client.chat_update.call_count >= 3

        # Verify runtime execution date in synthesis prompt
        run_call_kwargs = mock_runner.run.call_args[1]
        sent_content = run_call_kwargs["content"]
        sent_text = sent_content.parts[0].text
        assert "This is getting executed as of:" in sent_text

        # Verify job was persisted to store upon success
        persisted = await agent.store.get_job(job_id)
        assert persisted is not None
        assert persisted.status == TaskStatus.COMPLETED
        assert len(persisted.full_report_markdown) > 0
        assert persisted.word_count > 0
        assert persisted.token_economics.total_tokens > 0
        assert len(persisted.queries) > 0
        assert persisted.pdf_path.endswith(".pdf")


@pytest.mark.asyncio
async def test_compute_job_token_economics_flow():
    """Verify compute_job_token_economics extracts metadata from Redis or falls back to empty."""
    import time
    missing_job_id = f"econ_missing_{time.time()}"

    # 1. Missing in Redis -> empty models list
    missing_econ = await compute_job_token_economics(job_id=missing_job_id, has_visual=True)
    assert missing_econ.models_used == []
    assert missing_econ.total_tokens == 0
    assert missing_econ.is_estimated is True

    # 2. Recorded in Redis -> parsed accurately
    populated_job_id = f"econ_pop_{time.time()}"
    await record_session_token_usage(
        session_id=f"vision-{populated_job_id}",
        model_name="gemini-2.5-flash",
        provider="Google GenAI",
        prompt_tokens=300,
        completion_tokens=200,
    )
    await record_session_token_usage(
        session_id=f"synth-{populated_job_id}",
        model_name="gemini-2.5-pro",
        provider="Google GenAI",
        prompt_tokens=1200,
        completion_tokens=2800,
    )

    populated_econ = await compute_job_token_economics(job_id=populated_job_id, has_visual=True)
    assert len(populated_econ.models_used) == 2
    assert populated_econ.total_input_tokens == 1500
    assert populated_econ.total_output_tokens == 3000
    assert populated_econ.total_tokens == 4500
    assert populated_econ.total_estimated_cost_usd > 0
    assert populated_econ.is_estimated is False

