from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import random
import re
import time
from typing import Any

import httpx

from chat_agent.agents.runner import clip_text, run_agent
from chat_agent.config import settings
from chat_agent.slack.post_generator import generate_slack_post

logger = logging.getLogger(__name__)
_MENTION = re.compile(r"<@[^>]+>\s*")
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


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
    token = settings.aryhant_slack_bot_token
    payload: dict[str, Any] = {"channel": channel}
    if text:
        payload["text"] = text
    if blocks:
        payload["blocks"] = blocks
    if not payload.get("text") and blocks:
        payload["text"] = "Aryhant Update"
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


class SlackHTTPClientAdapter:
    """HTTP client adapter providing chat_postMessage and chat_update for research workflows."""

    async def chat_postMessage(
        self,
        channel: str,
        text: str = "",
        thread_ts: str = "",
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await post_slack_message(channel=channel, text=text, thread_ts=thread_ts, blocks=blocks)

    async def chat_update(
        self,
        channel: str,
        ts: str,
        text: str = "",
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        token = settings.aryhant_slack_bot_token
        payload: dict[str, Any] = {"channel": channel, "ts": ts}
        if text:
            payload["text"] = text
        if blocks:
            payload["blocks"] = blocks
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://slack.com/api/chat.update",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                return resp.json()
        except Exception as exc:
            logger.warning("SlackHTTPClientAdapter.chat_update failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    async def users_info(self, user: str) -> dict[str, Any]:
        token = settings.aryhant_slack_bot_token
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://slack.com/api/users.info",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"user": user},
                )
                return resp.json()
        except Exception as exc:
            logger.warning("SlackHTTPClientAdapter.users_info failed for %s: %s", user, exc)
            return {"ok": False, "error": str(exc)}


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

        client_adapter = SlackHTTPClientAdapter()

        from chat_agent.services.turso_memory_service import get_turso_memory_service

        user_id_key = f"slack:{user}"
        turso_svc = get_turso_memory_service()
        try:
            memory_context = await turso_svc.aget_user_memory_context(user_id_key)
        except Exception as exc:
            logger.warning("Failed to fetch memory context in Slack HTTP handler for %s: %s", user_id_key, exc)
            memory_context = "No specific stored preferences yet; use standard ICSE Grade 5 balanced explanations."
        prompt = f"[channel=slack channel_id={channel} thread_ts={thread_ts or msg_ts} user_id={user_id_key}]\n{event_text(event)}"

        attachments: list[tuple[bytes, str]] = []
        if settings.MULTIMODAL_ENABLED:
            from chat_agent.utils.multimodal import extract_and_download_slack_attachments

            attachments = await extract_and_download_slack_attachments(event)

        session_id = f"slack:{channel}:{thread_ts}" if thread_ts else f"slack:{channel}:{msg_ts}"

        raw_text = event_text(event).strip()
        from chat_agent.research.dispatcher import (
            RESEARCH_CONCURRENCY_SEMAPHORE,
            acquire_user_job_slot,
            new_job_id,
            parse_research_trigger,
        )
        if raw_text.startswith(("/admin", "/audit")):
            from chat_agent.slack.slack_auth import check_slack_authorization
            is_allowed, _, _, email = await check_slack_authorization(
                client=client_adapter,
                user_id=user,
                channel=channel,
                thread_ts=thread_ts or msg_ts,
                notify_on_deny=True,
            )
            if not is_allowed:
                logger.warning("Access denied in Slack HTTP handler for admin user %s (email: %r)", user, email)
                return {"ok": False, "error": "unauthorized"}

            from chat_agent.agents.admin_agent import get_admin_agent

            ack_msg = await post_slack_message(
                channel=channel,
                thread_ts=thread_ts or msg_ts,
                text="⏳ *Running administrative audit & data retention maintenance...*",
            )
            target_thread = thread_ts or msg_ts

            async def _run_http_admin() -> None:
                try:
                    report_data = await get_admin_agent().run_maintenance(days=7, prune_days=15, user_id=user_id_key)
                    await post_slack_message(
                        channel=channel,
                        thread_ts=target_thread,
                        text=report_data.get("report", "Administrative maintenance finished."),
                    )
                except Exception as e_adm:
                    logger.error("Slack HTTP admin maintenance failed: %s", e_adm, exc_info=True)
                    await post_slack_message(
                        channel=channel,
                        thread_ts=target_thread,
                        text=f"⚠️ Administrative maintenance failed: {e_adm}",
                    )

            adm_task = asyncio.create_task(_run_http_admin())
            _BACKGROUND_TASKS.add(adm_task)
            adm_task.add_done_callback(_BACKGROUND_TASKS.discard)
            return {"ok": True}

        trigger = parse_research_trigger(raw_text)
        if trigger:
            cmd, req_topic = trigger

            from chat_agent.slack.slack_auth import check_slack_authorization
            is_allowed, _, _, email = await check_slack_authorization(
                client=client_adapter,
                user_id=user,
                channel=channel,
                thread_ts=thread_ts or msg_ts,
                notify_on_deny=True,
            )
            if not is_allowed:
                logger.warning("Access denied in Slack HTTP handler for research/deliberate user %s (email: %r)", user, email)
                return {"ok": False, "error": "unauthorized"}

            if not await acquire_user_job_slot(user_id_key):
                await post_slack_message(
                    channel=channel,
                    thread_ts=thread_ts or msg_ts,
                    text="⚠️ You currently have a research or deliberation job in progress. Please wait for it to complete.",
                )
                return {"ok": False, "error": "job_in_progress"}

            job_id = new_job_id(cmd)
            from chat_agent.research import get_research_agent

            async def _run_http_research_job() -> None:
                async with RESEARCH_CONCURRENCY_SEMAPHORE:
                    await get_research_agent().execute_job(
                        job_id=job_id,
                        command=cmd,
                        topic=req_topic,
                        channel_id=channel,
                        thread_ts=thread_ts or msg_ts,
                        user_id=user_id_key,
                        attachments=attachments,
                        client=client_adapter,
                    )

            bg_job = asyncio.create_task(_run_http_research_job())
            _BACKGROUND_TASKS.add(bg_job)
            bg_job.add_done_callback(_BACKGROUND_TASKS.discard)
            return {"ok": True, "job_id": job_id}

        reply = await run_agent(
            user_id=user_id_key,
            session_id=session_id,
            message=prompt,
            attachments=attachments,
            user_memory_context=memory_context,
        )
        post_data = generate_slack_post(reply)
        await post_slack_message(
            channel=channel,
            text=post_data["text"],
            thread_ts=thread_ts or msg_ts,
            blocks=post_data["blocks"],
        )
        bg_task = asyncio.create_task(
            turso_svc.extract_and_reinforce(
                user_id=user_id_key,
                user_text=event_text(event),
                assistant_reply=reply,
            )
        )
        _BACKGROUND_TASKS.add(bg_task)
        bg_task.add_done_callback(_BACKGROUND_TASKS.discard)

        return {"ok": True, "channel": channel}
    except Exception as err:
        remove_dedup_event(event_id)
        logger.error("Failed to handle Slack payload for event %s: %s", event_id, err)
        raise
