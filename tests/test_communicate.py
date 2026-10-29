from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from chat_agent.app import app
from chat_agent.communicate.client import set_agentmail_client
from chat_agent.communicate.intent import is_administrative_query
from chat_agent.communicate.llm import generate_communicate_reply
from chat_agent.communicate.service import process_communicate_event, render_email_html
from chat_agent.config import settings


@pytest.fixture
def mock_agentmail():
    """Mock AgentMail client with inboxes, messages, and threads hierarchy."""
    client = MagicMock()
    client.inboxes = MagicMock()
    client.inboxes.messages = MagicMock()
    client.inboxes.messages.reply = AsyncMock()
    client.inboxes.messages.update = AsyncMock()
    client.inboxes.threads = MagicMock()
    client.inboxes.threads.get = AsyncMock()
    set_agentmail_client(client)
    yield client
    set_agentmail_client(None)


def test_intent_detection():
    """Verify administrative keyword intent matching."""
    assert is_administrative_query("System Status & Audit", "Please provide a telemetry report") is True
    assert is_administrative_query("Nightly Prune", "Check retention metrics") is True
    assert is_administrative_query("Health check", "What is the token consumption?") is True
    assert is_administrative_query("Math lesson", "Can you explain ICSE grade 5 fractions?") is False
    assert is_administrative_query("", "") is False


@pytest.mark.asyncio
async def test_communicate_unauthorized_sender(mock_agentmail, monkeypatch):
    """Unauthorized senders must be silently dropped without responding, and labeled unauthorized_sender."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org,ops@amritai.org")

    payload = {
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_unauth",
            "from_": "attacker@unknown.com",
            "subject": "System audit request",
            "extracted_text": "Give me the system audit report",
        }
    }

    await process_communicate_event(payload)

    # Must update label to unauthorized_sender and remove unreplied
    mock_agentmail.inboxes.messages.update.assert_awaited_once_with(
        inbox_id="inbox_123",
        message_id="msg_unauth",
        add_labels=["unauthorized_sender"],
        remove_labels=["unreplied"],
    )
    # Must NOT send any reply
    mock_agentmail.inboxes.messages.reply.assert_not_called()


@pytest.mark.asyncio
async def test_communicate_non_admin_query_ignored(mock_agentmail, monkeypatch):
    """Allowed senders asking non-administrative queries must be ignored and labeled ignored_non_admin."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org")

    payload = {
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_non_admin",
            "from_": "admin@amritai.org",
            "subject": "Hello Aryhant",
            "extracted_text": "Can you help me solve a math problem about fractions?",
        }
    }

    await process_communicate_event(payload)

    mock_agentmail.inboxes.messages.update.assert_awaited_once_with(
        inbox_id="inbox_123",
        message_id="msg_non_admin",
        add_labels=["ignored_non_admin"],
    )
    mock_agentmail.inboxes.messages.reply.assert_not_called()


@pytest.mark.asyncio
async def test_communicate_admin_query_success(mock_agentmail, monkeypatch):
    """Allowed sender asking an administrative query receives a synthesized audit report."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org")

    payload = {
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_admin_ok",
            "from_": "Admin User <admin@amritai.org>",
            "subject": "Aryhant 7-Day Operations Telemetry & Retention Audit",
            "extracted_text": "Please provide the latest operational audit and data retention metrics.",
        }
    }

    mock_reply = "# ✅ Administrative & Operations Audit\n\n| Metric Category | Telemetry |\n| --- | --- |\n| Status | HEALTHY |"

    with patch("chat_agent.communicate.service.generate_communicate_reply", AsyncMock(return_value=mock_reply)):
        await process_communicate_event(payload)

    # Must reply with message_id, text, html
    mock_agentmail.inboxes.messages.reply.assert_awaited_once()
    call_kwargs = mock_agentmail.inboxes.messages.reply.call_args.kwargs
    assert call_kwargs["inbox_id"] == "inbox_123"
    assert call_kwargs["message_id"] == "msg_admin_ok"
    assert "HEALTHY" in call_kwargs["text"]
    assert "<table" in call_kwargs["html"]
    # bcc should be omitted if unset
    assert "bcc" not in call_kwargs

    # Must mark replied
    mock_agentmail.inboxes.messages.update.assert_awaited_once_with(
        inbox_id="inbox_123",
        message_id="msg_admin_ok",
        add_labels=["replied"],
        remove_labels=["unreplied"],
    )


@pytest.mark.asyncio
async def test_communicate_extracted_html_priority(mock_agentmail, monkeypatch):
    """extracted_html must take priority over raw text and raw html when extracted_text is missing."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org")

    payload = {
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_html_prio",
            "from_": "admin@amritai.org",
            "subject": "Telemetry Check",
            "extracted_text": "",
            "extracted_html": "<p>Please audit telemetry status</p>",
            "text": "Ignored raw text",
            "html": "<p>Ignored raw html</p>",
        }
    }

    mock_reply = "# ✅ Administrative & Operations Audit\n\nOk"

    with patch("chat_agent.communicate.service.generate_communicate_reply", AsyncMock(return_value=mock_reply)) as mock_gen:
        await process_communicate_event(payload)
        # Ensure the extracted_html was passed to the LLM
        assert "<p>Please audit telemetry status</p>" in mock_gen.call_args[0][1]


@pytest.mark.asyncio
async def test_communicate_depth_limit(mock_agentmail, monkeypatch):
    """Threads exceeding COMMUNICATE_MAX_THREAD_DEPTH must be halted and labeled depth_limit_reached."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org")

    thread_mock = MagicMock()
    thread_mock.messages = [MagicMock() for _ in range(15)]
    mock_agentmail.inboxes.threads.get.return_value = thread_mock

    payload = {
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_deep",
            "thread_id": "thread_deep",
            "from_": "admin@amritai.org",
            "subject": "System Status Audit",
            "extracted_text": "Please provide an audit report",
        }
    }

    await process_communicate_event(payload)

    mock_agentmail.inboxes.messages.update.assert_awaited_once_with(
        inbox_id="inbox_123",
        message_id="msg_deep",
        add_labels=["depth_limit_reached"],
    )
    mock_agentmail.inboxes.messages.reply.assert_not_called()


@pytest.mark.asyncio
async def test_communicate_dict_thread_depth(mock_agentmail, monkeypatch):
    """Thread depth check must also work when the SDK returns a dictionary mapping."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org")

    # Mock thread returned as dict instead of object
    mock_agentmail.inboxes.threads.get.return_value = {
        "messages": [{"id": f"m_{i}"} for i in range(15)]
    }

    payload = {
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_dict_depth",
            "thread_id": "thread_dict_deep",
            "from_": "admin@amritai.org",
            "subject": "System Status Audit",
            "extracted_text": "Please provide an audit report",
        }
    }

    await process_communicate_event(payload)

    mock_agentmail.inboxes.messages.update.assert_awaited_once_with(
        inbox_id="inbox_123",
        message_id="msg_dict_depth",
        add_labels=["depth_limit_reached"],
    )
    mock_agentmail.inboxes.messages.reply.assert_not_called()


@pytest.mark.asyncio
async def test_communicate_no_reply_protocol(mock_agentmail, monkeypatch):
    """When LLM returns NO_REPLY, the service must label llm_no_reply and skip sending."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org")

    payload = {
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_concluded",
            "from_": "admin@amritai.org",
            "subject": "Audit Report Followup",
            "extracted_text": "Thanks, this audit is resolved.",
        }
    }

    with patch("chat_agent.communicate.service.generate_communicate_reply", AsyncMock(return_value="NO_REPLY")):
        await process_communicate_event(payload)

    mock_agentmail.inboxes.messages.update.assert_awaited_once_with(
        inbox_id="inbox_123",
        message_id="msg_concluded",
        add_labels=["llm_no_reply"],
    )
    mock_agentmail.inboxes.messages.reply.assert_not_called()


@pytest.mark.asyncio
async def test_communicate_llm_primary_failover(monkeypatch):
    """Verify primary model failure triggers fallback model execution."""
    telemetry = {"failure_count": 0, "deleted_records_count": 5}
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "mock-openai-key")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-openai-key")

    with patch(
        "chat_agent.communicate.llm._call_nebius_or_openai",
        AsyncMock(side_effect=[Exception("Rate limit on primary"), "Fallback report"]),
    ), patch(
        "chat_agent.communicate.llm._call_gemini",
        AsyncMock(return_value="Gemini fallback report"),
    ):
        reply = await generate_communicate_reply("Audit", "Status", telemetry)
        assert reply == "Fallback report"


@pytest.mark.asyncio
async def test_communicate_llm_gemini_fallback_when_openai_key_missing(monkeypatch):
    """Verify missing openai_api_key triggers failover to Gemini fallback without live network calls."""
    telemetry = {"failure_count": 0, "deleted_records_count": 5}
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch(
        "chat_agent.communicate.llm._call_nebius_or_openai",
        AsyncMock(side_effect=Exception("Rate limit on primary")),
    ), patch(
        "chat_agent.communicate.llm._call_gemini",
        AsyncMock(return_value="Gemini fallback report"),
    ):
        reply = await generate_communicate_reply("Audit", "Status", telemetry)
        assert reply == "Gemini fallback report"


def test_communicate_endpoint_with_auth(monkeypatch):
    """Test POST /api/communicate with shared secret authentication."""
    monkeypatch.setattr(settings, "ARYHANT_WEBHOOK_SHARED_SECRET", "super-test-secret")
    client = TestClient(app)

    payload = {
        "event_type": "message.received",
        "message": {
            "inbox_id": "inbox_123",
            "message_id": "msg_001",
            "from_": "admin@amritai.org",
            "subject": "System audit",
            "extracted_text": "Audit report",
        },
    }

    # 1. Missing secret -> 401
    resp_unauth = client.post("/api/communicate", json=payload)
    assert resp_unauth.status_code == 401

    # 2. Valid forwarded secret -> 200 Queued
    headers = {"X-Qstash-Forward-X-Webhook-Secret": "super-test-secret"}
    with patch("chat_agent.communicate.router.process_communicate_event", AsyncMock()):
        resp_ok = client.post("/api/communicate", json=payload, headers=headers)
        assert resp_ok.status_code == 200
        assert resp_ok.json() == {"ok": True, "status": "queued"}


def test_communicate_endpoint_fail_closed(monkeypatch):
    """When no secrets are configured on the server, endpoint must fail-closed with 503."""
    monkeypatch.setattr(settings, "ARYHANT_WEBHOOK_SHARED_SECRET", "")
    monkeypatch.setattr(settings, "QSTASH_CURRENT_SIGNING_KEY", "")
    client = TestClient(app)

    payload = {
        "event_type": "message.received",
        "message": {"inbox_id": "inbox_123", "message_id": "msg_001"},
    }

    resp = client.post("/api/communicate", json=payload)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_communicate_recipient_mismatch_skipped(mock_agentmail, monkeypatch):
    """When ARYHANT_AGENTMAIL_EMAILID is configured, emails not addressed to it must be skipped."""
    monkeypatch.setattr(settings, "ARYHANT_ALLOWED_EMAILS", "admin@amritai.org")
    monkeypatch.setattr(settings, "ARYHANT_AGENTMAIL_EMAILID", "aryhant@agentmail.to")

    payload = {
        "message": {
            "inbox_id": "other_inbox",
            "message_id": "msg_mismatch",
            "from_": "admin@amritai.org",
            "to": ["someone_else@example.com"],
            "subject": "System audit",
            "extracted_text": "Audit report",
        }
    }

    await process_communicate_event(payload)

    # Must be completely skipped: no replies and no label updates
    mock_agentmail.inboxes.messages.reply.assert_not_called()
    mock_agentmail.inboxes.messages.update.assert_not_called()


def test_render_email_html_mild_gradient():
    """Verify that render_email_html loads the template with the central header and mild gradient palette."""
    rendered = render_email_html("### Operational Status\n\nAll tasks operational.")
    # Check palette colors
    assert "#f6eee3" in rendered
    assert "linear-gradient" in rendered
    assert "Operational Status" in rendered
    # Check central header 'Aryhant'
    assert "<h1" in rendered
    assert "Aryhant</h1>" in rendered
    assert "text-align: center" in rendered
    # Ensure no artificial white card or unwanted banner subtitles were introduced
    assert "background: #ffffff" not in rendered
    assert "Autonomous Administrative Report" not in rendered

