from __future__ import annotations

import logging
from typing import Any

import httpx

from chat_agent.config import settings

logger = logging.getLogger(__name__)


async def fetch_google_ai_overview(query: str, api_key: str | None = None) -> dict[str, Any]:
    """Fetch Google AI Overview text blocks and citations from SerpApi."""
    key = api_key or getattr(settings, "SERPAPI_API_KEY", "") or ""
    if not key:
        logger.info("[SerpApi] \u23f9 Skipped Google AI Overview: SERPAPI_API_KEY unconfigured.")
        return {"status": "skipped", "text": "", "references": []}

    clean_query = query.strip()
    logger.info("[SerpApi] \u25b6 Starting Google AI Overview fetch for query: %r", clean_query)
    if not clean_query:
        return {"status": "empty_query", "text": "", "references": []}

    async with httpx.AsyncClient(timeout=25.0) as client:
        try:
            resp = await client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google",
                    "q": clean_query,
                    "api_key": key,
                    "gl": "us",
                    "hl": "en",
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            ai_data: dict[str, Any] = data.get("ai_overview") or {}

            page_token = ai_data.get("page_token")
            if page_token:
                overview_resp = await client.get(
                    "https://serpapi.com/search",
                    params={
                        "engine": "google_ai_overview",
                        "page_token": page_token,
                        "api_key": key,
                    },
                )
                overview_resp.raise_for_status()
                ai_data = overview_resp.json().get("ai_overview") or ai_data

            text_blocks: list[dict[str, Any]] = ai_data.get("text_blocks") or []
            raw_refs: list[dict[str, Any]] = ai_data.get("references") or []

            text_parts: list[str] = []
            for block in text_blocks:
                b_type = block.get("type")
                if b_type == "paragraph" and block.get("snippet"):
                    text_parts.append(str(block["snippet"]).strip())
                elif b_type == "list" and block.get("list"):
                    for item in block["list"]:
                        title = item.get("title", "").strip()
                        snippet = item.get("snippet", "").strip()
                        if title and snippet:
                            text_parts.append(f"- **{title}**: {snippet}")
                        elif snippet:
                            text_parts.append(f"- {snippet}")

            references: list[dict[str, str]] = [
                {
                    "title": str(r.get("title") or "Source"),
                    "url": str(r.get("link") or ""),
                    "snippet": str(r.get("snippet") or ""),
                }
                for r in raw_refs
                if r.get("link")
            ]

            summary_text = "\n\n".join(text_parts).strip()
            status_val = "success" if summary_text else "no_overview"
            logger.info("[SerpApi] \u23f9 Completed Google AI Overview fetch for query: %r (status=%s, refs=%d, chars=%d)", clean_query, status_val, len(references), len(summary_text))
            return {
                "status": "success" if summary_text else "no_overview",
                "text": summary_text,
                "references": references,
            }
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code in (401, 403):
                logger.warning("SerpApi request rejected (HTTP %s): Check or reset SERPAPI_API_KEY.", status_code)
            else:
                logger.warning("SerpApi request failed with HTTP %s for %s", status_code, getattr(exc.request.url, "path", "/search"))
            logger.info("[SerpApi] \u23f9 Completed Google AI Overview fetch with HTTP error (HTTP %s)", status_code)
            return {"status": "error", "error": f"HTTP {status_code}", "text": "", "references": []}
        except Exception as exc:
            logger.warning("SerpApi Google AI Overview query failed: %s", type(exc).__name__)
            logger.info("[SerpApi] \u23f9 Completed Google AI Overview fetch with error: %s", type(exc).__name__)
            return {"status": "error", "error": type(exc).__name__, "text": "", "references": []}
