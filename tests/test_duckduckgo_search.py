"""Unit tests for modular DuckDuckGo search engine and scraper."""

from unittest.mock import MagicMock, patch
import pytest

from chat_agent.tools.duckduckgo_search import (
    decode_ddg_text,
    extract_real_url,
    is_ddg_challenge_page,
    parse_ddg_html,
    search_ddgs_library,
    search_duckduckgo,
    search_duckduckgo_rest,
)
from chat_agent.tools.tool_factory import DuckDuckGoSearchTool


def test_extract_real_url():
    # 1. Unwraps uddg redirect
    redirect = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FFastAPI&rut=1"
    assert extract_real_url(redirect) == "https://en.wikipedia.org/wiki/FastAPI"

    # 2. Filters ad trackers
    ad_link = "https://duckduckgo.com/y.js?ad_domain=example.com"
    assert extract_real_url(ad_link) == ""

    # 3. Direct http/https URLs
    direct = "https://python.org"
    assert extract_real_url(direct) == "https://python.org"

    # 4. Non-http URLs
    assert extract_real_url("javascript:void(0)") == ""
    assert extract_real_url("") == ""


def test_is_ddg_challenge_page():
    assert is_ddg_challenge_page("") is True
    assert is_ddg_challenge_page("   ") is True
    assert is_ddg_challenge_page("<html><body>Unfortunately, bots are not allowed</body></html>") is True
    assert is_ddg_challenge_page("<html><body>cf-challenge error</body></html>") is True
    assert is_ddg_challenge_page("<html><body>anomaly detected</body></html>") is True
    assert is_ddg_challenge_page('<html><div class="result__body">results</div></html>') is False


def test_decode_ddg_text():
    raw = "<b>FastAPI</b> &amp; <i>Python</i> &quot;web&quot; &#39;framework&#39;."
    assert decode_ddg_text(raw) == "FastAPI & Python \"web\" 'framework'."


def test_parse_ddg_html_bs4_and_block_scoped_regex():
    sample_html = """
    <html>
      <body>
        <div class="result results_links results_links_deep web-result">
          <div class="result__body">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsite1.com&rut=1">Site <b>One</b></a>
            <a class="result__snippet">Snippet for site one.</a>
          </div>
        </div>
        <div class="result results_links results_links_deep web-result">
          <div class="result__body">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsite2.com&rut=1">Site Two</a>
            <!-- No snippet in site two -->
          </div>
        </div>
        <div class="result results_links results_links_deep web-result">
          <div class="result__body">
            <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsite3.com&rut=1">Site Three</a>
            <div class="result__snippet">Snippet for site three.</div>
          </div>
        </div>
      </body>
    </html>
    """
    # 1. Parse using BeautifulSoup (or fallback)
    results = parse_ddg_html(sample_html, max_results=5)
    assert len(results) == 3
    assert results[0]["title"] == "Site One"
    assert results[0]["url"] == "https://site1.com"
    assert results[0]["snippet"] == "Snippet for site one."

    # Verify site 2 does NOT inherit site 3's snippet (no snippet drift)
    assert results[1]["title"] == "Site Two"
    assert results[1]["url"] == "https://site2.com"
    assert results[1]["snippet"] == ""

    assert results[2]["title"] == "Site Three"
    assert results[2]["url"] == "https://site3.com"
    assert results[2]["snippet"] == "Snippet for site three."

    # 2. Force regex fallback by simulating bs4 not installed
    with patch.dict("sys.modules", {"bs4": None}):
        results_regex = parse_ddg_html(sample_html, max_results=5)
        assert len(results_regex) == 3
        assert results_regex[0]["url"] == "https://site1.com"
        assert results_regex[1]["snippet"] == ""  # Zero snippet drift in regex mode
        assert results_regex[2]["snippet"] == "Snippet for site three."


def test_search_ddgs_library_success_and_failure():
    # Success
    mock_ddgs_inst = MagicMock()
    mock_ddgs_inst.text.return_value = [{"title": "T", "href": "https://t.com", "body": "B"}]
    mock_ddgs_cls = MagicMock()
    mock_ddgs_cls.return_value.__enter__.return_value = mock_ddgs_inst

    with patch.dict("sys.modules", {"ddgs": MagicMock(DDGS=mock_ddgs_cls)}):
        res = search_ddgs_library("test", max_results=3)
        assert len(res) == 1
        assert res[0]["title"] == "T"

    # Failure / not installed
    with patch.dict("sys.modules", {"ddgs": None, "duckduckgo_search": None}):
        assert search_ddgs_library("test") is None


def test_search_duckduckgo_rest_success_and_challenge_error():
    mock_resp = MagicMock()
    mock_resp.text = """
    <div class="result">
        <a class="result__a" href="https://example.com">Example Title</a>
        <a class="result__snippet">Example Snippet</a>
    </div>
    """
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp):
        res = search_duckduckgo_rest("test query")
        assert len(res) == 1
        assert res[0]["title"] == "Example Title"
        assert res[0]["url"] == "https://example.com"

    # Bot challenge page raises RuntimeError
    mock_challenge_resp = MagicMock()
    mock_challenge_resp.text = "<html><body>Unfortunately, bots are not allowed</body></html>"
    mock_challenge_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_challenge_resp):
        with pytest.raises(RuntimeError, match="bot-challenge"):
            search_duckduckgo_rest("test query")


def test_search_duckduckgo_orchestration():
    # 1. Library returns items -> uses library results
    mock_library_items = [{"title": "Lib", "href": "https://lib.com", "body": "Lib Body"}]
    with patch("chat_agent.tools.duckduckgo_search.search_ddgs_library", return_value=mock_library_items):
        res = search_duckduckgo("query")
        assert len(res) == 1
        assert res[0]["title"] == "Lib"
        assert res[0]["url"] == "https://lib.com"

    # 2. Library fails -> falls back to REST
    mock_rest_items = [{"title": "REST", "url": "https://rest.com", "snippet": "REST Snippet"}]
    with patch("chat_agent.tools.duckduckgo_search.search_ddgs_library", return_value=None), \
         patch("chat_agent.tools.duckduckgo_search.search_duckduckgo_rest", return_value=mock_rest_items):
        res = search_duckduckgo("query")
        assert len(res) == 1
        assert res[0]["title"] == "REST"
        assert res[0]["url"] == "https://rest.com"


def test_duckduckgo_search_tool_integration():
    tool = DuckDuckGoSearchTool()
    assert tool.is_configured() is True

    mock_items = [{"title": "Doc", "url": "https://doc.com", "snippet": "Body"}]
    with patch("chat_agent.tools.tool_factory.search_duckduckgo", return_value=mock_items):
        norm_res = tool.search("query", max_results=3)
        assert norm_res.provider == "duckduckgo"
        assert len(norm_res.results) == 1
        assert norm_res.results[0].title == "Doc"
        assert norm_res.results[0].url == "https://doc.com"
        assert norm_res.results[0].content == "Body"
