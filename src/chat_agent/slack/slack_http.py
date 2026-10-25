from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from typing import Any

import httpx
from chat_agent.agents.runner import clip_text, run_agent
from chat_agent.config import settings
from chat_agent.slack.post_generator import generate_slack_post

logger = logging.getLogger(__name__)
_MENTION = re.compile(r"<@[^>]+>\s*")


def verify_slack_signature(body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    digest = hmac.new(
        secret.encode("utf-8"),
        f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def should_handle_event(event: dict[str, Any]) -> bool:
    if not event or event.get("bot_id") or event.get("subtype") == "bot_message":
        return False
    etype = event.get("type")
    if etype == "app_mention":
        return True
    if etype == "message" and event.get("channel_type") in {"im", "mpim"}:
        return True
    return False


def event_text(event: dict[str, Any]) -> str:
    return clip_text(_MENTION.sub("", event.get("text") or "").strip())


async def post_slack_message(
    channel: str,
    text: str = "",
    thread_ts: str = "",
    blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not text and not blocks:
        raise ValueError("Either text or blocks must be provided to post_slack_message.")
    token = settings.slack_bot_token
    payload: dict[str, Any] = {"channel": channel}
    if text:
        payload["text"] = text
    if blocks:
        payload["blocks"] = blocks
    if not payload.get("text") and blocks:
        payload["text"] = "Slack Bot Update"
    if thread_ts:
        payload["thread_ts"] = thread_ts
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        data: dict[str, Any] = response.json()
        if not data.get("ok"):
            logger.error("Slack post failed: %s", data)
        return data


_PROCESSED_EVENTS: dict[str, float] = {}
_DEDUP_TTL_SECONDS = 600.0


def is_duplicate_event(event_id: str) -> bool:
    """Check and record event ID to prevent duplicate processing within TTL."""
    if not event_id:
        return False
    now = time.time()
    if len(_PROCESSED_EVENTS) > 1000:
        expired = [k for k, t in _PROCESSED_EVENTS.items() if now - t > _DEDUP_TTL_SECONDS]
        for k in expired:
            _PROCESSED_EVENTS.pop(k, None)
    if event_id in _PROCESSED_EVENTS:
        if now - _PROCESSED_EVENTS[event_id] < _DEDUP_TTL_SECONDS:
            return True
    _PROCESSED_EVENTS[event_id] = now
    return False


def remove_dedup_event(event_id: str) -> None:
    """Evict event ID from dedup cache if processing failed."""
    _PROCESSED_EVENTS.pop(event_id, None)


async def handle_slack_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}
    event = payload.get("event") or {}
    if not should_handle_event(event):
        return {"ignored": True}
    channel = event.get("channel")
    if not channel:
        return {"ignored": True}

    event_id = payload.get("event_id") or event.get("client_msg_id") or f"{channel}:{event.get('ts')}"
    if is_duplicate_event(event_id):
        logger.info("Ignoring duplicate Slack event: %s", event_id)
        return {"ignored": True, "duplicate": True}

    try:
        user = event.get("user") or "slack-user"
        thread_ts = event.get("thread_ts") or ""
        msg_ts = event.get("ts") or str(time.time())
        prompt = f"[channel=slack channel_id={channel} thread_ts={thread_ts or msg_ts}]\n{event_text(event)}"

        attachments: list[tuple[bytes, str]] = []
        if settings.MULTIMODAL_ENABLED:
            from chat_agent.utils.multimodal import extract_and_download_slack_attachments

            attachments = await extract_and_download_slack_attachments(event)

        session_id = f"slack:{channel}:{thread_ts}" if thread_ts else f"slack:{channel}:{msg_ts}"
        reply = await run_agent(
            user_id=f"slack:{user}",
            session_id=session_id,
            message=prompt,
            attachments=attachments,
        )
        post_data = generate_slack_post(reply)
        await post_slack_message(
            channel=channel,
            text=post_data["text"],
            thread_ts=thread_ts or msg_ts,
            blocks=post_data["blocks"],
        )
        return {"ok": True, "channel": channel}
    except Exception as err:
        remove_dedup_event(event_id)
        logger.error("Failed to handle Slack payload for event %s: %s", event_id, err)
        raise
