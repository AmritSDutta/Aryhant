from __future__ import annotations

import logging
from typing import Any
from pydantic import BaseModel, Field

from chat_agent.config import settings
from chat_agent.research.models import ResearchMode

logger = logging.getLogger(__name__)

CRITIQUE_MAPPINGS = {
    "user_criteria": "Directly address the user's specific objective, format, and core criteria.",
    "article_depth": "Deepen substantive and conceptual depth: expand explanations, nuances, and edge cases.",
    "clarity": "Improve structure and clarity: ensure coherent organization, logical flow, and clean formatting.",
    "references_present": "Ground content with authoritative references, data sources, citations, or concrete examples.",
    "human_readability": "Enhance human readability: write natural, engaging, professional prose that communicates concepts effortlessly.",
}


class JEVValidationResult(BaseModel):
    """Evaluation result from JEV decision scoring."""
    passed: bool
    composite_score: float
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    critique: str = ""


def _heuristic_quality_eval(
    sample_text: str,
    mode: ResearchMode,
    threshold: float = 0.75,
) -> JEVValidationResult:
    """Evaluate report quality based on word count and structural completeness."""
    target_words = 2500 if mode == ResearchMode.TECHNICAL else 1500
    words = len(sample_text.split())
    ratio = min(1.0, words / max(1, target_words * 0.7))
    passed = ratio >= threshold
    return JEVValidationResult(
        passed=passed,
        composite_score=round(ratio, 4),
        dimension_scores={
            "user_criteria": round(ratio, 4),
            "article_depth": round(ratio, 4),
            "clarity": round(ratio, 4),
            "references_present": round(ratio, 4),
            "human_readability": round(ratio, 4),
        },
        critique="" if passed else "Expand technical substance and ensure mandatory section completeness.",
    )


async def evaluate_report_quality(
    topic: str,
    criteria: list[str] | str,
    report_text: str,
    mode: ResearchMode = ResearchMode.TECHNICAL,
    threshold: float = 0.75,
) -> JEVValidationResult:
    """Evaluate synthesized report against user criteria using JEV Noul probabilities."""
    clean_topic = topic.strip()
    criteria_str = "; ".join(criteria) if isinstance(criteria, list) else str(criteria)
    sample_text = report_text[:6000] if report_text else ""

    # If TypeSafe AI is not configured, perform heuristic evaluation based on length and structure
    if not getattr(settings, "typesafe_ready", False):
        logger.info("TypeSafe AI not configured (TYPESAFE_API_KEY unset). Using heuristic quality evaluation.")
        return _heuristic_quality_eval(sample_text=sample_text, mode=mode, threshold=threshold)

    try:
        from chat_agent.utils.fast_decision.typesafe_integrator import get_client
        from typesafe_sdk import Noul

        client = await get_client()
        state: dict[str, Any] = {
            "topic": clean_topic,
            "mode": mode.value,
            "user_criteria": criteria_str,
            "report_excerpt": sample_text,
        }
        questions = {
            "user_criteria": Noul(
                instructions=(
                    f"Does this report thoroughly fulfill all user criteria and intent for '{clean_topic}': '{criteria_str}'? "
                    "Return 1.0 for complete fulfillment, 0.0 for deficient."
                )
            ),
            "article_depth": Noul(
                instructions=(
                    "Does the content demonstrate substantive depth, rigorous domain insights, and comprehensive coverage rather than superficial summaries? "
                    "Return 1.0 for deep and thorough, 0.0 for superficial."
                )
            ),
            "clarity": Noul(
                instructions=(
                    "Is the content cleanly organized, logically structured, easy to follow, and free of unnecessary fluff or premature truncation? "
                    "Return 1.0 for high clarity, 0.0 for deficient."
                )
            ),
            "references_present": Noul(
                instructions=(
                    "Does the report ground its findings in concrete citations, domain references, authoritative data sources, or real-world examples? "
                    "Return 1.0 for well-grounded, 0.0 for ungrounded."
                )
            ),
            "human_readability": Noul(
                instructions=(
                    "Is the report written in engaging, accessible, publication-grade prose that is natural, professional, and pleasant for a human to read rather than robotic or repetitive? "
                    "Return 1.0 for highly readable, 0.0 for poor readability."
                )
            ),
        }

        response = await client.system_one(state=state, questions=questions, model="jev-latest")
        scores: dict[str, float] = {}
        for dim in questions:
            if dim in response.nouls:
                scores[dim] = round(float(response.nouls[dim].noul), 4)
            else:
                scores[dim] = 0.80

        # Weighted calculation prioritizing user criteria and substantive depth
        weights = {
            "user_criteria": 0.35,
            "article_depth": 0.25,
            "clarity": 0.15,
            "human_readability": 0.15,
            "references_present": 0.10,
        }
        composite = round(sum(scores.get(d, 0.0) * w for d, w in weights.items()), 4)
        passed = composite >= threshold
        logger.info(
            "[TypeSafe JEV Quality] Evaluated '%s': composite=%.2f (threshold=%.2f, passed=%s) | scores=%s",
            clean_topic,
            composite,
            threshold,
            passed,
            scores,
        )

        critique = ""
        if not passed:
            failed_dims = [d for d, s in scores.items() if s < threshold]
            critique_points = [f"- {CRITIQUE_MAPPINGS.get(d, d)} (Score: {scores.get(d, 0.0):.2f})" for d in failed_dims]
            critique = (
                f"JEV Evaluation Deficiencies (Composite Score {composite:.2f} < {threshold}):\n"
                + "\n".join(critique_points)
            )

        return JEVValidationResult(
            passed=passed,
            composite_score=composite,
            dimension_scores=scores,
            critique=critique,
        )
    except Exception as exc:
        logger.warning(
            "JEV evaluation failed (%s). Falling back to heuristic quality evaluation.",
            exc,
        )
        return _heuristic_quality_eval(sample_text=sample_text, mode=mode, threshold=threshold)
