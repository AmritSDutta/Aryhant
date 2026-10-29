from __future__ import annotations

import asyncio
import logging
from typing import Any

from google.genai import types

from chat_agent.agents.model_runner import get_model_runner
from chat_agent.config import settings

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


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
    history: list[dict[str, Any]] | None = None,
) -> str:
    """Execute the configured model runner asynchronously with text and optional attachments."""
    try:
        from chat_agent.services.session_task_service import get_session_task_service

        reg_task = asyncio.create_task(
            get_session_task_service().acreate_task(
                session_id=session_id,
                user_id=user_id,
                task_type="chat",
                provider=getattr(settings, "MODEL_PROVIDER", "gemini"),
            )
        )
        _BACKGROUND_TASKS.add(reg_task)
        reg_task.add_done_callback(_BACKGROUND_TASKS.discard)
    except Exception as exc:
        logger.warning("Failed to schedule chat session task registration: %s", exc)

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
    raw_reply = await runner.run(
        user_id=user_id,
        session_id=session_id,
        content=content,
        user_memory_context=user_memory_context,
        history=history,
    )
    from chat_agent.utils.text_formatter import format_human_readable_text

    return format_human_readable_text(raw_reply)
