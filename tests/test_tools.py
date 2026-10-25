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

    tool_unconfigured = TavilySearchTool(api_key="TAVILY_API_KEY")
    assert tool_unconfigured.is_configured() is False

    tool_empty = TavilySearchTool(api_key="")
    assert tool_empty.is_configured() is False


def test_tavily_search_mocked():
    mock_tavily_inst = MagicMock()
    mock_tavily_inst.search.return_value = {
        "results": [{"title": "Test Title", "url": "https://test.com", "content": "Test Body"}]
    }
    mock_tavily_mod = MagicMock(TavilyClient=MagicMock(return_value=mock_tavily_inst))

    with patch.dict("sys.modules", {"tavily": mock_tavily_mod}):
        tool = TavilySearchTool(api_key="valid-key")
        res = tool.search(query="python fastapi")
        assert len(res.results) == 1
        assert res.results[0].title == "Test Title"
        assert res.results[0].content == "Test Body"


def test_tavily_search_rest_fallback_when_module_missing():
    import sys
    import requests

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "answer": "REST answer",
        "results": [{"title": "REST Title", "url": "https://rest.com", "content": "REST Body", "score": 0.95}],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.dict(sys.modules, {"tavily": None}), \
         patch("requests.post", return_value=mock_resp) as mock_post:
        tool = TavilySearchTool(api_key="valid-key")
        res = tool.search(query="python fastapi")
        assert res.answer == "REST answer"
        assert len(res.results) == 1
        assert res.results[0].title == "REST Title"
        assert res.results[0].url == "https://rest.com"
        mock_post.assert_called_once()


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

