from __future__ import annotations

import logging
import re
from typing import Any

from chat_agent.research.models import ResearchMode

logger = logging.getLogger(__name__)

_CLEAR_KEYWORDS = {
    "vs", "architecture", "internals", "algorithm", "protocol", "benchmark",
    "benchmarks", "performance", "comparison", "latency", "throughput",
    "consensus", "database", "distributed", "security", "framework",
}

_STOP_WORDS = {
    "a", "an", "the", "tell", "me", "about", "can", "you", "explain", "what",
    "is", "are", "how", "to", "do", "please", "some", "good", "best", "give",
    "write", "paper", "guide", "on", "for", "in", "of", "and", "or", "with",
}


def is_clear_scope(topic: str, has_attachments: bool = False) -> bool:
    """Determine if a query has sufficient clarity to auto-proceed immediately."""
    if has_attachments:
        return False
    words = re.findall(r"\b\w+\b", topic.strip().lower())
    if not words:
        return False
    if any(w in _CLEAR_KEYWORDS for w in words):
        return True
    content_words = [w for w in words if w not in _STOP_WORDS]
    return len(content_words) >= 3


def formulate_scope(
    topic: str,
    mode: ResearchMode,
    attachment_brief: str = "",
) -> dict[str, Any]:
    """Formulate structured objective, focus areas, assumptions, and success criteria."""
    clean_topic = topic.strip()
    is_tech = mode == ResearchMode.TECHNICAL

    if is_tech:
        focus_areas = [
            "Architectural & Foundational Mechanics",
            "Concrete Implementation & Verified Code Patterns",
            "Edge Cases, Failure Modes & Bottlenecks",
            "Quantitative Benchmarks & Trade-offs",
        ]
        success_criteria = [
            f"Thoroughly explains internal mechanics and protocols for {clean_topic}.",
            "Provides verified implementation patterns or code snippets.",
            "Includes quantitative benchmarks and production failure modes.",
        ]
    else:
        focus_areas = [
            "Core Evaluation Criteria & Comparison Matrix",
            "Detailed Contender Deep-Dive with Pros & Cons",
            "Hidden Catches, Fees & Policy Fine Print",
            "Step-by-Step Practical Buying/Decision Plan",
        ]
        success_criteria = [
            f"Provides actionable verdict and comparison matrix for {clean_topic}.",
            "Highlights hidden costs, pitfalls, and contract terms.",
            "Delivers structured decision checklist for immediate execution.",
        ]

    assumptions = [
        "Analysis reflects current 2026 production standards and market conditions.",
        "Primary emphasis is placed on reliability, cost efficiency, and verified data.",
    ]
    if attachment_brief:
        assumptions.append(f"Incorporates visual context: {attachment_brief[:100]}...")

    return {
        "topic": clean_topic,
        "mode": mode.value,
        "objective": f"Produce authoritative {'technical whitepaper' if is_tech else 'decision guide'} on {clean_topic}",
        "focus_areas": focus_areas,
        "success_criteria": success_criteria,
        "assumptions": assumptions,
    }


def render_scope_notice(scope_data: dict[str, Any], wait_sec: int = 20) -> str:
    """Render Slack mrkdwn summary card with informational review grace window."""
    topic = scope_data.get("topic", "Topic")
    objective = scope_data.get("objective", "")
    focus_areas = scope_data.get("focus_areas", [])
    criteria = scope_data.get("success_criteria", [])

    focus_lines = "\n".join(f"• {f}" for f in focus_areas)
    criteria_lines = "\n".join(f"• {c}" for c in criteria)

    return (
        f"📋 *Research Scope & Criteria Formulated*\n"
        f"*Topic:* `{topic}`\n"
        f"*Objective:* {objective}\n\n"
        f"*Key Focus Areas:*\n{focus_lines}\n\n"
        f"*Target Success Criteria:*\n{criteria_lines}\n\n"
        f"⏱️ _Proceeding automatically with deep research in {wait_sec} seconds..._"
    )
