from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse

from chat_agent.communicate.service import process_communicate_event
from chat_agent.config.qstash_authentication import verify_qstash
from chat_agent.config.settings import settings
from chat_agent.webhooks import authorize_webhook

logger = logging.getLogger(__name__)

router = APIRouter(tags=["communicate"])


async def _authenticate_request(request: Request, body: bytes) -> None:
    """Verify incoming request using QStash signature or shared webhook secret (fail-closed)."""
    # 1. QStash signature verification if header is present
    if request.headers.get("Upstash-Signature") or request.headers.get("upstash-signature"):
        await verify_qstash(request)
        return

    shared = getattr(settings, "aryhant_webhook_shared_secret", "")
    qstash_key = getattr(settings, "qstash_current_signing_key", "")

    # 2. Forwarded webhook secret verification
    forwarded = (
        request.headers.get("X-Webhook-Secret")
        or request.headers.get("X-Qstash-Forward-X-Webhook-Secret")
        or request.headers.get("x-webhook-secret")
        or request.headers.get("x-qstash-forward-x-webhook-secret")
    )

    if shared and forwarded:
        authorize_webhook(request, body)
        return

    # 3. Fail closed if neither secret is configured on the server
    if not shared and not qstash_key:
        logger.error(
            "[Communicate] Webhook rejected (503): Neither ARYHANT_WEBHOOK_SHARED_SECRET "
            "nor QSTASH_CURRENT_SIGNING_KEY is configured on the server."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable: Webhook authentication unconfigured.",
        )

    # 4. Credentials exist on server but provided authentication is missing or invalid
    logger.warning("[Communicate] Webhook rejected (401): Credentials missing, mismatched, or invalid.")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Valid QStash or Webhook signature required.",
    )


@router.post("/api/communicate", response_model=None)
async def communicate_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any] | JSONResponse:
    """Receive AgentMail webhook deliveries via QStash or edge proxy and enqueue background response."""
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=status.HTTP_400_BAD_REQUEST)

    # Optional AgentMail / Svix URL challenge
    if payload.get("type") == "url_verification" or payload.get("challenge"):
        return {"challenge": payload.get("challenge", "")}

    await _authenticate_request(request, body)

    background_tasks.add_task(process_communicate_event, payload)
    return {"ok": True, "status": "queued"}
