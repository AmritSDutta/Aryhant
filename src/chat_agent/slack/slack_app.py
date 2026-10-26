from __future__ import annotations

import asyncio
import logging
from typing import Any

from chat_agent.agents.runner import clip_text, run_agent
from chat_agent.config import settings, slack_ready

logger = logging.getLogger(__name__)


def build_slack_app() -> Any:
    try:
        from slack_bolt.app.async_app import AsyncApp
    except ImportError as err:
        raise ImportError(
            "slack_bolt is not installed. Install with `pip install slack-bolt`."
        ) from err
    app = AsyncApp(token=settings.aryhant_slack_bot_token)
    _register_handlers(app)
    return app


def _register_handlers(app: Any) -> None:
    @app.event("app_mention")
    async def on_app_mention(event: dict[str, Any]) -> None:
        logger.info("Received app_mention event: %s", event)
        await _handle_event(app, event)

    @app.event("message")
    async def on_message(event: dict[str, Any]) -> None:
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return
        # Always handle 1-on-1 Direct Messages (DMs)
        if event.get("channel_type") in {"im", "mpim"}:
            logger.info("Received direct message (DM) event: %s", event)
            await _handle_event(app, event)
            return
        # In channels, only reply if not restricted to mentions
        if not settings.REPLY_ONLY_TO_MENTIONS:
            logger.info("Received channel message event: %s", event)
            await _handle_event(app, event)


async def _handle_event(app: Any, event: dict[str, Any]) -> None:
    """Run the direct LLM engine for a Slack event and post a threaded reply."""
    channel = event.get("channel") or ""
    text = (event.get("text") or "").strip()
    if not channel or not text:
        return
    logger.info("Processing Slack event for user=%s in channel=%s: %r", event.get("user"), channel, text)

    user = event.get("user") or "slack-user"
    thread_ts = event.get("thread_ts") or ""
    msg_ts = event.get("ts") or ""
    prompt = f"[channel=slack channel_id={channel} thread_ts={thread_ts or msg_ts}]\n{clip_text(text)}"

    attachments: list[tuple[bytes, str]] = []
    if settings.MULTIMODAL_ENABLED:
        try:
            from chat_agent.utils.multimodal import extract_and_download_slack_attachments

            attachments = await extract_and_download_slack_attachments(event)
        except Exception as err:
            logger.warning("Failed to download Slack attachments: %s", err)

    session_id = f"slack:{channel}:{thread_ts}" if thread_ts else f"slack:{channel}:{msg_ts}"
    try:
        reply = await run_agent(
            user_id=f"slack:{user}",
            session_id=session_id,
            message=prompt,
            attachments=attachments,
        )
    except Exception as err:
        logger.error("Agent failed for Slack event %s: %s", msg_ts, err)
        reply = "Sorry, I could not process that message."

    from chat_agent.slack.post_generator import generate_slack_post

    post_data = generate_slack_post(reply)
    await app.client.chat_postMessage(
        channel=channel,
        text=post_data["text"],
        thread_ts=thread_ts or msg_ts,
        blocks=post_data.get("blocks"),
    )


async def start_slack() -> None:
    if not slack_ready():
        logger.warning("Slack tokens missing; Slack channel is disabled.")
        return
    try:
        from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
    except ImportError as err:
        raise ImportError(
            "slack_bolt socket mode adapter is not installed. Install with `pip install slack-bolt aiohttp`."
        ) from err
    slack_app = build_slack_app()
    logger.info("Starting Slack Socket Mode listener.")
    handler = AsyncSocketModeHandler(slack_app, settings.aryhant_slack_app_token)
    await handler.start_async()


def run_slack_blocking() -> None:
    if not slack_ready():
        raise RuntimeError("Set ARYHANT_SLACK_BOT_TOKEN and ARYHANT_SLACK_APP_TOKEN before starting Slack.")
    asyncio.run(start_slack())
