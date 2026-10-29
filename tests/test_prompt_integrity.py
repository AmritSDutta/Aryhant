"""Hermetic unit tests for prompt integrity, memory boundary framing, and formatting."""

from chat_agent.agents.prompt import (
    INSTRUCTION,
    QA_GENERATOR_INSTRUCTION,
    format_instruction,
)
from chat_agent.research.research_agent import (
    DELIBERATION_SYSTEM_PROMPT,
    TECHNICAL_SYSTEM_PROMPT,
)


def test_instruction_roles_and_dispatch() -> None:
    """Verify presence of all 4 roles and role routing criteria in INSTRUCTION."""
    assert "Role 1 (Daily & Educational)" in INSTRUCTION
    assert "Role 2 (Technical Research)" in INSTRUCTION
    assert "Role 3 (Product Deliberation)" in INSTRUCTION
    assert "Role 4 (Admin & Operations)" in INSTRUCTION
    assert "Role Selection: Activate the role" in INSTRUCTION


def test_instruction_security_framing_order() -> None:
    """Verify security warning appears before untrusted context injection block."""
    directive_idx: int = INSTRUCTION.find("SECURITY DIRECTIVE")
    context_tag_idx: int = INSTRUCTION.find("<student_learning_context>")
    placeholder_idx: int = INSTRUCTION.find("{USER_MEMORY_CONTEXT}")

    assert directive_idx != -1
    assert context_tag_idx != -1
    assert placeholder_idx != -1
    assert directive_idx < context_tag_idx < placeholder_idx


def test_instruction_code_block_exception_and_emoji() -> None:
    """Verify code block exception in formatting and presence of :mostly_sunny:."""
    assert "backticks (`inline` or ```block```)" in INSTRUCTION
    assert ":mostly_sunny:" in INSTRUCTION


def test_format_instruction_timestamp_and_memory() -> None:
    """Verify format_instruction successfully replaces placeholders."""
    result: str = format_instruction(user_memory_context="Enjoys visual fractions.")
    assert "{CURRENT_DATE}" not in result
    assert "{USER_MEMORY_CONTEXT}" not in result
    assert "Enjoys visual fractions." in result


def test_qa_generator_instruction_schema_and_no_preamble() -> None:
    """Verify QA generator prompt enforces root JSON array and no prose preamble."""
    assert "JSON root array only" in QA_GENERATOR_INSTRUCTION
    assert '{"id": <integer starting at 1>' in QA_GENERATOR_INSTRUCTION
    assert "without prepending explanatory prose" in QA_GENERATOR_INSTRUCTION


def test_research_prompts_integrity() -> None:
    """Verify technical and deliberation research prompts do not contain rigid legacy couplings."""
    assert "Context7" not in TECHNICAL_SYSTEM_PROMPT
    assert "publication-grade technical report" in TECHNICAL_SYSTEM_PROMPT
    assert "For abstract decisions, provide a structured criteria evaluation" in DELIBERATION_SYSTEM_PROMPT
