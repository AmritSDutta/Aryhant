from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from google.genai import types

from chat_agent.config import settings

logger = logging.getLogger(__name__)


@runtime_checkable
class ModelRunner(Protocol):
    """Protocol for model execution engines."""

    async def run(
        self,
        user_id: str,
        session_id: str,
        content: types.Content,
        user_memory_context: str | None = None,
    ) -> str:
        """Execute model with user message content and session context."""
        ...


def get_model_runner(provider: str | None = None) -> ModelRunner:
    """Return the active model runner instance for the configured provider."""
    selected = (provider or getattr(settings, "MODEL_PROVIDER", "gemini")).lower().strip()
    if selected == "gemini":
        from chat_agent.agents.gemini_model_runner import GeminiModelRunner

        return GeminiModelRunner()
    if selected == "nebius":
        from chat_agent.agents.nebius_model_runner import NebiusModelRunner

        return NebiusModelRunner()
    raise ValueError(f"Unsupported model provider: '{selected}'. Supported: 'gemini', 'nebius'")
