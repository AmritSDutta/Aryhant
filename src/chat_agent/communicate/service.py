from __future__ import annotations

import logging
import os
import re
from email.utils import parseaddr
from typing import Any

import markdown

from chat_agent.communicate.client import get_agentmail_client
from chat_agent.communicate.config import get_communicate_config
from chat_agent.communicate.intent import is_administrative_query
from chat_agent.communicate.llm import generate_communicate_reply
from chat_agent.config import settings
from chat_agent.services.session_task_service import get_session_task_service

logger = logging.getLogger(__name__)


def extract_email_address(raw_from: str) -> str:
    """Extract clean lowercase email address from raw From header."""
    _, addr = parseaddr(raw_from or "")
    if addr and "@" in addr:
        return addr.strip().lower()
    match = re.search(r"[\w\.-]+@[\w\.-]+", raw_from or "")
    if match:
        return match.group(0).strip().lower()
    return (raw_from or "").strip().lower()


def extract_all_recipient_emails(raw_recipients: Any) -> set[str]:
    """Extract set of clean lowercase email addresses from raw to/cc list or string."""
    recipients: set[str] = set()
    if not raw_recipients:
        return recipients
    if isinstance(raw_recipients, (str, bytes)):
        raw_recipients = [raw_recipients]
    elif not isinstance(raw_recipients, (list, tuple, set)):
        raw_recipients = [raw_recipients]

    for item in raw_recipients:
        if isinstance(item, dict):
            addr = item.get("email") or item.get("address") or ""
        elif hasattr(item, "email"):
            addr = getattr(item, "email", "")
        else:
            addr = str(item)
        clean = extract_email_address(addr)
        if clean:
            recipients.add(clean)
    return recipients


def _get_field(obj: Any, key: str, default: Any = "") -> Any:
    """Read a field safely from a dictionary or an object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


_TEMPLATE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "email_format.html"))


def _load_email_template() -> str:
    """Read dedicated HTML email template from disk with embedded fallback."""
    if os.path.isfile(_TEMPLATE_PATH):
        try:
            with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as exc:
            logger.warning("[Communicate] Could not read %s: %s", _TEMPLATE_PATH, exc)
    return (
        '<div style="margin: 0; padding: 24px 12px; width: 100%; min-height: 100vh; background-color: #f6eee3; background: linear-gradient(135deg, #fdfbf7 0%, #f6eee3 50%, #eee1cf 100%); font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.6; color: #3b2e25;">'
        '<div style="max-width: 640px; margin: 0 auto; border-radius: 12px; overflow: hidden; border: 1px solid #ebdccb;">'
        '<div style="background-color: #5d4a3b; background: linear-gradient(135deg, #493627 0%, #7c4d25 50%, #a76d2e 100%); padding: 26px 20px; text-align: center;">'
        '<h1 style="margin: 0; font-size: 26px; font-weight: 700; color: #ffffff; letter-spacing: 0.5px; text-align: center;">Aryhant</h1>'
        '</div>'
        '<div style="padding: 28px 24px; background-color: #fdfbf7; background: linear-gradient(180deg, #fdfbf7 0%, #f6eee3 100%);">'
        "<CONTENT>"
        "</div></div></div>"
    )


def render_email_html(reply_markdown: str) -> str:
    """Render markdown response into styled HTML using dedicated email_format.html."""
    template = _load_email_template()
    converted = markdown.markdown(reply_markdown, extensions=["tables", "fenced_code"])
    # Format tables with inline borders and colors for universal email client compatibility
    converted = converted.replace(
        "<table>",
        '<table cellpadding="8" cellspacing="0" border="1" style="border-collapse: collapse; width: 100%; border: 1px solid #ebdccb; margin: 16px 0; font-size: 14px;">',
    )
    converted = re.sub(
        r"<th(?:\s+style=\"[^\"]*\")?>",
        '<th style="background-color: #f4ece1; color: #493627; font-weight: 600; padding: 8px 12px; border: 1px solid #ebdccb; text-align: left;">',
        converted,
    )
    converted = re.sub(
        r"<td(?:\s+style=\"[^\"]*\")?>",
        '<td style="padding: 8px 12px; border: 1px solid #ebdccb; color: #3b2e25; text-align: left;">',
        converted,
    )
    return template.replace("<CONTENT>", converted)


async def process_communicate_event(event_payload: dict[str, Any]) -> None:
    """Orchestrate incoming AgentMail event processing for administrative operations."""
    config = get_communicate_config()
    client = get_agentmail_client()

    # The payload may wrap the message directly or under "message" / "data"
    message_data = event_payload.get("message") or event_payload.get("data") or event_payload
    inbox_id = _get_field(message_data, "inbox_id") or config.agentmail_inbox_id
    message_id = _get_field(message_data, "message_id") or _get_field(message_data, "id")
    thread_id = _get_field(message_data, "thread_id")
    raw_from = _get_field(message_data, "from_") or _get_field(message_data, "from") or ""
    subject = _get_field(message_data, "subject") or ""

    sender_email = extract_email_address(raw_from)
    logger.info("[Communicate] Inbound email from '%s' | Subject: '%s'", sender_email, subject)

    # ── 0. Recipient Matching (Target Email Verification) ───────────────────
    target_email = (config.agentmail_inbox_id or getattr(settings, "aryhant_agentmail_emailid", "")).strip().lower()
    if target_email:
        recipients = extract_all_recipient_emails(_get_field(message_data, "to"))
        recipients.update(extract_all_recipient_emails(_get_field(message_data, "cc")))
        inbox_matches = bool(inbox_id and inbox_id.strip().lower() == target_email)
        recipient_matches = target_email in recipients or any(target_email in r for r in recipients)

        if not (inbox_matches or recipient_matches):
            logger.info(
                "[Communicate] Inbound email not addressed to '%s' (inbox='%s', recipients=%s). Skipping.",
                target_email,
                inbox_id,
                recipients,
            )
            return

    # ── 1. Sender Allowlist Gating ──────────────────────────────────────────
    if not settings.is_email_allowed(sender_email):
        logger.warning(
            "[Communicate Security] Sender '%s' is NOT in ARYHANT_ALLOWED_EMAILS. Silently dropping.",
            sender_email,
        )
        if client and inbox_id and message_id:
            try:
                await client.inboxes.messages.update(
                    inbox_id=inbox_id,
                    message_id=message_id,
                    add_labels=["unauthorized_sender"],
                    remove_labels=["unreplied"],
                )
            except Exception as e:
                logger.warning("[Communicate] Could not update labels for unauthorized email: %s", e)
        return

    # ── 2. Content Extraction (AgentMail Skill Rules: extracted wins over raw) ─
    email_body = (
        _get_field(message_data, "extracted_text")
        or _get_field(message_data, "extracted_html")
        or _get_field(message_data, "text")
        or _get_field(message_data, "html")
        or ""
    )

    # ── 3. Administrative Scope Filtering ────────────────────────────────────
    if not is_administrative_query(subject, email_body):
        logger.info(
            "[Communicate Scope] Email from '%s' is not an administrative query. Ignoring without reply.",
            sender_email,
        )
        if client and inbox_id and message_id:
            try:
                await client.inboxes.messages.update(
                    inbox_id=inbox_id,
                    message_id=message_id,
                    add_labels=["ignored_non_admin"],
                )
            except Exception as e:
                logger.warning("[Communicate] Could not label ignored non-admin email: %s", e)
        return

    # ── 4. Thread Depth Guardrail ─────────────────────────────────────────────
    if client and inbox_id and thread_id:
        try:
            thread = await client.inboxes.threads.get(inbox_id=inbox_id, thread_id=thread_id)
            messages = _get_field(thread, "messages", []) or []
            if len(messages) > config.max_thread_depth:
                logger.warning(
                    "[Communicate] Thread depth (%d) exceeds max (%d). Halting.",
                    len(messages),
                    config.max_thread_depth,
                )
                await client.inboxes.messages.update(
                    inbox_id=inbox_id,
                    message_id=message_id,
                    add_labels=["depth_limit_reached"],
                )
                return
        except Exception as e:
            logger.info("[Communicate] Could not inspect thread depth: %s. Continuing.", e)

    # ── 5. Gather Administrative Telemetry & Retention Pruning ───────────────
    task_service = get_session_task_service()
    deleted_count = 0
    try:
        deleted_count = await task_service.adelete_records_older_than(days=15)
    except Exception as e:
        logger.warning("[Communicate] Retention pruning failed: %s", e)

    metrics_7d = {}
    failed_tasks = []
    try:
        metrics_7d = await task_service.aget_table_metrics(days=7)
        failed_tasks = await task_service.aget_failed_tasks(limit=5, days=7)
    except Exception as e:
        logger.warning("[Communicate] Reading metrics failed: %s", e)

    sanitized_failures = [
        {
            "task_type": ft.get("task_type"),
            "provider": ft.get("provider"),
            "model_name": ft.get("model_name"),
            "error_summary": str(ft.get("error_message") or "")[:200],
            "duration_ms": ft.get("duration_ms"),
        }
        for ft in failed_tasks
    ]

    telemetry_payload = {
        "telemetry_window_days": 7,
        "retention_prune_days": 15,
        "deleted_records_count": deleted_count,
        "current_active_tasks": metrics_7d.get("total_tasks", 0),
        "status_breakdown": metrics_7d.get("status_breakdown", {}),
        "task_type_breakdown": metrics_7d.get("task_type_breakdown", {}),
        "token_economics": {
            "prompt_tokens": metrics_7d.get("prompt_tokens_sum", 0),
            "completion_tokens": metrics_7d.get("completion_tokens_sum", 0),
            "total_tokens": metrics_7d.get("total_tokens_sum", 0),
        },
        "avg_duration_ms": metrics_7d.get("avg_duration_ms", 0.0),
        "failure_count": metrics_7d.get("failure_count", 0),
        "recent_failures": sanitized_failures,
    }

    # ── 6. Generate Reply via LLM (Primary -> Fallback) ──────────────────────
    reply_text = await generate_communicate_reply(subject, email_body, telemetry_payload)

    # ── 7. Respect NO_REPLY ──────────────────────────────────────────────────
    if reply_text.strip().upper() == "NO_REPLY":
        logger.info("[Communicate] LLM returned NO_REPLY. Skipping dispatch.")
        if client and inbox_id and message_id:
            try:
                await client.inboxes.messages.update(
                    inbox_id=inbox_id,
                    message_id=message_id,
                    add_labels=["llm_no_reply"],
                )
            except Exception as e:
                logger.warning("[Communicate] Failed to add llm_no_reply label: %s", e)
        return

    # ── 8. Dispatch Reply via AgentMail ───────────────────────────────────────
    if not (client and inbox_id and message_id):
        logger.warning("[Communicate] Missing client or IDs (inbox: %s, msg: %s). Cannot send reply.",
                       inbox_id, message_id)
        return

    html_body = render_email_html(reply_text)

    reply_kwargs: dict[str, Any] = {
        "inbox_id": inbox_id,
        "message_id": message_id,
        "text": reply_text,
        "html": html_body,
    }
    if config.agentmail_bcc_email:
        reply_kwargs["bcc"] = [config.agentmail_bcc_email]

    logger.info("[Communicate] Sending reply to %s (inbox: %s, msg: %s)", sender_email, inbox_id, message_id)
    await client.inboxes.messages.reply(**reply_kwargs)

    await client.inboxes.messages.update(
        inbox_id=inbox_id,
        message_id=message_id,
        add_labels=["replied"],
        remove_labels=["unreplied"],
    )
    logger.info("[Communicate] Successfully replied and updated labels.")
