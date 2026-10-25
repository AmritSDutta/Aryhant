"""Hermetic unit tests for the direct LLM engine, runner dispatch, and text clipping."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_agent.agents.runner import clip_text, run_agent
from chat_agent.app import ChatRequest
from chat_agent.tools.tool_factory import get_current_time


def test_clip_text_keeps_short_messages():
    assert clip_text("hello", 20) == "hello"


def test_clip_text_truncates_long_messages():
    result = clip_text("x" * 50, 10)
    assert result.startswith("xxxxxxxxxx")
    assert result.endswith("[truncated]")


def test_chat_request_payload_defaults():
    payload = ChatRequest(message="hi", channel="slack")
    assert payload.channel == "slack"
    assert payload.user_id == "web-user"
    assert payload.session_id == "web-session"


def test_get_current_time_tool():
    res = get_current_time()
    assert res["status"] == "success"
    assert "ist_time" in res
    assert "utc_time" in res
    assert res["timezone"] == "IST (UTC+5:30)"


@pytest.mark.asyncio
async def test_run_agent_empty_prompt():
    reply = await run_agent("u1", "s1", "")
    assert reply == "I need a message to reply to."


@pytest.mark.asyncio
async def test_run_agent_malicious_prompt_interception():
    from chat_agent.config import settings

    with patch.object(settings, "IS_GEMINI_MODERATION_ENOUGH", False):
        reply = await run_agent("u1", "s1", "rm -rf /")
        assert "potentially unsafe content" in reply.lower()


@pytest.mark.asyncio
async def test_run_agent_direct_genai_reply():
    with patch(
        "chat_agent.agents.runner._call_gemini",
        new_callable=AsyncMock,
        return_value="Hello from AI model",
    ) as mock_call:
        reply = await run_agent("u1", "s-direct", "Hello assistant")
    assert reply == "Hello from AI model"
    assert mock_call.await_count == 1


@pytest.mark.asyncio
async def test_run_agent_retry_succeeds_on_third_attempt():
    from google.genai import types

    from chat_agent.agents.runner import _run_with_retry_and_fallback

    content = types.Content(parts=[types.Part.from_text(text="test")])

    with patch(
        "chat_agent.agents.runner._call_gemini",
        new_callable=AsyncMock,
        side_effect=["", Exception("503 UNAVAILABLE: high demand"), "Recovered reply"],
    ) as mock_call, patch(
        "chat_agent.agents.runner._async_backoff", new_callable=AsyncMock
    ):
        reply = await _run_with_retry_and_fallback("u1", "s-retry", content)
        assert reply == "Recovered reply"
        assert mock_call.await_count == 3


@pytest.mark.asyncio
async def test_run_agent_fallback_openai_completion_when_gemini_fails():
    from google.genai import types

    from chat_agent.agents.runner import _run_with_retry_and_fallback

    content = types.Content(parts=[types.Part.from_text(text="test question")])

    mock_client = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI Direct Response"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    with patch(
        "chat_agent.agents.runner._call_gemini", side_effect=Exception("GenAI unavailable")
    ), patch(
        "chat_agent.agents.runner._async_backoff", new_callable=AsyncMock
    ), patch(
        "openai.AsyncOpenAI", return_value=mock_client
    ):
        reply = await _run_with_retry_and_fallback("u1", "s-fb", content)
        assert reply == "OpenAI Direct Response"


@pytest.mark.asyncio
async def test_run_agent_fallback_openai_httpx_when_module_missing():
    import sys
    from google.genai import types

    from chat_agent.agents.runner import _run_with_retry_and_fallback

    content = types.Content(parts=[types.Part.from_text(text="test question")])

    mock_http_resp = MagicMock()
    mock_http_resp.json.return_value = {
        "choices": [{"message": {"content": "HTTPX REST OpenAI Response"}}]
    }
    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value.post = AsyncMock(return_value=mock_http_resp)

    with patch(
        "chat_agent.agents.runner._call_gemini", side_effect=Exception("GenAI failed")
    ), patch(
        "chat_agent.agents.runner._async_backoff", new_callable=AsyncMock
    ), patch.dict(
        sys.modules, {"openai": None}
    ), patch(
        "httpx.AsyncClient", return_value=mock_http_client
    ):
        reply = await _run_with_retry_and_fallback("u1", "s-fb-httpx", content)
        assert reply == "HTTPX REST OpenAI Response"


@pytest.mark.asyncio
async def test_run_agent_all_retries_and_fallback_fail():
    from google.genai import types

    from chat_agent.agents.runner import _run_with_retry_and_fallback

    content = types.Content(parts=[types.Part.from_text(text="test")])

    with patch(
        "chat_agent.agents.runner._call_gemini", side_effect=Exception("Fatal failure")
    ), patch(
        "chat_agent.agents.runner._async_backoff", new_callable=AsyncMock
    ), patch(
        "openai.AsyncOpenAI", side_effect=Exception("OpenAI API unreachable")
    ):
        reply = await _run_with_retry_and_fallback("u1", "s-dead", content)
        assert reply == "I did not produce a reply."


@pytest.mark.asyncio
async def test_failed_attempt_does_not_duplicate_history():
    """A failed attempt must not leave duplicate user content in session history."""
    from google.genai import types

    from chat_agent.agents import runner as runner_mod

    runner_mod._HISTORY.clear()
    content = types.Content(parts=[types.Part.from_text(text="test")])
    calls = {"count": 0}

    async def fake_call(model: str, contents: list) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            return ""
        return "Recovered reply"

    with patch.object(runner_mod, "_call_gemini", fake_call), patch(
        "chat_agent.agents.runner._async_backoff", new_callable=AsyncMock
    ):
        reply = await runner_mod._run_with_retry_and_fallback("u1", "s-hist", content)

    assert reply == "Recovered reply"
    assert calls["count"] == 2
    history = runner_mod._HISTORY["s-hist"]
    assert len(history) == 2  # one user content + one model reply
    assert history[0].parts[0].text == "test"


@pytest.mark.asyncio
async def test_execute_tool_call_runs_registered_tool():
    from google.genai import types

    from chat_agent.agents.runner import _execute_tool_call

    fc = types.FunctionCall(name="get_current_time", args={})
    part = await _execute_tool_call(fc)
    assert part.function_response.response["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_execute_tool_call_unknown_tool():
    from google.genai import types

    from chat_agent.agents.runner import _execute_tool_call

    fc = types.FunctionCall(name="does_not_exist", args={})
    part = await _execute_tool_call(fc)
    assert "Unknown tool" in part.function_response.response["error"]
