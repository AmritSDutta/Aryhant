from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, patch

from chat_agent.research.engine import _is_fresh_entry, gather_research_intelligence
from chat_agent.research.models import ResearchMode, ToolOutputEntry
from chat_agent.services.redis_research_store import RedisResearchStore


@pytest.mark.asyncio
async def test_redis_job_indexing_and_lookup():
    """Verify thread and user-topic indexes map deterministically to job_id."""
    store = RedisResearchStore(redis_url="")  # In-memory mode
    channel_id = "C_TEST_101"
    thread_ts = "1729876543.000100"
    user_id = "slack:U_ALICE"
    topic = "Distributed Consensus Algorithms"
    job_id = "job-consensus-999"

    await store.index_job(
        channel_id=channel_id,
        thread_ts=thread_ts,
        user_id=user_id,
        topic=topic,
        job_id=job_id,
    )

    # 1. Lookup by thread
    found_by_thread = await store.find_active_job(channel_id, thread_ts, "other_user", "different topic")
    assert found_by_thread == job_id

    # 2. Lookup by user and topic without thread
    found_by_topic = await store.find_active_job("C_OTHER", "", user_id, "distributed consensus algorithms")
    assert found_by_topic == job_id

    # 3. Non-existent returns None
    assert await store.find_active_job("C_UNKNOWN", "999.999", "U_UNKNOWN", "Unknown") is None


def test_tool_output_freshness():
    """Verify _is_fresh_entry evaluates status and TTL correctly."""
    now = time.time()
    fresh_entry = ToolOutputEntry(status="ok", fetched_at=now - 100, data={"content": "valid"})
    assert _is_fresh_entry(fresh_entry) is True

    expired_entry = ToolOutputEntry(status="ok", fetched_at=now - 90000, data={"content": "old"})
    assert _is_fresh_entry(expired_entry) is False

    failed_entry = ToolOutputEntry(status="failed", fetched_at=now - 10, error="API timeout")
    assert _is_fresh_entry(failed_entry) is False


@pytest.mark.asyncio
async def test_gather_intelligence_reuses_valid_cache():
    """Verify gather_research_intelligence skips external API calls when cached tool outputs exist."""
    now = time.time()
    cached_tool_outputs = {
        "serpapi": ToolOutputEntry(
            status="ok",
            fetched_at=now - 200,
            data={
                "status": "success",
                "text": "Cached Google AI Overview on Raft",
                "references": [{"title": "Raft Paper", "url": "https://raft.github.io"}],
            },
        ),
        "tavily": ToolOutputEntry(
            status="ok",
            fetched_at=now - 200,
            data={
                "status": "completed",
                "content": "Cached Tavily Mini-Research on Raft",
                "sources": [{"title": "Tavily Raft", "url": "https://tavily.com/raft"}],
            },
        ),
        "context7": ToolOutputEntry(
            status="ok",
            fetched_at=now - 200,
            data={"status": "success", "code_snippets": []},
        ),
        "websearch": ToolOutputEntry(
            status="ok",
            fetched_at=now - 200,
            data={"snippets": ["Cached snippet 1"], "sources": []},
        ),
    }

    with patch("chat_agent.research.engine.fetch_google_ai_overview") as mock_serp, \
         patch("chat_agent.research.engine.run_tavily_mini_research_polling") as mock_tav:

        intel = await gather_research_intelligence(
            topic="Raft Consensus",
            mode=ResearchMode.TECHNICAL,
            cached_tool_outputs=cached_tool_outputs,
        )

        # Neither SerpApi nor Tavily polling should be called!
        mock_serp.assert_not_called()
        mock_tav.assert_not_called()

        assert "Cached Google AI Overview on Raft" in intel["dossier"]
        assert "Cached Tavily Mini-Research on Raft" in intel["dossier"]
        assert any("raft.github.io" in s.url for s in intel["sources"])


@pytest.mark.asyncio
async def test_gather_intelligence_refetches_failed_stream():
    """Verify poison prevention: failed cached entry is re-fetched rather than reused."""
    now = time.time()
    cached_with_failure = {
        "serpapi": ToolOutputEntry(status="failed", fetched_at=now - 100, error="HTTP 500"),
        "tavily": ToolOutputEntry(
            status="ok",
            fetched_at=now - 100,
            data={"status": "completed", "content": "Tavily content", "sources": []},
        ),
    }

    fresh_serp_data = {
        "status": "success",
        "text": "Freshly fetched SerpApi data",
        "references": [],
    }

    with patch("chat_agent.research.engine.fetch_google_ai_overview", new_callable=AsyncMock) as mock_serp, \
         patch("chat_agent.research.engine.run_tavily_mini_research_polling") as mock_tav, \
         patch("chat_agent.research.engine.search_context7", new_callable=AsyncMock) as mock_c7:

        mock_serp.return_value = fresh_serp_data
        mock_c7.return_value = {"status": "success", "code_snippets": []}

        intel = await gather_research_intelligence(
            topic="Paxos Protocol",
            mode=ResearchMode.TECHNICAL,
            cached_tool_outputs=cached_with_failure,
        )

        # SerpApi was failed in cache, so it MUST be re-fetched
        mock_serp.assert_called_once()
        # Tavily was "ok" in cache, so it must NOT be re-fetched
        mock_tav.assert_not_called()

        assert "Freshly fetched SerpApi data" in intel["dossier"]
        assert intel["tool_outputs"]["serpapi"].status == "ok"


@pytest.mark.asyncio
async def test_completed_job_short_circuits_on_resume():
    """Verify resume short-circuits when finding an already COMPLETED job."""
    from chat_agent.research.research_agent import DualResearchAgent
    from chat_agent.research.models import ResearchJobState, TaskStatus

    agent = DualResearchAgent()
    mock_client = AsyncMock()

    completed_job = ResearchJobState(
        job_id="job_comp_001",
        command="/research",
        topic="Consensus Algorithms",
        status=TaskStatus.COMPLETED,
        pdf_path="/tmp/consensus.pdf",
        executive_summary="Consensus is vital for distributed systems.",
    )

    with patch.object(agent.store, "find_active_job", return_value="job_comp_001"), \
         patch.object(agent.store, "get_job", return_value=completed_job), \
         patch("chat_agent.research.research_agent.gather_research_intelligence") as mock_gather, \
         patch("chat_agent.research.research_agent.release_user_job_slot") as mock_release:

        await agent.execute_job(
            job_id="job_comp_001",
            command="/research",
            topic="Consensus Algorithms",
            channel_id="C_TEST",
            thread_ts="1234.5678",
            user_id="slack:U_USER1",
            attachments=[],
            client=mock_client,
        )

        # Gathering must NOT run!
        mock_gather.assert_not_called()
        # Slot must be released!
        mock_release.assert_called_once_with("slack:U_USER1")
        # Notice posted
        mock_client.chat_postMessage.assert_called_once()
        call_text = mock_client.chat_postMessage.call_args[1]["text"]
        assert "Research already completed for this topic" in call_text

