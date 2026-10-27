"""Hermetic unit tests for Slack HTTP handlers, signature verification, and webhook authorization."""

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException, Request

from chat_agent.slack.post_generator import chunk_text, generate_slack_post
from chat_agent.slack.slack_http import (
    event_text,
    handle_slack_payload,
    post_slack_message,
    should_handle_event,
    verify_slack_signature,
)
from chat_agent.webhooks import authorize_webhook


def test_verify_slack_signature_valid():
    secret = "test_signing_secret"
    timestamp = str(int(time.time()))
    body = b'{"text":"hello"}'

    digest = hmac.new(
        secret.encode("utf-8"),
        f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signature = f"v0={digest}"

    assert verify_slack_signature(body, timestamp, signature, secret) is True


def test_verify_slack_signature_expired():
    secret = "test_signing_secret"
    old_timestamp = str(int(time.time()) - 400)  # > 300s old
    body = b'{"text":"hello"}'
    signature = "v0=dummy"

    assert verify_slack_signature(body, old_timestamp, signature, secret) is False


def test_should_handle_event_cases():
    assert should_handle_event({"type": "app_mention", "text": "<@U123> hi"}) is True
    assert should_handle_event({"type": "message", "channel_type": "im", "text": "hello"}) is True
    assert should_handle_event({"type": "message", "channel_type": "mpim", "text": "group"}) is True
    assert should_handle_event({"type": "message", "channel_type": "channel", "text": "noise"}) is False
    assert should_handle_event({"type": "app_mention", "bot_id": "B123", "text": "loop"}) is False
    assert should_handle_event({}) is False


def test_event_text_strips_mention():
    assert event_text({"text": "<@U12345>   what time is it?"}) == "what time is it?"
    assert event_text({"text": "no mention"}) == "no mention"


@pytest.mark.asyncio
async def test_post_slack_message_text_only():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await post_slack_message("C123", text="Hello channel", thread_ts="12345.67")
        assert res == {"ok": True}
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["channel"] == "C123"
        assert call_kwargs["json"]["text"] == "Hello channel"
        assert "blocks" not in call_kwargs["json"]


@pytest.mark.asyncio
async def test_post_slack_message_blocks_only_fallback():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "ts": "12345.67"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Block text"}}]
    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await post_slack_message(
            channel="C123",
            blocks=blocks,
            thread_ts="12345.67",
        )
        assert res["ok"] is True
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["channel"] == "C123"
        assert call_kwargs["json"]["blocks"] == blocks
        assert call_kwargs["json"]["text"] == "Aryhant Update"


@pytest.mark.asyncio
async def test_post_slack_message_both_text_and_blocks():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Block text"}}]
    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await post_slack_message(
            channel="C123",
            text="Custom Fallback",
            blocks=blocks,
            thread_ts="12345.67",
        )
        assert res == {"ok": True}
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["text"] == "Custom Fallback"
        assert call_kwargs["json"]["blocks"] == blocks


@pytest.mark.asyncio
async def test_post_slack_message_empty_payload_raises_value_error():
    with pytest.raises(ValueError, match="Either text or blocks must be provided"):
        await post_slack_message("C123")


def test_chunk_text_word_boundary():
    words = ["word" + str(i) for i in range(700)]
    long_text = " ".join(words)
    chunks = chunk_text(long_text, max_chunk_size=2800)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 2800
        assert not chunk.endswith(" ")
        assert not chunk.startswith(" ")


def test_generate_slack_post_blocks():
    reply = "# Math Quiz for Grade 5\n\nQ1: What is 12 x 8?\n> Hint: Think of 12 x 4 doubled.\n\nContext: St. Xavier's ICSE"
    post = generate_slack_post(reply)
    assert "Math Quiz for Grade 5" in post["text"]
    assert len(post["blocks"]) >= 3
    assert post["blocks"][0]["type"] == "header"
    assert post["blocks"][1]["type"] == "divider"
    assert post["blocks"][2]["type"] == "section"
    assert "What is 12 x 8?" in post["blocks"][2]["text"]["text"]
    assert post["blocks"][3]["type"] == "context"


def test_generate_slack_post_formatted_context_prefixes():
    reply = "**Note:** Test note 1\n\n> **Hint:** Test hint 2\n\n*Source:* Textbook page 42"
    post = generate_slack_post(reply)
    assert len(post["blocks"]) == 3
    for b in post["blocks"]:
        assert b["type"] == "context"


def test_generate_slack_post_bold_text_is_section_not_header():
    reply = "*Important note for students:* Please review chapter 4."
    post = generate_slack_post(reply)
    assert len(post["blocks"]) == 1
    assert post["blocks"][0]["type"] == "section"
    assert "*Important note for students:*" in post["blocks"][0]["text"]["text"]


def test_generate_slack_post_empty_fallback():
    post = generate_slack_post("")
    assert post["text"] == "Aryhant Update"
    assert len(post["blocks"]) == 1
    assert post["blocks"][0]["type"] == "section"


def test_generate_slack_post_strict_20_block_limit():
    paragraphs = [f"Paragraph {i}: This is some test content for paragraph {i}." for i in range(15)]
    reply = "\n\n".join(paragraphs)
    post = generate_slack_post(reply)
    assert len(post["blocks"]) == 15


def test_generate_slack_post_truncation_notice():
    paragraphs = [f"Paragraph {i}: This is test content for paragraph {i}." for i in range(35)]
    long_reply = "\n\n".join(paragraphs)
    post = generate_slack_post(long_reply)
    assert len(post["blocks"]) == 20
    assert post["blocks"][-1]["type"] == "context"
    assert "truncated" in post["blocks"][-1]["elements"][0]["text"].lower()


def test_generate_slack_post_paragraph_chunking():
    long_paragraph = "word " * 1200
    post = generate_slack_post(long_paragraph)
    assert len(post["blocks"]) >= 2
    for block in post["blocks"]:
        assert block["type"] == "section"
        assert len(block["text"]["text"]) <= 3000


def test_generate_slack_post_limits():
    header_raw = "# " + "H" * 300
    context_raw = "Note: " + "C" * 3000
    reply = f"{header_raw}\n\n{context_raw}"
    post = generate_slack_post(reply)
    header_block = post["blocks"][0]
    assert header_block["type"] == "header"
    assert len(header_block["text"]["text"]) <= 150

    context_block = post["blocks"][2]
    assert context_block["type"] == "context"
    assert len(context_block["elements"][0]["text"]) <= 2000


@pytest.mark.asyncio
async def test_handle_slack_payload_flow():
    payload = {
        "type": "event_callback",
        "event": {
            "type": "app_mention",
            "text": "<@U123> help me summarize",
            "channel": "C123",
            "user": "U456",
            "ts": "12345.67",
        },
    }

    with patch("chat_agent.slack.slack_http.run_agent", new_callable=AsyncMock) as mock_agent, patch(
        "chat_agent.slack.slack_http.post_slack_message", new_callable=AsyncMock
    ) as mock_post:
        mock_agent.return_value = "Summary of research"
        result = await handle_slack_payload(payload)
        assert result == {"ok": True, "channel": "C123"}
        mock_agent.assert_awaited_once()
        mock_post.assert_awaited_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["channel"] == "C123"
        assert call_kwargs["text"] == "Summary of research"
        assert call_kwargs["thread_ts"] == "12345.67"
        assert len(call_kwargs["blocks"]) == 1


def test_authorize_webhook_shared_secret_success():
    req = MagicMock(spec=Request)
    req.headers = {"X-Webhook-Secret": "my_shared_secret"}
    with patch("chat_agent.webhooks.settings") as mock_settings:
        mock_settings.webhook_shared_secret = "my_shared_secret"
        mock_settings.slack_signing_secret = ""
        # Should succeed without raising
        authorize_webhook(req, b"body")


def test_authorize_webhook_invalid_raises_401():
    req = MagicMock(spec=Request)
    req.headers = {"X-Webhook-Secret": "wrong_secret"}
    with patch("chat_agent.webhooks.settings") as mock_settings:
        mock_settings.webhook_shared_secret = "my_shared_secret"
        mock_settings.slack_signing_secret = ""
        with pytest.raises(HTTPException) as exc_info:
            authorize_webhook(req, b"body")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_socket_mode_decoupled():
    import sys
    from chat_agent.slack.slack_app import build_slack_app, start_slack

    mock_bolt = MagicMock()
    mock_socket_handler = MagicMock()
    mock_socket_handler.AsyncSocketModeHandler.return_value.start_async = AsyncMock()

    with patch.dict(sys.modules, {
        "slack_bolt": mock_bolt,
        "slack_bolt.app": mock_bolt.app,
        "slack_bolt.app.async_app": mock_bolt.app.async_app,
        "slack_bolt.adapter": mock_bolt.adapter,
        "slack_bolt.adapter.socket_mode": mock_bolt.adapter.socket_mode,
        "slack_bolt.adapter.socket_mode.aiohttp": mock_socket_handler,
    }), patch("chat_agent.slack.slack_app.slack_ready", return_value=True):
        app = build_slack_app()
        assert app is not None
        await start_slack()
        mock_socket_handler.AsyncSocketModeHandler.assert_called_once()
        mock_socket_handler.AsyncSocketModeHandler.return_value.start_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_slack_handle_event_deterministic_denial():
    """Verify unauthorized email gets deterministic polite denial without calling run_agent."""
    from chat_agent.slack.slack_app import _handle_event, POLITE_DENIAL_MESSAGE, _USER_PROFILE_CACHE

    _USER_PROFILE_CACHE.clear()
    mock_app = MagicMock()
    mock_app.client = AsyncMock()
    mock_app.client.users_info.return_value = {
        "ok": True,
        "user": {
            "profile": {
                "display_name": "Intruder User",
                "real_name": "Intruder Real",
                "email": "unauthorized@example.com",
            }
        },
    }

    event = {
        "channel": "C_TEST_DENIAL",
        "user": "U_UNAUTH",
        "text": "What is the capital of France?",
        "ts": "12345.67",
    }

    with patch("chat_agent.slack.slack_app.settings") as mock_settings, patch(
        "chat_agent.slack.slack_app.run_agent", new_callable=AsyncMock
    ) as mock_run_agent:
        mock_settings.allowed_emails_list = ["student@school.org"]
        mock_settings.is_email_allowed.return_value = False

        await _handle_event(mock_app, event)

        mock_run_agent.assert_not_called()
        mock_app.client.chat_postMessage.assert_awaited_once_with(
            channel="C_TEST_DENIAL",
            text=POLITE_DENIAL_MESSAGE,
            thread_ts="12345.67",
        )


@pytest.mark.asyncio
async def test_slack_handle_event_allowed_email():
    """Verify authorized email proceeds to run_agent and posts agent output."""
    from chat_agent.slack.slack_app import _handle_event, _USER_PROFILE_CACHE

    _USER_PROFILE_CACHE.clear()
    mock_app = MagicMock()
    mock_app.client = AsyncMock()
    mock_app.client.users_info.return_value = {
        "ok": True,
        "user": {
            "profile": {
                "display_name": "Authorized Student",
                "real_name": "Student Real",
                "email": "student@school.org",
            }
        },
    }

    event = {
        "channel": "C_TEST_ALLOWED",
        "user": "U_AUTH",
        "text": "Explain photosynthesis",
        "ts": "23456.78",
    }

    with patch("chat_agent.slack.slack_app.settings") as mock_settings, patch(
        "chat_agent.slack.slack_app.run_agent", new_callable=AsyncMock
    ) as mock_run_agent, patch(
        "chat_agent.services.turso_memory_service.get_turso_memory_service"
    ) as mock_get_turso:
        mock_settings.allowed_emails_list = ["student@school.org"]
        mock_settings.is_email_allowed.return_value = True
        mock_settings.MULTIMODAL_ENABLED = False
        mock_run_agent.return_value = "Photosynthesis is the process..."

        mock_turso = AsyncMock()
        mock_turso.aget_user_memory_context.return_value = "Memory context"
        mock_turso.aupdate_user_profile = AsyncMock()
        mock_turso.extract_and_reinforce = AsyncMock()
        mock_get_turso.return_value = mock_turso

        await _handle_event(mock_app, event)

        mock_run_agent.assert_awaited_once()
        mock_app.client.chat_postMessage.assert_awaited_once()
        call_kwargs = mock_app.client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "C_TEST_ALLOWED"
        assert "Photosynthesis" in call_kwargs["text"]
