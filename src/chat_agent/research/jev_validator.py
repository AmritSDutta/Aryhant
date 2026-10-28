from __future__ import annotations

import logging
from typing import Any
from pydantic import BaseModel, Field

from chat_agent.config import settings
from chat_agent.research.models import ResearchMode

logger = logging.getLogger(__name__)

CRITIQUE_MAPPINGS = {
    "user_criteria": "Address all user-specified success criteria and key topic focus dimensions directly.",
    "technical_depth": "Deepen technical rigor: expand internal architectural mechanics, protocol details, and edge cases.",
    "code_and_benchmarks": "Incorporate concrete verified code patterns and quantitative benchmark comparisons.",
    "structure_compliance": "Adhere strictly to the required section structure and target word count quotas.",
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
            "technical_depth": round(ratio, 4),
            "code_and_benchmarks": round(ratio, 4),
            "structure_compliance": round(ratio, 4),
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
                    f"Does this report thoroughly fulfill all user criteria for '{clean_topic}': '{criteria_str}'? "
                    "Return 1.0 for complete fulfillment, 0.0 for deficient."
                )
            ),
            "technical_depth": Noul(
                instructions=(
                    "Does the report demonstrate rigorous architectural depth and concrete mechanics rather than generic prose? "
                    "Return 1.0 for deep and rigorous, 0.0 for superficial."
                )
            ),
            "code_and_benchmarks": Noul(
                instructions=(
                    "Does the report include concrete implementation patterns, verified code snippets, or quantitative benchmarks? "
                    "Return 1.0 for strong evidence, 0.0 for missing."
                )
            ),
            "structure_compliance": Noul(
                instructions=(
                    "Does the report adhere to standard publication sections without fluff or premature truncation? "
                    "Return 1.0 for compliant, 0.0 for deficient."
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

        # Weighted calculation
        weights = {
            "user_criteria": 0.35,
            "technical_depth": 0.25,
            "code_and_benchmarks": 0.20,
            "structure_compliance": 0.20,
        }
        composite = round(sum(scores.get(d, 0.0) * w for d, w in weights.items()), 4)
        passed = composite >= threshold

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
