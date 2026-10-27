from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from chat_agent.research.models import ResearchMode, ResearchSource
from chat_agent.tools.context7_tool import search_context7
from chat_agent.tools.sandbox_tool import execute_code_in_sandbox
from chat_agent.tools.serpapi_tool import fetch_google_ai_overview
from chat_agent.tools.tavily_research_tool import run_tavily_mini_research_polling
from chat_agent.tools.tool_factory import get_search_pool

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


async def gather_research_intelligence(
    topic: str,
    mode: ResearchMode,
    session_id: str = "",
    user_id: str = "",
    visual_notes: str = "",
    on_status_update: Callable[[str], Coroutine[Any, Any, None]] | None = None,
) -> dict[str, Any]:
    """Gather triple-source intelligence: Google AI Overview, Tavily Mini-Research, Context7, and WebSearch."""
    is_tech = mode == ResearchMode.TECHNICAL
    sources: list[ResearchSource] = []

    # 1. Google AI Overview via SerpApi
    if on_status_update:
        await on_status_update("Querying Google AI Overview...")
    gai_task = asyncio.create_task(fetch_google_ai_overview(topic))

    # 2. Tavily Mini-Research with async polling
    tav_task = asyncio.create_task(
        run_tavily_mini_research_polling(
            query=topic,
            session_id=session_id,
            human_id=user_id,
            on_status_update=on_status_update,
        )
    )

    # 3. Context7 code search (for technical mode)
    c7_task = asyncio.create_task(search_context7(topic)) if is_tech else None

    # 4. WebSearchToolPool queries
    subqueries = generate_subqueries(topic, mode)
    pool = get_search_pool()

    async def _run_search(q: str) -> dict[str, Any]:
        return await pool.search_async(q, max_results=3)

    search_tasks = [asyncio.create_task(_run_search(q)) for q in subqueries]

    # Wait for all intelligence streams concurrently
    gai_res, tav_res = await asyncio.gather(gai_task, tav_task)
    c7_res = await c7_task if c7_task else {"status": "skipped", "code_snippets": [], "info_snippets": []}
    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

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

    # Extract Context7 code snippets
    c7_snippets = c7_res.get("code_snippets", [])

    # Extract WebSearchToolPool snippets
    pool_snippets: list[str] = []
    for r in search_results:
        if isinstance(r, Exception):
            continue
        if hasattr(r, "results"):
            for item in getattr(r, "results", []):
                title = getattr(item, "title", "")
                url = getattr(item, "url", "")
                content = getattr(item, "content", "")
                if url:
                    sources.append(ResearchSource(title=title, url=url, snippet=content[:180], provider="WebSearchPool"))
                if content:
                    pool_snippets.append(f"[{title}] {content}")

    # Extract candidate Context7 code for Sandbox verification (technical mode)
    candidate_code: str = ""
    candidate_title: str = ""
    if is_tech and c7_snippets:
        candidate_code = c7_snippets[0].get("code", "")
        candidate_title = c7_snippets[0].get("title", "Context7 Snippet")

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
    if c7_snippets:
        c7_block: list[str] = ["### Context7 Verified Code Snippets"]
        for c in c7_snippets[:3]:
            c7_block.append(f"#### {c.get('title')} ({c.get('library_id')})\n```\n{c.get('code')}\n```")
        dossier_sections.append("\n".join(c7_block))
    if pool_snippets:
        dossier_sections.append("### Web Search Findings\n" + "\n\n".join(pool_snippets[:6]))

    return {
        "dossier": "\n\n".join(dossier_sections),
        "sources": deduped_sources,
        "candidate_code": candidate_code,
        "candidate_title": candidate_title,
        "c7_snippets": c7_snippets,
    }
