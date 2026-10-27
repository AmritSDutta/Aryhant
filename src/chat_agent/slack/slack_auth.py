from __future__ import annotations

import logging
from typing import Any

from chat_agent.config import settings

logger = logging.getLogger(__name__)

POLITE_DENIAL_MESSAGE: str = (
    "Hello! Access to this assistant is restricted to authorized users. "
    "Your email address is not on the permitted list. "
    "Please contact your workspace administrator if you need access."
)

_USER_PROFILE_CACHE: dict[str, tuple[str, str, str]] = {}


async def resolve_user_profile_info(client: Any, user_id: str) -> tuple[str, str, str]:
    """Resolve display name, real name, and email for a Slack user with memory caching."""
    if not user_id or user_id == "slack-user":
        return ("Aryhant Student", "Student", "")
    if user_id in _USER_PROFILE_CACHE:
        return _USER_PROFILE_CACHE[user_id]
    try:
        resp = await client.users_info(user=user_id)
        if resp.get("ok"):
            u = resp.get("user") or {}
            prof = u.get("profile") or {}
            real = prof.get("real_name") or u.get("real_name") or "Student"
            display = prof.get("display_name") or u.get("name") or real
            email = (prof.get("email") or "").strip().lower()
            info = (display, real, email)
            _USER_PROFILE_CACHE[user_id] = info
            logger.info("Resolved Slack user %s profile: display=%r, real=%r, email=%r", user_id, display, real, email)
            return info
    except Exception as exc:
        logger.debug("Slack users_info lookup notice for %s: %s", user_id, exc)
    return ("Aryhant Student", "Student", "")


async def check_slack_authorization(
    client: Any,
    user_id: str,
    channel: str = "",
    thread_ts: str = "",
    notify_on_deny: bool = True,
) -> tuple[bool, str, str, str]:
    """Resolve caller profile, verify email allowlist, and return authorization tuple."""
    display_name, real_name, email = await resolve_user_profile_info(client, user_id)
    is_allowed = settings.is_email_allowed(email)
    if not is_allowed:
        logger.warning(
            "Access denied for Slack user %s (email: %r). Not in ARYHANT_ALLOWED_EMAILS.",
            user_id,
            email,
        )
        if notify_on_deny and channel and hasattr(client, "chat_postMessage"):
            try:
                await client.chat_postMessage(
                    channel=channel,
                    text=POLITE_DENIAL_MESSAGE,
                    thread_ts=thread_ts,
                )
            except Exception as e:
                logger.warning("Failed to post denial message to Slack: %s", e)
    return is_allowed, display_name, real_name, email
