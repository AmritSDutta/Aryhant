"""Tests for secondary agent question generation and TypeSafe curation."""

import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import pytest

from chat_agent.agents.question_generator import (
    BaseQuestionGenerator,
    GeminiQuestionGenerator,
    NebiusQuestionGenerator,
    QuestionGenerator,
    generate_candidate_questions,
    generate_curated_questions,
    get_question_generator,
)
from chat_agent.config import Settings
from chat_agent.schema.fundamental_schema import QuestionAnswerSchema


@pytest.mark.asyncio
async def test_generate_candidate_questions_success() -> None:
    """Verify candidate generation parses valid JSON response into schemas."""
    mock_items = [
        {"id": i, "question": f"Question {i}?", "hint": f"Hint {i}."}
        for i in range(1, 16)
    ]
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(mock_items)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("chat_agent.agents.question_generator._get_genai_client", return_value=mock_client):
        results = await generate_candidate_questions("Fractions", provider="gemini")

    assert len(results) == 15
    assert isinstance(results[0], QuestionAnswerSchema)
    assert results[0].id == 1
    assert results[0].question == "Question 1?"
    assert results[0].hint == "Hint 1."


@pytest.mark.asyncio
async def test_generate_curated_questions_typesafe_not_ready() -> None:
    """Verify generate_curated_questions returns candidates directly when TypeSafe is unconfigured."""
    mock_candidates = [
        QuestionAnswerSchema(id=i, question=f"Q{i}", hint=f"H{i}")
        for i in range(1, 16)
    ]

    with patch(
        "chat_agent.agents.question_generator.generate_candidate_questions",
        AsyncMock(return_value=mock_candidates),
    ), patch.object(Settings, "typesafe_ready", new_callable=PropertyMock, return_value=False):
        results = await generate_curated_questions("Decimals")

    assert len(results) == 10
    assert results[0].score is None


@pytest.mark.asyncio
async def test_generate_curated_questions_typesafe_failure_fallback() -> None:
    """Verify generate_curated_questions gracefully falls back to candidates if TypeSafe raises."""
    mock_candidates = [
        QuestionAnswerSchema(id=i, question=f"Q{i}", hint=f"H{i}")
        for i in range(1, 16)
    ]

    with patch(
        "chat_agent.agents.question_generator.generate_candidate_questions",
        AsyncMock(return_value=mock_candidates),
    ), patch.object(
        Settings, "typesafe_ready", new_callable=PropertyMock, return_value=True
    ), patch(
        "chat_agent.agents.question_generator.get_feedback",
        AsyncMock(side_effect=RuntimeError("TypeSafe connection error")),
    ):
        results = await generate_curated_questions("Decimals")

    assert len(results) == 10
    assert results[0].score is None


@pytest.mark.asyncio
async def test_generate_candidate_questions_openai_fallback_malformed() -> None:
    """Verify OpenAI fallback returns empty list and logs warning on missing questions key."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({"invalid_key": []})))]

    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock(return_value=mock_resp)

    with patch(
        "chat_agent.agents.question_generator._get_genai_client",
        side_effect=RuntimeError("GenAI down"),
    ), patch.object(
        Settings, "nebius_api_key", new_callable=PropertyMock, return_value=""
    ), patch.object(
        Settings, "openai_api_key", new_callable=PropertyMock, return_value="sk-test"
    ), patch(
        "openai.AsyncOpenAI",
        return_value=mock_openai,
    ):
        results = await generate_candidate_questions("Algebra", provider="gemini")

    assert results == []


def test_question_generator_base_inheritance() -> None:
    """Verify both Gemini and Nebius implementations inherit from BaseQuestionGenerator."""
    gemini_gen = GeminiQuestionGenerator()
    nebius_gen = NebiusQuestionGenerator()
    assert isinstance(gemini_gen, BaseQuestionGenerator)
    assert isinstance(nebius_gen, BaseQuestionGenerator)
    assert isinstance(gemini_gen, QuestionGenerator)
    assert isinstance(nebius_gen, QuestionGenerator)


def test_get_question_generator_factory() -> None:
    """Verify factory dispatches supported generators and rejects unknown providers."""
    assert isinstance(get_question_generator("gemini"), GeminiQuestionGenerator)
    assert isinstance(get_question_generator("nebius"), NebiusQuestionGenerator)
    with pytest.raises(ValueError, match="Unsupported question generator provider"):
        get_question_generator("unsupported_provider")


@pytest.mark.asyncio
async def test_nebius_question_generator_primary_success() -> None:
    """Verify Nebius generator calls primary Nemotron nano model and parses JSON questions wrapper."""
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({
                    "questions": [
                        {"id": 1, "question": "What is 2+2?", "hint": "Think of basic addition."}
                    ]
                })
            )
        )
    ]
    mock_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20, total_tokens=30)

    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock(return_value=mock_resp)

    gen = NebiusQuestionGenerator(api_key="test-nebius-key")
    with patch("openai.AsyncOpenAI", return_value=mock_openai):
        results = await gen.generate_candidate_questions("Arithmetic")

    assert len(results) == 1
    assert isinstance(results[0], QuestionAnswerSchema)
    assert results[0].id == 1
    assert results[0].question == "What is 2+2?"
    assert results[0].hint == "Think of basic addition."
    mock_openai.chat.completions.create.assert_awaited_once()
    assert mock_openai.chat.completions.create.call_args[1]["model"] == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"


@pytest.mark.asyncio
async def test_nebius_question_generator_root_list_success() -> None:
    """Verify Nebius generator handles direct JSON list responses."""
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps([
                    {"id": 1, "question": "Define photosynthesis.", "hint": "Think of sunlight and plants."}
                ])
            )
        )
    ]
    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock(return_value=mock_resp)

    gen = NebiusQuestionGenerator(api_key="test-nebius-key")
    with patch("openai.AsyncOpenAI", return_value=mock_openai):
        results = await gen.generate_candidate_questions("Biology")

    assert len(results) == 1
    assert results[0].question == "Define photosynthesis."


@pytest.mark.asyncio
async def test_nebius_question_generator_fallback_to_120b() -> None:
    """Verify Nebius generator falls back to nvidia/nemotron-3-super-120b-a12b on primary failure."""
    mock_primary_err = RuntimeError("Nemotron 30B primary model failed")
    mock_fallback_resp = MagicMock()
    mock_fallback_resp.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps([
                    {"id": 1, "question": "What is gravity?", "hint": "Think of falling objects."}
                ])
            )
        )
    ]

    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock(
        side_effect=[mock_primary_err, mock_fallback_resp]
    )

    gen = NebiusQuestionGenerator(api_key="test-nebius-key")
    with patch("openai.AsyncOpenAI", return_value=mock_openai):
        results = await gen.generate_candidate_questions("Physics")

    assert len(results) == 1
    assert results[0].question == "What is gravity?"
    assert mock_openai.chat.completions.create.await_count == 2
    second_call_model = mock_openai.chat.completions.create.call_args_list[1][1]["model"]
    assert second_call_model == "nvidia/nemotron-3-super-120b-a12b"


@pytest.mark.asyncio
async def test_gemini_question_generator_fallback_to_120b() -> None:
    """Verify Gemini generator falls back to 120b OpenAI-compatible model when GenAI fails."""
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps([
                    {"id": 1, "question": "What is an obtuse angle?", "hint": "More than 90 degrees."}
                ])
            )
        )
    ]
    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock(return_value=mock_resp)

    gen = GeminiQuestionGenerator()
    with patch(
        "chat_agent.agents.question_generator._get_genai_client",
        side_effect=RuntimeError("Google GenAI unavailable"),
    ), patch.object(
        Settings, "nebius_api_key", new_callable=PropertyMock, return_value="test-nebius-key"
    ), patch(
        "openai.AsyncOpenAI",
        return_value=mock_openai,
    ):
        results = await gen.generate_candidate_questions("Geometry")

    assert len(results) == 1
    assert results[0].question == "What is an obtuse angle?"
    mock_openai.chat.completions.create.assert_awaited_once()
    assert mock_openai.chat.completions.create.call_args[1]["model"] == "nvidia/nemotron-3-super-120b-a12b"
