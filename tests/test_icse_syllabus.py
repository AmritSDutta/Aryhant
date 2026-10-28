"""Tests for IcseSyllabusService and the get_icse_syllabus agent tool."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from chat_agent.services.icse_syllabus_service import IcseSyllabusService
from scripts.init_turso_db import SCHEMA_SQL

SAMPLE_ENTRIES = [
    {"subject": "Mathematics", "chapter": "Fractions", "subtopics": "Types, comparison, addition"},
    {"subject": "Mathematics", "chapter": "Decimals", "subtopics": "Place value, conversion"},
    {"subject": "Science", "chapter": "Plants", "subtopics": "Parts, photosynthesis"},
]


@pytest.fixture
def syllabus_service(tmp_path: Path) -> IcseSyllabusService:
    """Provide a fresh IcseSyllabusService backed by an isolated temporary SQLite DB."""
    db_file = tmp_path / "test_syllabus.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    for statement in SCHEMA_SQL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            cursor.execute(stmt)
    conn.commit()
    conn.close()
    return IcseSyllabusService(db_path=str(db_file), database_url="", auth_token="")


def test_upsert_and_get_by_subject(syllabus_service: IcseSyllabusService) -> None:
    """Verify subject-wise filtering is case-insensitive and complete without a subject."""
    assert syllabus_service.upsert_syllabus_entries(SAMPLE_ENTRIES) == 3
    math_rows = syllabus_service.get_syllabus("mathematics")
    assert [r["chapter"] for r in math_rows] == ["Fractions", "Decimals"]
    assert syllabus_service.list_syllabus_subjects() == ["Mathematics", "Science"]
    assert len(syllabus_service.get_syllabus()) == 3


def test_upsert_is_idempotent(syllabus_service: IcseSyllabusService) -> None:
    """Re-upserting updates subtopics instead of duplicating rows."""
    syllabus_service.upsert_syllabus_entries(SAMPLE_ENTRIES)
    updated = [{"subject": "Science", "chapter": "Plants", "subtopics": "Parts, photosynthesis, germination"}]
    assert syllabus_service.upsert_syllabus_entries(updated) == 1
    all_rows = syllabus_service.get_syllabus()
    assert len(all_rows) == 3
    plants = syllabus_service.get_syllabus("Science")[0]
    assert plants["subtopics"] == "Parts, photosynthesis, germination"


def test_syllabus_context_formatting(syllabus_service: IcseSyllabusService) -> None:
    """Verify prompt-injection formatting and empty string for unknown subjects."""
    syllabus_service.upsert_syllabus_entries(SAMPLE_ENTRIES)
    context = syllabus_service.get_syllabus_context("Mathematics")
    assert context.startswith("ICSE Grade 5 Mathematics syllabus:")
    assert "- Fractions: Types, comparison, addition" in context
    assert syllabus_service.get_syllabus_context("History") == ""


def test_get_icse_syllabus_tool(
    syllabus_service: IcseSyllabusService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the agent tool returns subjects list, syllabus context, and not_found."""
    from chat_agent.tools import tool_factory

    syllabus_service.upsert_syllabus_entries(SAMPLE_ENTRIES)
    monkeypatch.setattr(tool_factory, "IcseSyllabusService", lambda: syllabus_service)

    listing = tool_factory.get_icse_syllabus()
    assert listing["status"] == "success"
    assert listing["subjects"] == ["Mathematics", "Science"]

    math_result = tool_factory.get_icse_syllabus("mathematics")
    assert math_result["status"] == "success"
    assert math_result["chapter_count"] == 2
    assert "- Decimals" in math_result["syllabus"]

    missing = tool_factory.get_icse_syllabus("History")
    assert missing["status"] == "not_found"
    assert missing["available_subjects"] == ["Mathematics", "Science"]


def test_resolve_subject_fuzzy(syllabus_service: IcseSyllabusService) -> None:
    """Verify query-style subject matching: partial, word-overlap, typo, and miss."""
    syllabus_service.upsert_syllabus_entries(SAMPLE_ENTRIES)
    assert syllabus_service.resolve_subject("math") == "Mathematics"
    assert syllabus_service.resolve_subject("general science") == "Science"  # word-overlap path
    assert syllabus_service.resolve_subject("matematics") == "Mathematics"  # typo path
    assert syllabus_service.resolve_subject("history") == ""


def test_tool_fuzzy_subject(
    syllabus_service: IcseSyllabusService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent tool resolves fuzzy subject queries instead of failing."""
    from chat_agent.tools import tool_factory

    syllabus_service.upsert_syllabus_entries(SAMPLE_ENTRIES)
    monkeypatch.setattr(tool_factory, "IcseSyllabusService", lambda: syllabus_service)

    result = tool_factory.get_icse_syllabus("math")
    assert result["status"] == "success"
    assert result["subject"] == "Mathematics"
    assert result["requested"] == "math"


def test_tool_registered_for_model_runners() -> None:
    """Verify get_icse_syllabus is wired into both runners' tool maps and Nebius declarations."""
    from chat_agent.agents import gemini_model_runner, nebius_model_runner

    assert "get_icse_syllabus" in nebius_model_runner._TOOL_MAP
    assert "get_icse_syllabus" in gemini_model_runner._TOOL_MAP
    declared = [t["function"]["name"] for t in nebius_model_runner.OPENAI_TOOLS]
    assert "get_icse_syllabus" in declared
