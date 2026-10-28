from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from chat_agent.research.faq_engine import generate_topic_faqs
from chat_agent.research.models import ResearchMode, ToolOutputEntry


@pytest.mark.asyncio
async def test_faq_engine_cache_reuse():
    """Verify generate_topic_faqs reuses fresh cached entries without invoking model runner."""
    now = time.time()
    cached = ToolOutputEntry(
        status="ok",
        fetched_at=now - 50,
        data="### Q: What is Raft?\nA: A consensus algorithm.",
    )

    with patch("chat_agent.research.faq_engine.get_model_runner") as mock_runner:
        faq_text, entry = await generate_topic_faqs(
            topic="Raft",
            mode=ResearchMode.TECHNICAL,
            cached_entry=cached,
        )

        mock_runner.assert_not_called()
        assert "### Q: What is Raft?" in faq_text
        assert entry.status == "ok"


@pytest.mark.asyncio
async def test_faq_engine_generation_when_missing():
    """Verify generate_topic_faqs invokes runner when cache is absent."""
    mock_runner = AsyncMock()
    mock_runner.run.return_value = "### Q: How does io_uring handle SQEs?\nA: Via submission ring."

    with patch("chat_agent.research.faq_engine.get_model_runner", return_value=mock_runner), \
         patch("chat_agent.research.faq_engine.get_search_pool") as mock_pool:

        pool_inst = AsyncMock()
        pool_inst.search_async.return_value = MagicMock(results=[])
        mock_pool.return_value = pool_inst

        faq_text, entry = await generate_topic_faqs(
            topic="Linux io_uring",
            mode=ResearchMode.TECHNICAL,
            cached_entry=None,
        )

        mock_runner.run.assert_called_once()
        assert "io_uring" in faq_text
        assert entry.status == "ok"
        assert entry.fetched_at > 0
