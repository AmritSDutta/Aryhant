"""Tests for TypeSafe hint evaluation feedback integration."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from typesafe_sdk import NoulAnswer, SystemOneResponse, Usage

from chat_agent.schema.fundamental_schema import QuestionAnswerSchema
from chat_agent.utils.fast_decision.typesafe_integrator import get_feedback


@pytest.mark.asyncio
async def test_get_feedback_empty() -> None:
    """Verify empty list input returns empty list immediately."""
    result = await get_feedback([])
    assert result == []


@pytest.mark.asyncio
async def test_get_feedback_scoring_and_top_10() -> None:
    """Verify question items are scored with Noul probabilities and sorted descending."""
    input_items = [
        QuestionAnswerSchema(
            id=101,
            question="What is 5 + 7?",
            hint="Add 5 and 5 first, then add 2.",
        ),
        QuestionAnswerSchema(
            id=102,
            question="What is the speed of light?",
            hint="It is fast.",
        ),
    ]

    mock_noul_101 = NoulAnswer(type="noul", noul=0.92)
    mock_noul_102 = NoulAnswer(type="noul", noul=0.35)

    mock_response = SystemOneResponse(
        model="jev-latest",
        usage=Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        answers={
            "hint_eval_101": mock_noul_101,
            "hint_eval_102": mock_noul_102,
        },
    )

    mock_client = MagicMock()
    mock_client.system_one = AsyncMock(return_value=mock_response)

    with patch(
        "chat_agent.utils.fast_decision.typesafe_integrator.get_client",
        AsyncMock(return_value=mock_client),
    ):
        results = await get_feedback(input_items)

    assert len(results) == 2
    assert results[0].id == 101
    assert results[0].score == 0.92
    assert results[1].id == 102
    assert results[1].score == 0.35
    assert results[0].score >= results[1].score


@pytest.mark.asyncio
async def test_get_feedback_with_user_input() -> None:
    """Verify user_input is incorporated into TypeSafe state and instructions."""
    input_items = [
        QuestionAnswerSchema(id=1, question="What is 2+2?", hint="Count fingers.")
    ]
    mock_response = SystemOneResponse(
        model="jev-latest",
        usage=Usage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        answers={"hint_eval_1": NoulAnswer(type="noul", noul=0.88)},
    )
    mock_client = MagicMock()
    mock_client.system_one = AsyncMock(return_value=mock_response)

    with patch(
        "chat_agent.utils.fast_decision.typesafe_integrator.get_client",
        AsyncMock(return_value=mock_client),
    ):
        results = await get_feedback(input_items, user_input="Grade 5 Addition")

    assert len(results) == 1
    assert results[0].score == 0.88
    called_state = mock_client.system_one.call_args[1]["state"]
    assert called_state.get("user_query") == "Grade 5 Addition"



@pytest.mark.asyncio
async def test_get_feedback_top_10_limit() -> None:
    """Verify get_feedback truncates output to top 10 highest-scoring items."""
    input_items = [
        QuestionAnswerSchema(id=i, question=f"Q{i}", hint=f"H{i}")
        for i in range(1, 16)
    ]

    answers = {
        f"hint_eval_{i}": NoulAnswer(
            type="noul",
            noul=round((i % 10) / 10.0, 2),
        )
        for i in range(1, 16)
    }

    mock_response = SystemOneResponse(
        model="jev-latest",
        usage=Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        answers=answers,
    )

    mock_client = MagicMock()
    mock_client.system_one = AsyncMock(return_value=mock_response)

    with patch(
        "chat_agent.utils.fast_decision.typesafe_integrator.get_client",
        AsyncMock(return_value=mock_client),
    ):
        results = await get_feedback(input_items)

    assert len(results) == 10
    scores = [item.score for item in results if item.score is not None]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_get_client_concurrency() -> None:
    """Verify concurrent get_client calls return the exact same singleton instance."""
    import asyncio
    import chat_agent.utils.fast_decision.typesafe_integrator as ti

    ti._async_typesafe_client = None

    with patch.object(ti, "AsyncTypeSafeClient", side_effect=lambda **kwargs: MagicMock()):
        clients = await asyncio.gather(*[ti.get_client() for _ in range(10)])

    assert len(clients) == 10
    first_client = clients[0]
    for c in clients:
        assert c is first_client





