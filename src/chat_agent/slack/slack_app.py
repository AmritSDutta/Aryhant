from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from chat_agent.agents.runner import clip_text, run_agent
from chat_agent.config import settings, slack_ready

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
from chat_agent.slack.slack_auth import (
    POLITE_DENIAL_MESSAGE,
    _USER_PROFILE_CACHE,
    check_slack_authorization,
    resolve_user_profile_info,
)

_resolve_user_profile_info = resolve_user_profile_info
_SYNCED_USER_PROFILES: set[tuple[str, str, str, str]] = set()


async def _resolve_user_names(client: Any, user_id: str) -> tuple[str, str]:
    """Resolve display and real name for a Slack user with memory caching."""
    d_name, r_name, _ = await _resolve_user_profile_info(client, user_id)
    return (d_name, r_name)


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
    @app.command("/preferences")
    async def on_preferences_command(ack: Any, body: dict[str, Any], client: Any) -> None:
        user_id = body.get("user_id") or "slack-user"
        _, _, email = await _resolve_user_profile_info(client, user_id)
        if not settings.is_email_allowed(email):
            logger.warning("Access denied for command /preferences from user %s (email: %r)", user_id, email)
            await ack(POLITE_DENIAL_MESSAGE)
            return
        await ack()
        trigger_id = body.get("trigger_id")
        if trigger_id:
            from chat_agent.services.turso_memory_service import get_turso_memory_service
            from chat_agent.slack.preferences_modal import build_preferences_modal

            turso_service = get_turso_memory_service()
            memories = await turso_service.alist_user_memories(f"slack:{user_id}")
            view = build_preferences_modal(memories)
            await client.views_open(trigger_id=trigger_id, view=view)

    async def _dispatch_slash_research_command(
        ack: Any,
        body: dict[str, Any],
        client: Any,
        command: str,
    ) -> None:
        user_id = body.get("user_id") or "slack-user"
        user_id_key = f"slack:{user_id}"
        is_allowed, _, _, email = await check_slack_authorization(client, user_id, notify_on_deny=False)
        if not is_allowed:
            logger.warning("Access denied for command %s from user %s (email: %r)", command, user_id, email)
            await ack(POLITE_DENIAL_MESSAGE)
            return
        await ack()
        topic = (body.get("text") or "").strip()
        channel_id = body.get("channel_id") or ""
        if not topic:
            example = "Linux io_uring" if command == "/research" else "Best term life insurance"
            await client.chat_postMessage(channel=channel_id, text=f"Please specify a topic or query, e.g. `{command} {example}`.")
            return

        from chat_agent.research.dispatcher import (
            RESEARCH_CONCURRENCY_SEMAPHORE,
            acquire_user_job_slot,
            new_job_id,
        )
        if not await acquire_user_job_slot(user_id_key):
            await client.chat_postMessage(
                channel=channel_id,
                text="⚠️ You currently have a research or deliberation job in progress. Please wait for it to complete.",
            )
            return

        job_id = new_job_id(command)
        from chat_agent.research import get_research_agent
        agent = get_research_agent()

        async def _run_command_job() -> None:
            async with RESEARCH_CONCURRENCY_SEMAPHORE:
                await agent.execute_job(
                    job_id=job_id,
                    command=command,
                    topic=topic,
                    channel_id=channel_id,
                    thread_ts="",
                    user_id=user_id_key,
                    attachments=[],
                    client=client,
                )

        task = asyncio.create_task(_run_command_job())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    async def _dispatch_slash_admin_command(
        ack: Any,
        body: dict[str, Any],
        client: Any,
        command: str,
    ) -> None:
        user_id = body.get("user_id") or "slack-user"
        user_id_key = f"slack:{user_id}"
        is_allowed, _, _, email = await check_slack_authorization(client, user_id, notify_on_deny=False)
        if not is_allowed:
            logger.warning("Access denied for command %s from user %s (email: %r)", command, user_id, email)
            await ack(POLITE_DENIAL_MESSAGE)
            return
        await ack("⏳ *Running administrative audit & data retention maintenance...*")
        channel_id = body.get("channel_id") or ""

        from chat_agent.agents.admin_agent import get_admin_agent
        from chat_agent.slack.post_generator import generate_slack_post
        from chat_agent.utils.text_formatter import format_human_readable_text

        async def _run_slash_admin_job() -> None:
            try:
                report_data = await get_admin_agent().run_maintenance(days=7, prune_days=15, user_id=user_id_key)
                raw_report = report_data.get("report", "✅ Administrative maintenance completed successfully.")
                humanized = format_human_readable_text(raw_report)
                post_data = generate_slack_post(humanized)
                await client.chat_postMessage(
                    channel=channel_id,
                    text=post_data["text"],
                    blocks=post_data.get("blocks"),
                )
            except Exception as e_adm:
                logger.error("Slack slash admin background job failed: %s", e_adm, exc_info=True)
                await client.chat_postMessage(
                    channel=channel_id,
                    text=f"⚠️ Administrative maintenance failed: {e_adm}",
                )

        adm_task = asyncio.create_task(_run_slash_admin_job())
        _BACKGROUND_TASKS.add(adm_task)
        adm_task.add_done_callback(_BACKGROUND_TASKS.discard)

    @app.command("/research")
    async def on_research_command(ack: Any, body: dict[str, Any], client: Any) -> None:
        await _dispatch_slash_research_command(ack, body, client, "/research")

    @app.command("/deliberate")
    async def on_deliberate_command(ack: Any, body: dict[str, Any], client: Any) -> None:
        await _dispatch_slash_research_command(ack, body, client, "/deliberate")

    @app.command("/admin")
    async def on_admin_command(ack: Any, body: dict[str, Any], client: Any) -> None:
        await _dispatch_slash_admin_command(ack, body, client, "/admin")

    @app.command("/audit")
    async def on_audit_command(ack: Any, body: dict[str, Any], client: Any) -> None:
        await _dispatch_slash_admin_command(ack, body, client, "/audit")

    @app.action("delete_memory_action")
    async def on_delete_memory(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        user_id = body.get("user", {}).get("id") or "slack-user"
        actions = body.get("actions", [])
        memory_id = actions[0].get("value") if actions else None
        view_id = body.get("view", {}).get("id")

        if memory_id and view_id:
            from chat_agent.services.turso_memory_service import get_turso_memory_service
            from chat_agent.slack.preferences_modal import build_preferences_modal

            turso_service = get_turso_memory_service()
            await turso_service.adelete_memory(f"slack:{user_id}", memory_id)
            updated = await turso_service.alist_user_memories(f"slack:{user_id}")
            new_view = build_preferences_modal(updated)
            await client.views_update(view_id=view_id, view=new_view)

    @app.action("clear_memories_action")
    async def on_clear_memories(ack: Any, body: dict[str, Any], client: Any) -> None:
        await ack()
        user_id = body.get("user", {}).get("id") or "slack-user"
        view_id = body.get("view", {}).get("id")

        if view_id:
            from chat_agent.services.turso_memory_service import get_turso_memory_service
            from chat_agent.slack.preferences_modal import build_preferences_modal

            turso_service = get_turso_memory_service()
            await turso_service.aclear_user_memories(f"slack:{user_id}")
            new_view = build_preferences_modal([])
            await client.views_update(view_id=view_id, view=new_view)

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
    from chat_agent.services.turso_memory_service import get_turso_memory_service

    user_id_key = f"slack:{user}"
    turso_svc = get_turso_memory_service()
    d_name, r_name, email = await _resolve_user_profile_info(app.client, user)
    logger.info("Resolved caller for %s: display=%r, email=%r (allowed=%s)", user_id_key, d_name, email, settings.is_email_allowed(email))
    if not settings.is_email_allowed(email):
        logger.warning(
            "Access denied for Slack user %s (email: %r). Not in ARYHANT_ALLOWED_EMAILS.",
            user,
            email,
        )
        await app.client.chat_postMessage(
            channel=channel,
            text=POLITE_DENIAL_MESSAGE,
            thread_ts=thread_ts or msg_ts,
        )
        return

    user_sig = (user_id_key, d_name, r_name, email)
    if user_sig not in _SYNCED_USER_PROFILES:
        async def _sync_profile_task() -> None:
            try:
                await turso_svc.aupdate_user_profile(user_id_key, display_name=d_name, real_name=r_name, email=email)
                _SYNCED_USER_PROFILES.add(user_sig)
                logger.info("User profile synced and registered in _SYNCED_USER_PROFILES: %s", user_sig)
            except Exception as e:
                logger.warning("Failed to sync user profile %s: %s", user_sig, e)

        profile_task = asyncio.create_task(_sync_profile_task())
        _BACKGROUND_TASKS.add(profile_task)
        profile_task.add_done_callback(_BACKGROUND_TASKS.discard)

    try:
        memory_context = await turso_svc.aget_user_memory_context(user_id_key)
    except Exception as exc:
        logger.warning("Failed to fetch memory context in Slack app handler for %s: %s", user_id_key, exc)
        memory_context = "No specific stored preferences yet; use standard ICSE Grade 5 balanced explanations."
    prompt = f"[channel=slack channel_id={channel} thread_ts={thread_ts or msg_ts} user_id={user_id_key}]\n{clip_text(text)}"

    attachments: list[tuple[bytes, str]] = []
    if settings.MULTIMODAL_ENABLED:
        try:
            from chat_agent.utils.multimodal import extract_and_download_slack_attachments

            attachments = await extract_and_download_slack_attachments(event)
        except Exception as err:
            logger.warning("Failed to download Slack attachments: %s", err)

    session_id = f"slack:{channel}:{thread_ts}" if thread_ts else f"slack:{channel}:{msg_ts}"

    from chat_agent.research.dispatcher import (
        RESEARCH_CONCURRENCY_SEMAPHORE,
        acquire_user_job_slot,
        new_job_id,
        parse_research_trigger,
    )
    if text.strip().startswith(("/admin", "/audit")):
        from chat_agent.agents.admin_agent import get_admin_agent

        ack_msg = await app.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts or msg_ts,
            text="⏳ *Running administrative audit & data retention maintenance...*",
        )
        target_thread = thread_ts or msg_ts

        from chat_agent.slack.post_generator import generate_slack_post
        from chat_agent.utils.text_formatter import format_human_readable_text

        async def _run_slack_admin() -> None:
            try:
                report_data = await get_admin_agent().run_maintenance(days=7, prune_days=15, user_id=user_id_key)
                raw_report = report_data.get("report", "✅ Administrative maintenance completed successfully.")
                humanized = format_human_readable_text(raw_report)
                post_data = generate_slack_post(humanized)
                await app.client.chat_postMessage(
                    channel=channel,
                    thread_ts=target_thread,
                    text=post_data["text"],
                    blocks=post_data.get("blocks"),
                )
            except Exception as e_adm:
                logger.error("Slack admin maintenance background job failed: %s", e_adm, exc_info=True)
                await app.client.chat_postMessage(
                    channel=channel,
                    thread_ts=target_thread,
                    text=f"⚠️ Administrative maintenance failed: {e_adm}",
                )

        adm_task = asyncio.create_task(_run_slack_admin())
        _BACKGROUND_TASKS.add(adm_task)
        adm_task.add_done_callback(_BACKGROUND_TASKS.discard)
        return

    trigger = parse_research_trigger(text)
    if trigger:
        cmd, req_topic = trigger
        if not await acquire_user_job_slot(user_id_key):
            await app.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts or msg_ts,
                text="⚠️ You currently have a research or deliberation job in progress. Please wait for it to complete.",
            )
            return
        job_id = new_job_id(cmd)
        from chat_agent.research import get_research_agent

        async def _run_event_job() -> None:
            async with RESEARCH_CONCURRENCY_SEMAPHORE:
                await get_research_agent().execute_job(
                    job_id=job_id,
                    command=cmd,
                    topic=req_topic,
                    channel_id=channel,
                    thread_ts=thread_ts or msg_ts,
                    user_id=user_id_key,
                    attachments=attachments,
                    client=app.client,
                )

        res_task = asyncio.create_task(_run_event_job())
        _BACKGROUND_TASKS.add(res_task)
        res_task.add_done_callback(_BACKGROUND_TASKS.discard)
        return
    try:
        reply = await run_agent(
            user_id=f"slack:{user}",
            session_id=session_id,
            message=prompt,
            attachments=attachments,
            user_memory_context=memory_context,
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
    bg_task = asyncio.create_task(
        turso_svc.extract_and_reinforce(
            user_id=user_id_key,
            user_text=text,
            assistant_reply=reply,
            display_name=d_name,
            real_name=r_name,
        )
    )
    _BACKGROUND_TASKS.add(bg_task)
    bg_task.add_done_callback(_BACKGROUND_TASKS.discard)


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
