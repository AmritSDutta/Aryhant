"""Hermetic unit tests for Settings, readiness helpers, Auth0, and Grafana config."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException

from chat_agent.config import (
    Settings,
    email_ready,
    llm_ready,
    settings,
    slack_http_ready,
    slack_ready,
    webhook_auth_ready,
)
from chat_agent.config.auth0_config import get_jwks, verify_token
from chat_agent.config.grafana_config import setup_grafana


def test_settings_initialization_and_properties():
    cfg = Settings(
        APP_NAME="custom-bot",
        USER_LLM_API_KEY="custom-api-key",
        USER_LLM_MODEL="gemini-3.5-flash-lite",
        ARYHANT_SLACK_BOT_TOKEN="xoxb-custom",
        ARYHANT_SLACK_APP_TOKEN="xapp-custom",
        SLACK_SIGNING_SECRET="secret",
        WEBHOOK_SHARED_SECRET="shared",
        EMAIL_ENABLED=True,
        EMAIL_ADDRESS="agent@domain.com",
        EMAIL_PASSWORD="agent-secret-pass",
        EMAIL_ALLOWED_SENDERS="sender1@domain.com, sender2@domain.com",
        GROQ_API_KEY="gsk-key",
        GRAFANA_USER_ID="custom-grafana-user",
        QSTASH_CURRENT_SIGNING_KEY="sig_key_curr",
        QSTASH_NEXT_SIGNING_KEY="sig_key_next",
    )

    assert cfg.app_name == "custom-bot"
    assert cfg.api_key == "custom-api-key"
    assert cfg.model == "gemini-3.5-flash-lite"
    assert cfg.slack_ready is True
    assert cfg.aryhant_slack_bot_token == "xoxb-custom"
    assert cfg.aryhant_slack_app_token == "xapp-custom" 
    assert cfg.slack_http_ready is True
    assert cfg.webhook_auth_ready is True
    assert cfg.email_ready is True
    assert cfg.email_allowed_senders_list == ["sender1@domain.com", "sender2@domain.com"]
    assert cfg.qstash_ready is True
    assert cfg.qstash_current_signing_key == "sig_key_curr"
    assert cfg.qstash_next_signing_key == "sig_key_next"
    assert cfg.grafana_user_id == "custom-grafana-user"


def test_settings_unconfigured_defaults():
    cfg = Settings(
        USER_LLM_API_KEY="",
        GEMINI_API_KEY="",
        GOOGLE_API_KEY="",
        ARYHANT_SLACK_BOT_TOKEN="",
        ARYHANT_SLACK_APP_TOKEN="",
        EMAIL_ENABLED=False,
        QSTASH_CURRENT_SIGNING_KEY="",
    )
    assert cfg.llm_ready is False
    assert cfg.slack_ready is False
    assert cfg.slack_http_ready is False
    assert cfg.email_ready is False
    assert cfg.qstash_ready is False
    assert cfg.email_allowed_senders_list == []


@pytest.mark.asyncio
async def test_auth0_get_jwks_mocked():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"keys": [{"kid": "test-kid", "kty": "RSA"}]}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client), patch(
        "chat_agent.config.auth0_config._jwks_cache", None
    ):
        jwks = await get_jwks()
        assert "keys" in jwks
        assert jwks["keys"][0]["kid"] == "test-kid"


@pytest.mark.asyncio
async def test_auth0_verify_token_when_auth_disabled():
    with patch("chat_agent.config.auth0_config.settings") as mock_settings:
        mock_settings.REQUIRE_AUTH = False
        res = await verify_token(None)
        assert res == {"payload": {}, "permissions": []}


def test_setup_grafana_unconfigured():
    app_mock = MagicMock()
    with patch("chat_agent.config.grafana_config.settings") as mock_cfg:
        mock_cfg.GRAFANA_API_TOKEN = ""
        mock_cfg.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        mock_cfg.grafana_user_id = ""
        # Should return silently without error
        setup_grafana(app_mock)


def test_setup_grafana_missing_user_id():
    app_mock = MagicMock()
    with patch("chat_agent.config.grafana_config.settings") as mock_cfg:
        mock_cfg.GRAFANA_API_TOKEN = "glc_token"
        mock_cfg.OTEL_EXPORTER_OTLP_ENDPOINT = "https://otlp.example.com"
        mock_cfg.grafana_user_id = ""
        with patch.dict("os.environ", {}, clear=True):
            setup_grafana(app_mock)



def test_settings_aryhant_slack_tokens():
    cfg = Settings(
        USER_LLM_API_KEY="custom-api-key",
        ARYHANT_SLACK_BOT_TOKEN="xoxb-aryhant",
        ARYHANT_SLACK_APP_TOKEN="xapp-aryhant",
    )
    assert cfg.aryhant_slack_bot_token == "xoxb-aryhant"
    assert cfg.aryhant_slack_app_token == "xapp-aryhant"
    assert cfg.slack_ready is True
    assert cfg.slack_http_ready is True
