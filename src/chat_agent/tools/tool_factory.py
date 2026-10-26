"""Tool Factory for managing LLM tool bindings, web search tool pool, and provider functions."""

import abc
import logging
import random
import re
import threading
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import requests
from chat_agent.config import settings
from chat_agent.utils.openai_utility import generate_openai_summary
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SearchProvider(str, Enum):
    """Supported Web Search Providers."""

    TAVILY = "tavily"
    EXA = "exa"
    FIRECRAWL = "firecrawl"
    SERPER = "serper"
    DUCKDUCKGO = "duckduckgo"
    RANDOM = "random"
    AUTO = "auto"


DEFAULT_TOOL_WEIGHTS: Dict[str, float] = {
    SearchProvider.DUCKDUCKGO.value: 25.0,
    SearchProvider.EXA.value: 20.0,
    SearchProvider.FIRECRAWL.value: 25.0,
    SearchProvider.TAVILY.value: 25.0,
    SearchProvider.SERPER.value: 5.0,
}


class SearchResultItem(BaseModel):
    """Normalized individual search result."""

    title: str = ""
    url: str = ""
    content: str = ""
    score: Optional[float] = None
    published_date: Optional[str] = None
    provider: str = ""


def clean_tool_response(text: str) -> str:
    """Removes emojis, control characters, and redundant whitespace from tool outputs."""
    if not text:
        return ""
    text = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27BF\u2300-\u23FF\u2B00-\u2BFF]', '', text)
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class NormalizedSearchResponse(BaseModel):
    """Normalized search response across all web search providers."""

    query: str
    provider: str
    answer: Optional[str] = None
    results: List[SearchResultItem] = Field(default_factory=list)
    raw_response: Optional[Dict[str, Any]] = None

    def to_formatted_string(self) -> str:
        """Format normalized search results into a clean readable string for LLM prompts."""
        if not self.results and not self.answer:
            return ""

        parts = []
        if self.answer:
            parts.append(f"Answer: {self.answer}")

        for i, res in enumerate(self.results, 1):
            title = res.title or "No title"
            url = res.url or ""
            content = res.content or ""
            parts.append(f"{content}")
        response = "\n".join(parts)
        cleaned_response = clean_tool_response(response)
        logger.info(f'search result context: {cleaned_response[:150]}')
        return cleaned_response


class BaseWebSearchTool(abc.ABC):
    """Abstract Base Class for Web Search Provider Tools."""

    def __init__(self, name: str, api_key: Optional[str] = None):
        self.name = name
        self.api_key = api_key

    def is_configured(self) -> bool:
        """Check if the tool has a valid API key configured."""
        if not self.api_key:
            return False
        invalid_defaults = {
            "TAVILY_API_KEY",
            "EXA_API_KEY",
            "FIRECRAWL_API_KEY",
            "SERPER_API_KEY",
            "",
        }
        return self.api_key not in invalid_defaults

    @abc.abstractmethod
    def search(self, query: str, max_results: int = 10, **kwargs) -> NormalizedSearchResponse:
        """Execute web search and return normalized output."""
        pass

    async def search_async(self, query: str, max_results: int = 10, **kwargs) -> NormalizedSearchResponse:
        """Execute async web search in a non-blocking worker thread."""
        import asyncio

        return await asyncio.to_thread(self.search, query, max_results=max_results, **kwargs)


class TavilySearchTool(BaseWebSearchTool):
    """Tavily Search Tool Provider with Keyless-First and TavilyClient Fallback."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(name=SearchProvider.TAVILY.value,
                         api_key=api_key if api_key is not None else settings.TAVILY_API_KEY)

    def is_configured(self) -> bool:
        """Tavily search is always configured via keyless access mode."""
        return True

    def is_keyed(self) -> bool:
        """Check if a valid, non-placeholder Tavily API key is configured."""
        if not self.api_key:
            return False
        invalid_defaults = {"TAVILY_API_KEY", ""}
        return self.api_key not in invalid_defaults

    def search(self, query: str, max_results: int = 10, **kwargs: Any) -> NormalizedSearchResponse:
        """Execute web search using Tavily. Tries keyless first; falls back to TavilyClient on failure."""
        raw_res: Any = None

        # 1. Attempt keyless search first
        try:
            url = "https://api.tavily.com/search"
            headers = {
                "Content-Type": "application/json",
                "X-Tavily-Access-Mode": "keyless",
            }
            payload: Dict[str, Any] = {
                "query": query,
                "max_results": max_results,
                "include_answer": kwargs.get("include_answer", True),
                "search_depth": kwargs.get("search_depth", "basic"),
            }
            for k, v in kwargs.items():
                if k not in payload:
                    payload[k] = v

            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            raw_res = resp.json()
        except Exception as e_keyless:
            logger.info("Tavily keyless search failed (%s). Checking TavilyClient fallback.", e_keyless)

        # 2. Keyed fallback via TavilyClient if configured (do not retry keyed REST on failure)
        if raw_res is None and self.is_keyed():
            try:
                from tavily import TavilyClient

                client = TavilyClient(api_key=self.api_key)
                raw_res = client.search(query=query, max_results=max_results, **kwargs)
            except Exception as e_sdk:
                logger.warning("Tavily client search failed: %s", e_sdk)

        if raw_res is None:
            return NormalizedSearchResponse(
                query=query,
                provider=self.name,
                answer="tavily failed try with some other websearch",
                results=[],
                raw_response={"error": "tavily failed try with some other websearch"},
            )

        answer = None
        results = []

        if isinstance(raw_res, dict):
            answer = raw_res.get("answer")
            raw_items = raw_res.get("results", [])
            for item in raw_items:
                results.append(
                    SearchResultItem(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        content=item.get("content", ""),
                        score=item.get("score"),
                        published_date=item.get("published_date"),
                        provider=self.name,
                    )
                )
        else:
            if hasattr(raw_res, "answer"):
                answer = raw_res.answer
            if hasattr(raw_res, "results"):
                for item in raw_res.results:
                    results.append(
                        SearchResultItem(
                            title=getattr(item, "title", ""),
                            url=getattr(item, "url", ""),
                            content=getattr(item, "content", ""),
                            score=getattr(item, "score", None),
                            published_date=getattr(item, "published_date", None),
                            provider=self.name,
                        )
                    )

        return NormalizedSearchResponse(
            query=query,
            provider=self.name,
            answer=answer,
            results=results,
            raw_response=raw_res if isinstance(raw_res, dict) else None,
        )

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Extract web content from URLs via Tavily /extract. Tries keyless first; falls back to TavilyClient on failure."""
        url = "https://api.tavily.com/extract"

        try:
            headers = {
                "Content-Type": "application/json",
                "X-Tavily-Access-Mode": "keyless",
            }
            payload: Dict[str, Any] = {"urls": urls}
            for k, v in kwargs.items():
                if k not in payload:
                    payload[k] = v
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
        except Exception as e_keyless:
            logger.info("Tavily keyless extract failed (%s). Checking API key fallback.", e_keyless)

        if self.is_keyed():
            try:
                from tavily import TavilyClient

                client = TavilyClient(api_key=self.api_key)
                if hasattr(client, "extract"):
                    data = client.extract(urls=urls, **kwargs)
                    if isinstance(data, dict):
                        return data.get("results", [])
                    return getattr(data, "results", [])
            except Exception as e_sdk:
                logger.warning("Tavily client extract failed: %s", e_sdk)

        return [{"error": "tavily failed try with some other websearch"}]

    async def extract_async(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        """Execute asynchronous URL extraction in a non-blocking worker thread."""
        import asyncio

        return await asyncio.to_thread(self.extract, urls, **kwargs)


class ExaSearchTool(BaseWebSearchTool):
    """Exa (Metaphor) AI Search Tool Provider."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(name=SearchProvider.EXA.value,
                         api_key=api_key if api_key is not None else settings.EXA_API_KEY)

    def search(self, query: str, max_results: int = 10, **kwargs) -> NormalizedSearchResponse:
        url = "https://api.exa.ai/search"
        headers = {
            "x-api-key": self.api_key or "",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "numResults": max_results,
            "contents": {"text": True},
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        raw_res = resp.json()

        results = []
        raw_items = raw_res.get("results", [])
        for item in raw_items:
            content = item.get("text") or item.get("snippet") or item.get("summary", "")
            results.append(
                SearchResultItem(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=content,
                    score=item.get("score"),
                    published_date=item.get("publishedDate"),
                    provider=self.name,
                )
            )

        return NormalizedSearchResponse(
            query=query,
            provider=self.name,
            answer=None,
            results=results,
            raw_response=raw_res,
        )


class FirecrawlSearchTool(BaseWebSearchTool):
    """Firecrawl Search Tool Provider."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            name=SearchProvider.FIRECRAWL.value,
            api_key=api_key if api_key is not None else settings.FIRECRAWL_API_KEY,
        )

    def search(self, query: str, max_results: int = 10, **kwargs) -> NormalizedSearchResponse:
        url = "https://api.firecrawl.dev/v1/search"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "limit": max_results,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        raw_res = resp.json()

        results = []
        data_items = raw_res.get("data", [])
        for item in data_items:
            content = item.get("markdown") or item.get("description") or item.get("content", "")
            results.append(
                SearchResultItem(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=content,
                    provider=self.name,
                )
            )

        return NormalizedSearchResponse(
            query=query,
            provider=self.name,
            answer=None,
            results=results,
            raw_response=raw_res,
        )


class SerperSearchTool(BaseWebSearchTool):
    """Serper.dev Google Search Tool Provider."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(name=SearchProvider.SERPER.value,
                         api_key=api_key if api_key is not None else settings.SERPER_API_KEY)

    def search(self, query: str, max_results: int = 10, **kwargs) -> NormalizedSearchResponse:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": self.api_key or "",
            "Content-Type": "application/json",
        }
        payload = {"q": query, "num": max_results}

        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        raw_res = resp.json()

        answer = raw_res.get("answerBox", {}).get("answer") or raw_res.get("answerBox", {}).get("snippet")
        results = []
        for item in raw_res.get("organic", []):
            results.append(
                SearchResultItem(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    content=item.get("snippet", ""),
                    published_date=item.get("date"),
                    provider=self.name,
                )
            )

        return NormalizedSearchResponse(
            query=query,
            provider=self.name,
            answer=answer,
            results=results,
            raw_response=raw_res,
        )


class DuckDuckGoSearchTool(BaseWebSearchTool):
    """DuckDuckGo Search Tool Provider (No API Key Required)."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(name=SearchProvider.DUCKDUCKGO.value, api_key=api_key)

    def is_configured(self) -> bool:
        """DuckDuckGo requires no API key."""
        return True

    def _search_ddgs_library(self, query: str, max_results: int) -> Optional[List[Dict[str, Any]]]:
        """Try searching via DDGS Python package if installed."""
        try:
            try:
                from ddgs import DDGS
            except (ImportError, ModuleNotFoundError):
                from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except (ImportError, ModuleNotFoundError) as e_import:
            logger.debug(f"DuckDuckGo library package not installed ({e_import}), attempting REST fallback...")
            return None
        except Exception as e_ddg:
            logger.warning(f"DDGS library search failed ({e_ddg}), attempting REST fallback...")
            return None

    def search(self, query: str, max_results: int = 5, **kwargs) -> NormalizedSearchResponse:
        results = []
        raw_res = None
        effective_max = min(max_results, getattr(settings, "DUCKDUCKGO_MAX_RESULTS", 5))
        max_snippet_len = getattr(settings, "SEARCH_MAX_SNIPPET_LENGTH", 500)

        raw_items = self._search_ddgs_library(query, effective_max)

        if raw_items is not None:
            raw_res = {"results": raw_items}
            for item in raw_items[:effective_max]:
                content_text = (item.get("body") or item.get("snippet") or "")[:max_snippet_len]
                results.append(
                    SearchResultItem(
                        title=item.get("title", ""),
                        url=item.get("href") or item.get("url", ""),
                        content=content_text,
                        provider=self.name,
                    )
                )
        else:
            try:
                url = "https://html.duckduckgo.com/html/"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                data = {"q": query}
                resp = requests.post(url, data=data, headers=headers, timeout=10)
                resp.raise_for_status()

                try:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(resp.text, "html.parser")
                    results_elements = soup.find_all("div", class_="result__body")
                    for elem in results_elements[:effective_max]:
                        title_elem = elem.find("a", class_="result__a")
                        snippet_elem = elem.find("a", class_="result__snippet")
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                            href = title_elem.get("href", "")
                            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                            snippet = snippet[:max_snippet_len]
                            results.append(
                                SearchResultItem(
                                    title=title,
                                    url=href,
                                    content=snippet,
                                    provider=self.name,
                                )
                            )
                except (ImportError, ModuleNotFoundError):
                    import html
                    import re

                    pattern = re.compile(
                        r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<a class="result__snippet"[^>]*>(.*?)</a>|<div class="result__snippet"[^>]*>(.*?)</div>)',
                        re.DOTALL | re.IGNORECASE,
                    )
                    for match in pattern.finditer(resp.text):
                        if len(results) >= effective_max:
                            break
                        href, raw_title, snip1, snip2 = match.groups()
                        title = html.unescape(re.sub(r"<[^>]+>", "", raw_title).strip())
                        raw_snip = snip1 or snip2 or ""
                        snippet = html.unescape(re.sub(r"<[^>]+>", "", raw_snip).strip())[:max_snippet_len]
                        if title:
                            results.append(
                                SearchResultItem(
                                    title=title,
                                    url=href,
                                    content=snippet,
                                    provider=self.name,
                                )
                            )
            except Exception as e_rest:
                logger.error(f"DuckDuckGo REST fallback failed: {e_rest}")

        return NormalizedSearchResponse(
            query=query,
            provider=self.name,
            answer=None,
            results=results,
            raw_response=raw_res,
        )


class WebSearchToolPool:
    """Tool pool managing search providers with weighted random tool selection & fallback."""

    def __init__(self, tool_weights: Optional[Dict[str, float]] = None):
        self.tools: Dict[str, BaseWebSearchTool] = {
            SearchProvider.TAVILY.value: TavilySearchTool(),
            SearchProvider.EXA.value: ExaSearchTool(),
            SearchProvider.FIRECRAWL.value: FirecrawlSearchTool(),
            SearchProvider.SERPER.value: SerperSearchTool(),
            SearchProvider.DUCKDUCKGO.value: DuckDuckGoSearchTool(),
        }
        self.call_counts: Dict[str, int] = {name: 0 for name in self.tools}
        self.tool_weights: Dict[str, float] = tool_weights or DEFAULT_TOOL_WEIGHTS.copy()

    def get_tool_usage_counts(self) -> Dict[str, int]:
        """Return in-memory successful search call counts for all tools."""
        return dict(self.call_counts)

    def get_configured_providers(self) -> List[BaseWebSearchTool]:
        """Return list of providers that have valid configured API keys."""
        configured = [tool for tool in self.tools.values() if tool.is_configured()]
        logger.info(f"[WebSearchToolPool] Available search providers: {[t.name for t in configured]}")
        return configured

    def _get_weighted_shuffled_candidates(self, tools: List[BaseWebSearchTool]) -> List[BaseWebSearchTool]:
        """Weighted sampling without replacement based on configured provider weights."""
        available = tools.copy()
        ordered = []
        while available:
            weights = [self.tool_weights.get(t.name, 10.0) for t in available]
            chosen = random.choices(available, weights=weights, k=1)[0]
            ordered.append(chosen)
            available.remove(chosen)
        return ordered

    def search(
            self,
            query: str,
            provider: Optional[Union[str, SearchProvider]] = None,
            max_results: int = 10,
            **kwargs,
    ) -> NormalizedSearchResponse:
        """Search the web using a weighted randomly selected tool or requested provider with fallback."""
        target_provider = provider or settings.DEFAULT_SEARCH_PROVIDER
        if isinstance(target_provider, SearchProvider):
            target_provider = target_provider.value

        configured_tools = self.get_configured_providers()

        # If no tools are explicitly configured with real keys, fall back to all registered tools (e.g., Tavily)
        if not configured_tools:
            configured_tools = list(self.tools.values())

        if target_provider in (SearchProvider.RANDOM.value, SearchProvider.AUTO.value, None):
            candidate_tools = self._get_weighted_shuffled_candidates(configured_tools)
        else:
            primary_tool = self.tools.get(target_provider)
            if primary_tool:
                other_tools = [t for t in configured_tools if t.name != target_provider]
                candidate_tools = [primary_tool] + self._get_weighted_shuffled_candidates(other_tools)
            else:
                candidate_tools = self._get_weighted_shuffled_candidates(configured_tools)

        errors = []
        for tool in candidate_tools:
            try:
                logger.info(
                    f"[WebSearchToolPool] Executing search via provider '{tool.name}' for query: '{query[:50]}'")
                res = tool.search(query=query, max_results=max_results, **kwargs)
                if res.answer == "tavily failed try with some other websearch" and not res.results:
                    logger.warning(f"[WebSearchToolPool] Provider '{tool.name}' failed. Trying fallback...")
                    errors.append(f"{tool.name}: {res.answer}")
                    continue
                self.call_counts[tool.name] = self.call_counts.get(tool.name, 0) + 1
                logger.info(
                    f"✅ [WebSearchToolPool] Provider '{tool.name}' search succeeded! "
                    f"(Call #{self.call_counts[tool.name]} for {tool.name} | Total Pool Usage: {dict(self.call_counts)})"
                )
                return res
            except Exception as e:
                logger.warning(f"[WebSearchToolPool] Provider '{tool.name}' failed: {e}. Trying fallback...")
                errors.append(f"{tool.name}: {e}")

        logger.error(f"[WebSearchToolPool] All candidate providers failed for query '{query}': {errors}")
        failed_answer = "tavily failed try with some other websearch" if any("tavily failed" in err for err in errors) else None
        return NormalizedSearchResponse(
            query=query,
            provider="error",
            answer=failed_answer,
            results=[],
            raw_response={"errors": errors},
        )


_tool_pool: Optional[WebSearchToolPool] = None


def get_search_pool() -> WebSearchToolPool:
    """Get global WebSearchToolPool singleton."""
    global _tool_pool
    if _tool_pool is None:
        _tool_pool = WebSearchToolPool()
    return _tool_pool


def search_web(
    query: str,
    provider: Optional[Union[str, SearchProvider]] = None,
    max_results: int = 10,
    **kwargs,
) -> dict[str, Any]:
    """Search the web for real-time information, research, curriculum questions, and current news."""
    pool = get_search_pool()
    norm_res = pool.search(query=query, provider=provider, max_results=max_results, **kwargs)
    formatted = format_search_response(norm_res)
    return {
        "status": "success" if (norm_res.results or norm_res.answer) else "no_results",
        "query": query,
        "provider": norm_res.provider,
        "answer": norm_res.answer,
        "results": [r.model_dump() for r in norm_res.results],
        "content": formatted,
    }


def extract_web_content(urls: List[str]) -> Dict[str, Any]:
    """Extract clean web page content from URLs using Tavily extract."""
    tool = TavilySearchTool()
    try:
        results = tool.extract(urls)
        return {"status": "success", "results": results}
    except Exception as e:
        logger.error(f"Failed to extract web content from {urls}: {e}")
        return {"status": "error", "error": str(e), "results": []}


def get_search_tool_usage_counts() -> Dict[str, int]:
    """Get total search call counts per tool from the global search pool."""
    return get_search_pool().get_tool_usage_counts()


def format_search_response(search_response: Any) -> str:
    """Helper to format search response or dict into readable text for prompts,
    summarized via generate_summaries as final step."""
    if not search_response:
        return ""

    if isinstance(search_response, NormalizedSearchResponse):
        raw_text = search_response.to_formatted_string()
    elif isinstance(search_response, dict):
        parts = []
        if search_response.get("answer"):
            parts.append(f"Answer: {search_response['answer']}")
        results = search_response.get("results", [])
        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            url = result.get("url", "")
            content = result.get("content", "")
            parts.append(f"\n[{i}] {title}\nURL: {url}\n{content}")
        raw_text = "\n".join(parts)
    else:
        parts = []
        if hasattr(search_response, "answer") and search_response.answer:
            parts.append(f"Answer: {search_response.answer}")
        if hasattr(search_response, "results"):
            for i, result in enumerate(search_response.results, 1):
                title = getattr(result, "title", "No title")
                url = getattr(result, "url", "")
                content = getattr(result, "content", "")
                parts.append(f"\n[{i}] {title}\nURL: {url}\n{content}")
        raw_text = "\n".join(parts)

    return generate_openai_summary(raw_text, model_name="gpt-5-nano") if len(raw_text) > 10000 else raw_text


def get_current_time() -> dict:
    """Return current Indian Standard Time (IST, UTC+5:30) and UTC time as ISO 8601."""
    from datetime import datetime, timedelta, timezone

    ist_tz = timezone(timedelta(hours=5, minutes=30), name="IST")
    now_ist = datetime.now(ist_tz).replace(microsecond=0).isoformat()
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "status": "success",
        "ist_time": now_ist,
        "utc_time": now_utc,
        "timezone": "IST (UTC+5:30)",
    }


def _generate_study_notes_pdf_sync(
    title: str,
    content: str,
    subject: str = "Science",
    tags: Optional[List[str]] = None,
    visual: str = "science",
    margin_tip: str = "",
    channel: Optional[str] = None,
    thread_ts: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Compile the study notes PDF and auto-upload to Slack; executed on a background thread."""
    import os
    logger.info("[Notes Engine] Phase 1: Starting study notes PDF compilation for title: '%s' (subject=%s)", title, subject)
    if output_path and not _is_allowed_upload_path(output_path):
        logger.warning("[Notes Engine] Ignoring output_path outside allowed upload directories: %s", output_path)
        output_path = None
    try:
        from chat_agent.infographics import generate_handwritten_notes_pdf

        target_path = generate_handwritten_notes_pdf(
            title=title,
            content=content,
            tags=tags,
            subject=subject,
            visual=visual,
            margin_tip=margin_tip,
            output_path=output_path,
        )
        file_size = os.path.getsize(target_path)
        logger.info("[Notes Engine] Phase 1: ✅ PDF compiled successfully: %s (%d bytes)", target_path, file_size)

        upload_channel = _normalize_channel_ref(channel)
        upload_thread = _normalize_thread_ts(thread_ts)
        upload_status = "not_requested"
        if upload_channel or settings.slack_http_ready:
            logger.info("[Notes Engine] Phase 2: Triggering auto-upload to Slack (channel=%s, thread_ts=%s)", upload_channel, upload_thread)
            upload_res = upload_file_to_slack(file_path=target_path, channel=upload_channel, thread_ts=upload_thread, title=title)
            upload_status = upload_res.get("status", "queued")
            logger.info("[Notes Engine] Phase 2: Slack upload finished with status=%s for: %s", upload_status, target_path)

        return {
            "status": "success",
            "pdf_path": target_path,
            "file_name": os.path.basename(target_path),
            "file_size_bytes": file_size,
            "title": title,
            "subject": subject,
            "slack_upload": upload_status,
        }
    except Exception as e:
        logger.error("[Notes Engine] Phase 1: ❌ Failed to generate study notes PDF: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "title": title,
        }


def generate_study_notes_pdf(
    title: str,
    content: str,
    subject: str = "Science",
    tags: Optional[List[str]] = None,
    visual: str = "science",
    margin_tip: str = "",
    channel: Optional[str] = None,
    thread_ts: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue study notes PDF compilation and Slack delivery on a background thread; returns immediately so the reply is not blocked."""
    logger.info("[Notes Engine] Queuing background PDF compilation for title: '%s' (subject=%s)", title, subject)
    threading.Thread(
        target=_generate_study_notes_pdf_sync,
        args=(title, content, subject, tags, visual, margin_tip, channel, thread_ts, output_path),
        daemon=True,
    ).start()
    return {
        "status": "queued",
        "title": title,
        "subject": subject,
        "message": "PDF compilation and Slack delivery are running in the background; the file will appear in the thread shortly.",
    }


def _generate_infographic_pdf_sync(
    lesson_data: Dict[str, Any],
    channel: Optional[str] = None,
    thread_ts: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Compile the lesson infographic PDF and auto-upload to Slack; executed on a background thread."""
    import os
    title = lesson_data.get("title", "Lesson Infographic") if isinstance(lesson_data, dict) else "Lesson Infographic"
    logger.info("[Infographic Engine] Phase 1: Starting lesson infographic poster compilation for: '%s'", title)
    if output_path and not _is_allowed_upload_path(output_path):
        logger.warning("[Infographic Engine] Ignoring output_path outside allowed upload directories: %s", output_path)
        output_path = None
    try:
        from chat_agent.infographics import generate_lesson_infographic

        target_path = generate_lesson_infographic(
            lesson_data=lesson_data,
            output_path=output_path,
        )
        file_size = os.path.getsize(target_path)
        logger.info("[Infographic Engine] Phase 1: ✅ Infographic PDF compiled successfully: %s (%d bytes)", target_path, file_size)

        upload_channel = _normalize_channel_ref(channel)
        upload_thread = _normalize_thread_ts(thread_ts)
        upload_status = "not_requested"
        if upload_channel or settings.slack_http_ready:
            logger.info("[Infographic Engine] Phase 2: Triggering auto-upload to Slack (channel=%s, thread_ts=%s)", upload_channel, upload_thread)
            upload_res = upload_file_to_slack(file_path=target_path, channel=upload_channel, thread_ts=upload_thread, title=title)
            upload_status = upload_res.get("status", "queued")
            logger.info("[Infographic Engine] Phase 2: Slack upload finished with status=%s for: %s", upload_status, target_path)

        return {
            "status": "success",
            "pdf_path": target_path,
            "file_name": os.path.basename(target_path),
            "file_size_bytes": file_size,
            "title": title,
            "slack_upload": upload_status,
        }
    except Exception as e:
        logger.error("[Infographic Engine] Phase 1: ❌ Failed to generate infographic PDF: %s", e)
        return {
            "status": "error",
            "error": str(e),
        }


def generate_infographic_pdf(
    lesson_data: Dict[str, Any],
    channel: Optional[str] = None,
    thread_ts: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue lesson infographic PDF compilation and Slack delivery on a background thread; returns immediately so the reply is not blocked."""
    title = lesson_data.get("title", "Lesson Infographic") if isinstance(lesson_data, dict) else "Lesson Infographic"
    logger.info("[Infographic Engine] Queuing background PDF compilation for: '%s'", title)
    threading.Thread(
        target=_generate_infographic_pdf_sync,
        args=(lesson_data, channel, thread_ts, output_path),
        daemon=True,
    ).start()
    return {
        "status": "queued",
        "title": title,
        "message": "Infographic compilation and Slack delivery are running in the background; the file will appear in the thread shortly.",
    }


def _is_allowed_upload_path(file_path: str) -> bool:
    """Allow uploads only from the agent-generated PDF output directories."""
    import tempfile
    from pathlib import Path

    resolved = Path(file_path).resolve()
    allowed_roots = [
        (Path(tempfile.gettempdir()) / "aryhant_notes").resolve(),
        (Path(tempfile.gettempdir()) / "aryhant_infographics").resolve(),
    ]
    return any(resolved.is_relative_to(root) for root in allowed_roots)


def _normalize_channel_ref(channel: Any) -> str:
    """Coerce a model-provided channel argument (dict or str) into a plain channel ID string."""
    if isinstance(channel, dict):
        for key in ("channel_id", "channel", "id"):
            value = channel.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(channel, str):
        return channel.strip()
    return ""


def _normalize_thread_ts(thread_ts: Any) -> str:
    """Coerce a model-provided thread_ts (float or str) into a plain string."""
    if thread_ts is None:
        return ""
    return str(thread_ts).strip()


def _upload_file_to_slack_sync(
    file_path: str,
    channel: str,
    thread_ts: str,
    title: str,
    initial_comment: str,
    token: str,
) -> Dict[str, Any]:
    """Run the blocking 3-step Slack external upload; executed on a background thread."""
    import os
    import httpx

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    doc_title = title or file_name

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        with httpx.Client(timeout=30.0) as client:
            # Step 1: Request upload URL
            get_url_resp = client.post(
                "https://slack.com/api/files.getUploadURLExternal",
                headers={"Authorization": f"Bearer {token}"},
                data={"filename": file_name, "length": file_size},
            )
            url_data = get_url_resp.json()
            if not url_data.get("ok"):
                logger.error("files.getUploadURLExternal failed: %s", url_data)
                return {
                    "status": "error",
                    "error": url_data.get("error", "Failed to get upload URL"),
                    "file_path": file_path,
                }

            upload_url = url_data["upload_url"]
            file_id = url_data["file_id"]

            # Step 2: Upload file bytes
            upload_resp = client.post(
                upload_url,
                content=file_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
            if upload_resp.status_code != 200:
                logger.error("Upload to Slack external URL failed: status %d", upload_resp.status_code)
                return {
                    "status": "error",
                    "error": f"Upload HTTP status {upload_resp.status_code}",
                    "file_path": file_path,
                }

            # Step 3: Complete upload
            complete_payload = {
                "files": [{"id": file_id, "title": doc_title}],
                "channel_id": channel,
            }
            if thread_ts:
                complete_payload["thread_ts"] = thread_ts
            if initial_comment:
                complete_payload["initial_comment"] = initial_comment

            complete_resp = client.post(
                "https://slack.com/api/files.completeUploadExternal",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=complete_payload,
            )
            comp_data = complete_resp.json()
            if not comp_data.get("ok"):
                logger.error("files.completeUploadExternal failed: %s", comp_data)
                return {
                    "status": "error",
                    "error": comp_data.get("error", "Failed to complete upload"),
                    "file_path": file_path,
                }

            return {
                "status": "success",
                "file_id": file_id,
                "file_name": file_name,
                "channel": channel,
                "thread_ts": thread_ts,
            }
    except Exception as err:
        logger.error("Exception uploading file to Slack: %s", err)
        return {
            "status": "error",
            "error": str(err),
            "file_path": file_path,
        }


def upload_file_to_slack(
    file_path: str,
    channel: str = "",
    thread_ts: str = "",
    title: str = "",
    initial_comment: str = "",
) -> Dict[str, Any]:
    """Queue upload of a local file (e.g. PDF study notes) to a Slack thread on a background thread and return immediately."""
    import os

    channel = _normalize_channel_ref(channel)
    thread_ts = _normalize_thread_ts(thread_ts)

    if not os.path.isfile(file_path):
        return {
            "status": "error",
            "error": f"File not found at path: {file_path}",
            "file_path": file_path,
        }

    if not _is_allowed_upload_path(file_path):
        return {
            "status": "error",
            "error": "Uploads are restricted to generated study notes and infographics directories.",
            "file_path": file_path,
        }

    token = settings.slack_bot_token
    if not token or not channel:
        return {
            "status": "skipped",
            "reason": "Slack bot token or target channel not configured.",
            "file_path": file_path,
        }

    threading.Thread(
        target=_upload_file_to_slack_sync,
        args=(file_path, channel, thread_ts, title, initial_comment, token),
        daemon=True,
    ).start()
    return {
        "status": "queued",
        "file_path": file_path,
        "file_name": os.path.basename(file_path),
        "channel": channel,
        "thread_ts": thread_ts,
    }