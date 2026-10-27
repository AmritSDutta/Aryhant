from __future__ import annotations

import hmac
import logging

from fastapi import HTTPException, Request

from chat_agent.config import settings
from chat_agent.slack.slack_http import verify_slack_signature

logger = logging.getLogger(__name__)


def _header(request: Request, name: str) -> str:
    return request.headers.get(name) or request.headers.get(name.lower()) or ""


def authorize_webhook(request: Request, body: bytes) -> None:
    shared = settings.webhook_shared_secret
    provided = _header(request, "X-Webhook-Secret") or _header(request, "X-Qstash-Forward-X-Webhook-Secret")
    if shared and provided and hmac.compare_digest(shared, provided):
        logger.info("Webhook authorization successful (shared secret matched).")
        return
    slack_secret = settings.slack_signing_secret
    if slack_secret and verify_slack_signature(
        body,
        _header(request, "X-Slack-Request-Timestamp"),
        _header(request, "X-Slack-Signature"),
        slack_secret,
    ):
        logger.info("Webhook authorization successful (Slack signature verified).")
        return

    if not shared and not slack_secret:
        logger.error("Webhook rejected (503): Neither WEBHOOK_SHARED_SECRET nor SLACK_SIGNING_SECRET is configured on the server.")
        raise HTTPException(status_code=503, detail="Service unavailable.")

    logger.warning("Webhook rejected (401): Credentials mismatched or invalid.")
    raise HTTPException(status_code=401, detail="Unauthorized.")
