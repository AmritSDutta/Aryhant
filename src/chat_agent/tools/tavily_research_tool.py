from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable, Coroutine

from chat_agent.config import settings

logger = logging.getLogger(__name__)


async def run_tavily_mini_research_polling(
    query: str,
    session_id: str = "",
    human_id: str = "",
    max_poll_seconds: float = 60.0,
    poll_interval: float = 4.0,
    on_status_update: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Execute Tavily Mini-Research with async polling, session tracking, and fallback."""
    key = api_key or getattr(settings, "TAVILY_API_KEY", "") or ""
    if not key:
        logger.info("[Tavily] ⏸ Skipped Tavily mini-research: TAVILY_API_KEY unconfigured.")
        return {"status": "skipped", "content": "", "sources": []}

    clean_query = query.strip()
    if not clean_query:
        return {"status": "empty_query", "content": "", "sources": []}

    current_date = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%B %Y")
    tavily_query = f"As of {current_date}, {clean_query}" if not clean_query.lower().startswith("as of") else clean_query

    logger.info("[Tavily] ▶ Starting Tavily mini-research for query: %r (session_id=%s)", tavily_query, session_id)

    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        logger.warning("tavily package not installed; skipping Tavily mini-research.")
        return {"status": "missing_dependency", "content": "", "sources": []}

    client = AsyncTavilyClient(api_key=key)
    try:
        kwargs: dict[str, Any] = {
            "input": tavily_query,
            "model": "mini",
            "citation_format": "numbered",
        }
        if session_id:
            kwargs["session_id"] = session_id
        if human_id:
            kwargs["human_id"] = human_id

        task = await client.research(**kwargs)
        if not isinstance(task, dict):
            return {"status": "failed", "content": "", "sources": []}

        request_id = str(task.get("request_id") or "")
        if not request_id:
            return {"status": "failed", "content": "", "sources": []}

        elapsed = 0.0
        while elapsed < max_poll_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            res = await client.get_research(request_id)
            current_status = str(res.get("status") or "").lower()

            if on_status_update:
                try:
                    await on_status_update(f"Tavily Mini-Research ({current_status}... {int(elapsed)}s)")
                except Exception as status_err:
                    logger.debug("Status update callback notice: %s", status_err)

            if current_status == "completed":
                raw_sources = res.get("sources") or []
                sources: list[dict[str, str]] = [
                    {
                        "title": str(s.get("title") or "Source"),
                        "url": str(s.get("url") or ""),
                    }
                    for s in raw_sources
                    if isinstance(s, dict) and s.get("url")
                ]
                logger.info("[Tavily] ⏹ Completed Tavily mini-research for query: %r (status=completed, elapsed=%.2fs, sources=%d)", tavily_query, elapsed, len(sources))
                return {
                    "status": "completed",
                    "content": str(res.get("content") or ""),
                    "sources": sources,
                    "request_id": request_id,
                }
            if current_status == "failed":
                err_msg = str(res.get("error") or "Unknown error")
                logger.warning("Tavily research task %s failed: %s", request_id, err_msg)
                logger.info("[Tavily] ⏹ Completed Tavily mini-research (status=failed, elapsed=%.2fs, error=%s)", elapsed, err_msg)
                return {"status": "failed", "error": err_msg, "content": "", "sources": []}

        logger.warning("Tavily research task %s timed out after %ds", request_id, int(max_poll_seconds))
        logger.info("[Tavily] ⏹ Completed Tavily mini-research (status=timeout, elapsed=%.2fs)", elapsed)
        return {"status": "timeout", "content": "", "sources": []}
    except Exception as exc:
        logger.warning("Tavily mini-research polling exception: %s", exc)
        logger.info("[Tavily] ⏹ Completed Tavily mini-research with error: %s", exc)
        return {"status": "error", "error": str(exc), "content": "", "sources": []}
