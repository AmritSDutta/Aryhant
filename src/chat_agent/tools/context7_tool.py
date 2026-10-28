from __future__ import annotations

import logging
from typing import Any

import httpx

from chat_agent.config import settings

logger = logging.getLogger(__name__)


async def search_context7(
    query: str,
    library: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Search Context7 v3 API exclusively for finding coding documentation, library APIs, and verified code snippets.

    Note: This tool is strictly for software libraries and technical coding documentation. It is NOT for general, domain, or market research.
    """
    key = api_key or getattr(settings, "CONTEXT7_API_KEY", "") or ""
    if not key:
        logger.info("CONTEXT7_API_KEY unconfigured; skipping Context7 search.")
        return {"status": "skipped", "code_snippets": [], "info_snippets": []}

    clean_query = query.strip()
    if not clean_query:
        return {"status": "empty_query", "code_snippets": [], "info_snippets": []}

    headers: dict[str, str] = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    params: dict[str, str] = {
        "query": clean_query,
        "type": "json",
    }
    if library:
        params["library"] = library.strip()

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(
                "https://context7.com/api/v3/search",
                headers=headers,
                params=params,
            )
            if resp.status_code == 404:
                logger.info("Context7: no library or code snippets found for query %r (HTTP 404).", clean_query)
                return {"status": "not_found", "code_snippets": [], "info_snippets": []}
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

            code_items: list[dict[str, Any]] = data.get("codeSnippets") or []
            info_items: list[dict[str, Any]] = data.get("infoSnippets") or []

            code_snippets: list[dict[str, str]] = []
            for item in code_items:
                if isinstance(item, dict):
                    code_snippets.append({
                        "library_id": str(item.get("libraryId") or ""),
                        "title": str(item.get("codeTitle") or item.get("title") or "Code Snippet"),
                        "code": str(item.get("code") or item.get("content") or "").strip(),
                    })

            info_snippets: list[dict[str, str]] = []
            for item in info_items:
                if isinstance(item, dict):
                    info_snippets.append({
                        "library_id": str(item.get("libraryId") or ""),
                        "content": str(item.get("content") or "").strip(),
                    })

            return {
                "status": "success",
                "code_snippets": code_snippets,
                "info_snippets": info_snippets,
            }
        except Exception as exc:
            logger.warning("Context7 search request failed: %s", exc)
            return {"status": "error", "error": str(exc), "code_snippets": [], "info_snippets": []}
