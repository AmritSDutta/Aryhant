from __future__ import annotations

import logging

from chat_agent.config import settings
from chat_agent.question_generator.base_question_generator import (
    BaseQuestionGenerator,
    _get_genai_client,
)
from chat_agent.question_generator.gemini_question_generator import GeminiQuestionGenerator
from chat_agent.question_generator.nebius_question_generator import NebiusQuestionGenerator
from chat_agent.schema.fundamental_schema import QuestionAnswerSchema
from chat_agent.utils.fast_decision.typesafe_integrator import get_feedback

logger = logging.getLogger(__name__)

# Backwards compatibility alias
QuestionGenerator = BaseQuestionGenerator


def get_question_generator(provider: str | None = None) -> BaseQuestionGenerator:
    """Return a QuestionGenerator instance for the configured provider."""
    selected = (
        provider
        or getattr(settings, "QUESTION_GENERATOR_PROVIDER", None)
        or getattr(settings, "question_generator_provider", "gemini")
    ).lower().strip()

    if selected == "gemini":
        return GeminiQuestionGenerator()
    if selected == "nebius":
        return NebiusQuestionGenerator()
    raise ValueError(f"Unsupported question generator provider: '{selected}'. Supported: 'gemini', 'nebius'")


async def generate_candidate_questions(
    topic: str,
    min_count: int = 15,
    max_count: int = 20,
    provider: str | None = None,
    generator: BaseQuestionGenerator | None = None,
) -> list[QuestionAnswerSchema]:
    """Generate raw candidate practice questions for the requested topic."""
    import chat_agent.agents.question_generator as qg

    gen = generator or qg.get_question_generator(provider)
    return await gen.generate_candidate_questions(topic, min_count=min_count, max_count=max_count)


async def generate_curated_questions(
    topic: str,
    provider: str | None = None,
    generator: BaseQuestionGenerator | None = None,
) -> list[QuestionAnswerSchema]:
    """Generate candidate questions and return the top 10 scored by TypeSafe AI (with graceful fallback)."""

    candidates: list[QuestionAnswerSchema] = await generate_candidate_questions(
        topic, provider=provider, generator=generator
    )
    if not candidates:
        return []

    if not settings.typesafe_ready:
        logger.info("TypeSafe AI not configured (TYPESAFE_API_KEY unset). Returning unscored candidates.")
        return candidates[:10]

    try:
        return await get_feedback(candidates, user_input=topic)
    except Exception as e:
        logger.warning("TypeSafe AI feedback scoring failed; falling back to unscored candidates: %s", e)
        return candidates[:10]


__all__ = [
    "BaseQuestionGenerator",
    "GeminiQuestionGenerator",
    "NebiusQuestionGenerator",
    "QuestionGenerator",
    "generate_candidate_questions",
    "generate_curated_questions",
    "get_feedback",
    "get_question_generator",
    "_get_genai_client",
]
