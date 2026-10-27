from __future__ import annotations

import time
from typing import Any

from chat_agent.research.models import ResearchJobState, ResearchMode, TaskStatus, TodoItem


def initialize_default_todos(mode: ResearchMode) -> list[TodoItem]:
    """Create default milestone tasks for technical research or deliberation."""
    now = time.time()
    if mode == ResearchMode.TECHNICAL:
        return [
            TodoItem(id="plan", title="Analyze topic, visual context & plan queries", status=TaskStatus.PENDING, updated_at=now),
            TodoItem(id="gather", title="Gather Google AI Overview, Tavily Mini-Research & Context7 code", status=TaskStatus.PENDING, updated_at=now),
            TodoItem(id="sandbox", title="Verify code execution in Nebius Sandbox", status=TaskStatus.PENDING, updated_at=now),
            TodoItem(id="synthesize", title="Synthesize technical publication (~2,500 words)", status=TaskStatus.PENDING, updated_at=now),
            TodoItem(id="deliver", title="Compile ReportLab PDF & upload to Slack", status=TaskStatus.PENDING, updated_at=now),
        ]
    return [
        TodoItem(id="plan", title="Analyze decision context, criteria & user intent", status=TaskStatus.PENDING, updated_at=now),
        TodoItem(id="gather", title="Gather Google AI Overview, Tavily Mini-Research & market data", status=TaskStatus.PENDING, updated_at=now),
        TodoItem(id="synthesize", title="Synthesize comparative decision guide (~1,500 words)", status=TaskStatus.PENDING, updated_at=now),
        TodoItem(id="deliver", title="Compile Decision Guide PDF & upload to Slack", status=TaskStatus.PENDING, updated_at=now),
    ]


def render_slack_todo_board(job: ResearchJobState) -> list[dict[str, Any]]:
    """Render dynamic Slack Block Kit blocks representing the live research TODO board."""
    icons = {
        TaskStatus.PENDING: "⬜",
        TaskStatus.IN_PROGRESS: "🔄",
        TaskStatus.COMPLETED: "✅",
        TaskStatus.FAILED: "❌",
    }

    is_tech = job.mode == ResearchMode.TECHNICAL
    header_title = "🔍 Technical Research In Progress" if is_tech else "⚖️ Deliberation & Decision Guide In Progress"
    mode_label = "Technical Whitepaper (~2,500 words)" if is_tech else "Decision & Buying Guide (~1,500 words)"

    elapsed = int(time.time() - job.created_at) if job.created_at else 0
    clean_topic = job.topic[:120]

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_title,
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Topic:*\n`{clean_topic}`"},
                {"type": "mrkdwn", "text": f"*Scope:*\n{mode_label}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{job.status.value.upper()}"},
                {"type": "mrkdwn", "text": f"*Elapsed Time:*\n{elapsed}s"},
            ],
        },
        {"type": "divider"},
    ]

    task_lines: list[str] = []
    for idx, t in enumerate(job.todos, 1):
        icon = icons.get(t.status, "⬜")
        detail_suffix = f" _({t.details})_" if t.details and t.status in (TaskStatus.IN_PROGRESS, TaskStatus.FAILED) else ""
        task_lines.append(f"{icon} *{idx}. {t.title}*{detail_suffix}")

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "\n".join(task_lines) if task_lines else "No tasks defined.",
        },
    })

    if job.status == TaskStatus.COMPLETED:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🎉 *Execution Complete!* Generated {job.word_count} words in {elapsed}s. PDF publication attached below.",
                }
            ],
        })
    elif job.status == TaskStatus.FAILED:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"⚠️ *Execution Error:* {job.error or 'An unexpected error occurred during processing.'}",
                }
            ],
        })

    return blocks
