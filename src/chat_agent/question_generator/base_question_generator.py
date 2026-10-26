from __future__ import annotations

import abc
import json
import logging
from typing import Any, Optional

from google import genai
from pydantic import TypeAdapter

from chat_agent.config import settings
from chat_agent.schema.fundamental_schema import QuestionAnswerSchema

logger = logging.getLogger(__name__)

_genai_client: Optional[genai.Client] = None
_schema_adapter: TypeAdapter[list[QuestionAnswerSchema]] = TypeAdapter(list[QuestionAnswerSchema])


def _get_genai_client() -> genai.Client:
    """Return a cached Google GenAI client instance."""
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.api_key)
    return _genai_client


def _parse_json_questions(raw_content: str) -> list[QuestionAnswerSchema]:
    """Parse JSON string into QuestionAnswerSchema items supporting root list or object wrapper."""
    content_str = (raw_content or "").strip()
    if not content_str:
        return []
    try:
        parsed = json.loads(content_str)
    except Exception as err:
        logger.warning("Failed to decode JSON questions: %s", err)
        return []

    if isinstance(parsed, list):
        raw_list = parsed
    elif isinstance(parsed, dict):
        if "questions" in parsed and isinstance(parsed["questions"], list):
            raw_list = parsed["questions"]
        else:
            for val in parsed.values():
                if isinstance(val, list):
                    raw_list = val
                    break
            else:
                logger.warning("JSON object missing questions list key: %s", parsed)
                raw_list = []
    else:
        raw_list = []

    return _schema_adapter.validate_python(raw_list)


async def _call_openai_compatible_questions(
    prompt: str,
    system_instruction: str,
    model: str,
    api_key: str,
    base_url: str | None = None,
) -> list[QuestionAnswerSchema]:
    """Execute chat completion with JSON parsing against an OpenAI-compatible endpoint."""
    if not api_key:
        return []

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt},
    ]

    try:
        from openai import AsyncOpenAI

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        client = AsyncOpenAI(**client_kwargs)
        completion = await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        usage = getattr(completion, "usage", None)
        if usage:
            logger.info(
                "[Token Usage] Model: '%s' (Questions) | Prompt: %d | Completion: %d | Total: %d tokens",
                model,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
                getattr(usage, "total_tokens", 0) or 0,
            )
        raw_content = completion.choices[0].message.content or "{}"
        return _parse_json_questions(raw_content)
    except (ImportError, ModuleNotFoundError):
        import httpx

        endpoint = f"{(base_url or 'https://api.openai.com/v1').rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        }
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            resp = await http_client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            raw_content = data.get("choices", [{}])[0].get("message", {}).get("content") or "{}"
            return _parse_json_questions(raw_content)


class BaseQuestionGenerator(abc.ABC):
    """Abstract base class for question generation engines."""

    @abc.abstractmethod
    async def generate_candidate_questions(
        self,
        topic: str,
        min_count: int = 15,
        max_count: int = 20,
    ) -> list[QuestionAnswerSchema]:
        """Generate candidate questions on a given topic."""
        ...
