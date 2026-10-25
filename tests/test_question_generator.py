"""Tests for secondary agent question generation and TypeSafe curation."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from chat_agent.agents.question_generator import (
    generate_candidate_questions,
    generate_curated_questions,
)
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
        results = await generate_candidate_questions("Fractions")

    assert len(results) == 15
    assert isinstance(results[0], QuestionAnswerSchema)
    assert results[0].id == 1
    assert results[0].question == "Question 1?"
    assert results[0].hint == "Hint 1."


@pytest.mark.asyncio
async def test_generate_curated_questions_pipeline() -> None:
    """Verify end-to-end generation and TypeSafe curation pipeline."""
    mock_candidates = [
        QuestionAnswerSchema(id=i, question=f"Q{i}", hint=f"H{i}")
        for i in range(1, 16)
    ]
    mock_scored_top_10 = [
        QuestionAnswerSchema(id=i, question=f"Q{i}", hint=f"H{i}", score=round(1.0 - (i * 0.05), 2))
        for i in range(1, 11)
    ]

    with patch(
        "chat_agent.agents.question_generator.generate_candidate_questions",
        AsyncMock(return_value=mock_candidates),
    ), patch(
        "chat_agent.agents.question_generator.get_feedback",
        AsyncMock(return_value=mock_scored_top_10),
    ) as mock_fb:
        results = await generate_curated_questions("Decimals")

    assert len(results) == 10
    mock_fb.assert_awaited_once_with(mock_candidates, user_input="Decimals")
    assert results[0].score == 0.95


@pytest.mark.asyncio
async def test_generate_curated_questions_typesafe_not_ready() -> None:
    """Verify generate_curated_questions returns candidates directly when TypeSafe is unconfigured."""
    from unittest.mock import PropertyMock
    from chat_agent.config import Settings

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
    from unittest.mock import PropertyMock
    from chat_agent.config import Settings

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
    from unittest.mock import PropertyMock
    from chat_agent.config import Settings

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=json.dumps({"invalid_key": []})))]

    mock_openai = MagicMock()
    mock_openai.chat.completions.create = AsyncMock(return_value=mock_resp)

    with patch(
        "chat_agent.agents.question_generator._get_genai_client",
        side_effect=RuntimeError("GenAI down"),
    ), patch.object(
        Settings, "openai_api_key", new_callable=PropertyMock, return_value="sk-test"
    ), patch(
        "openai.AsyncOpenAI",
        return_value=mock_openai,
    ):
        results = await generate_candidate_questions("Algebra")

    assert results == []


