from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from chat_agent.config.settings import Settings
from chat_agent.research.jev_validator import evaluate_report_quality
from chat_agent.research.models import ResearchMode


@pytest.mark.asyncio
async def test_jev_validator_passing_score():
    """Verify high JEV scores pass without critique."""
    mock_client = AsyncMock()
    mock_response = MagicMock()

    # High scores across all dimensions
    mock_response.nouls = {
        "user_criteria": MagicMock(noul=0.90),
        "technical_depth": MagicMock(noul=0.85),
        "code_and_benchmarks": MagicMock(noul=0.80),
        "structure_compliance": MagicMock(noul=0.95),
    }
    mock_client.system_one.return_value = mock_response

    with patch.object(Settings, "typesafe_ready", new_callable=PropertyMock, return_value=True), \
         patch("chat_agent.utils.fast_decision.typesafe_integrator.get_client", return_value=mock_client):

        res = await evaluate_report_quality(
            topic="Distributed Systems",
            criteria=["Explain Raft and Paxos"],
            report_text="Comprehensive report text...",
            mode=ResearchMode.TECHNICAL,
        )

        assert res.passed is True
        assert res.composite_score >= 0.75
        assert res.critique == ""


@pytest.mark.asyncio
async def test_jev_validator_critique_derivation_on_failure():
    """Verify deterministic critique derivation from dimensions scoring below 0.75."""
    mock_client = AsyncMock()
    mock_response = MagicMock()

    # Low scores on technical depth and code
    mock_response.nouls = {
        "user_criteria": MagicMock(noul=0.80),
        "technical_depth": MagicMock(noul=0.55),
        "code_and_benchmarks": MagicMock(noul=0.50),
        "structure_compliance": MagicMock(noul=0.85),
    }
    mock_client.system_one.return_value = mock_response

    with patch.object(Settings, "typesafe_ready", new_callable=PropertyMock, return_value=True), \
         patch("chat_agent.utils.fast_decision.typesafe_integrator.get_client", return_value=mock_client):

        res = await evaluate_report_quality(
            topic="High Performance Caching",
            criteria=["Provide code benchmarks"],
            report_text="Superficial text with no code...",
            mode=ResearchMode.TECHNICAL,
        )

        assert res.passed is False
        assert res.composite_score < 0.75
        assert "JEV Evaluation Deficiencies" in res.critique
        assert "Deepen technical rigor" in res.critique or "concrete verified code" in res.critique


@pytest.mark.asyncio
async def test_jev_validator_exception_fallback_with_log(caplog):
    """Verify that exceptions in JEV client trigger a warning log and honest heuristic evaluation."""
    mock_client = AsyncMock()
    mock_client.system_one.side_effect = RuntimeError("TypeSafe connection error")

    with patch.object(Settings, "typesafe_ready", new_callable=PropertyMock, return_value=True), \
         patch("chat_agent.utils.fast_decision.typesafe_integrator.get_client", return_value=mock_client), \
         caplog.at_level("WARNING"):

        short_report = "Incomplete draft with very few words."
        res = await evaluate_report_quality(
            topic="Operating Systems",
            criteria=["Explain virtual memory"],
            report_text=short_report,
            mode=ResearchMode.TECHNICAL,
        )

        assert res.passed is False
        assert res.composite_score < 0.75
        assert "Falling back to heuristic quality evaluation" in caplog.text
