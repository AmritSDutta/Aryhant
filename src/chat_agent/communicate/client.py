from __future__ import annotations

import logging
from typing import Any
from chat_agent.communicate.config import get_communicate_config

logger = logging.getLogger(__name__)

_agentmail_client: Any = None


def get_agentmail_client() -> Any:
    """Return singleton AsyncAgentMail instance or mockable proxy."""
    global _agentmail_client
    if _agentmail_client is not None:
        return _agentmail_client

    config = get_communicate_config()
    try:
        from agentmail import AsyncAgentMail

        _agentmail_client = AsyncAgentMail(api_key=config.agentmail_api_key)
    except Exception as err:
        logger.warning("agentmail SDK unavailable or failed to initialize: %s. Using placeholder.", err)
        _agentmail_client = None
    return _agentmail_client


def set_agentmail_client(client: Any) -> None:
    """Explicitly inject client (useful for unit tests)."""
    global _agentmail_client
    _agentmail_client = client
