"""Tests for Nano/VL model routing, image extraction, history prefetch, and client caching."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from google.genai import types

from chat_agent.agents import nebius_model_runner as nmr


def _text_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def _image_content(text: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[
            types.Part(text=text),
            types.Part.from_bytes(data=b"fake-image-bytes", mime_type="image/jpeg"),
        ],
    )


@pytest.fixture
def capture_completions(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture every _call_nebius_completion invocation instead of hitting the API."""
    calls: list[dict[str, Any]] = []

    async def fake_completion(**kwargs: Any) -> str:
        calls.append(kwargs)
        if kwargs.get("enable_tools", True) is False:
            return "WORKSHEET TEXT: 12 x 8 = ?"
        return "Here is the step-by-step answer."

    monkeypatch.setattr(nmr, "_call_nebius_completion", fake_completion)
    monkeypatch.setattr(nmr.settings, "NEBIUS_API_KEY", "test-nebius-key")
    return calls


@pytest.mark.asyncio
async def test_text_turn_routes_to_chat_model(capture_completions: list[dict[str, Any]]) -> None:
    """A text-only turn makes exactly one completion on the Nano chat model."""
    runner = nmr.NebiusModelRunner()
    reply = await runner.run(user_id="u", session_id="s-text", content=_text_content("hi"))
    assert reply == "Here is the step-by-step answer."
    assert len(capture_completions) == 1
    assert capture_completions[0]["model"] == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"


@pytest.mark.asyncio
async def test_image_turn_extracts_with_vl_then_answers_on_nano(
    capture_completions: list[dict[str, Any]],
) -> None:
    """An image turn runs a VL extraction call first, then answers on Nano with text-only content."""
    runner = nmr.NebiusModelRunner()
    reply = await runner.run(user_id="u", session_id="s-img", content=_image_content("Solve this"))
    assert reply == "Here is the step-by-step answer."
    assert len(capture_completions) == 2

    extraction_call, answer_call = capture_completions
    assert extraction_call["model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert extraction_call["enable_tools"] is False
    assert answer_call["model"] == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

    # Nano's user message must contain the extracted text, not image parts.
    user_msg = answer_call["messages"][-1]["content"]
    assert isinstance(user_msg, str) and "[Image content: WORKSHEET TEXT:" in user_msg


@pytest.mark.asyncio
async def test_vl_extraction_failure_falls_back_to_vl_answer(
    monkeypatch: pytest.MonkeyPatch,
    capture_completions: list[dict[str, Any]],
) -> None:
    """If the VL extraction call fails, the whole turn is answered on the VL model."""
    original_extract = nmr._extract_image_content

    async def failing_extract(*args: Any, **kwargs: Any) -> str:
        return ""

    monkeypatch.setattr(nmr, "_extract_image_content", failing_extract)
    runner = nmr.NebiusModelRunner()
    reply = await runner.run(user_id="u", session_id="s-fb", content=_image_content("Solve this"))
    assert reply == "Here is the step-by-step answer."
    assert len(capture_completions) == 1
    assert capture_completions[0]["model"] == "nvidia/Nemotron-3.5-Super-VL"
    monkeypatch.setattr(nmr, "_extract_image_content", original_extract)


@pytest.mark.asyncio
async def test_prefetched_history_is_used(capture_completions: list[dict[str, Any]]) -> None:
    """A prefetched history list is used verbatim instead of fetching from Redis."""
    prefetched = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]

    async def fail_fetch(session_id: str) -> list[dict[str, Any]]:
        raise AssertionError("should not fetch history when prefetched")

    import chat_agent.agents.nebius_model_runner as runner_mod

    monkeypatch_target = runner_mod._get_nebius_history
    runner_mod._get_nebius_history = fail_fetch
    try:
        runner = runner_mod.NebiusModelRunner()
        await runner.run(
            user_id="u", session_id="s-hist", content=_text_content("hi"), history=prefetched
        )
    finally:
        runner_mod._get_nebius_history = monkeypatch_target
    sent = capture_completions[0]["messages"]
    assert sent[1:3] == prefetched


def test_client_cache_reuses_clients(tmp_path: Path) -> None:
    """The AsyncOpenAI client cache returns one instance per (key, url) pair."""
    nmr._CLIENT_CACHE.clear()
    a = nmr._get_openai_client("k1", "https://x/v1")
    b = nmr._get_openai_client("k1", "https://x/v1")
    c = nmr._get_openai_client("k2", "https://x/v1")
    assert a is b
    assert a is not c
    nmr._CLIENT_CACHE.clear()
