from __future__ import annotations

import json
import logging
from typing import Any

from chat_agent.communicate.config import get_communicate_config
from chat_agent.config import settings

logger = logging.getLogger(__name__)

COMMUNICATE_SYSTEM_PROMPT = """You are Aryhant's Administrative & Operations Reporter (Role 4).
You are replying via email to an authorized administrator.
Your objective is to analyze the provided operational telemetry and data retention metrics from Aryhant's session_tasks, and synthesize a clear, executive-ready operational audit report.

FORMAT CONSTRAINTS FOR EMAIL:
- Format the core metrics in a clean Markdown Data Table.
- Accurately report:
  * Executive Verdict & Operational Status (HEALTHY / ATTENTION REQUIRED)
  * Data Retention & Pruning (>15d DB records, >30d Slack files)
  * 7-Day Task Volume & Status Breakdown (Completed, In-Progress, Failed)
  * Task Type Distribution (Chat, Research, Admin)
  * Execution Latency (Average ms)
  * Token Consumption (Prompt, Completion, Total)
  * Failure Diagnostics (Root cause analysis or '0 failures recorded in 7 days')
  * Actionable Recommendations (1-2 bullet points)
- If the conversation was already concluded or requires no response, output exactly: NO_REPLY
"""


async def _call_gemini(model: str, prompt: str, api_key: str) -> str:
    """Call Google GenAI for reply generation."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=COMMUNICATE_SYSTEM_PROMPT,
            temperature=0.1,
        ),
    )
    return (response.text or "").strip()


async def _call_nebius_or_openai(
    model: str,
    prompt: str,
    api_key: str,
    base_url: str = "https://api.tokenfactory.nebius.com/v1",
) -> str:
    """Call Nebius or OpenAI-compatible endpoint."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": COMMUNICATE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    return (resp.choices[0].message.content or "").strip()


async def generate_communicate_reply(
    subject: str,
    email_text: str,
    telemetry_payload: dict[str, Any],
) -> str:
    """Generate an administrative audit response using configured model with provider-aware fallback."""
    config = get_communicate_config()
    telemetry_json = json.dumps(telemetry_payload, indent=2)

    prompt = (
        f"Subject: {subject}\n"
        f"Inbound Email:\n{email_text}\n\n"
        f"Operational Telemetry & Retention Audit:\n```json\n{telemetry_json}\n```\n\n"
        "Please provide the administrative operations audit report for email dispatch:"
    )

    primary_model = config.model
    fallback_model = config.fallback_model
    provider = config.provider

    # 1. Try Primary Model
    try:
        logger.info("[Communicate LLM] Executing primary model '%s' (%s)", primary_model, provider)
        if provider == "nebius":
            nebius_key = getattr(settings, "NEBIUS_API_KEY", "")
            base_url = getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
            reply = await _call_nebius_or_openai(primary_model, prompt, nebius_key, base_url)
        else:
            api_key = settings.api_key
            reply = await _call_gemini(primary_model, prompt, api_key)

        if reply:
            return reply
    except Exception as exc:
        logger.warning(
            "[Communicate LLM] Primary model '%s' failed: %s. Retrying with fallback '%s'",
            primary_model,
            exc,
            fallback_model,
        )

    # 2. Try Fallback Model (provider-aware routing)
    try:
        logger.info("[Communicate LLM] Executing fallback model '%s'", fallback_model)
        if "gemini" in fallback_model.lower():
            api_key = settings.api_key
            reply = await _call_gemini(fallback_model, prompt, api_key)
        elif fallback_model.lower().startswith("gpt-"):
            openai_key = getattr(settings, "openai_api_key", "")
            if openai_key:
                reply = await _call_nebius_or_openai(fallback_model, prompt, openai_key, "https://api.openai.com/v1")
            else:
                logger.info("[Communicate LLM] openai_api_key missing for '%s'. Failing over to Gemini fallback.", fallback_model)
                reply = await _call_gemini("gemini-flash-lite-latest", prompt, settings.api_key)
        else:
            nebius_key = getattr(settings, "NEBIUS_API_KEY", "")
            base_url = getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
            reply = await _call_nebius_or_openai(fallback_model, prompt, nebius_key, base_url)

        if reply:
            return reply
    except Exception as fb_exc:
        logger.error("[Communicate LLM] Fallback model '%s' failed: %s", fallback_model, fb_exc)

    # Deterministic fallback summary if external models are unreachable
    failures = telemetry_payload.get("failure_count", 0)
    deleted_count = telemetry_payload.get("deleted_records_count", 0)
    verdict = "HEALTHY" if failures == 0 else f"ATTENTION REQUIRED ({failures} failures)"
    return (
        "# ✅ Administrative & Operations Audit\n\n"
        "| Metric Category | Operational Telemetry & Health Data |\n"
        "| :--- | :--- |\n"
        f"| **System Verdict** | {verdict} |\n"
        f"| **Data Retention** | {deleted_count} DB records pruned (>15d) |\n"
        "| **Operational Telemetry** | Active window: 7 days |\n"
        f"| **Failure Diagnostics** | {failures} failure(s) recorded in 7 days |\n"
        "| **Recommendations** | System operating nominally; continue regular automated pruning audits. |\n"
    )
