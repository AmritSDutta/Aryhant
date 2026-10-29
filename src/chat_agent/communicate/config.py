from __future__ import annotations

import os
from dataclasses import dataclass
from chat_agent.config import settings


@dataclass(frozen=True)
class CommunicateConfig:
    """Configuration options for the AgentMail communicate endpoint and LLM dispatch."""

    provider: str
    model: str
    fallback_model: str
    max_thread_depth: int
    agentmail_api_key: str
    agentmail_inbox_id: str
    agentmail_bcc_email: str
    agentmail_webhook_secret: str


def get_communicate_config() -> CommunicateConfig:
    """Retrieve communication configuration dynamically from environment and core settings."""
    provider = (
        os.getenv("COMMUNICATE_PROVIDER")
        or getattr(settings, "MODEL_PROVIDER", "nebius")
    ).lower().strip()

    if provider == "nebius":
        default_model = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
        default_fallback = "gpt-6-luna"
    else:
        default_model = "gemini-flash-lite-latest"
        default_fallback = "gemini-3.1-flash-lite"

    model = os.getenv("COMMUNICATE_MODEL") or default_model
    fallback_model = os.getenv("COMMUNICATE_FALLBACK_MODEL") or default_fallback

    try:
        depth = int(os.getenv("COMMUNICATE_MAX_THREAD_DEPTH", "10"))
    except ValueError:
        depth = 10

    return CommunicateConfig(
        provider=provider,
        model=model,
        fallback_model=fallback_model,
        max_thread_depth=depth,
        agentmail_api_key=getattr(settings, "aryhant_agentmail_api_key", ""),
        agentmail_inbox_id=getattr(settings, "aryhant_agentmail_emailid", ""),
        agentmail_bcc_email=getattr(settings, "aryhant_agentmail_bcc_email", ""),
        agentmail_webhook_secret=getattr(settings, "aryhant_webhook_shared_secret", ""),
    )
