from __future__ import annotations

import asyncio
import random
import time
from typing import Literal

_ACTIVE_USER_RESEARCH_JOBS: set[str] = set()
_ACTIVE_USER_LOCK = asyncio.Lock()
RESEARCH_CONCURRENCY_SEMAPHORE = asyncio.Semaphore(2)


def parse_research_trigger(raw_text: str) -> tuple[Literal["/research", "/deliberate"], str] | None:
    """Parse research trigger commands and topics, rejecting normal prose."""
    clean = (raw_text or "").strip()
    lower = clean.lower()

    if lower.startswith("/research"):
        topic = clean[len("/research"):].strip()
        return ("/research", topic or "General Overview")
    if lower.startswith("/deliberate"):
        topic = clean[len("/deliberate"):].strip()
        return ("/deliberate", topic or "General Deliberation")
    if lower.startswith("research:"):
        topic = clean[len("research:"):].strip()
        if len(topic) >= 3:
            return ("/research", topic)
    if lower.startswith("deliberate:"):
        topic = clean[len("deliberate:"):].strip()
        if len(topic) >= 3:
            return ("/deliberate", topic)
    return None


def new_job_id(command: str) -> str:
    """Generate a unique timestamped job ID for research or deliberation."""
    prefix = "res" if "research" in command else "del"
    return f"{prefix}_{int(time.time())}_{random.randint(1000, 9999)}"


async def acquire_user_job_slot(user_id: str) -> bool:
    """Acquire an active research slot for user. Returns False if user has an active job."""
    async with _ACTIVE_USER_LOCK:
        if user_id in _ACTIVE_USER_RESEARCH_JOBS:
            return False
        _ACTIVE_USER_RESEARCH_JOBS.add(user_id)
        return True


async def release_user_job_slot(user_id: str) -> None:
    """Release active research slot for user."""
    async with _ACTIVE_USER_LOCK:
        _ACTIVE_USER_RESEARCH_JOBS.discard(user_id)
