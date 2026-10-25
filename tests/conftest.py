"""Shared fixtures for hermetic, isolated testing across the test suite."""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from chat_agent.app import app
from chat_agent.config import Settings


@pytest.fixture
def mock_settings() -> Settings:
    """Provide an isolated, predictable Settings instance for tests."""
    return Settings(
        APP_NAME="test-aryhant",
        USER_LLM_API_KEY="test-llm-key",
        USER_LLM_MODEL="gemini-flash-lite-latest",
        SLACK_BOT_TOKEN="xoxb-test-bot-token",
        SLACK_APP_TOKEN="xapp-test-app-token",
        SLACK_SIGNING_SECRET="test-slack-secret",
        WEBHOOK_SHARED_SECRET="test-webhook-secret",
        EMAIL_ENABLED=True,
        EMAIL_ADDRESS="bot@example.com",
        EMAIL_PASSWORD="test-password",
        EMAIL_SMTP_HOST="smtp.example.com",
        EMAIL_SMTP_PORT=587,
        EMAIL_IMAP_HOST="imap.example.com",
        EMAIL_IMAP_PORT=993,
        EMAIL_ALLOWED_SENDERS="allowed@example.com",
        GROQ_API_KEY="gsk-test-key",
    )


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI TestClient with rate limits/lifespan enabled."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singleton clients, receivers, and runners between tests."""
    import chat_agent.agents.runner as runner_mod
    import chat_agent.config.qstash_authentication as qstash_mod
    import chat_agent.utils.input_validation as iv

    iv._groq_client = None
    iv._openai_client = None
    runner_mod._runners = {}
    qstash_mod._receiver = None
    yield
    iv._groq_client = None
    iv._openai_client = None
    runner_mod._runners = {}
    qstash_mod._receiver = None



