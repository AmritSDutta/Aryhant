"""Hermetic unit tests for the direct LLM engine, runner dispatch, and text clipping."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_agent.agents.gemini_model_runner import (
    GeminiModelRunner,
    _execute_tool_call,
    _run_with_retry_and_fallback,
)
from chat_agent.agents.model_runner import ModelRunner, get_model_runner
from chat_agent.agents.nebius_model_runner import NebiusModelRunner
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


def test_model_runner_protocol_compliance():
    """Verify Gemini and Nebius runners satisfy the ModelRunner protocol."""
    assert isinstance(GeminiModelRunner(), ModelRunner)
    assert isinstance(NebiusModelRunner(), ModelRunner)


def test_get_model_runner_factory():
    """Verify factory returns appropriate runner instances."""
    assert isinstance(get_model_runner("gemini"), GeminiModelRunner)
    assert isinstance(get_model_runner("nebius"), NebiusModelRunner)
    with pytest.raises(ValueError, match="Unsupported model provider"):
        get_model_runner("unsupported_provider")


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
    with patch("chat_agent.agents.model_runner.settings.MODEL_PROVIDER", "gemini"), patch(
        "chat_agent.agents.gemini_model_runner._call_gemini",
        new_callable=AsyncMock,
        return_value="Hello from AI model",
    ) as mock_call:
        reply = await run_agent("u1", "s-direct", "Hello assistant")
    assert reply == "Hello from AI model"
    assert mock_call.await_count == 1


@pytest.mark.asyncio
async def test_run_agent_retry_succeeds_on_third_attempt():
    from google.genai import types

    content = types.Content(parts=[types.Part.from_text(text="test")])

    with patch(
        "chat_agent.agents.gemini_model_runner._call_gemini",
        new_callable=AsyncMock,
        side_effect=["", Exception("503 UNAVAILABLE: high demand"), "Recovered reply"],
    ) as mock_call, patch(
        "chat_agent.agents.gemini_model_runner._async_backoff", new_callable=AsyncMock
    ):
        reply = await _run_with_retry_and_fallback("u1", "s-retry", content)
        assert reply == "Recovered reply"
        assert mock_call.await_count == 3


@pytest.mark.asyncio
async def test_run_agent_fallback_openai_completion_when_gemini_fails():
    from google.genai import types

    content = types.Content(parts=[types.Part.from_text(text="test question")])

    mock_client = AsyncMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI Direct Response"
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    with patch(
        "chat_agent.agents.gemini_model_runner._call_gemini", side_effect=Exception("GenAI unavailable")
    ), patch(
        "chat_agent.agents.gemini_model_runner._async_backoff", new_callable=AsyncMock
    ), patch(
        "openai.AsyncOpenAI", return_value=mock_client
    ):
        reply = await _run_with_retry_and_fallback("u1", "s-fb", content)
        assert reply == "OpenAI Direct Response"


@pytest.mark.asyncio
async def test_run_agent_fallback_openai_httpx_when_module_missing():
    import sys
    from google.genai import types

    content = types.Content(parts=[types.Part.from_text(text="test question")])

    mock_http_resp = MagicMock()
    mock_http_resp.json.return_value = {
        "choices": [{"message": {"content": "HTTPX REST OpenAI Response"}}]
    }
    mock_http_client = AsyncMock()
    mock_http_client.__aenter__.return_value.post = AsyncMock(return_value=mock_http_resp)

    with patch(
        "chat_agent.agents.gemini_model_runner._call_gemini", side_effect=Exception("GenAI failed")
    ), patch(
        "chat_agent.agents.gemini_model_runner._async_backoff", new_callable=AsyncMock
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

    content = types.Content(parts=[types.Part.from_text(text="test")])

    with patch(
        "chat_agent.agents.gemini_model_runner._call_gemini", side_effect=Exception("Fatal failure")
    ), patch(
        "chat_agent.agents.gemini_model_runner._async_backoff", new_callable=AsyncMock
    ), patch(
        "openai.AsyncOpenAI", side_effect=Exception("OpenAI API unreachable")
    ):
        reply = await _run_with_retry_and_fallback("u1", "s-dead", content)
        assert reply == "I did not produce a reply."


@pytest.mark.asyncio
async def test_failed_attempt_does_not_duplicate_history():
    """A failed attempt must not leave duplicate user content in session history."""
    from google.genai import types

    from chat_agent.agents import gemini_model_runner as gmr

    gmr._HISTORY.clear()
    content = types.Content(parts=[types.Part.from_text(text="test")])
    calls = {"count": 0}

    async def fake_call(
        model: str,
        contents: list,
        user_memory_context: str | None = None,
        session_id: str = "",
        system_instruction: str | None = None,
        enable_tools: bool = True,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            return ""
        return "Recovered reply"

    with patch.object(gmr, "_call_gemini", fake_call), patch(
        "chat_agent.agents.gemini_model_runner._async_backoff", new_callable=AsyncMock
    ):
        reply = await gmr._run_with_retry_and_fallback("u1", "s-hist", content)

    assert reply == "Recovered reply"
    assert calls["count"] == 2
    history = gmr._HISTORY["s-hist"]
    assert len(history) == 2  # one user content + one model reply
    assert history[0].parts[0].text == "test"


@pytest.mark.asyncio
async def test_execute_tool_call_runs_registered_tool():
    from google.genai import types

    fc = types.FunctionCall(name="get_current_time", args={})
    part = await _execute_tool_call(fc)
    assert part.function_response.response["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_execute_tool_call_unknown_tool():
    from google.genai import types

    fc = types.FunctionCall(name="does_not_exist", args={})
    part = await _execute_tool_call(fc)
    assert "Unknown tool" in part.function_response.response["error"]


@pytest.mark.asyncio
async def test_nebius_model_runner_success():
    from google.genai import types

    runner = NebiusModelRunner()
    content = types.Content(parts=[types.Part.from_text(text="hello nebius")])

    with patch(
        "chat_agent.agents.nebius_model_runner._call_nebius_completion",
        new_callable=AsyncMock,
        return_value="Nebius response",
    ), patch(
        "chat_agent.agents.nebius_model_runner.settings.NEBIUS_API_KEY", "mock-nebius-key"
    ):
        reply = await runner.run("u1", "s-nebius", content)
        assert reply == "Nebius response"


@pytest.mark.asyncio
async def test_nebius_model_runner_multimodal_vision_input():
    from google.genai import types

    runner = NebiusModelRunner()
    part_text = types.Part.from_text(text="Describe this picture")
    part_image = types.Part.from_bytes(data=b"fake-image-bytes", mime_type="image/png")
    content = types.Content(parts=[part_text, part_image])

    async def _fake_completion(**kwargs):
        if kwargs.get("enable_tools", True) is False:
            return "TRANSCRIPT: a cat on a mat"
        return "Image description from Nemotron"

    with patch(
        "chat_agent.agents.nebius_model_runner._call_nebius_completion",
        new=AsyncMock(side_effect=_fake_completion),
    ) as mock_call, patch(
        "chat_agent.agents.nebius_model_runner.settings.NEBIUS_API_KEY", "mock-nebius-key"
    ):
        reply = await runner.run("u1", "s-nebius-vision", content)
        assert reply == "Image description from Nemotron"
        assert mock_call.call_count == 2

        # Phase 1: VL extraction call receives the raw image parts.
        extraction_kwargs = mock_call.call_args_list[0][1]
        assert extraction_kwargs["model"] == "nvidia/Nemotron-3.5-Super-VL"
        assert extraction_kwargs["enable_tools"] is False
        extraction_msg = extraction_kwargs["messages"][-1]
        assert isinstance(extraction_msg["content"], list)
        assert extraction_msg["content"][0]["type"] == "text"
        assert extraction_msg["content"][1]["type"] == "image_url"
        assert extraction_msg["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

        # Phase 2: Nano answers with text-only content containing the extraction.
        answer_kwargs = mock_call.call_args_list[1][1]
        assert answer_kwargs["model"] == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
        answer_content = answer_kwargs["messages"][-1]["content"]
        assert isinstance(answer_content, str)
        assert "[Image content: TRANSCRIPT: a cat on a mat]" in answer_content


@pytest.mark.asyncio
async def test_nebius_model_runner_tool_execution():
    from chat_agent.agents.nebius_model_runner import _call_nebius_completion

    mock_client = AsyncMock()

    mock_tc = MagicMock()
    mock_tc.id = "call_time_1"
    mock_tc.function.name = "get_current_time"
    mock_tc.function.arguments = "{}"

    mock_msg_round1 = MagicMock()
    mock_msg_round1.content = None
    mock_msg_round1.tool_calls = [mock_tc]

    mock_resp1 = MagicMock()
    mock_resp1.choices = [MagicMock(message=mock_msg_round1)]

    mock_msg_round2 = MagicMock()
    mock_msg_round2.content = "Current time is 10:00 PM IST"
    mock_msg_round2.tool_calls = None

    mock_resp2 = MagicMock()
    mock_resp2.choices = [MagicMock(message=mock_msg_round2)]

    mock_client.chat.completions.create = AsyncMock(side_effect=[mock_resp1, mock_resp2])

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        reply = await _call_nebius_completion(
            model="nvidia/Nemotron-3.5-Super-VL",
            messages=[{"role": "user", "content": "What time is it?"}],
            api_key="mock-key",
            base_url="https://api.tokenfactory.nebius.com/v1",
        )
        assert reply == "Current time is 10:00 PM IST"
        assert mock_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_gemini_token_usage_logging(caplog):
    import logging
    from google.genai import types
    from chat_agent.agents.gemini_model_runner import _call_gemini

    mock_resp = MagicMock()
    mock_resp.candidates = [MagicMock()]
    mock_resp.candidates[0].content.parts = []
    mock_resp.text = "Answer"
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = 120
    mock_usage.candidates_token_count = 45
    mock_usage.total_token_count = 165
    mock_resp.usage_metadata = mock_usage

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("chat_agent.agents.gemini_model_runner._get_genai_client", return_value=mock_client):
        with caplog.at_level(logging.INFO):
            content = types.Content(parts=[types.Part.from_text(text="Hi")])
            ans = await _call_gemini("gemini-flash-lite-latest", [content])
            assert ans == "Answer"
            assert "[Token Usage]" in caplog.text
            assert "Prompt: 120" in caplog.text
            assert "Candidates: 45" in caplog.text
            assert "Total: 165 tokens" in caplog.text
