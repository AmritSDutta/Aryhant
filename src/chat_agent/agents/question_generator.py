import json
import logging
from typing import Optional
from pydantic import TypeAdapter
from google import genai
from google.genai import types

from chat_agent.agents.prompt import QA_GENERATOR_INSTRUCTION, format_instruction
from chat_agent.config import settings
from chat_agent.schema.fundamental_schema import QuestionAnswerSchema
from chat_agent.utils.fast_decision.typesafe_integrator import get_feedback

logger = logging.getLogger(__name__)
_genai_client: Optional[genai.Client] = None
_schema_adapter: TypeAdapter[list[QuestionAnswerSchema]] = TypeAdapter(list[QuestionAnswerSchema])


def _get_genai_client() -> genai.Client:
    """Return a cached Google GenAI client instance."""
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.api_key)
    return _genai_client


async def generate_candidate_questions(
    topic: str,
    min_count: int = 15,
    max_count: int = 20,
) -> list[QuestionAnswerSchema]:
    system_instruction: str = format_instruction(QA_GENERATOR_INSTRUCTION)
    prompt: str = (
        f"Generate between {min_count} and {max_count} distinct Grade 5 ICSE practice questions "
        f"and guiding pedagogical hints on the topic: '{topic}'."
    )

    try:
        client: genai.Client = _get_genai_client()
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=list[QuestionAnswerSchema],
            temperature=0.7,
        )
        response = await client.aio.models.generate_content(
            model=settings.model,
            contents=prompt,
            config=config,
        )
        raw_text: str = (response.text or "").strip()
        if raw_text:
            return _schema_adapter.validate_json(raw_text)
    except Exception as e:
        logger.warning("Primary GenAI structured question generation failed: %s", e)

    # Fallback to OpenAI structured completion if configured
    fallback_model: str = settings.fallback_gpt_model
    openai_key: str = settings.openai_api_key
    if openai_key:
        try:
            from openai import AsyncOpenAI

            openai_client = AsyncOpenAI(api_key=openai_key)
            completion = await openai_client.chat.completions.create(
                model=fallback_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content_str: str = completion.choices[0].message.content or "{}"
            parsed = json.loads(content_str)
            if isinstance(parsed, list):
                raw_list = parsed
            elif "questions" in parsed and isinstance(parsed["questions"], list):
                raw_list = parsed["questions"]
            else:
                logger.warning("OpenAI response JSON missing 'questions' list key: %s", parsed)
                raw_list = []
            return _schema_adapter.validate_python(raw_list)
        except Exception as err:
            logger.error("Fallback OpenAI question generation failed: %s", err)

    return []


async def generate_curated_questions(
    topic: str,
) -> list[QuestionAnswerSchema]:
    """Generate 15-20 candidate questions and return the top 10 scored by TypeSafe AI (with graceful fallback)."""
    candidates: list[QuestionAnswerSchema] = await generate_candidate_questions(topic)
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


