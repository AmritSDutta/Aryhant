"""Interprets and converts Markdown responses into human-consumable text with fallback cleanup."""
from __future__ import annotations

import logging
import re
from typing import Match

from chat_agent.utils.math_formatter import clean_math_text

logger = logging.getLogger(__name__)

# Common abbreviations to guard against false sentence-boundary splits
ABBREVIATIONS = (
    r"(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)(?<!\bDr)(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bProf)"
    r"(?<!\bapprox)(?<!\bmin)(?<!\bmax)(?<!\bsec)(?<!\bhr)(?<!\bno)(?<!\bfig)(?<!\bcf)"
    r"(?<!\b\d)"
)


def fallback_cleanup_markdown(text: str) -> str:
    """Safe fallback that strips Markdown markers and un-glues text using direct regex."""
    if not text:
        return ""
    t = text

    # Un-glue glued bold markers: 'text:**1. Heading**' -> 'text:\n\n1. Heading\n'
    t = re.sub(r"(?<=[^\n])\s*\*\*(\d+\.\s+[^*]+)\*\*", r"\n\n\1\n", t)
    t = re.sub(r"(?<=[^\n])\s*\*\*([A-Za-z0-9\s—–':]+)\*\*", r"\n\n\1\n", t)

    # Strip remaining bold/italic asterisks and underscores
    t = re.sub(r"[*_]{2}(.*?)[*_]{2}", r"\1", t)
    t = re.sub(r"[*_](.*?)[*_]", r"\1", t)

    # Strip markdown headers '# Heading'
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.MULTILINE)

    # Un-glue sentence boundaries (e.g. 'light!So the Sun' -> 'light!\n\nSo the Sun')
    t = re.sub(rf"{ABBREVIATIONS}([.!?])([A-Z][a-z])", r"\1\n\n\2", t)

    # Un-glue emojis followed by capitalized word (e.g. ':mostly_sunny:Would you' -> ':mostly_sunny:\n\nWould you')
    t = re.sub(r"(:[a-zA-Z0-9_+-]+:)\s*([A-Z])", r"\1\n\n\2", t)

    # Normalize paragraph breaks and whitespace
    lines = [line.strip() for line in t.split("\n")]
    t = "\n".join(lines)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return clean_math_text(t)


def interpret_markdown(text: str) -> str:
    """Interpret Markdown semantics into structured human-readable text."""
    if not text:
        return ""

    out = text

    # Step 1: Interpret code blocks by preserving indented plain text
    def _code_block_replacer(match: Match[str]) -> str:
        code_content = match.group(1).strip()
        return f"\n\n{code_content}\n\n"

    out = re.sub(r"```(?:\w+)?\n?(.*?)```", _code_block_replacer, out, flags=re.DOTALL)

    # Step 2: Interpret inline code `code` -> 'code'
    out = re.sub(r"`([^`]+)`", r"'\1'", out)

    # Step 3: Interpret links [Text](url) -> Text (url) or just Text if url is redundant
    def _link_replacer(match: Match[str]) -> str:
        lbl = match.group(1).strip()
        target = match.group(2).strip()
        return f"{lbl} ({target})" if target and target != lbl else lbl

    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link_replacer, out)

    # Step 4: Interpret glued numbered headings: '**1. Title**' -> '\n\n1. Title\n'
    out = re.sub(r"(?<=[^\n])\s*\*\*(\d+\.\s+[^*]+)\*\*", r"\n\n\1\n", out)

    # Step 5: Interpret glued callout labels: '**Fun fact:**', '**Bonus: Why...**'
    out = re.sub(r"(?<=[^\n])\s*\*\*([A-Za-z0-9\s—–':?]+)\*\*", r"\n\n\1\n", out)

    # Step 6: Interpret bold headings followed immediately by body text: '**Title**Body'
    out = re.sub(r"\*\*([^*]+)\*\*(?=[A-Za-z0-9])", r"\1\n\n", out)

    # Step 7: Interpret standard Markdown ATX headers: '## Heading' -> prominent plain text heading
    out = re.sub(r"^#{1,6}\s*(.*?)\s*$", r"\n\n\1\n", out, flags=re.MULTILINE)

    # Step 8: Convert markdown bullet points ('* item', '- item', '+ item') to clean bullets
    out = re.sub(r"^\s*[-*+]\s+", r"• ", out, flags=re.MULTILINE)

    # Step 9: Strip remaining double asterisks and underscores (interpret bold as clean text)
    out = re.sub(r"[*_]{2}(.*?)[*_]{2}", r"\1", out)
    # Strip standalone emphasis asterisks around words: '*word*' -> 'word'
    out = re.sub(r"(?<!\S)\*([^*]+)\*(?!\S)", r"\1", out)

    # Step 10: Un-glue sentence transitions glued to punctuation: 'light!So' -> 'light!\n\nSo'
    out = re.sub(rf"{ABBREVIATIONS}([.!?])([A-Z][a-z])", r"\1\n\n\2", out)

    # Step 11: Un-glue emojis followed by capital letter: ':mostly_sunny:Would you' -> ':mostly_sunny:\n\nWould you'
    out = re.sub(r"(:[a-zA-Z0-9_+-]+:)\s*([A-Z])", r"\1\n\n\2", out)

    # Step 12: Separate closing conversational questions onto their own paragraph
    out = re.sub(
        r"(?<=[.!?])\s*(Would you like|Do you want to know|Let me know if|Feel free to ask|Can I help)",
        r"\n\n\1",
        out,
    )

    # Step 13: Clean up LaTeX / math notation
    out = clean_math_text(out)

    # Step 14: Normalize paragraph spacing and line breaks
    lines = [line.strip() for line in out.split("\n")]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()

    return out


def format_human_readable_text(text: str) -> str:
    """Interpret Markdown semantics into human-consumable text with fallback cleanup."""
    if not text or not text.strip():
        return ""
    try:
        return interpret_markdown(text)
    except Exception as exc:
        logger.warning("Markdown interpretation failed (%s). Executing fallback cleanup.", exc)
        return fallback_cleanup_markdown(text)
