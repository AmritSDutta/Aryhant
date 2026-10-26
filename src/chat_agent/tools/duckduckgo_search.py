"""DuckDuckGo web search engine with ddgs integration and block-scoped HTML fallback."""

import html
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import requests

logger = logging.getLogger(__name__)

DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
DDG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DDG_HEADERS = {
    "User-Agent": DDG_USER_AGENT,
    "Accept": "text/html",
    "Referer": "https://html.duckduckgo.com/",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_real_url(href: str) -> str:
    """Extract and unquote target destination URL from DuckDuckGo uddg redirect or direct link."""
    if not href or re.search(r"duckduckgo\.com/y\.js", href, re.IGNORECASE):
        return ""

    uddg_match = re.search(r"[?&]uddg=([^&]+)", href)
    if uddg_match:
        try:
            candidate = unquote(uddg_match.group(1))
        except Exception:
            return ""
    elif href.startswith("//"):
        candidate = f"https:{href}"
    else:
        candidate = href

    return candidate if re.match(r"^https?://", candidate, re.IGNORECASE) else ""


def is_ddg_challenge_page(html_text: str) -> bool:
    """Detect if DuckDuckGo returned an HTTP 200 bot-challenge or anomaly page."""
    if not html_text or not html_text.strip():
        return True
    if re.search(r'class="[^"]*\bresult\b[^"]*"', html_text, re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"anomaly|unfortunately,?\s*bots|are you a robot|too many requests|challenge-platform|cf-challenge",
            html_text,
            re.IGNORECASE,
        )
    )


def decode_ddg_text(text: str) -> str:
    """Strip tags with space separation, decode HTML entities, and clean whitespace."""
    if not text:
        return ""
    stripped = re.sub(r"<[^>]+>", " ", text)
    unescaped = html.unescape(stripped)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in unescaped.splitlines()]
    return " ".join([line for line in lines if line]).strip()


def parse_ddg_html(
    html_text: str,
    max_results: int = 5,
    max_snippet_len: int = 500,
) -> List[Dict[str, str]]:
    """Parse DuckDuckGo HTML using block segmentation to prevent cross-result snippet drift."""
    results: List[Dict[str, str]] = []
    if not html_text or max_results <= 0:
        return results

    # 1. Primary parser: BeautifulSoup if available
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_text, "html.parser")
        result_elements = soup.find_all("div", class_="result__body")
        for elem in result_elements:
            if len(results) >= max_results:
                break
            title_elem = elem.find("a", class_="result__a")
            if not title_elem:
                continue

            raw_href = title_elem.get("href", "")
            url = extract_real_url(raw_href)
            if not url:
                continue

            title = decode_ddg_text(title_elem.get_text(separator=" ", strip=True)) or url
            snippet_elem = elem.find("a", class_="result__snippet") or elem.find("div", class_="result__snippet")
            snippet = decode_ddg_text(snippet_elem.get_text(separator=" ", strip=True)) if snippet_elem else ""
            snippet = snippet[:max_snippet_len]

            results.append({"title": title, "url": url, "snippet": snippet})

        if results:
            return results
    except (ImportError, ModuleNotFoundError):
        pass

    # 2. Block-scoped regex fallback: isolate each result block before extracting fields
    blocks = re.split(r'class="[^"]*\bresult\b[^"]*"', html_text, flags=re.IGNORECASE)[1:]
    anchor_re = re.compile(r'<a\b([^>]*class="[^"]*result__a[^"]*"[^>]*)>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    snippet_re = re.compile(
        r'(?:<a\b[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|<div\b[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>)',
        re.DOTALL | re.IGNORECASE,
    )
    href_re = re.compile(r'href="([^"]+)"', re.IGNORECASE)

    for block in blocks:
        if len(results) >= max_results:
            break

        anchor_match = anchor_re.search(block)
        if not anchor_match:
            continue

        tag_attrs, raw_title = anchor_match.groups()
        href_match = href_re.search(tag_attrs)
        if not href_match:
            continue

        raw_href = html.unescape(href_match.group(1))
        url = extract_real_url(raw_href)
        if not url:
            continue

        title = decode_ddg_text(raw_title) or url
        snip_match = snippet_re.search(block)
        snippet = ""
        if snip_match:
            s1, s2 = snip_match.groups()
            snippet = decode_ddg_text(s1 or s2 or "")[:max_snippet_len]

        results.append({"title": title, "url": url, "snippet": snippet})

    return results


def search_ddgs_library(query: str, max_results: int = 5) -> Optional[List[Dict[str, Any]]]:
    """Execute search using ddgs (or duckduckgo_search) Python library."""
    try:
        try:
            from ddgs import DDGS
        except (ImportError, ModuleNotFoundError):
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
            return raw if raw else None
    except (ImportError, ModuleNotFoundError) as e_import:
        logger.debug("ddgs library not installed (%s), using REST scraper.", e_import)
        return None
    except Exception as e_ddg:
        logger.info("ddgs library search failed (%s), using REST scraper.", e_ddg)
        return None


def search_duckduckgo_rest(
    query: str,
    max_results: int = 5,
    max_snippet_len: int = 500,
    timeout: float = 10.0,
) -> List[Dict[str, str]]:
    """Execute direct REST search against html.duckduckgo.com with anti-bot headers."""
    trimmed = query.strip()
    if not trimmed:
        return []

    resp = requests.post(
        DDG_HTML_ENDPOINT,
        data={"q": trimmed},
        headers=DDG_HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()

    if is_ddg_challenge_page(resp.text):
        raise RuntimeError("DuckDuckGo returned a bot-challenge page")

    return parse_ddg_html(resp.text, max_results=max_results, max_snippet_len=max_snippet_len)


def search_duckduckgo(
    query: str,
    max_results: int = 5,
    max_snippet_len: int = 500,
) -> List[Dict[str, str]]:
    """Execute DuckDuckGo search: library first, falling back to block-scoped HTML scraper."""
    trimmed = query.strip()
    if not trimmed:
        return []

    # 1. Primary: ddgs library
    raw_items = search_ddgs_library(trimmed, max_results=max_results)
    if raw_items is not None:
        results: List[Dict[str, str]] = []
        for item in raw_items[:max_results]:
            title = decode_ddg_text(str(item.get("title", "")))
            raw_url = str(item.get("href") or item.get("url", ""))
            url = extract_real_url(raw_url) or raw_url
            body = decode_ddg_text(str(item.get("body") or item.get("snippet", "")))[:max_snippet_len]
            results.append({"title": title, "url": url, "snippet": body})
        if results:
            return results

    # 2. Resilient REST fallback
    try:
        return search_duckduckgo_rest(
            trimmed,
            max_results=max_results,
            max_snippet_len=max_snippet_len,
        )
    except Exception as e_rest:
        logger.warning("DuckDuckGo REST fallback failed: %s", e_rest)
        return []
