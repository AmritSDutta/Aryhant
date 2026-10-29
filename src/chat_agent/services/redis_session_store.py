"""Asynchronous Redis session history store for Aryhant multi-turn conversations."""
from __future__ import annotations

import collections
import json
import logging
import os

import redis.asyncio as aioredis

from chat_agent.config import settings

logger = logging.getLogger(__name__)

_MAX_IN_MEMORY_SESSIONS = 100
_HISTORY_CAP = 20
_IN_MEMORY_HISTORY: collections.OrderedDict[str, list[dict[str, str]]] = collections.OrderedDict()
REDIS_KEY_PREFIX: str = "aryhant:"


def format_session_key(session_id: str) -> str:
    """Format and guarantee that every Redis key is strictly namespaced under 'aryhant:' prefix."""
    raw = (session_id or "default").strip()
    while raw.startswith(REDIS_KEY_PREFIX):
        raw = raw[len(REDIS_KEY_PREFIX):].strip()
    if raw.startswith("session:"):
        raw = raw[len("session:"):].strip()
    if raw.endswith(":history"):
        raw = raw[:-len(":history")].strip()
    key = f"{REDIS_KEY_PREFIX}session:{raw}:history"
    assert key.startswith(REDIS_KEY_PREFIX), f"Redis key must start with '{REDIS_KEY_PREFIX}', got: {key}"
    return key


def _store_in_memory_turn(session_id: str, entry: dict[str, str]) -> None:
    """Store single turn in bounded LRU in-memory history cache."""
    history = _IN_MEMORY_HISTORY.setdefault(session_id, [])
    history.append(entry)
    if len(history) > _HISTORY_CAP:
        _IN_MEMORY_HISTORY[session_id] = history[-_HISTORY_CAP:]
    _IN_MEMORY_HISTORY.move_to_end(session_id)
    if len(_IN_MEMORY_HISTORY) > _MAX_IN_MEMORY_SESSIONS:
        _IN_MEMORY_HISTORY.popitem(last=False)


def _store_in_memory_exchange(session_id: str, user_entry: dict[str, str], assistant_entry: dict[str, str]) -> None:
    """Store exchange pair in bounded LRU in-memory history cache."""
    history = _IN_MEMORY_HISTORY.setdefault(session_id, [])
    history.append(user_entry)
    history.append(assistant_entry)
    if len(history) > _HISTORY_CAP:
        _IN_MEMORY_HISTORY[session_id] = history[-_HISTORY_CAP:]
    _IN_MEMORY_HISTORY.move_to_end(session_id)
    if len(_IN_MEMORY_HISTORY) > _MAX_IN_MEMORY_SESSIONS:
        _IN_MEMORY_HISTORY.popitem(last=False)


class RedisSessionStore:
    """Manages multi-turn conversation thread histories in Redis with a 20-turn sliding window."""

    def __init__(self, redis_url: str | None = None, ttl_sec: int | None = None) -> None:
        raw_redis = redis_url if redis_url is not None else (os.getenv("ARYHANT_REDIS_URL") or settings.ARYHANT_REDIS_URL)
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
                    socket_keepalive=True,
                    health_check_interval=30,
                )
            except Exception as exc:
                logger.warning("Failed to initialize Redis client (%s). Using in-memory fallback.", exc)
                return None
        return self._client

    async def pre_warm(self) -> bool:
        """Pre-warm the Redis connection pool with an initial ping; returns True on success."""
        client = self._get_client()
        if not client:
            return False
        try:
            await client.ping()
            logger.info("Redis session store pre-warmed successfully.")
            return True
        except Exception as exc:
            logger.warning("Redis pre-warm ping failed (%s). Using in-memory fallback if needed.", exc)
            return False

    async def get_history(self, session_id: str) -> list[dict[str, str]]:
        """Fetch the most recent turns for a session (bounded to sliding window cap)."""
        client = self._get_client()
        if client:
            try:
                key = format_session_key(session_id)
                raw_items = await client.lrange(key, -_HISTORY_CAP, -1)
                history: list[dict[str, str]] = []
                for item in (raw_items or []):
                    try:
                        parsed = json.loads(item)
                        if isinstance(parsed, dict) and "role" in parsed and "content" in parsed:
                            history.append({"role": str(parsed["role"]), "content": str(parsed["content"])})
                    except Exception:
                        continue
                return history
            except Exception as exc:
                logger.warning("Redis get_history failed for %s (%s). Using fallback.", session_id, exc)

        if session_id in _IN_MEMORY_HISTORY:
            _IN_MEMORY_HISTORY.move_to_end(session_id)
            return list(_IN_MEMORY_HISTORY[session_id])
        return []

    async def append_exchange(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        assistant_role: str = "assistant",
    ) -> None:
        """Atomically append user and assistant turns in a single pipeline."""
        u_entry = {"role": "user", "content": user_content}
        a_entry = {"role": assistant_role, "content": assistant_content}
        client = self._get_client()
        if client:
            try:
                key = format_session_key(session_id)
                pipe = client.pipeline(transaction=True)
                pipe.rpush(key, json.dumps(u_entry))
                pipe.rpush(key, json.dumps(a_entry))
                pipe.ltrim(key, -_HISTORY_CAP, -1)
                pipe.expire(key, self.ttl_sec)
                await pipe.execute()
                return
            except Exception as exc:
                logger.warning("Redis append_exchange failed for %s (%s). Using fallback.", session_id, exc)

        _store_in_memory_exchange(session_id, u_entry, a_entry)

    async def append_turn(self, session_id: str, role: str, content: str) -> None:
        """Append a message turn to history, trim to last 20 turns, and refresh TTL."""
        entry = {"role": role, "content": content}
        client = self._get_client()
        if client:
            try:
                key = format_session_key(session_id)
                pipe = client.pipeline(transaction=True)
                pipe.rpush(key, json.dumps(entry))
                pipe.ltrim(key, -_HISTORY_CAP, -1)
                pipe.expire(key, self.ttl_sec)
                await pipe.execute()
                return
            except Exception as exc:
                logger.warning("Redis append_turn failed for %s (%s). Using fallback.", session_id, exc)

        _store_in_memory_turn(session_id, entry)

    async def clear_history(self, session_id: str) -> None:
        """Clear conversation history for a session."""
        client = self._get_client()
        if client:
            try:
                key = format_session_key(session_id)
                await client.delete(key)
            except Exception as exc:
                logger.warning("Redis clear_history failed for %s: %s", session_id, exc)

        _IN_MEMORY_HISTORY.pop(session_id, None)

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None


_session_store_instance: RedisSessionStore | None = None


def get_redis_session_store() -> RedisSessionStore:
    """Return the global RedisSessionStore singleton."""
    global _session_store_instance
    if _session_store_instance is None:
        _session_store_instance = RedisSessionStore()
    return _session_store_instance
