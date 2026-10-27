from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from qstash import Receiver

from chat_agent.config.settings import settings

logger = logging.getLogger(__name__)

_receiver: Receiver | None = None


def get_receiver() -> Receiver:
    """Retrieve or initialize QStash Receiver using configured keys."""
    global _receiver
    if _receiver is None:
        _receiver = Receiver(
            current_signing_key=settings.qstash_current_signing_key,
            next_signing_key=settings.qstash_next_signing_key,
        )
    return _receiver


async def verify_qstash(request: Request) -> None:
    """FastAPI dependency to verify incoming Upstash-Signature against request body."""
    signature = request.headers.get("Upstash-Signature")
    if not signature:
        logger.warning("Upstash signature header is missing")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing signature",
        )

    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    receiver = get_receiver()
    try:
        receiver.verify(
            body=body_str,
            signature=signature,
        )
    except Exception as e:
        logger.warning("Upstash signature verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        ) from e
