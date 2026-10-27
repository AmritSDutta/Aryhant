from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import redis.asyncio as aioredis

from chat_agent.config import settings
from chat_agent.research.models import ResearchJobState, TaskStatus, TodoItem

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX: str = "aryhant:"
_IN_MEMORY_JOBS: dict[str, str] = {}
_IN_MEMORY_CAP: int = 500
_store_instance: RedisResearchStore | None = None


def format_job_key(job_id: str) -> str:
    """Format and guarantee that every Redis job key starts with 'aryhant:job:'."""
    raw = (job_id or "default").strip()
    while raw.startswith(REDIS_KEY_PREFIX):
        raw = raw[len(REDIS_KEY_PREFIX):].strip()
    if raw.startswith("job:"):
        raw = raw[len("job:"):].strip()
    key = f"{REDIS_KEY_PREFIX}job:{raw}"
    if not key.startswith(REDIS_KEY_PREFIX):
        raise ValueError(f"Key must start with '{REDIS_KEY_PREFIX}', got: {key}")
    return key


class RedisResearchStore:
    """Persistent storage for research and deliberation jobs in Redis with in-memory fallback."""

    def __init__(self, redis_url: str | None = None, ttl_sec: int | None = None) -> None:
        raw_redis = redis_url if redis_url is not None else getattr(settings, "ARYHANT_REDIS_URL", "")
        self.redis_url: str = (raw_redis or "").strip().strip("'").strip('"')
        self.ttl_sec: int = ttl_sec or getattr(settings, "REDIS_TTL_SEC", 86400)
        self._client: aioredis.Redis | None = None

    def _get_client(self) -> aioredis.Redis | None:
        if not self.redis_url:
            return None
        if self._client is None:
            try:
                self._client = aioredis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_timeout=5.0,
                    socket_connect_timeout=5.0,
                    health_check_interval=30,
                )
            except Exception as exc:
                logger.warning("Failed to initialize Redis client (%s). Using in-memory fallback.", exc)
                return None
        return self._client

    async def save_job(self, job: ResearchJobState) -> None:
        """Persist or update research job state."""
        job.updated_at = time.time()
        payload = job.model_dump_json()
        key = format_job_key(job.job_id)

        client = self._get_client()
        if client:
            try:
                await client.set(key, payload, ex=self.ttl_sec)
                return
            except Exception as exc:
                logger.warning("Redis save_job failed (%s). Saving to in-memory fallback.", exc)

        if len(_IN_MEMORY_JOBS) >= _IN_MEMORY_CAP:
            oldest_key = next(iter(_IN_MEMORY_JOBS))
            _IN_MEMORY_JOBS.pop(oldest_key, None)
        _IN_MEMORY_JOBS[key] = payload

    async def get_job(self, job_id: str) -> ResearchJobState | None:
        """Retrieve research job state by ID."""
        key = format_job_key(job_id)
        client = self._get_client()
        if client:
            try:
                raw = await client.get(key)
                if raw:
                    return ResearchJobState.model_validate_json(raw)
            except Exception as exc:
                logger.warning("Redis get_job failed (%s). Checking in-memory fallback.", exc)

        raw_mem = _IN_MEMORY_JOBS.get(key)
        if raw_mem:
            return ResearchJobState.model_validate_json(raw_mem)
        return None

    async def update_todo_status(
        self,
        job_id: str,
        task_id: str,
        status: TaskStatus,
        details: str = "",
        existing_job: ResearchJobState | None = None,
    ) -> ResearchJobState | None:
        """Advance status of a single milestone task and persist."""
        job = existing_job if existing_job is not None else await self.get_job(job_id)
        if not job:
            return None

        found = False
        now = time.time()
        for t in job.todos:
            if t.id == task_id:
                t.status = status
                if details:
                    t.details = details
                t.updated_at = now
                found = True
                break

        if not found:
            job.todos.append(TodoItem(id=task_id, title=task_id, status=status, details=details, updated_at=now))

        all_done = all(t.status == TaskStatus.COMPLETED for t in job.todos)
        any_failed = any(t.status == TaskStatus.FAILED for t in job.todos)
        if any_failed:
            job.status = TaskStatus.FAILED
        elif all_done:
            job.status = TaskStatus.COMPLETED

        await self.save_job(job)
        return job

    async def clear_job(self, job_id: str) -> None:
        """Remove a job state from storage."""
        key = format_job_key(job_id)
        client = self._get_client()
        if client:
            try:
                await client.delete(key)
            except Exception as exc:
                logger.warning("Redis clear_job failed: %s", exc)
        _IN_MEMORY_JOBS.pop(key, None)


def get_research_store() -> RedisResearchStore:
    """Return singleton RedisResearchStore instance."""
    global _store_instance
    if _store_instance is None:
        _store_instance = RedisResearchStore()
    return _store_instance


_IN_MEMORY_SESSION_TOKENS: dict[str, dict[str, Any]] = {}
_TOKEN_TTL_SEC: int = 3600


async def record_session_token_usage(
    session_id: str,
    model_name: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int | None = None,
) -> None:
    """Store raw response token usage metadata temporarily in Redis for a session."""
    if not session_id:
        return
    tot = total_tokens if total_tokens is not None else (prompt_tokens + completion_tokens)
    data = {
        "model_name": model_name,
        "provider": provider,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": tot,
        "timestamp": time.time(),
    }
    store = get_research_store()
    client = store._get_client()
    key = f"{REDIS_KEY_PREFIX}tokens:{session_id}"
    if client:
        try:
            await client.set(key, json.dumps(data), ex=_TOKEN_TTL_SEC)
            return
        except Exception as exc:
            logger.debug("Failed to record session token usage in Redis (%s), saving in-memory", exc)
    if len(_IN_MEMORY_SESSION_TOKENS) >= 500:
        oldest = next(iter(_IN_MEMORY_SESSION_TOKENS))
        _IN_MEMORY_SESSION_TOKENS.pop(oldest, None)
    _IN_MEMORY_SESSION_TOKENS[key] = data


async def get_session_token_usage(session_id: str) -> dict[str, Any] | None:
    """Retrieve raw response token usage metadata for a session if recorded."""
    if not session_id:
        return None
    key = f"{REDIS_KEY_PREFIX}tokens:{session_id}"
    store = get_research_store()
    client = store._get_client()
    if client:
        try:
            raw = await client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Failed to get session token usage from Redis (%s), checking in-memory", exc)
    return _IN_MEMORY_SESSION_TOKENS.get(key)
