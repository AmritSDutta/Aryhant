"""Unit tests for the Slack /preferences Block Kit modal builder and handlers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from chat_agent.slack.preferences_modal import build_preferences_modal


def test_build_preferences_modal_empty():
    """Verify empty modal layout when student has no memories."""
    view = build_preferences_modal([])
    assert view["type"] == "modal"
    assert view["title"]["text"] == "Aryhant Preferences"
    # Contains intro section, divider, and empty note
    block_texts = [b.get("text", {}).get("text", "") for b in view["blocks"] if "text" in b]
    assert any("No specific preferences" in t for t in block_texts)


def test_build_preferences_modal_with_items():
    """Verify modal layout contains skill badges, preferences with delete buttons, and clear all."""
    memories = [
        {
            "id": "mem-1",
            "text": "Prime Factorization",
            "is_skill": True,
            "weight": 3,
            "source": "request",
            "category": "Mathematics",
        },
        {
            "id": "mem-2",
            "text": "Prefers step-by-step arithmetic hints",
            "is_skill": False,
            "weight": 1,
            "source": "manual",
            "category": "Mathematics",
        },
    ]

    view = build_preferences_modal(memories)
    assert view["type"] == "modal"

    # Verify skill badge is rendered
    block_texts = [b.get("text", {}).get("text", "") for b in view["blocks"] if "text" in b]
    assert any("Learned Skills & Mastered Topics" in t for t in block_texts)
    assert any("Prime Factorization" in t for t in block_texts)

    # Verify preference row with delete button accessory
    action_buttons = []
    for b in view["blocks"]:
        accessory = b.get("accessory")
        if accessory and accessory.get("action_id") == "delete_memory_action":
            action_buttons.append(accessory)

    assert len(action_buttons) == 1
    assert action_buttons[0]["value"] == "mem-2"
    assert action_buttons[0]["style"] == "danger"

    # Verify Clear All action exists
    actions_blocks = [b for b in view["blocks"] if b.get("type") == "actions"]
    assert len(actions_blocks) == 1
    clear_btn = actions_blocks[0]["elements"][0]
    assert clear_btn["action_id"] == "clear_memories_action"
    assert clear_btn["style"] == "danger"
    assert "confirm" in clear_btn


def test_preferences_modal_cap_and_overflow():
    """Verify modal limits displayed preferences to 25 and includes an overflow note."""
    memories = [
        {
            "id": f"mem-{i}",
            "text": f"Preference {i}",
            "is_skill": False,
            "weight": 1,
            "source": "manual",
            "category": "Math",
        }
        for i in range(40)
    ]

    view = build_preferences_modal(memories)
    # Check that block count does not exceed Slack's 100-block limit
    assert len(view["blocks"]) < 100

    # Count delete buttons (should be exactly 25)
    delete_buttons = [
        b.get("accessory")
        for b in view["blocks"]
        if b.get("accessory", {}).get("action_id") == "delete_memory_action"
    ]
    assert len(delete_buttons) == 25

    # Check for overflow notice block
    context_blocks = [b for b in view["blocks"] if b.get("type") == "context"]
    assert len(context_blocks) == 1
    assert "Showing top 25 of 40 preferences" in context_blocks[0]["elements"][0]["text"]

