"""Hermetic unit tests for FastAPI application endpoints and webhooks."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from chat_agent.app import ChatRequest, app
from chat_agent.config.qstash_authentication import verify_qstash


@pytest.fixture(autouse=True)
def override_qstash_auth():
    """Bypass QStash verification and default auth for general app endpoint tests."""
    app.dependency_overrides[verify_qstash] = lambda: None
    with patch("chat_agent.config.auth0_config.settings.REQUIRE_AUTH", False):
        yield
    app.dependency_overrides.pop(verify_qstash, None)


def test_root_endpoint(client: TestClient):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json() == {
        "name": "Private Chat Agent",
        "version": "0.1.0",
    }


def test_api_health_endpoint(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {
        "status": "healthy",
        "version": "0.1.0",
        "ok": True,
    }


def test_chat_endpoint_demo_mode_when_unconfigured(client: TestClient):
    with patch("chat_agent.app.llm_ready", return_value=False):
        res = client.post("/api/chat", json={"message": "Hello bot", "channel": "web"})
        assert res.status_code == 200
        data = res.json()
        assert "Demo mode" in data["reply"]
        assert data["model"] == "demo"
        assert data["channel"] == "web"


def test_chat_endpoint_live_mode_mocked_agent(client: TestClient):
    with patch("chat_agent.app.llm_ready", return_value=True), patch(
        "chat_agent.app.run_agent", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = "Mocked AI assistant response"
        res = client.post("/api/chat", json={"message": "Help me plan", "channel": "web"})
        assert res.status_code == 200
        data = res.json()
        assert data["reply"] == "Mocked AI assistant response"
        mock_run.assert_awaited_once()


def test_chat_endpoint_input_validation_rejection(client: TestClient):
    res = client.post("/api/chat", json={"message": "rm -rf /", "channel": "web"})
    assert res.status_code == 400
    assert "Input validation failed" in res.json()["detail"]


def test_chat_endpoint_auth_enforced_when_require_auth_true(client: TestClient):
    with patch("chat_agent.config.auth0_config.settings.REQUIRE_AUTH", True):
        res = client.post("/api/chat", json={"message": "Hello", "channel": "web"})
        assert res.status_code == 401
        assert res.json()["detail"] == "Missing authorization token"


def test_slack_webhook_url_verification(client: TestClient):
    payload = {"type": "url_verification", "challenge": "secret_challenge_123"}
    res = client.post("/webhooks/slack", json=payload)
    assert res.status_code == 200
    assert res.json() == {"challenge": "secret_challenge_123"}


def test_slack_webhook_event_authorized(client: TestClient):
    payload = {
        "type": "event_callback",
        "event": {"type": "app_mention", "text": "<@U123> hi", "channel": "C123", "user": "U456"},
    }
    with patch("chat_agent.app.authorize_webhook"), patch(
        "chat_agent.app.slack_http_ready", return_value=True
    ), patch(
        "chat_agent.app.handle_slack_payload",
        new_callable=AsyncMock,
        return_value={"ok": True, "channel": "C123"},
    ) as mock_handle:
        res = client.post("/webhooks/slack", json=payload)
        assert res.status_code == 200
        assert res.json() == {"ok": True}
        mock_handle.assert_awaited_once()
