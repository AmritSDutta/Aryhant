from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

from chat_agent.research.models import ResearchMode, ResearchSource, ToolOutputEntry
from chat_agent.tools.serpapi_tool import fetch_google_ai_overview
from chat_agent.tools.tavily_research_tool import run_tavily_mini_research_polling

logger = logging.getLogger(__name__)


def generate_subqueries(topic: str, mode: ResearchMode) -> list[str]:
    """Generate 3-4 targeted subqueries for multi-provider web search."""
    clean = topic.strip()
    if mode == ResearchMode.TECHNICAL:
        return [
            f"{clean} architecture internals mechanics",
            f"{clean} benchmarks performance trade-offs",
            f"{clean} failure modes edge cases production",
        ]
    return [
        f"{clean} best options pricing comparison 2026",
        f"{clean} reviews pros cons true cost",
        f"{clean} pitfalls hidden fees fine print guide",
    ]


def _is_fresh_entry(entry: ToolOutputEntry | None, max_age: float = 86400.0) -> bool:
    if not entry or entry.status != "ok":
        return False
    return (time.time() - entry.fetched_at) < max_age


async def gather_research_intelligence(
    topic: str,
    mode: ResearchMode,
    session_id: str = "",
    user_id: str = "",
    visual_notes: str = "",
    on_status_update: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    cached_tool_outputs: dict[str, ToolOutputEntry] | None = None,
) -> dict[str, Any]:
    """Gather deterministic intelligence (SerpApi, Tavily) with 24-hour tool-level caching.

    Note: Context7 and WebSearch are agent tools invoked by the model dynamically,
    not deterministic upfront streams. Context7 results are not cached.
    """
    sources: list[ResearchSource] = []
    now = time.time()
    tool_outputs: dict[str, ToolOutputEntry] = dict(cached_tool_outputs or {})

    # 1. Google AI Overview via SerpApi (deterministic)
    gai_entry = tool_outputs.get("serpapi")
    if _is_fresh_entry(gai_entry):
        logger.info("[SerpApi] Reusing cached Google AI Overview for %r", topic)
        gai_res = gai_entry.data if isinstance(gai_entry.data, dict) else {}
        gai_task = None
    else:
        if on_status_update:
            await on_status_update("Querying Google AI Overview...")
        gai_task = asyncio.create_task(fetch_google_ai_overview(topic))

    # 2. Tavily Mini-Research with async polling (deterministic)
    tav_entry = tool_outputs.get("tavily")
    if _is_fresh_entry(tav_entry):
        logger.info("[Tavily] Reusing cached Tavily Mini-Research for %r", topic)
        tav_res = tav_entry.data if isinstance(tav_entry.data, dict) else {}
        tav_task = None
    else:
        tav_task = asyncio.create_task(
            run_tavily_mini_research_polling(
                query=topic,
                session_id=session_id,
                human_id=user_id,
                on_status_update=on_status_update,
            )
        )

    # Await pending async deterministic tasks
    if gai_task:
        gai_res = await gai_task
        status_ok = gai_res.get("status") in ("success", "no_overview")
        tool_outputs["serpapi"] = ToolOutputEntry(
            status="ok" if status_ok else "failed",
            fetched_at=now,
            data=gai_res,
            error=gai_res.get("error", ""),
        )
    if tav_task:
        tav_res = await tav_task
        status_ok = tav_res.get("status") in ("completed", "skipped")
        tool_outputs["tavily"] = ToolOutputEntry(
            status="ok" if status_ok else "failed",
            fetched_at=now,
            data=tav_res,
            error=tav_res.get("error", ""),
        )

    # Extract Google AI Overview data
    gai_text = gai_res.get("text", "")
    for ref in gai_res.get("references", []):
        sources.append(ResearchSource(
            title=ref.get("title") or "Google AI Overview Source",
            url=ref.get("url") or "",
            snippet=ref.get("snippet") or "",
            provider="Google AI Overview",
        ))

    # Extract Tavily Mini-Research data
    tav_text = tav_res.get("content", "")
    for s in tav_res.get("sources", []):
        sources.append(ResearchSource(
            title=s.get("title") or "Tavily Source",
            url=s.get("url") or "",
            provider="Tavily Mini-Research",
        ))

    # Deduplicate sources by URL
    seen_urls: set[str] = set()
    deduped_sources: list[ResearchSource] = []
    for s in sources:
        if s.url and s.url not in seen_urls:
            seen_urls.add(s.url)
            deduped_sources.append(s)

    # Build unified context dossier
    dossier_sections: list[str] = []
    if visual_notes:
        dossier_sections.append(f"### Visual Evidence & Architecture Notes\n{visual_notes}")
    if gai_text:
        dossier_sections.append(f"### Google AI Overview\n{gai_text}")
    if tav_text:
        dossier_sections.append(f"### Tavily Mini-Research Synthesis\n{tav_text}")

    return {
        "dossier": "\n\n".join(dossier_sections),
        "sources": deduped_sources,
        "candidate_code": "",
        "candidate_title": "",
        "c7_snippets": [],
        "tool_outputs": tool_outputs,
    }
