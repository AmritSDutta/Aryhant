from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

from chat_agent.research.models import ResearchMode, ResearchSource, ToolOutputEntry
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
    """Gather 4-stream intelligence (SerpApi, Tavily, Context7, WebSearch) with 24-hour tool-level caching."""
    is_tech = mode == ResearchMode.TECHNICAL
    sources: list[ResearchSource] = []
    now = time.time()
    tool_outputs: dict[str, ToolOutputEntry] = dict(cached_tool_outputs or {})

    # 1. Google AI Overview via SerpApi
    gai_entry = tool_outputs.get("serpapi")
    if _is_fresh_entry(gai_entry):
        logger.info("[SerpApi] Reusing cached Google AI Overview for %r", topic)
        gai_res = gai_entry.data if isinstance(gai_entry.data, dict) else {}
        gai_task = None
    else:
        if on_status_update:
            await on_status_update("Querying Google AI Overview...")
        gai_task = asyncio.create_task(fetch_google_ai_overview(topic))

    # 2. Tavily Mini-Research with async polling
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

    # 3. Context7 code search (for technical mode)
    c7_entry = tool_outputs.get("context7")
    if is_tech:
        if _is_fresh_entry(c7_entry):
            logger.info("[Context7] Reusing cached Context7 code for %r", topic)
            c7_res = c7_entry.data if isinstance(c7_entry.data, dict) else {}
            c7_task = None
        else:
            c7_task = asyncio.create_task(search_context7(topic))
    else:
        c7_res = {"status": "skipped", "code_snippets": [], "info_snippets": []}
        c7_task = None

    # 4. WebSearchToolPool queries
    ws_entry = tool_outputs.get("websearch")
    if _is_fresh_entry(ws_entry):
        logger.info("[WebSearchPool] Reusing cached web search findings for %r", topic)
        ws_data = ws_entry.data if isinstance(ws_entry.data, dict) else {}
        pool_snippets = list(ws_data.get("snippets") or [])
        cached_sources = ws_data.get("sources") or []
        for s in cached_sources:
            if isinstance(s, dict):
                sources.append(ResearchSource(**s))
            elif isinstance(s, ResearchSource):
                sources.append(s)
        search_tasks = []
    else:
        subqueries = generate_subqueries(topic, mode)
        pool = get_search_pool()

        async def _run_search(q: str) -> dict[str, Any]:
            return await pool.search_async(q, max_results=3)

        search_tasks = [asyncio.create_task(_run_search(q)) for q in subqueries]
        pool_snippets = []

    # Await pending async tasks
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
    if c7_task:
        c7_res = await c7_task
        status_ok = c7_res.get("status") != "error"
        tool_outputs["context7"] = ToolOutputEntry(
            status="ok" if status_ok else "failed",
            fetched_at=now,
            data=c7_res,
        )
    if search_tasks:
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
        websearch_sources: list[dict[str, str]] = []
        for r in search_results:
            if isinstance(r, Exception):
                continue
            if hasattr(r, "results"):
                for item in getattr(r, "results", []):
                    title = getattr(item, "title", "")
                    url = getattr(item, "url", "")
                    content = getattr(item, "content", "")
                    if url:
                        src = ResearchSource(title=title, url=url, snippet=content[:180], provider="WebSearchPool")
                        sources.append(src)
                        websearch_sources.append(src.model_dump())
                    if content:
                        pool_snippets.append(f"[{title}] {content}")
        tool_outputs["websearch"] = ToolOutputEntry(
            status="ok",
            fetched_at=now,
            data={"snippets": pool_snippets, "sources": websearch_sources},
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

    # Extract Context7 code snippets
    c7_snippets = c7_res.get("code_snippets", [])

    # Extract candidate Context7 code for Sandbox verification (technical mode)
    candidate_code: str = ""
    candidate_title: str = ""
    if is_tech and c7_snippets:
        for c in c7_snippets:
            c_code = (c.get("code") or "").strip()
            if c_code and len(c_code.splitlines()) < 30:
                candidate_code = c_code
                candidate_title = c.get("title", "Context7 Snippet")
                break

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
        "tool_outputs": tool_outputs,
    }
