from __future__ import annotations

import logging
import time
from typing import Any

from google.genai import types

from chat_agent.agents.model_runner import get_model_runner
from chat_agent.research.models import ResearchMode, ToolOutputEntry
from chat_agent.tools.tool_factory import get_search_pool

logger = logging.getLogger(__name__)

FAQ_SYSTEM_PROMPT = """You are an expert technical and practical FAQ curator.
Your task is to generate 4-6 concise, highly practical Frequently Asked Questions (FAQs) for the given topic.
Each FAQ must target real-world edge cases, common pitfalls, misconceptions, or pricing/implementation catches.

Format each item cleanly as:
### Q: [Question Title]
[Detailed, actionable answer in 2-3 sentences]
"""


async def generate_topic_faqs(
    topic: str,
    mode: ResearchMode = ResearchMode.TECHNICAL,
    cached_entry: ToolOutputEntry | None = None,
    session_id: str = "",
    user_id: str = "faq-worker",
) -> tuple[str, ToolOutputEntry]:
    """Generate 4-6 curated topic FAQs with web search and 24-hour cache support."""
    now = time.time()
    if cached_entry and cached_entry.status == "ok" and (now - cached_entry.fetched_at) < 86400:
        logger.info("Reusing cached FAQs for topic %r (age: %ds)", topic, int(now - cached_entry.fetched_at))
        return str(cached_entry.data or ""), cached_entry

    clean_topic = topic.strip()
    if not clean_topic:
        empty_entry = ToolOutputEntry(status="ok", fetched_at=now, data="")
        return "", empty_entry

    try:
        # 1. Quick search for community questions and common pitfalls
        pool = get_search_pool()
        search_query = f"{clean_topic} common pitfalls questions FAQ 2026"
        search_res = await pool.search_async(search_query, max_results=3)
        search_snippets: list[str] = []
        if hasattr(search_res, "results"):
            for item in getattr(search_res, "results", []):
                snippet = getattr(item, "content", "")
                if snippet:
                    search_snippets.append(snippet[:250])

        context_str = "\n".join(search_snippets) if search_snippets else "No search context."
        user_prompt = (
            f"Topic: {clean_topic}\n"
            f"Research Mode: {mode.value}\n\n"
            f"Background Search Evidence:\n{context_str}\n\n"
            "Generate 4-6 targeted FAQs covering practical caveats, edge cases, and best practices."
        )

        runner = get_model_runner()
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_prompt)],
        )
        faq_text = await runner.run(
            user_id=user_id,
            session_id=session_id or f"faq-{int(now)}",
            content=content,
            system_instruction=FAQ_SYSTEM_PROMPT,
            enable_tools=False,
        )
        clean_faqs = faq_text.strip()
        entry = ToolOutputEntry(status="ok", fetched_at=now, data=clean_faqs)
        return clean_faqs, entry
    except Exception as exc:
        logger.warning("Async FAQ generation failed for %r: %s", clean_topic, exc)
        failed_entry = ToolOutputEntry(status="failed", fetched_at=now, error=str(exc))
        return "", failed_entry
