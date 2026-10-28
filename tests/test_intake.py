from __future__ import annotations

import pytest

from chat_agent.research.intake import formulate_scope, is_clear_scope, render_scope_notice
from chat_agent.research.models import ResearchMode


def test_is_clear_scope_logic():
    """Verify clarity heuristics for auto-proceed decisions."""
    # Detailed queries -> True (auto-proceed)
    assert is_clear_scope("Kafka vs RabbitMQ latency benchmarks") is True
    assert is_clear_scope("PostgreSQL indexing strategy internals") is True
    assert is_clear_scope("BGP routing protocol failure modes") is True

    # Short / ambiguous queries & conversational filler -> False (intake card)
    assert is_clear_scope("python") is False
    assert is_clear_scope("insurance") is False
    assert is_clear_scope("tell me about computers") is False
    assert is_clear_scope("what is python") is False
    assert is_clear_scope("can you explain everything") is False

    # Attachments present -> False (visual intake required)
    assert is_clear_scope("Kafka vs RabbitMQ latency benchmarks", has_attachments=True) is False


def test_formulate_scope_modes():
    """Verify scope formulation for technical whitepapers vs deliberation buying guides."""
    tech_scope = formulate_scope("Distributed Transactions", ResearchMode.TECHNICAL)
    assert "whitepaper" in tech_scope["objective"].lower()
    assert len(tech_scope["focus_areas"]) >= 3
    assert len(tech_scope["success_criteria"]) >= 3

    delib_scope = formulate_scope("Best Term Life Insurance", ResearchMode.DELIBERATE)
    assert "decision guide" in delib_scope["objective"].lower()
    assert any("matrix" in f.lower() for f in delib_scope["focus_areas"])


def test_render_scope_notice():
    """Verify rendering of Slack informational scope notice."""
    scope = formulate_scope("Rust vs Go", ResearchMode.TECHNICAL)
    rendered = render_scope_notice(scope, wait_sec=20)
    assert "*Research Scope & Criteria Formulated*" in rendered
    assert "Rust vs Go" in rendered
    assert "20 seconds" in rendered
