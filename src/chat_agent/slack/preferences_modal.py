"""Slack Block Kit modal builder for viewing and managing student memories and preferences."""
from __future__ import annotations

from typing import Any

MAX_MODAL_PREFERENCES = 25


def build_preferences_modal(memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate a Slack Block Kit modal view for student preferences and skills."""
    skills = [m for m in memories if m.get("is_skill")]
    preferences = [m for m in memories if not m.get("is_skill")]
    displayed_preferences = preferences[:MAX_MODAL_PREFERENCES]
    has_overflow = len(preferences) > MAX_MODAL_PREFERENCES

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "👋 *Personal AI Memory & Learning Preferences*\nAryhant uses these verified habits and preferences to tailor explanations and math hints to you.",
            },
        },
        {"type": "divider"},
    ]

    # Section 1: Mastered Skills Badges
    if skills:
        skill_tags = " • ".join(f"`{s['text']}`" for s in skills)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🏆 *Learned Skills & Mastered Topics*\n{skill_tags}",
            },
        })
        blocks.append({"type": "divider"})

    # Section 2: Active Preferences with Delete Actions
    if preferences:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Active Preferences & Learning Habits*",
            },
        })

        if has_overflow:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Showing top {MAX_MODAL_PREFERENCES} of {len(preferences)} preferences._",
                    }
                ],
            })

        for p in displayed_preferences:
            source_tag = "Manual" if p.get("source") == "manual" else "Auto-learned"
            category = p.get("category", "General")
            text = p.get("text", "")
            mem_id = p.get("id", "")

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• *[{category}]* {text}\n  _Source: {source_tag} (Strength: {p.get('weight', 1)})_",
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Delete", "emoji": True},
                    "action_id": "delete_memory_action",
                    "value": mem_id,
                    "style": "danger",
                },
            })

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Clear All Preferences", "emoji": True},
                    "action_id": "clear_memories_action",
                    "style": "danger",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Clear All Preferences?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": "Are you sure you want to permanently delete all your stored preferences and learned skills? This cannot be undone.",
                        },
                        "confirm": {"type": "plain_text", "text": "Yes, Clear All"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                }
            ],
        })
    else:
        if not skills:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_No specific preferences or skills recorded yet. As you ask questions, Aryhant will automatically learn your study habits and recurring subjects._",
                },
            })

    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Aryhant Preferences"},
        "close": {"type": "plain_text", "text": "Done"},
        "blocks": blocks,
    }
