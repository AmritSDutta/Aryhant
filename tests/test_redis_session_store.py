"""Unit tests for the RedisSessionStore and in-memory sliding window history."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from chat_agent.services.redis_session_store import RedisSessionStore, _IN_MEMORY_HISTORY


@pytest.fixture(autouse=True)
def clean_in_memory_history():
    """Ensure in-memory history dictionary is clean before each test."""
    _IN_MEMORY_HISTORY.clear()
    yield
    _IN_MEMORY_HISTORY.clear()


@pytest.mark.asyncio
async def test_in_memory_fallback_append_and_get():
    """Verify in-memory fallback works seamlessly when Redis URL is unconfigured."""
    store = RedisSessionStore(redis_url="")

    session_id = "test-session-1"
    await store.append_turn(session_id, "user", "Hello Aryhant")
    await store.append_turn(session_id, "assistant", "Hello! How can I help with your studies today?")

    history = await store.get_history(session_id)
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "Hello Aryhant"}
    assert history[1] == {"role": "assistant", "content": "Hello! How can I help with your studies today?"}


@pytest.mark.asyncio
async def test_sliding_window_cap():
    """Verify conversation history is capped to the most recent 20 turns."""
    store = RedisSessionStore(redis_url="")
    session_id = "test-session-cap"

    # Add 25 turns
    for i in range(25):
        await store.append_turn(session_id, "user" if i % 2 == 0 else "assistant", f"Message {i}")

    history = await store.get_history(session_id)
    assert len(history) == 20
    # The oldest 5 messages should have been trimmed away
    assert history[0]["content"] == "Message 5"
    assert history[-1]["content"] == "Message 24"


@pytest.mark.asyncio
async def test_clear_history():
    """Verify history can be cleared for a session."""
    store = RedisSessionStore(redis_url="")
    session_id = "test-session-clear"

    await store.append_turn(session_id, "user", "Test message")
    assert len(await store.get_history(session_id)) == 1

    await store.clear_history(session_id)
    assert len(await store.get_history(session_id)) == 0


@pytest.mark.asyncio
async def test_redis_pipeline_interaction():
    """Verify Redis client uses pipeline with rpush, ltrim, and expire."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, "OK", True])
    mock_redis.pipeline.return_value = mock_pipe
    mock_redis.lrange = AsyncMock(return_value=['{"role": "user", "content": "Hi"}'])
    mock_redis.delete = AsyncMock(return_value=1)

    store = RedisSessionStore(redis_url="redis://localhost:6379", ttl_sec=3600)
    store._client = mock_redis

    await store.append_turn("session-123", "user", "Hi")
    mock_redis.pipeline.assert_called_once_with(transaction=True)
    mock_pipe.rpush.assert_called_once()
    mock_pipe.ltrim.assert_called_once_with("aryhant:session:session-123:history", -20, -1)
    mock_pipe.expire.assert_called_once_with("aryhant:session:session-123:history", 3600)

    history = await store.get_history("session-123")
    assert len(history) == 1
    assert history[0] == {"role": "user", "content": "Hi"}

    await store.clear_history("session-123")
    mock_redis.delete.assert_called_once_with("aryhant:session:session-123:history")


@pytest.mark.asyncio
async def test_append_exchange_atomic():
    """Verify append_exchange records both user and assistant turns atomically."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 2, "OK", True])
    mock_redis.pipeline.return_value = mock_pipe

    store = RedisSessionStore(redis_url="redis://localhost:6379", ttl_sec=3600)
    store._client = mock_redis

    await store.append_exchange("session-atomic", "What is LCM?", "LCM is Lowest Common Multiple.")
    assert mock_pipe.rpush.call_count == 2
    mock_pipe.ltrim.assert_called_once_with("aryhant:session:session-atomic:history", -20, -1)
    mock_pipe.expire.assert_called_once_with("aryhant:session:session-atomic:history", 3600)


@pytest.mark.asyncio
async def test_lru_in_memory_eviction():
    """Verify in-memory history dictionary caps at 100 sessions."""
    store = RedisSessionStore(redis_url="")
    for i in range(110):
        await store.append_turn(f"session-{i}", "user", f"msg {i}")

    assert len(_IN_MEMORY_HISTORY) == 100
    # Oldest sessions (0..9) should be evicted
    assert "session-0" not in _IN_MEMORY_HISTORY
    assert "session-9" not in _IN_MEMORY_HISTORY
    assert "session-10" in _IN_MEMORY_HISTORY
    assert "session-109" in _IN_MEMORY_HISTORY


@pytest.mark.asyncio
async def test_redis_empty_lrange_no_fallback():
    """Verify that an empty list from an active Redis client returns empty without falling back."""
    mock_redis = MagicMock()
    mock_redis.lrange = AsyncMock(return_value=[])

    store = RedisSessionStore(redis_url="redis://localhost:6379", ttl_sec=3600)
    store._client = mock_redis

    # Even if in-memory history has entries for this session, Redis is authoritative
    _IN_MEMORY_HISTORY["session-authoritative"] = [{"role": "user", "content": "Stale fallback"}]

    history = await store.get_history("session-authoritative")
    assert history == []


def test_redis_key_prefix_enforcement():
    """Verify that format_session_key strictly prepends aryhant: and prevents nested prefixing."""
    from chat_agent.services.redis_session_store import format_session_key, REDIS_KEY_PREFIX

    # Standard session ID
    k1 = format_session_key("session-abc")
    assert k1 == "aryhant:session:session-abc:history"
    assert k1.startswith(REDIS_KEY_PREFIX)

    # Slack session ID
    k2 = format_session_key("slack:C12345:1712345678.000")
    assert k2 == "aryhant:session:slack:C12345:1712345678.000:history"
    assert k2.startswith(REDIS_KEY_PREFIX)

    # Already prefixed session ID (no nested aryhant:aryhant:)
    k3 = format_session_key("aryhant:session:my-id:history")
    assert k3 == "aryhant:session:my-id:history"
    assert k3.startswith(REDIS_KEY_PREFIX)

    # Partial prefixing
    k4 = format_session_key("aryhant:session:custom-session")
    assert k4 == "aryhant:session:custom-session:history"
    assert k4.startswith(REDIS_KEY_PREFIX)



