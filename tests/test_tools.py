"""Hermetic unit tests for Search Tool Providers, Tool Pool, and text utilities."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from chat_agent.tools.tool_factory import (
    BaseWebSearchTool,
    DuckDuckGoSearchTool,
    ExaSearchTool,
    NormalizedSearchResponse,
    SearchProvider,
    SearchResultItem,
    TavilySearchTool,
    WebSearchToolPool,
    clean_tool_response,
    format_search_response,
)
from chat_agent.utils.openai_utility import (
    clean_text_response,
    generate_openai_summary,
    generate_openai_summary_async,
)
from chat_agent.utils.path_utils import resolve_csv_path


def test_clean_tool_response_removes_emojis_and_whitespace():
    raw = "  Hello 🚀 world! \t\n\n\n\nNew paragraph.  "
    cleaned = clean_tool_response(raw)
    assert "🚀" not in cleaned
    assert cleaned == "Hello world!\n\nNew paragraph."


def test_normalized_search_response_formatting():
    item1 = SearchResultItem(title="Doc 1", url="https://example.com/1", content="Content 1")
    item2 = SearchResultItem(title="Doc 2", url="https://example.com/2", content="Content 2")
    norm = NormalizedSearchResponse(query="test", provider="tavily", results=[item1, item2])
    formatted = norm.to_formatted_string()
    assert "Content 1" in formatted
    assert "Content 2" in formatted


def test_is_configured_logic():
    tool_configured = TavilySearchTool(api_key="tvly-actual-key")
    assert tool_configured.is_configured() is True
    assert tool_configured.is_keyed() is True

    tool_unconfigured = TavilySearchTool(api_key="TAVILY_API_KEY")
    assert tool_unconfigured.is_configured() is True
    assert tool_unconfigured.is_keyed() is False

    tool_empty = TavilySearchTool(api_key="")
    assert tool_empty.is_configured() is True
    assert tool_empty.is_keyed() is False

    tool_exa = ExaSearchTool(api_key="EXA_API_KEY")
    assert tool_exa.is_configured() is False


def test_tavily_search_keyless_success():
    import requests

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "answer": "Keyless answer",
        "results": [{"title": "Keyless Title", "url": "https://keyless.com", "content": "Keyless Body"}],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp) as mock_post:
        tool = TavilySearchTool(api_key="")
        res = tool.search(query="python fastapi")
        assert res.provider == "tavily"
        assert res.answer == "Keyless answer"
        assert len(res.results) == 1
        assert res.results[0].title == "Keyless Title"

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert call_args[0] == "https://api.tavily.com/search"
        assert call_kwargs["headers"].get("X-Tavily-Access-Mode") == "keyless"
        assert "Authorization" not in call_kwargs["headers"]
        assert "api_key" not in call_kwargs["json"]


def test_tavily_search_keyless_failure_fallback_to_sdk():
    import requests

    mock_tavily_inst = MagicMock()
    mock_tavily_inst.search.return_value = {
        "results": [{"title": "SDK Title", "url": "https://sdk.com", "content": "SDK Body"}]
    }
    mock_cls = MagicMock(return_value=mock_tavily_inst)
    mock_mod = MagicMock(TavilyClient=mock_cls)

    with patch("requests.post", side_effect=requests.RequestException("Rate limited")), \
         patch.dict("sys.modules", {"tavily": mock_mod, "tavily.tavily": mock_mod}):
        tool = TavilySearchTool(api_key="tvly-keyed-token")
        res = tool.search(query="python fastapi")
        assert len(res.results) == 1
        assert res.results[0].title == "SDK Title"
        mock_tavily_inst.search.assert_called_once_with(query="python fastapi", max_results=10)


def test_tavily_search_failure_returns_tavily_failed_message():
    import requests

    # 1. Unkeyed tool failure
    with patch("requests.post", side_effect=requests.RequestException("429 Too Many Requests")):
        tool = TavilySearchTool(api_key="")
        res = tool.search(query="python fastapi")
        assert res.answer == "tavily failed try with some other websearch"
        assert len(res.results) == 0
        assert res.provider == "tavily"

    # 2. Keyed tool where SDK also fails (no 3rd retry, return failed message directly)
    mock_tavily_mod = MagicMock()
    mock_tavily_mod.TavilyClient.side_effect = Exception("SDK connection error")
    with patch("requests.post", side_effect=requests.RequestException("Keyless rate limit")), \
         patch.dict("sys.modules", {"tavily": mock_tavily_mod}):
        tool_keyed = TavilySearchTool(api_key="tvly-secret")
        res_keyed = tool_keyed.search(query="python fastapi")
        assert res_keyed.answer == "tavily failed try with some other websearch"
        assert len(res_keyed.results) == 0


def test_web_search_tool_pool_tavily_failure_falls_back():
    import requests

    pool = WebSearchToolPool()
    tavily_tool = pool.tools[SearchProvider.TAVILY.value]
    ddg_tool = pool.tools[SearchProvider.DUCKDUCKGO.value]

    mock_ddg_res = NormalizedSearchResponse(
        query="test",
        provider="duckduckgo",
        results=[SearchResultItem(title="DDG Result", url="https://ddg.com", content="DDG Body")]
    )

    with patch.object(tavily_tool, "search", return_value=NormalizedSearchResponse(
        query="test", provider="tavily", answer="tavily failed try with some other websearch", results=[]
    )), patch.object(ddg_tool, "search", return_value=mock_ddg_res), \
         patch.object(pool, "get_configured_providers", return_value=[tavily_tool, ddg_tool]):
        res = pool.search(query="test", provider="tavily")
        assert res.provider == "duckduckgo"
        assert len(res.results) == 1
        assert res.results[0].title == "DDG Result"


def test_tavily_extract_keyless_and_fallback():
    import requests

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [{"url": "https://example.com", "raw_content": "Extracted text"}]
    }
    mock_resp.raise_for_status = MagicMock()

    # 1. Keyless extract success
    with patch("requests.post", return_value=mock_resp) as mock_post:
        tool = TavilySearchTool(api_key="")
        results = tool.extract(["https://example.com"])
        assert len(results) == 1
        assert results[0]["raw_content"] == "Extracted text"
        assert mock_post.call_args[1]["headers"].get("X-Tavily-Access-Mode") == "keyless"

    # 2. Keyless extract failure falling back to SDK extract
    mock_client = MagicMock()
    mock_client.extract.return_value = {"results": [{"url": "https://example.com", "raw_content": "SDK extract"}]}
    mock_tavily_mod = MagicMock(TavilyClient=MagicMock(return_value=mock_client))
    with patch("requests.post", side_effect=requests.RequestException("Keyless rate limit")), \
         patch.dict("sys.modules", {"tavily": mock_tavily_mod}):
        tool = TavilySearchTool(api_key="tvly-secret")
        results = tool.extract(["https://example.com"])
        assert len(results) == 1
        assert results[0]["raw_content"] == "SDK extract"

    # 3. Both keyless and SDK fail -> returns failure error item
    mock_client_fail = MagicMock()
    mock_client_fail.extract.side_effect = Exception("SDK error")
    with patch("requests.post", side_effect=requests.RequestException("Keyless rate limit")), \
         patch.dict("sys.modules", {"tavily": MagicMock(TavilyClient=MagicMock(return_value=mock_client_fail))}):
        tool = TavilySearchTool(api_key="tvly-secret")
        results = tool.extract(["https://example.com"])
        assert len(results) == 1
        assert results[0]["error"] == "tavily failed try with some other websearch"


@pytest.mark.asyncio
async def test_tavily_extract_async():
    tool = TavilySearchTool(api_key="")
    with patch.object(tool, "extract", return_value=[{"url": "https://async.com"}]) as mock_extract:
        res = await tool.extract_async(["https://async.com"])
        assert len(res) == 1
        mock_extract.assert_called_once_with(["https://async.com"])


def test_extract_web_content_tool_helper():
    from chat_agent.tools.tool_factory import extract_web_content

    with patch.object(TavilySearchTool, "extract", return_value=[{"url": "https://test.com", "content": "OK"}]):
        res = extract_web_content(["https://test.com"])
        assert res["status"] == "success"
        assert len(res["results"]) == 1

    with patch.object(TavilySearchTool, "extract", side_effect=Exception("Failed to fetch")):
        res = extract_web_content(["https://test.com"])
        assert res["status"] == "error"
        assert "Failed to fetch" in res["error"]


@pytest.mark.asyncio
async def test_search_async_delegates_to_thread():
    tool = TavilySearchTool(api_key="test-key")
    with patch.object(tool, "search") as mock_search:
        mock_search.return_value = NormalizedSearchResponse(
            query="async query", provider="tavily", results=[]
        )
        res = await tool.search_async("async query", max_results=5)
        assert res.query == "async query"
        mock_search.assert_called_once_with("async query", max_results=5)


def test_web_search_tool_pool_configured_selection():
    pool = WebSearchToolPool()
    with patch.object(pool.tools[SearchProvider.TAVILY.value], "is_configured", return_value=True), patch.object(
        pool.tools[SearchProvider.EXA.value], "is_configured", return_value=False
    ), patch.object(
        pool.tools[SearchProvider.FIRECRAWL.value], "is_configured", return_value=False
    ), patch.object(
        pool.tools[SearchProvider.SERPER.value], "is_configured", return_value=False
    ), patch.object(
        pool.tools[SearchProvider.DUCKDUCKGO.value], "is_configured", return_value=False
    ):
        configured = pool.get_configured_providers()
        assert len(configured) == 1
        assert configured[0].name == SearchProvider.TAVILY.value


def test_generate_openai_summary_fallback_on_error():
    with patch("openai.OpenAI", side_effect=Exception("No OpenAI key")):
        result = generate_openai_summary("Text to clean and summarize")
        assert result == "Text to clean and summarize"


@pytest.mark.asyncio
async def test_generate_openai_summary_async():
    mock_choice = MagicMock()
    mock_choice.message.content = "Async Summarized text"
    mock_response = MagicMock(choices=[mock_choice])

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        result = await generate_openai_summary_async("Fluffy long text", model_name="gpt-5-nano")
        assert result == "Async Summarized text"
        mock_client.chat.completions.create.assert_awaited_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"


def test_format_search_response_threshold():
    # 1. Short text <= 10000 chars should pass through without calling OpenAI
    short_resp = NormalizedSearchResponse(
        query="q",
        provider="p",
        results=[SearchResultItem(title="T", url="U", content="Short search text")],
    )
    with patch("chat_agent.tools.tool_factory.generate_openai_summary") as mock_summarize:
        formatted = format_search_response(short_resp)
        assert "Short search text" in formatted
        mock_summarize.assert_not_called()

    # 2. Long text > 10000 chars should trigger generate_openai_summary with gpt-5-nano
    long_content = "Word " * 2500  # ~12,500 chars
    long_resp = NormalizedSearchResponse(
        query="q",
        provider="p",
        results=[SearchResultItem(title="T", url="U", content=long_content)],
    )
    with patch("chat_agent.tools.tool_factory.generate_openai_summary", return_value="Summarized!") as mock_summarize:
        formatted = format_search_response(long_resp)
        assert formatted == "Summarized!"
        mock_summarize.assert_called_once()
        assert mock_summarize.call_args[1]["model_name"] == "gpt-5-nano"


def test_resolve_csv_path_relative_and_filename():
    resolved = resolve_csv_path("model_costs.csv")
    assert resolved.name == "model_costs.csv"
    assert resolved.is_absolute()


def test_search_web_tool_returns_json_serializable_dict():
    import json
    from chat_agent.tools.tool_factory import search_web

    mock_pool = MagicMock()
    mock_pool.search.return_value = NormalizedSearchResponse(
        query="test query",
        provider="tavily",
        answer="Summary answer",
        results=[SearchResultItem(title="Title", url="https://link.com", content="Details")],
    )

    with patch("chat_agent.tools.tool_factory.get_search_pool", return_value=mock_pool):
        res = search_web("test query")
        assert isinstance(res, dict)
        assert res["status"] == "success"
        assert res["query"] == "test query"
        assert res["provider"] == "tavily"
        # Must be JSON-serializable without errors for OpenAI and ADK tool execution
        serialized = json.dumps(res)
        assert "Summary answer" in serialized

