from __future__ import annotations

import logging
from typing import Optional

from google import genai
from google.genai import types

from chat_agent.agents.prompt import QA_GENERATOR_INSTRUCTION, format_instruction
from chat_agent.config import settings
from chat_agent.question_generator.base_question_generator import (
    BaseQuestionGenerator,
    _call_openai_compatible_questions,
    _schema_adapter,
)
from chat_agent.schema.fundamental_schema import QuestionAnswerSchema

logger = logging.getLogger(__name__)


class GeminiQuestionGenerator(BaseQuestionGenerator):
    """Google GenAI structured question generator with failover support."""

    def __init__(self, model: str | None = None, client: Optional[genai.Client] = None) -> None:
        self.model: str = model or settings.model
        self._client: Optional[genai.Client] = client

    def _get_client(self) -> genai.Client:
        if self._client is not None:
            return self._client
        import chat_agent.agents.question_generator as aqg

        return aqg._get_genai_client()

    async def generate_candidate_questions(
        self,
        topic: str,
        min_count: int = 15,
        max_count: int = 20,
    ) -> list[QuestionAnswerSchema]:
        """Generate structured candidate questions via Google GenAI with fallback."""
        system_instruction: str = format_instruction(QA_GENERATOR_INSTRUCTION)
        prompt: str = (
            f"Generate between {min_count} and {max_count} distinct Grade 5 ICSE practice questions "
            f"and guiding pedagogical hints on the topic: '{topic}'."
        )

        try:
            client = self._get_client()
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=list[QuestionAnswerSchema],
                temperature=0.7,
            )
            response = await client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            usage = getattr(response, "usage_metadata", None)
            if usage:
                logger.info(
                    "[Token Usage] Model: '%s' (Questions) | Prompt: %d | Candidates: %d | Total: %d tokens",
                    self.model,
                    getattr(usage, "prompt_token_count", 0) or 0,
                    getattr(usage, "candidates_token_count", 0) or 0,
                    getattr(usage, "total_token_count", 0) or 0,
                )
            raw_text: str = (response.text or "").strip()
            if raw_text:
                return _schema_adapter.validate_json(raw_text)
        except Exception as e:
            logger.warning("Primary GenAI structured question generation failed: %s", e)

        # Fallback 1: OpenAI-compatible endpoint with nvidia/nemotron-3-super-120b-a12b if Nebius ready
        nebius_key = getattr(settings, "nebius_api_key", "") or getattr(settings, "NEBIUS_API_KEY", "")
        if nebius_key:
            fallback_model = getattr(
                settings, "nebius_question_fallback_model", "nvidia/nemotron-3-super-120b-a12b"
            )
            base_url = getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
            try:
                results = await _call_openai_compatible_questions(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    model=fallback_model,
                    api_key=nebius_key,
                    base_url=base_url,
                )
                if results:
                    return results
            except Exception as err:
                logger.warning("Fallback OpenAI-compatible question generation failed: %s", err)

        # Fallback 2: Standard OpenAI fallback if configured
        openai_key = settings.openai_api_key
        if openai_key:
            fallback_gpt = settings.fallback_gpt_model
            try:
                return await _call_openai_compatible_questions(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    model=fallback_gpt,
                    api_key=openai_key,
                )
            except Exception as err:
                logger.error("Fallback OpenAI question generation failed: %s", err)

        return []
