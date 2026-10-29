from __future__ import annotations

import re

ADMIN_KEYWORDS: tuple[str, ...] = (
    "admin",
    "audit",
    "telemetry",
    "metrics",
    "health",
    "status",
    "prune",
    "retention",
    "latency",
    "token",
    "tokens",
    "failures",
    "errors",
    "performance",
    "system",
    "operations",
    "ops",
    "maintenance",
    "report",
)

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in ADMIN_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_administrative_query(subject: str, body: str) -> bool:
    """Check if subject or email body requests an administrative or operational audit/status."""
    combined = f"{subject or ''}\n{body or ''}".strip()
    if not combined:
        return False
    return bool(_PATTERN.search(combined))
