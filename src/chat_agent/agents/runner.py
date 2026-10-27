from __future__ import annotations

import logging

from google.genai import types

from chat_agent.agents.model_runner import get_model_runner
from chat_agent.config import settings

logger = logging.getLogger(__name__)


def clip_text(text: str, limit: int | None = None) -> str:
    """Clip input text to configured length."""
    limit = limit or settings.max_input_chars
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[truncated]"


async def run_agent(
    user_id: str,
    session_id: str,
    message: str = "",
    attachments: list[tuple[bytes, str]] | None = None,
    custom_content: types.Content | None = None,
    user_memory_context: str | None = None,
) -> str:
    """Execute the configured model runner asynchronously with text and optional attachments."""
    if custom_content is not None:
        content = custom_content
    else:
        prompt = clip_text(message)
        media_items = attachments or []
        if not prompt and not media_items:
            return "I need a message to reply to."

        from chat_agent.utils.multimodal import (
            build_adk_multimodal_content,
            validate_multimodal_payload,
        )

        if not await validate_multimodal_payload(prompt, media_items):
            logger.warning("Rejected potentially unsafe message from user %s", user_id)
            return "Your message could not be processed because it contains potentially unsafe content."

        content = build_adk_multimodal_content(prompt, media_items)

    runner = get_model_runner()
    return await runner.run(
        user_id=user_id,
        session_id=session_id,
        content=content,
        user_memory_context=user_memory_context,
    )
