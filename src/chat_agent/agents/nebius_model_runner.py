from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
import os
import random
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from google.genai import types

from chat_agent.agents.prompt import INSTRUCTION, format_instruction
from chat_agent.config import settings
from chat_agent.tools.tool_factory import (
    generate_infographic_pdf,
    generate_practice_questions,
    calculate_math,
    generate_study_notes_pdf,
    get_current_time,
    get_icse_syllabus,
    search_web,
)

logger = logging.getLogger(__name__)

_NEBIUS_HISTORY: dict[str, list[dict[str, Any]]] = {}
_HISTORY_CAP = 20
_MAX_TOOL_ROUNDS = 5

_TOOLS: list[Any] = [
    get_current_time,
    search_web,
    generate_study_notes_pdf,
    generate_infographic_pdf,
    generate_practice_questions,
    calculate_math,
    get_icse_syllabus,
]
_TOOL_MAP: dict[str, Any] = {fn.__name__: fn for fn in _TOOLS}

OPENAI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calculate_math",
            "description": "Safely evaluate a mathematical or arithmetic expression (e.g. 'lcm(12, 18)', 'gcd(24, 36)', '2**8', '(15 * 4) + 12').",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Mathematical expression to safely evaluate.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_practice_questions",
            "description": "Generate ICSE Grade 5 curriculum-aligned practice questions and pedagogical hints on any academic topic. Call this whenever practice questions, quizzes, worksheets, or exercise sets are requested, including when preparing study notes containing questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The academic topic or concept to generate practice questions for.",
                    },
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Return current date and time formatted in Indian Standard Time (IST) and UTC.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_icse_syllabus",
            "description": "Fetch the stored ICSE Grade 5 syllabus for one of the six subjects — Mathematics, English, Hindi, Science, Social Studies, or Computer Studies. Pass a subject to get its chapters and subtopics; omit it to list all subjects. Use before teaching a subject, planning lessons, or setting practice.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "One of: Mathematics, English, Hindi, Science, Social Studies, Computer Studies. Optional; omit to list all subjects.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for real-time information across search providers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {"type": "integer", "description": "Maximum results count.", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_study_notes_pdf",
            "description": "Generate handwritten notebook-style study notes PDF and upload it to Slack.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title or topic of study notes."},
                    "content": {"type": "string", "description": "Markdown content containing notes and headings."},
                    "subject": {"type": "string", "description": "Academic subject or category name."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Metadata tag labels."},
                    "visual": {"type": "string", "description": "Visual diagram style: science, math, or general."},
                    "channel": {"type": "string", "description": "Target Slack channel ID."},
                    "thread_ts": {"type": "string", "description": "Target Slack message thread timestamp."},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_infographic_pdf",
            "description": "Generate a lesson infographic poster PDF and upload it to Slack.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lesson_data": {"type": "object", "description": "Structured lesson JSON."},
                    "channel": {"type": "string", "description": "Target Slack channel ID."},
                    "thread_ts": {"type": "string", "description": "Target Slack message thread timestamp."},
                },
                "required": ["lesson_data"],
            },
        },
    },
]


def _system_prompt(user_memory_context: str | None = None) -> str:
    """Build the system instruction with the current IST timestamp."""
    return format_instruction(INSTRUCTION, user_memory_context=user_memory_context)


def _is_transient_error(e: Exception) -> bool:
    """Return True if exception indicates a transient network or server error."""
    msg = str(e).lower()
    transient_indicators = [
        "503",
        "unavailable",
        "429",
        "rate limit",
        "resource_exhausted",
        "timeout",
        "deadline exceeded",
        "connection reset",
    ]
    return any(indicator in msg for indicator in transient_indicators)


async def _async_backoff(attempt: int, base: float = 0.8, cap: float = 3.0) -> None:
    """Sleep with exponential backoff and jitter."""
    delay = min(base * (2 ** attempt) + random.uniform(0.1, 0.4), cap)
    logger.info("Transient error detected. Backing off for %.2fs before retry...", delay)
    await asyncio.sleep(delay)


async def _execute_tool_call(name: str, args: dict[str, Any]) -> Any:
    """Execute a model-requested tool call on a worker thread and return result."""
    fn = _TOOL_MAP.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    params = inspect.signature(fn).parameters
    safe_args = {k: v for k, v in args.items() if k in params}
    try:
        return await asyncio.to_thread(fn, **safe_args)
    except Exception as e:
        logger.warning("Tool '%s' failed: %s", name, e)
        return {"status": "error", "error": str(e)}


def _build_nebius_content(content: types.Content) -> str | list[dict[str, Any]]:
    """Convert types.Content parts into OpenAI/Nebius text or multimodal content items."""
    parts = getattr(content, "parts", None) or []
    has_images = any(
        getattr(p, "inline_data", None)
        and getattr(p.inline_data, "data", None)
        and (getattr(p.inline_data, "mime_type", "") or "").lower() != "application/pdf"
        for p in parts
    )
    if not has_images:
        text_chunks: list[str] = []
        for p in parts:
            text = getattr(p, "text", None)
            if text:
                text_chunks.append(text)
                continue
            inline_data = getattr(p, "inline_data", None)
            if inline_data and getattr(inline_data, "data", None):
                mime = (getattr(inline_data, "mime_type", "") or "").lower()
                if mime == "application/pdf":
                    from chat_agent.utils.pdf_extractor import extract_pdf_markdown

                    pdf_text = extract_pdf_markdown(inline_data.data)
                    text_chunks.append(
                        f"\n\n[PDF content:\n{pdf_text}\n]"
                        if pdf_text
                        else "\n\n[Attached PDF: empty or unreadable]"
                    )
        return "\n".join(t for t in text_chunks if t).strip() or "Hello"

    items: list[dict[str, Any]] = []
    for p in parts:
        text = getattr(p, "text", None)
        if text:
            items.append({"type": "text", "text": text})
            continue
        inline_data = getattr(p, "inline_data", None)
        if inline_data and getattr(inline_data, "data", None):
            mime = (getattr(inline_data, "mime_type", "") or "image/jpeg").lower()
            if mime == "application/pdf":
                from chat_agent.utils.pdf_extractor import extract_pdf_markdown

                pdf_text = extract_pdf_markdown(inline_data.data)
                formatted = (
                    f"\n\n[PDF content:\n{pdf_text}\n]"
                    if pdf_text
                    else "\n\n[Attached PDF: empty or unreadable]"
                )
                items.append({"type": "text", "text": formatted})
            else:
                b64_str = base64.b64encode(inline_data.data).decode("utf-8")
                items.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64_str}"},
                })
    return items if items else "Hello"


def _build_history_user_entry(user_content: str | list[dict[str, Any]]) -> str:
    """Convert user content into a compact text placeholder for prior turn history."""
    if isinstance(user_content, str):
        return user_content
    text_chunks: list[str] = []
    for item in user_content:
        if item.get("type") == "text":
            text_chunks.append(item.get("text", ""))
        elif item.get("type") == "image_url":
            text_chunks.append("[Attached Image - processed in prior turn]")
    return " ".join(text_chunks).strip() or "[Multimodal content]"


def _append_nebius_history(session_id: str, user_content: str | list[dict[str, Any]], reply: str) -> None:
    """Store a successful turn in session history with pruned binary data."""
    history = _NEBIUS_HISTORY.setdefault(session_id, [])
    raw_user = _build_history_user_entry(user_content)
    clean_user = re.sub(r"^\[channel=[^\]]+\]\s*", "", raw_user).strip() or raw_user
    history.append({"role": "user", "content": clean_user})
    history.append({"role": "assistant", "content": reply})
    if len(history) > _HISTORY_CAP:
        del history[: len(history) - _HISTORY_CAP]


async def _get_nebius_history(session_id: str) -> list[dict[str, Any]]:
    """Retrieve prior conversation turns from Redis or in-memory fallback."""
    from chat_agent.services.redis_session_store import get_redis_session_store

    store = get_redis_session_store()
    turns = await store.get_history(session_id)
    if turns:
        return turns
    return list(_NEBIUS_HISTORY.get(session_id, []))


async def _save_nebius_history(session_id: str, user_content: str | list[dict[str, Any]], reply: str) -> None:
    """Persist turn to Redis and local memory."""
    _append_nebius_history(session_id, user_content, reply)
    from chat_agent.services.redis_session_store import get_redis_session_store

    store = get_redis_session_store()
    user_str = _build_history_user_entry(user_content)
    clean_text = re.sub(r"^\[channel=[^\]]+\]\s*", "", user_str).strip() or user_str
    await store.append_exchange(session_id, clean_text, reply, assistant_role="assistant")


_CLIENT_CACHE: dict[tuple[str, str], AsyncOpenAI] = {}


def _get_openai_client(api_key: str, base_url: str) -> AsyncOpenAI:
    """Return a cached AsyncOpenAI client per (api_key, base_url) to avoid per-turn TLS handshakes."""
    from openai import AsyncOpenAI

    cache_key = (api_key, base_url)
    if cache_key not in _CLIENT_CACHE:
        _CLIENT_CACHE[cache_key] = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=180.0)
    return _CLIENT_CACHE[cache_key]


async def _extract_image_content(
    multimodal_content: list[dict[str, Any]],
    api_key: str,
    base_url: str,
    vl_model: str,
) -> str:
    """One VL call to transcribe/describe image content without solving it; empty string on failure."""
    extraction_instruction = (
        "Transcribe all text visible in the image exactly, then describe any diagrams, figures, "
        "or layout factually. Do not solve, answer, or explain the content."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": extraction_instruction},
        {"role": "user", "content": multimodal_content},
    ]
    try:
        reply = await _call_nebius_completion(
            model=vl_model,
            messages=messages,
            api_key=api_key,
            base_url=base_url,
            enable_tools=False,
            max_tokens=1200,
        )
        return (reply or "").strip()
    except Exception as e:
        logger.warning("[Model Routing] VL extraction call failed: %s", e)
        return ""


async def _call_nebius_completion(
    model: str,
    messages: list[dict[str, Any]],
    api_key: str,
    base_url: str,
    session_id: str = "",
    enable_tools: bool = True,
    max_tokens: int | None = None,
) -> str:
    """Execute chat completion request with manual tool calling loop."""
    convo = list(messages)
    effective_max_tokens = max_tokens or settings.max_output_tokens
    try:
        client = _get_openai_client(api_key, base_url)
        for _ in range(_MAX_TOOL_ROUNDS):
            call_kwargs: dict[str, Any] = {
                "model": model,
                "messages": convo,  # type: ignore[arg-type]
                "max_tokens": effective_max_tokens,
                "temperature": 0.2,
            }
            if enable_tools:
                call_kwargs["tools"] = OPENAI_TOOLS  # type: ignore[assignment]
            try:
                resp = await client.chat.completions.create(**call_kwargs)
            except Exception as tool_err:
                if enable_tools:
                    logger.info("Nebius tool calling request failed (%s). Retrying without tools.", tool_err)
                    call_kwargs.pop("tools", None)
                    resp = await client.chat.completions.create(**call_kwargs)
                else:
                    raise
            usage = getattr(resp, "usage", None)
            if usage:
                logger.info(
                    "[Token Usage] Model: '%s' | Prompt: %d | Completion: %d | Total: %d tokens",
                    model,
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                    getattr(usage, "total_tokens", 0) or 0,
                )
                if session_id:
                    try:
                        from chat_agent.services.redis_research_store import record_session_token_usage

                        asyncio.create_task(
                            record_session_token_usage(
                                session_id=session_id,
                                model_name=model,
                                provider="Nebius",
                                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                            )
                        )
                    except Exception:
                        pass
            choice = resp.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                return (msg.content or "").strip()

            convo.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                fn_name = tc.function.name
                raw_args = tc.function.arguments
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
                except Exception:
                    args = {}
                result = await _execute_tool_call(fn_name, args)
                convo.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result) if not isinstance(result, str) else result,
                })
        return ""
    except (ImportError, ModuleNotFoundError):
        import httpx

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=180.0) as http_client:
            for _ in range(_MAX_TOOL_ROUNDS):
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": convo,
                    "max_tokens": effective_max_tokens,
                    "temperature": 0.2,
                }
                if enable_tools:
                    payload['tools'] = OPENAI_TOOLS
                resp = await http_client.post(url, json=payload, headers=headers)
                if resp.status_code == 400:
                    payload.pop("tools", None)
                    resp = await http_client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage") or {}
                if usage:
                    logger.info(
                        "[Token Usage] Model: '%s' (HTTPX) | Prompt: %d | Completion: %d | Total: %d tokens",
                        model,
                        usage.get("prompt_tokens", 0) or 0,
                        usage.get("completion_tokens", 0) or 0,
                        usage.get("total_tokens", 0) or 0,
                    )
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    return (msg.get("content") or "").strip()

                convo.append(msg)
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    raw_args = tc["function"].get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
                    except Exception:
                        args = {}
                    result = await _execute_tool_call(fn_name, args)
                    convo.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result) if not isinstance(result, str) else result,
                    })
            return ""


class NebiusModelRunner:
    """Model execution engine using Nebius OpenAI-compatible Vision API."""

    async def run(
        self,
        user_id: str,
        session_id: str,
        content: types.Content,
        user_memory_context: str | None = None,
        system_instruction: str | None = None,
        enable_tools: bool = True,
        max_tokens: int | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        """Execute chat request with Nano/VL routing, retries and fallback."""
        user_content = _build_nebius_content(content)

        api_key = getattr(settings, "NEBIUS_API_KEY", "") or os.getenv("NEBIUS_API_KEY", "")
        base_url = getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
        chat_model = getattr(settings, "NEBIUS_CHAT_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
        vl_model = getattr(settings, "NEBIUS_MODEL", "nvidia/Nemotron-3.5-Super-VL")

        if isinstance(user_content, list):
            logger.info("[Model Routing] Image turn: extracting image content with VL '%s'", vl_model)
            extraction = ""
            if api_key:
                extraction = await _extract_image_content(user_content, api_key, base_url, vl_model)
            if extraction:
                text_bits = [i.get("text", "") for i in user_content if i.get("type") == "text"]
                user_text = "\n".join(t for t in text_bits if t).strip() or "Explain the attached image."
                user_content = f"{user_text}\n\n[Image content: {extraction}]"
                model = chat_model
            else:
                logger.warning("[Model Routing] VL extraction failed; answering directly on VL '%s'", vl_model)
                model = vl_model
        else:
            logger.info("[Model Routing] Text turn: routing to chat model '%s'", chat_model)
            model = chat_model

        sys_content = system_instruction if system_instruction is not None else _system_prompt(user_memory_context)
        messages: list[dict[str, Any]] = [{"role": "system", "content": sys_content}]
        messages.extend(history if history is not None else await _get_nebius_history(session_id))
        messages.append({"role": "user", "content": user_content})

        if api_key:
            for attempt in range(3):
                logger.info(
                    "[Model Selection] Nebius Attempt %d/3: Sending request to model '%s'",
                    attempt + 1,
                    model,
                )
                try:
                    reply = await _call_nebius_completion(
                        model=model,
                        messages=messages,
                        api_key=api_key,
                        base_url=base_url,
                        session_id=session_id,
                        enable_tools=enable_tools,
                        max_tokens=max_tokens,
                    )
                    if reply:
                        logger.info("[Model Execution] ✅ Success response received from Nebius '%s'", model)
                        await _save_nebius_history(session_id, user_content, reply)
                        return reply
                except Exception as e:
                    logger.warning("[Model Execution] ⚠️ Nebius model '%s' failed (attempt %d/3): %s", model, attempt + 1, e)
                    if attempt < 2 and _is_transient_error(e):
                        await _async_backoff(attempt)

        # Fallback to OpenAI if Nebius fails or is unconfigured
        fallback_gpt = getattr(settings, "FALLBACK_GPT_MODEL", "gpt-6-luna")
        openai_key = getattr(settings, "openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
        if fallback_gpt and openai_key:
            logger.info("[Model Selection] Nebius failover: Falling back to FALLBACK_GPT_MODEL '%s'", fallback_gpt)
            try:
                reply = await _call_nebius_completion(
                    model=fallback_gpt,
                    messages=messages,
                    api_key=openai_key,
                    base_url="https://api.openai.com/v1",
                    session_id=session_id,
                    enable_tools=enable_tools,
                    max_tokens=max_tokens,
                )
                if reply:
                    await _save_nebius_history(session_id, user_content, reply)
                    return reply
            except Exception as fb_err:
                logger.error("[Model Execution] ❌ Fallback model %s failed: %s", fallback_gpt, fb_err)

        return "I did not produce a reply."
