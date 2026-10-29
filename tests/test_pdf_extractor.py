"""Tests for LiteParse PDF extraction and Nebius PDF turn routing."""
from __future__ import annotations

import io
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from google.genai import types

from chat_agent.agents import nebius_model_runner as nmr
from chat_agent.utils.pdf_extractor import extract_pdf_markdown


def _create_sample_pdf(text: str) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, text)
    c.save()
    buf.seek(0)
    return buf.read()


def test_extract_pdf_markdown_valid():
    """Verify LiteParse extracts text into Markdown from valid PDF bytes."""
    pdf_bytes = _create_sample_pdf("Algebra Lesson 5: Solve for x")
    extracted = extract_pdf_markdown(pdf_bytes)
    assert "Algebra Lesson 5" in extracted
    assert "Solve for x" in extracted


def test_extract_pdf_markdown_corrupt():
    """Verify corrupt or unreadable PDF bytes fail gracefully with empty string."""
    corrupt_bytes = b"not-a-valid-pdf-header-content"
    extracted = extract_pdf_markdown(corrupt_bytes)
    assert extracted == ""


def test_extract_pdf_markdown_empty():
    """Verify empty input returns empty string immediately."""
    assert extract_pdf_markdown(b"") == ""


@pytest.mark.asyncio
async def test_pdf_attachment_routes_to_chat_model_as_text_turn():
    """Verify a PDF attachment is extracted into text and routes directly to the chat model without VL call."""
    pdf_bytes = _create_sample_pdf("History Chapter 2: The Indus Valley")

    part_text = types.Part(text="Summarize the attached document.")
    part_pdf = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    content = types.Content(parts=[part_text, part_pdf])

    calls: list[dict[str, Any]] = []

    async def fake_completion(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "Summary of Indus Valley civilization."

    with patch.object(nmr, "_call_nebius_completion", fake_completion), patch(
        "chat_agent.agents.nebius_model_runner.settings.NEBIUS_API_KEY", "test-nebius-key"
    ):
        runner = nmr.NebiusModelRunner()
        reply = await runner.run("u1", "s-pdf-test", content)

    assert reply == "Summary of Indus Valley civilization."
    # Exactly ONE completion call directly on Nano chat model (no VL extraction call)
    assert len(calls) == 1
    assert calls[0]["model"] == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

    # User message contains extracted PDF text
    user_msg = calls[0]["messages"][-1]["content"]
    assert isinstance(user_msg, str)
    assert "[PDF content:" in user_msg
    assert "The Indus Valley" in user_msg
