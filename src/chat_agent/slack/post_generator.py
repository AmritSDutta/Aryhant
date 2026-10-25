import re
from typing import Any

from chat_agent.utils.math_formatter import clean_math_text

MAX_BLOCKS = 20


def chunk_text(text: str, max_chunk_size: int = 2800) -> list[str]:
    """Split text into chunks of at most max_chunk_size, preferring whitespace boundaries."""
    if len(text) <= max_chunk_size:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chunk_size:
        split_idx = remaining.rfind("\n", 0, max_chunk_size)
        if split_idx == -1:
            split_idx = remaining.rfind(" ", 0, max_chunk_size)
        if split_idx <= 0:
            split_idx = max_chunk_size
        chunks.append(remaining[:split_idx].strip())
        remaining = remaining[split_idx:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def create_section_block(text: str, accessory: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a Slack section block with mrkdwn formatting (max 3000 chars)."""
    block: dict[str, Any] = {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text[:3000]},
    }
    if accessory:
        block["accessory"] = accessory
    return block


def create_header_block(text: str) -> dict[str, Any]:
    """Create a Slack header block with plain_text formatting (max 150 chars)."""
    clean_text = re.sub(r'^[#*]+\s*|\s*[#*]+$', '', text).strip()[:150]
    return {
        "type": "header",
        "text": {"type": "plain_text", "text": clean_text or "Aryhant Update", "emoji": True},
    }


def create_divider_block() -> dict[str, Any]:
    """Create a visual divider block."""
    return {"type": "divider"}


def create_context_block(text: str) -> dict[str, Any]:
    """Create a small context note block (max 2000 chars)."""
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": text[:2000]}],
    }


def generate_slack_post(reply: str) -> dict[str, Any]:
    """
    Convert raw agent reply into a structured Slack message payload
    containing fallback text and Block Kit blocks (strict 20-block limit).
    """
    clean_reply = clean_math_text((reply or "").strip())
    if not clean_reply:
        return {
            "text": "Aryhant Update",
            "blocks": [create_section_block("I did not produce a reply.")],
        }

    # Fallback text for mobile push notifications & screen readers
    fallback_text = clean_reply[:200].replace("\n", " ") or "Aryhant Update"

    blocks: list[dict[str, Any]] = []
    paragraphs = [p.strip() for p in clean_reply.split("\n\n") if p.strip()]
    truncated = False

    for idx, p in enumerate(paragraphs):
        remaining_paras = len(paragraphs) - idx
        max_allowed = MAX_BLOCKS - 1 if remaining_paras > 1 else MAX_BLOCKS

        if len(blocks) >= max_allowed:
            truncated = True
            break

        # Detect markdown headers (starts with #)
        if p.startswith("#"):
            if len(blocks) <= max_allowed - 2:
                blocks.append(create_header_block(p))
                blocks.append(create_divider_block())
            elif len(blocks) < max_allowed:
                blocks.append(create_header_block(p))
        else:
            # Detect footer context (handles **Note:**, > Note:, *Hint:*, etc.)
            clean_prefix = re.sub(r"^[\s*#>_]+", "", p).lower()
            if clean_prefix.startswith(("note:", "context:", "source:", "timestamp:", "hint:")):
                blocks.append(create_context_block(p))
            else:
                # Chunk long paragraphs to adhere to Slack's 3000-char section limit
                if len(p) > 2900:
                    chunks = chunk_text(p, max_chunk_size=2800)
                    for chunk in chunks:
                        if len(blocks) >= max_allowed:
                            truncated = True
                            break
                        blocks.append(create_section_block(chunk))
                else:
                    blocks.append(create_section_block(p))

    if truncated:
        notice = create_context_block("*(Message truncated due to Slack length limits)*")
        if len(blocks) < MAX_BLOCKS:
            blocks.append(notice)
        elif blocks:
            blocks[-1] = notice

    return {
        "text": fallback_text,
        "blocks": blocks[:MAX_BLOCKS],
    }
