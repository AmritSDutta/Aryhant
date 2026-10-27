"""Multimodal processing utilities for Slack attachments and Google ADK content parts."""

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from google.genai import types

from chat_agent.config import settings
from chat_agent.utils.input_validation import get_LLM_feedback_on_input, scan_for_vulnerability

logger = logging.getLogger(__name__)

SUPPORTED_MIME_PREFIXES: Tuple[str, ...] = (
    "image/",
    "audio/",
    "application/pdf",
    "text/csv",
    "text/plain",
    "text/markdown",
    "text/html",
    "application/json",
)


def extract_slack_files(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract and filter valid file attachments from a Slack event payload."""
    files = event.get("files") or []
    extracted: List[Dict[str, Any]] = []

    for f in files:
        if not isinstance(f, dict):
            continue
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue

        mimetype = f.get("mimetype") or "application/octet-stream"
        if not any(mimetype.startswith(p) or mimetype == p for p in SUPPORTED_MIME_PREFIXES):
            logger.info("Skipping unsupported attachment MIME type: %s", mimetype)
            continue

        extracted.append(
            {
                "id": f.get("id", ""),
                "name": f.get("name", "attachment"),
                "mimetype": mimetype,
                "size": f.get("size", 0),
                "url": url,
            }
        )

        if len(extracted) >= settings.MAX_ATTACHMENTS_PER_MESSAGE:
            break

    return extracted


async def download_slack_file(
    url: str,
    bot_token: Optional[str] = None,
    max_size_bytes: Optional[int] = None,
) -> Tuple[bytes, str]:
    """Download attachment bytes from Slack private URL using bot token authentication."""
    token = bot_token or settings.aryhant_slack_bot_token
    limit = max_size_bytes or (settings.MAX_SINGLE_ATTACHMENT_SIZE_KB * 1024)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        content = resp.content

        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type == "text/html" and not url.endswith((".html", ".htm")):
            raise ValueError("Received HTML error response from Slack CDN instead of file bytes.")

        if len(content) > limit:
            raise ValueError(f"Attachment size {len(content)} exceeds maximum limit of {limit} bytes.")

        return content, content_type


async def extract_and_download_slack_attachments(
    event: Dict[str, Any],
    bot_token: Optional[str] = None,
) -> List[Tuple[bytes, str]]:
    """Extract, download, and enforce cumulative size budget for Slack event attachments."""
    slack_files = extract_slack_files(event)
    if not slack_files:
        return []

    attachments: List[Tuple[bytes, str]] = []
    cumulative_bytes = 0
    max_cumulative = settings.MAX_CUMULATIVE_ATTACHMENT_SIZE_MB * 1024 * 1024

    for sf in slack_files:
        try:
            data, _ = await download_slack_file(sf["url"], bot_token=bot_token)
            if cumulative_bytes + len(data) > max_cumulative:
                logger.warning(
                    "Skipping attachment %s: cumulative size limit of %d bytes exceeded.",
                    sf.get("name"),
                    max_cumulative,
                )
                break
            # Preserve authoritative Slack metadata MIME type
            mimetype = sf.get("mimetype") or "application/octet-stream"
            attachments.append((data, mimetype))
            cumulative_bytes += len(data)
        except Exception as dl_err:
            logger.warning("Failed to download Slack attachment %s: %s", sf.get("name"), dl_err)

    return attachments


async def validate_multimodal_payload(prompt: str, media_items: List[Tuple[bytes, str]]) -> bool:
    """Validate prompt safety and multimodal media content within size budgets."""
    max_cumulative = settings.MAX_CUMULATIVE_ATTACHMENT_SIZE_MB * 1024 * 1024
    total_bytes = sum(len(data) for data, _ in media_items)
    if total_bytes > max_cumulative:
        logger.warning("Total attachment size (%d bytes) exceeds cumulative limit (%d bytes).",
                       total_bytes, max_cumulative)
        return False

    if settings.IS_GEMINI_MODERATION_ENOUGH:
        logger.info('bypassing explicit ,  trusting GEMINI moderation only')
        return True

    if prompt and not await scan_for_vulnerability(prompt):
        return False

    for media_bytes, mime_type in media_items:
        if not await get_LLM_feedback_on_input(media_type=mime_type, media_data=media_bytes):
            return False

    return True


def build_adk_multimodal_content(prompt: str, media_items: List[Tuple[bytes, str]]) -> types.Content:
    """Build a Google ADK Content object from prompt text and media parts."""
    parts: List[types.Part] = []
    cleaned_prompt = prompt.strip()

    if cleaned_prompt:
        parts.append(types.Part.from_text(text=cleaned_prompt))

    for data, mime_type in media_items:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

    return types.Content(role="user", parts=parts)

