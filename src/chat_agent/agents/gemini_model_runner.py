from __future__ import annotations

import asyncio
import inspect
import logging
import os
import random
from typing import Any

from google import genai
from google.genai import types

from chat_agent.agents.prompt import INSTRUCTION, format_instruction
from chat_agent.config import settings
from chat_agent.tools.tool_factory import (
    generate_infographic_pdf,
    generate_study_notes_pdf,
    get_current_time,
    search_web,
)

logger = logging.getLogger(__name__)

_genai_client: genai.Client | None = None
_HISTORY: dict[str, list[types.Content]] = {}
_HISTORY_CAP = 20
_MAX_TOOL_ROUNDS = 5

safety_settings = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
]

_TOOLS: list[Any] = [get_current_time, search_web, generate_study_notes_pdf, generate_infographic_pdf]
_TOOL_MAP: dict[str, Any] = {fn.__name__: fn for fn in _TOOLS}


def _get_genai_client() -> genai.Client:
    """Return a cached direct Google GenAI client."""
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.api_key)
    return _genai_client


def _system_prompt() -> str:
    """Build the system instruction with the current IST timestamp."""
    return format_instruction(INSTRUCTION)


def _prune_prior_binary_parts(session_id: str) -> None:
    """Replace raw binary parts in stored prior turns with text placeholders."""
    try:
        for content in _HISTORY.get(session_id, []):
            parts = getattr(content, "parts", None)
            if not parts:
                continue
            new_parts: list[types.Part] = []
            modified = False
            for part in parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data and getattr(inline_data, "data", None):
                    mime = getattr(inline_data, "mime_type", "attachment")
                    new_parts.append(types.Part.from_text(text=f"[Attachment: {mime} - processed in prior turn]"))
                    modified = True
                else:
                    new_parts.append(part)
            if modified:
                content.parts = new_parts
    except Exception as e:
        logger.warning("Failed to prune prior binary parts for session %s: %s", session_id, e)


def _append_history(session_id: str, user_content: types.Content, reply: str) -> None:
    """Store a successful exchange in the in-memory session history (bounded)."""
    history = _HISTORY.setdefault(session_id, [])
    history.append(user_content)
    history.append(types.Content(role="model", parts=[types.Part.from_text(text=reply)]))
    if len(history) > _HISTORY_CAP:
        del history[: len(history) - _HISTORY_CAP]


async def _execute_tool_call(function_call: Any) -> types.Part:
    """Execute a model-requested tool call on a worker thread and wrap the result."""
    fn = _TOOL_MAP.get(function_call.name)
    if fn is None:
        return types.Part.from_function_response(
            name=function_call.name,
            response={"error": f"Unknown tool: {function_call.name}"},
        )
    args = dict(function_call.args or {})
    params = inspect.signature(fn).parameters
    safe_args = {k: v for k, v in args.items() if k in params}
    try:
        result = await asyncio.to_thread(fn, **safe_args)
    except Exception as e:
        logger.warning("Tool '%s' failed: %s", function_call.name, e)
        result = {"status": "error", "error": str(e)}
    return types.Part.from_function_response(name=function_call.name, response={"result": result})


async def _call_gemini(model: str, contents: list[types.Content]) -> str:
    """Call Google GenAI directly with tool support (manual function-calling loop)."""
    client = _get_genai_client()
    config = types.GenerateContentConfig(
        system_instruction=_system_prompt(),
        temperature=0.2,
        max_output_tokens=settings.max_output_tokens,
        safety_settings=safety_settings,
        tools=_TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    convo = list(contents)
    for _ in range(_MAX_TOOL_ROUNDS):
        resp = await client.aio.models.generate_content(model=model, contents=convo, config=config)
        usage = getattr(resp, "usage_metadata", None)
        if usage:
            logger.info(
                "[Token Usage] Model: '%s' | Prompt: %d | Candidates: %d | Total: %d tokens",
                model,
                getattr(usage, "prompt_token_count", 0) or 0,
                getattr(usage, "candidates_token_count", 0) or 0,
                getattr(usage, "total_token_count", 0) or 0,
            )
        candidate = (resp.candidates or [None])[0]
        parts = list(getattr(getattr(candidate, "content", None), "parts", None) or [])
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        if not calls:
            return (resp.text or "").strip()
        convo.append(types.Content(role="model", parts=parts))
        responses = [await _execute_tool_call(fc) for fc in calls]
        convo.append(types.Content(role="user", parts=responses))
    return ""


def _is_transient_error(e: Exception) -> bool:
    """Return True if exception is a transient error (503, 429, timeouts, high demand)."""
    msg = str(e).lower()
    transient_indicators = [
        "503",
        "unavailable",
        "429",
        "resource_exhausted",
        "high demand",
        "spikes in demand",
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


async def _run_with_retry_and_fallback(
    user_id: str,
    session_id: str,
    content: types.Content,
) -> str:
    """Call a randomly selected FIRST_CHOICE_MODELS model up to 3 times, then fall back to FALLBACK_GPT_MODEL."""
    first_choice_models = getattr(settings, "FIRST_CHOICE_MODELS", []) or [settings.model]

    for attempt in range(3):
        chosen_model = random.choice(first_choice_models)
        logger.info(
            "[Model Selection] Phase 1 Attempt %d/3: Selected model '%s' from FIRST_CHOICE_MODELS",
            attempt + 1,
            chosen_model,
        )
        try:
            logger.info("[Model Execution] Sending request to Google GenAI model: %s", chosen_model)
            reply = await _call_gemini(chosen_model, list(_HISTORY.get(session_id, [])) + [content])
            if reply:
                logger.info("[Model Execution] ✅ Success response received from model '%s'", chosen_model)
                _append_history(session_id, content, reply)
                return reply
            logger.warning("[Model Execution] ⚠️ Empty response from model %s (attempt %d/3)", chosen_model, attempt + 1)
        except Exception as e:
            logger.warning("[Model Execution] ⚠️ Model '%s' failed (attempt %d/3): %s", chosen_model, attempt + 1, e)
            if attempt < 2 and _is_transient_error(e):
                await _async_backoff(attempt)

    fallback_gpt = getattr(settings, "FALLBACK_GPT_MODEL", "gpt-6-luna")
    if fallback_gpt:
        logger.info(
            "[Model Selection] Phase 2 Failover: All 3 primary attempts failed. Falling back to FALLBACK_GPT_MODEL: '%s'",
            fallback_gpt,
        )
        try:
            logger.info("[Model Execution] Sending request to OpenAI model: %s", fallback_gpt)

            user_text = "".join(
                getattr(p, "text", "") for p in (getattr(content, "parts", None) or [])
            ) or "Hello"

            openai_key = getattr(settings, "openai_api_key", "") or os.getenv("OPENAI_API_KEY", "")
            reply = ""
            try:
                from openai import AsyncOpenAI

                client = AsyncOpenAI(api_key=openai_key)
                try:
                    resp = await client.chat.completions.create(
                        model=fallback_gpt,
                        messages=[
                            {"role": "system", "content": _system_prompt()},
                            {"role": "user", "content": user_text},
                        ],
                        max_completion_tokens=settings.max_output_tokens,
                    )
                except Exception as e_tok:
                    logger.info(
                        "[Model Execution] OpenAI completion with max_completion_tokens failed (%s). Retrying with basic payload.",
                        e_tok,
                    )
                    resp = await client.chat.completions.create(
                        model=fallback_gpt,
                        messages=[
                            {"role": "system", "content": _system_prompt()},
                            {"role": "user", "content": user_text},
                        ],
                    )
                reply = (resp.choices[0].message.content or "").strip()
                usage = getattr(resp, "usage", None)
                if usage:
                    logger.info(
                        "[Token Usage] Model: '%s' (Fallback) | Prompt: %d | Completion: %d | Total: %d tokens",
                        fallback_gpt,
                        getattr(usage, "prompt_tokens", 0) or 0,
                        getattr(usage, "completion_tokens", 0) or 0,
                        getattr(usage, "total_tokens", 0) or 0,
                    )
            except (ImportError, ModuleNotFoundError) as e_pkg:
                logger.info(
                    "[Model Execution] OpenAI package not found (%s). Executing direct REST completion fallback.",
                    e_pkg,
                )
                import httpx

                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": fallback_gpt,
                    "messages": [
                        {"role": "system", "content": _system_prompt()},
                        {"role": "user", "content": user_text},
                    ],
                    "max_completion_tokens": settings.max_output_tokens,
                }
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    resp = await http_client.post(url, json=payload, headers=headers)
                    if resp.status_code == 400:
                        logger.info(
                            "[Model Execution] OpenAI REST completion returned 400. Retrying with minimal payload."
                        )
                        payload = {
                            "model": fallback_gpt,
                            "messages": [
                                {"role": "system", "content": _system_prompt()},
                                {"role": "user", "content": user_text},
                            ],
                        }
                        resp = await http_client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    usage = data.get("usage") or {}
                    if usage:
                        logger.info(
                            "[Token Usage] Model: '%s' (Fallback REST) | Prompt: %d | Completion: %d | Total: %d tokens",
                            fallback_gpt,
                            usage.get("prompt_tokens", 0) or 0,
                            usage.get("completion_tokens", 0) or 0,
                            usage.get("total_tokens", 0) or 0,
                        )
                    reply = (data["choices"][0]["message"]["content"] or "").strip()

            if reply:
                logger.info("[Model Execution] ✅ Success response received from fallback model '%s'", fallback_gpt)
                _append_history(session_id, content, reply)
                return reply
        except Exception as gpt_err:
            logger.error("[Model Execution] ❌ FALLBACK_GPT_MODEL %s failed: %s", fallback_gpt, gpt_err)

    return "I did not produce a reply."


class GeminiModelRunner:
    """Direct Google GenAI runner with 3x randomized attempts and OpenAI fallback."""

    async def run(
        self,
        user_id: str,
        session_id: str,
        content: types.Content,
    ) -> str:
        """Execute Gemini model with retries and fallback."""
        _prune_prior_binary_parts(session_id)
        return await _run_with_retry_and_fallback(
            user_id=user_id,
            session_id=session_id,
            content=content,
        )
