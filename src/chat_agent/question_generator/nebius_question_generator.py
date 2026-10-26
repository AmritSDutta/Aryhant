from __future__ import annotations

import logging

from chat_agent.agents.prompt import QA_GENERATOR_INSTRUCTION, format_instruction
from chat_agent.config import settings
from chat_agent.question_generator.base_question_generator import (
    BaseQuestionGenerator,
    _call_openai_compatible_questions,
)
from chat_agent.schema.fundamental_schema import QuestionAnswerSchema

logger = logging.getLogger(__name__)


class NebiusQuestionGenerator(BaseQuestionGenerator):
    """Nebius OpenAI-compatible question generator with automatic 120b failover."""

    def __init__(
        self,
        model: str | None = None,
        fallback_model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model: str = (
            model
            or getattr(settings, "nebius_question_model", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
        )
        self.fallback_model: str = (
            fallback_model
            or getattr(settings, "nebius_question_fallback_model", "nvidia/nemotron-3-super-120b-a12b")
        )
        self.base_url: str = (
            base_url
            or getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
        )
        self.api_key: str = (
            api_key
            or getattr(settings, "nebius_api_key", "")
            or getattr(settings, "NEBIUS_API_KEY", "")
        )

    async def generate_candidate_questions(
        self,
        topic: str,
        min_count: int = 15,
        max_count: int = 20,
    ) -> list[QuestionAnswerSchema]:
        """Generate candidate questions via Nebius OpenAI-compatible endpoint with failover."""
        system_instruction: str = format_instruction(QA_GENERATOR_INSTRUCTION)
        prompt: str = (
            f"Generate between {min_count} and {max_count} distinct Grade 5 ICSE practice questions "
            f"and guiding pedagogical hints on the topic: '{topic}'.\n"
            "Respond strictly with a JSON object in this format: "
            '{"questions": [{"id": 1, "question": "...", "hint": "..."}]}'
        )

        if self.api_key:
            # Primary attempt
            try:
                logger.info("[Question Gen] Nebius Primary: sending request to model '%s'", self.model)
                results = await _call_openai_compatible_questions(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    model=self.model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
                if results:
                    return results
            except Exception as e:
                logger.warning("Nebius primary model '%s' failed: %s", self.model, e)

            # Fallback attempt to 120b
            if self.fallback_model and self.fallback_model != self.model:
                try:
                    logger.info(
                        "[Question Gen] Nebius Failover: falling back to model '%s'",
                        self.fallback_model,
                    )
                    fallback_results = await _call_openai_compatible_questions(
                        prompt=prompt,
                        system_instruction=system_instruction,
                        model=self.fallback_model,
                        api_key=self.api_key,
                        base_url=self.base_url,
                    )
                    if fallback_results:
                        return fallback_results
                except Exception as fb_err:
                    logger.warning("Nebius fallback model '%s' failed: %s", self.fallback_model, fb_err)

        # Secondary failover to OpenAI if configured
        openai_key = getattr(settings, "openai_api_key", "")
        if openai_key:
            fallback_gpt = getattr(settings, "fallback_gpt_model", "gpt-6-luna")
            try:
                return await _call_openai_compatible_questions(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    model=fallback_gpt,
                    api_key=openai_key,
                )
            except Exception as err:
                logger.error("Secondary OpenAI fallback question generation failed: %s", err)

        return []
