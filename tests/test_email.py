"""Hermetic unit tests for email message formatting and template rendering."""

from unittest.mock import MagicMock, patch
import pytest

from chat_agent.config.email_message_helper import (
    _render_email_template,
    format_markdown_to_email_html,
    send_email_with_brevo_template,
)


def test_format_markdown_to_email_html():
    md = "# Hello\nThis is a **test** message."
    html = format_markdown_to_email_html(md, timestamp="2026-09-19", model_usage="0.001s")
    assert "<h1" in html
    assert "Hello" in html
    assert "Analysis completed at: 2026-09-19" in html
    assert "To build this response: 0.001s" in html


def test_format_markdown_to_email_html_empty():
    html = format_markdown_to_email_html("")
    assert "<p>No content available.</p>" in html


def test_render_email_template_fallback():
    rendered = _render_email_template("Test Subject", "<p>Body Content</p>", template_id=999)
    assert "<p>Body Content</p>" in rendered


def test_send_email_with_brevo_template_missing_key():
    with patch("chat_agent.config.email_message_helper.os.getenv", return_value=None):
        result = send_email_with_brevo_template(
            to_emails=["test@example.com"],
            cc_emails=[],
            subject_text="Subject",
            content="Content",
        )
        assert result is False
