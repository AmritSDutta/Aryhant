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

_CATALOG_PATTERN = re.compile(r"\b(top\s+\d+|\d+\s+questions?|interview\s+questions?)\b", re.I)


def is_clear_scope(topic: str, has_attachments: bool = False) -> bool:
    """Determine if a query has sufficient clarity to auto-proceed immediately."""
    if has_attachments:
        return False
    clean = topic.strip()
    # High-volume question or catalog queries require scope review and category framing
    if _CATALOG_PATTERN.search(clean):
        return False

    words = re.findall(r"\b\w+\b", clean.lower())
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
    is_question_catalog = bool(re.search(r"\b(questions?|interview|q&a|faq|top\s+\d+)\b", clean_topic, re.I))

    if is_tech:
        if is_question_catalog:
            focus_areas = [
                "Curated Question Taxonomy & Domain Breakdown",
                "In-Depth Architectural & Technical Solutions",
                "Edge Cases, Pitfalls & Real-World Gotchas",
                "Practical Evaluation & Industry Best Practices",
            ]
            success_criteria = [
                f"Directly delivers the requested collection of comprehensive questions and expert answers for {clean_topic}.",
                "Demonstrates rigorous technical and architectural depth across items.",
                "Covers critical edge cases, trade-offs, and practical industry nuances.",
            ]
        else:
            focus_areas = [
                "Architectural & Foundational Mechanics",
                "Concrete Implementation & Verified Patterns",
                "Edge Cases, Failure Modes & Bottlenecks",
                "Quantitative Benchmarks & Trade-offs",
            ]
            success_criteria = [
                f"Thoroughly explains internal mechanics and protocols for {clean_topic}.",
                "Provides verified implementation patterns, architectures, or concrete examples.",
                "Analyzes quantitative benchmarks, trade-offs, and production failure modes.",
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
        assumptions.append(f"Visual evidence incorporated: {attachment_brief[:100]}...")

    objective = (
        f"Publish a comprehensive technical whitepaper on {clean_topic}."
        if is_tech
        else f"Deliver an authoritative decision and buying guide for {clean_topic}."
    )

    return {
        "objective": objective,
        "focus_areas": focus_areas,
        "assumptions": assumptions,
        "success_criteria": success_criteria,
    }


def render_scope_notice(scope_data: dict[str, Any], wait_sec: int = 20) -> str:
    """Render Slack informational scope notice with structured bullet points."""
    focus_lines = "\n".join(f"• *{fa}*" for fa in scope_data.get("focus_areas", []))
    criteria_lines = "\n".join(f"• {sc}" for sc in scope_data.get("success_criteria", []))

    return (
        f"🎯 *Research Scope & Criteria Formulated*\n\n"
        f"*Objective:* {scope_data.get('objective', '')}\n\n"
        f"*Core Focus Dimensions:*\n{focus_lines}\n\n"
        f"*Success Criteria:*\n{criteria_lines}\n\n"
        f"⏱ _Auto-proceeding in {wait_sec} seconds. Reply in this thread to steer or clarify criteria._"
    )
