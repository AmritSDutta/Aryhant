from chat_agent.config.logging_config import setup_logging
from chat_agent.config.qstash_authentication import get_receiver, verify_qstash
from chat_agent.config.settings import Settings, settings


def llm_ready() -> bool:
    """Return True if LLM API key is configured."""
    return settings.llm_ready


def slack_ready() -> bool:
    """Return True if Slack bot and app tokens are configured."""
    return settings.slack_ready


def slack_http_ready() -> bool:
    """Return True if Slack bot token is configured."""
    return settings.slack_http_ready


def webhook_auth_ready() -> bool:
    """Return True if webhook or Slack secrets are configured."""
    return settings.webhook_auth_ready


def email_ready() -> bool:
    """Return True if email IMAP/SMTP credentials are fully configured."""
    return settings.email_ready


def qstash_ready() -> bool:
    """Return True if QStash signing keys are configured."""
    return settings.qstash_ready


__all__ = [
    "Settings",
    "settings",
    "llm_ready",
    "slack_ready",
    "slack_http_ready",
    "webhook_auth_ready",
    "email_ready",
    "qstash_ready",
    "setup_logging",
    "get_receiver",
    "verify_qstash",
]

