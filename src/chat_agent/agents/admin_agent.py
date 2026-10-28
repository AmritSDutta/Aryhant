"""Dedicated Administrative Agent (Role 4) for system telemetry audits, retention pruning, and failure debugging."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from typing import Any

from chat_agent.config import settings
from chat_agent.services.session_task_service import get_session_task_service
from chat_agent.tools.context7_tool import search_context7
from chat_agent.tools.tool_factory import search_web

logger = logging.getLogger(__name__)

NEBIUS_ADMIN_MODEL: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
GEMINI_ADMIN_MODEL: str = "gemini-flash-lite-latest"

ADMIN_SYSTEM_PROMPT = """You are Aryhant's Administrative & Operations Auditor (Role 4).
Your objective is to inspect operational telemetry from the session_tasks table, audit data retention pruning,
analyze recent task failures using Context7/WebSearch if needed, and synthesize a complete, unified operational audit.

FORMAT CONSTRAINTS:
- Begin with a single header: "# ✅ Administrative & Operations Audit"
- Summarize the entire audit inside a SINGLE Markdown Data Table rather than separate prose sections.
- Accurately report all telemetry metrics without omission:
  * Executive Verdict & Operational Status (HEALTHY / ATTENTION REQUIRED)
  * Data Retention & Pruning (Records purged older than 15 days, Slack files purged older than 30 days)
  * 7-Day Task Volume & Status Breakdown (Total tasks, completed, in-progress, created, failed)
  * Task Type Distribution (Chat, Research, Admin)
  * Execution Latency (Average duration in ms)
  * Token Economics (Prompt, completion, and total tokens consumed)
  * Diagnostics & Root Cause (Analysis of failures via Context7/WebSearch if any, or confirmation of 0 failures)
  * Actionable Recommendations (1-2 concise operational suggestions)

Mandatory Table Format:
# ✅ Administrative & Operations Audit

| Metric Category | Operational Telemetry & Health Data |
| :--- | :--- |
| **System Verdict** | [HEALTHY / ATTENTION REQUIRED] - [One-line summary] |
| **Data Retention** | [X] records pruned (>15 days), [Y] Slack files pruned (>30 days) |
| **Task Volume & Status** | Total: [N] (Completed: [C], In-Progress: [P], Failed: [F]) |
| **Task Type Distribution** | [Type breakdown, e.g. Chat: X, Research: Y, Admin: Z] |
| **Execution Latency** | Average: [X] ms |
| **Token Consumption** | Prompt: [P], Completion: [C], Total: [T] |
| **Failure Diagnostics** | [Failure analysis or '0 failures recorded in 7 days'] |
| **Recommendations** | [1-2 concise actionable suggestions] |
"""

# Private tools schema for OpenAI-compatible Nebius execution
ADMIN_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_context7",
            "description": "Search Context7 for official library documentation, error patterns, and framework usage to diagnose failures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Technical error or topic query (e.g. 'httpx connection timeout')",
                    },
                    "library": {
                        "type": "string",
                        "description": "Optional library name filter",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for upstream outages, rate limits, GitHub issues, or operational fixes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The web search query",
                    }
                },
                "required": ["query"],
            },
        },
    },
]

ADMIN_TOOLS_OPENAI = ADMIN_TOOLS  # Backward compatibility alias


async def prune_slack_files_older_than(days: int = 30) -> int:
    """Delete Slack files uploaded by the bot older than `days` using Slack API."""
    token = getattr(settings, "aryhant_slack_bot_token", "") or getattr(settings, "ARYHANT_SLACK_BOT_TOKEN", "")
    if not token:
        logger.info("[Slack Pruner] Skipped Slack file pruning: bot token not configured.")
        return 0
    logger.info('Started pruning slack deposited old files')
    cutoff_ts = int(time.time() - (days * 86400))
    deleted_count = 0
    try:
        import httpx

        async with httpx.AsyncClient(timeout=25.0) as client:
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get(
                "https://slack.com/api/files.list",
                headers=headers,
                params={"ts_to": cutoff_ts, "count": 100},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning("[Slack Pruner] files.list failed: %s", data.get("error"))
                return 0

            files = data.get("files") or []
            for f in files:
                fid = f.get("id")
                if not fid:
                    continue
                del_resp = await client.post(
                    "https://slack.com/api/files.delete",
                    headers=headers,
                    data={"file": fid},
                )
                del_data = del_resp.json()
                if del_data.get("ok"):
                    deleted_count += 1
                else:
                    logger.debug("[Slack Pruner] Failed to delete file %s: %s", fid, del_data.get("error"))

            if deleted_count > 0:
                logger.info("[Slack Pruner] Pruned %d Slack files older than %d days.", deleted_count, days)
    except Exception as exc:
        logger.warning("[Slack Pruner] Error pruning old Slack files: %s", exc)

    return deleted_count


def _sanitize_error_signature(raw_error: str | None) -> str:
    """Scrub sensitive paths, URLs, emails, and identifiers from error messages."""
    if not raw_error:
        return ""
    text = str(raw_error).strip()
    # Redact absolute paths (Windows & Unix)
    text = re.sub(r"[A-Za-z]:\\[^\s:;'\",)]+", "[path]", text)
    text = re.sub(r"/(?:[^\s:;'\",)]+/)+[^\s:;'\",)]*", "[path]", text)
    # Redact URLs & emails
    text = re.sub(r"https?://\S+", "[url]", text)
    text = re.sub(r"[\w\.-]+@[\w\.-]+", "[email]", text)
    # Redact long hex tokens & UUIDs
    text = re.sub(r"\b[0-9a-fA-F-]{16,}\b", "[id]", text)

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0][:120].strip()

    last_line = lines[-1]
    has_path = any("[path]" in l for l in lines)
    if has_path and "[path]" not in last_line:
        last_line = f"{last_line} (at [path])"

    return last_line[:120].strip()


async def _dispatch_admin_tool(fn_name: str, args: dict[str, Any]) -> str:
    """Execute private admin tool call with sanitized queries."""
    if fn_name == "search_context7":
        query = _sanitize_error_signature(args.get("query", ""))
        library = args.get("library")
        try:
            res = await search_context7(query=query, library=library)
            snippets = res.get("code_snippets") or []
            if snippets:
                return f"Context7 documentation found: {snippets[0].get('title', '')}\n{snippets[0].get('code', '')[:300]}"
            return "No matching documentation found in Context7."
        except Exception as e:
            return f"Context7 search error: {e}"

    elif fn_name == "search_web":
        query = _sanitize_error_signature(args.get("query", ""))
        try:
            res = await asyncio.to_thread(search_web, query)
            if isinstance(res, dict) and res.get("results"):
                top = res["results"][:2]
                summaries = [f"- {r.get('title', '')}: {r.get('url', '')}" for r in top]
                return "WebSearch findings:\n" + "\n".join(summaries)
            return "No relevant web search results found."
        except Exception as e:
            return f"WebSearch error: {e}"

    return f"Unknown tool: {fn_name}"


class AdminAgent:
    """Administrative and operations agent for telemetry auditing and retention management."""

    def __init__(self) -> None:
        self.task_service = get_session_task_service()

    async def _execute_nebius_report(
        self,
        messages: list[dict[str, Any]],
        model: str = NEBIUS_ADMIN_MODEL,
    ) -> tuple[str, dict[str, int]]:
        """Call Nebius TokenFactory API with Nemotron-3-Nano-30B and tool dispatch loop."""
        api_key = getattr(settings, "NEBIUS_API_KEY", "") or os.getenv("NEBIUS_API_KEY", "")
        base_url = getattr(settings, "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")

        if not api_key:
            logger.warning("NEBIUS_API_KEY not configured for AdminAgent. Generating fallback report.")
            return self._build_deterministic_report(messages), {"prompt": 0, "completion": 0, "total": 0}

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            convo = list(messages)
            tot_prompt = 0
            tot_completion = 0
            tot_tokens = 0

            for _ in range(5):
                resp = await client.chat.completions.create(
                    model=model,
                    messages=convo,  # type: ignore[arg-type]
                    tools=ADMIN_TOOLS,  # type: ignore[arg-type]
                    temperature=0.2,
                    max_tokens=2048,
                )
                usage = getattr(resp, "usage", None)
                if usage:
                    tot_prompt += getattr(usage, "prompt_tokens", 0) or 0
                    tot_completion += getattr(usage, "completion_tokens", 0) or 0
                    tot_tokens += getattr(usage, "total_tokens", 0) or 0

                msg = resp.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None)
                if not tool_calls:
                    tokens = {"prompt": tot_prompt, "completion": tot_completion, "total": tot_tokens}
                    return (msg.content or "").strip(), tokens

                convo.append(msg.model_dump())
                for tc in tool_calls:
                    fn_name = tc.function.name
                    try:
                        raw_args = tc.function.arguments
                        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
                    except Exception:
                        args = {}
                    tool_output = await _dispatch_admin_tool(fn_name, args)
                    convo.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output,
                    })

            tokens = {"prompt": tot_prompt, "completion": tot_completion, "total": tot_tokens}
            return (convo[-1].get("content") or "").strip(), tokens
        except Exception as exc:
            logger.warning("Nebius AdminAgent call failed (%s); using direct synthesis.", exc)
            return self._build_deterministic_report(messages), {"prompt": 0, "completion": 0, "total": 0}

    async def _execute_gemini_report(
        self,
        user_prompt: str,
        model: str = GEMINI_ADMIN_MODEL,
    ) -> tuple[str, dict[str, int]]:
        """Call Google GenAI with gemini-flash-lite-latest and tool dispatch loop."""
        from google import genai
        from google.genai import types

        api_key = getattr(settings, "api_key", "")
        if not api_key:
            logger.warning("Google GenAI api_key unconfigured for AdminAgent. Generating fallback report.")
            return self._build_deterministic_report([{"content": user_prompt}]), {"prompt": 0, "completion": 0, "total": 0}

        try:
            client = genai.Client(api_key=api_key)

            async def search_context7_tool(query: str, library: str | None = None) -> str:
                return await _dispatch_admin_tool("search_context7", {"query": query, "library": library})

            def search_web_tool(query: str) -> str:
                return asyncio.run(_dispatch_admin_tool("search_web", {"query": query}))

            config = types.GenerateContentConfig(
                system_instruction=ADMIN_SYSTEM_PROMPT,
                temperature=0.2,
                tools=[search_context7_tool, search_web_tool],
            )

            tot_prompt = 0
            tot_comp = 0
            tot_all = 0
            convo: list[types.Content] = [types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)])]

            for _ in range(5):
                resp = await client.aio.models.generate_content(
                    model=model,
                    contents=convo,
                    config=config,
                )
                usage = getattr(resp, "usage_metadata", None)
                if usage:
                    tot_prompt += getattr(usage, "prompt_token_count", 0) or 0
                    tot_comp += getattr(usage, "candidates_token_count", 0) or 0
                    tot_all += getattr(usage, "total_token_count", 0) or 0

                candidate = (resp.candidates or [None])[0]
                parts = list(getattr(getattr(candidate, "content", None), "parts", None) or [])
                calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
                if not calls:
                    tokens = {"prompt": tot_prompt, "completion": tot_comp, "total": tot_all}
                    return (resp.text or "").strip(), tokens

                convo.append(types.Content(role="model", parts=parts))
                tool_responses = []
                for fc in calls:
                    fn_name = fc.name
                    args = dict(fc.args or {})
                    res_text = await _dispatch_admin_tool(fn_name, args)
                    tool_responses.append(
                        types.Part.from_function_response(
                            name=fn_name,
                            response={"result": res_text},
                        )
                    )
                convo.append(types.Content(role="user", parts=tool_responses))

            tokens = {"prompt": tot_prompt, "completion": tot_comp, "total": tot_all}
            return (resp.text or "").strip(), tokens
        except Exception as exc:
            logger.warning("Gemini AdminAgent call failed (%s); using direct synthesis.", exc)
            return self._build_deterministic_report([{"content": user_prompt}]), {"prompt": 0, "completion": 0, "total": 0}

    def _build_deterministic_report(
        self,
        messages: list[dict[str, str]],
        failure_count: int | None = None,
        deleted_count: int = 0,
        deleted_slack_files: int = 0,
    ) -> str:
        """Construct fallback report if external LLM completion fails or is offline."""
        prompt_text = "\n".join(m.get("content", "") for m in messages if m.get("role") != "system")
        failures = 0
        if failure_count is not None:
            failures = failure_count
        else:
            try:
                match = re.search(r'"failure_count":\s*(\d+)', prompt_text)
                if match:
                    failures = int(match.group(1))
            except Exception:
                failures = 0

        status_str = f"ATTENTION REQUIRED - {failures} failures detected" if failures > 0 else "HEALTHY - All telemetry metrics within nominal bounds"
        return (
            "# ✅ Administrative & Operations Audit\n\n"
            "| Metric Category | Operational Telemetry & Health Data |\n"
            "| :--- | :--- |\n"
            f"| **System Verdict** | {status_str} |\n"
            f"| **Data Retention** | {deleted_count} DB records pruned (>15d), {deleted_slack_files} Slack files pruned (>30d) |\n"
            f"| **Operational Telemetry** | Active window: 7 days |\n"
            f"| **Failure Diagnostics** | {failures} failure(s) recorded |\n"
            "| **Recommendations** | System operating nominally; continue regular automated pruning audits |\n"
        )

    async def run_maintenance(
        self,
        days: int = 7,
        prune_days: int = 15,
        provider: str | None = None,
        user_id: str = "admin",
    ) -> dict[str, Any]:
        """Execute full administrative maintenance cycle: prune >15-day records, prune >30-day Slack files, read 7-day metrics, and investigate failures."""
        job_id = f"admin_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        start_ts = time.monotonic()
        active_provider = (provider or getattr(settings, "MODEL_PROVIDER", "nebius")).lower()
        active_model = NEBIUS_ADMIN_MODEL if active_provider == "nebius" else GEMINI_ADMIN_MODEL

        # Step 1: Record admin task start in session_tasks
        await self.task_service.acreate_task(
            task_id=job_id,
            session_id=job_id,
            user_id=user_id,
            task_type="admin",
            provider=active_provider,
            status="in_progress",
        )

        try:
            # Step 2: Deterministic retention pruning (15-day DB, 30-day Slack files)
            deleted_count = await self.task_service.adelete_records_older_than(days=prune_days)
            deleted_slack_files = await prune_slack_files_older_than(days=30)

            # Step 3: Deterministic 7-day telemetry & recent failures
            metrics_7d = await self.task_service.aget_table_metrics(days=days)
            failed_tasks = await self.task_service.aget_failed_tasks(limit=5, days=days)

            # Step 4: Sanitize failure records (no session_id, user_id, or raw ID)
            sanitized_recent_failures = [
                {
                    "task_type": ft.get("task_type"),
                    "provider": ft.get("provider"),
                    "model_name": ft.get("model_name"),
                    "error_summary": _sanitize_error_signature(ft.get("error_message")),
                    "duration_ms": ft.get("duration_ms"),
                }
                for ft in failed_tasks
            ]

            telemetry_payload = {
                "telemetry_window_days": days,
                "retention_prune_days": prune_days,
                "deleted_records_count": deleted_count,
                "deleted_slack_files_count": deleted_slack_files,
                "current_active_tasks": metrics_7d.get("total_tasks", 0),
                "status_breakdown": metrics_7d.get("status_breakdown", {}),
                "task_type_breakdown": metrics_7d.get("task_type_breakdown", {}),
                "token_economics": {
                    "prompt_tokens": metrics_7d.get("prompt_tokens_sum", 0),
                    "completion_tokens": metrics_7d.get("completion_tokens_sum", 0),
                    "total_tokens": metrics_7d.get("total_tokens_sum", 0),
                },
                "avg_duration_ms": metrics_7d.get("avg_duration_ms", 0.0),
                "failure_count": metrics_7d.get("failure_count", 0),
                "recent_failures": sanitized_recent_failures,
            }

            user_prompt = (
                f"Operational Telemetry & Retention Audit for session_tasks:\n"
                f"```json\n{json.dumps(telemetry_payload, indent=2)}\n```\n\n"
                "You have access to ADMIN_TOOLS (`search_context7` and `search_web`). "
                "If there are any recent failures or anomalies, use these tools to investigate root causes. "
                "Synthesize the complete audit into the mandatory SINGLE Markdown Data Table format starting with '# ✅ Administrative & Operations Audit'. "
                "Report all metrics accurately without omitting any telemetry figures."
            )

            # Step 5: Model execution with tool dispatch
            logger.info(
                "Invoking %s model (%s) for admin telemetry report synthesis (job_id=%s)",
                active_provider,
                active_model,
                job_id,
            )
            if active_provider == "gemini":
                report, tokens = await self._execute_gemini_report(user_prompt=user_prompt, model=active_model)
            else:
                messages = [
                    {"role": "system", "content": ADMIN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ]
                report, tokens = await self._execute_nebius_report(messages=messages, model=active_model)

            duration_ms = int((time.monotonic() - start_ts) * 1000)

            # Step 6: Complete admin task record in session_tasks
            await self.task_service.acomplete_task(
                task_id=job_id,
                status="completed",
                prompt_tokens=tokens["prompt"],
                completion_tokens=tokens["completion"],
                total_tokens=tokens["total"],
                duration_ms=duration_ms,
                model_name=active_model,
                metadata={
                    "deleted_count": deleted_count,
                    "deleted_slack_files": deleted_slack_files,
                    "retention_days": prune_days,
                    "telemetry_days": days,
                    "provider": active_provider,
                },
            )

            logger.info(
                "✅ Admin maintenance job %s completed successfully in %d ms (model=%s, tokens: prompt=%d completion=%d total=%d, pruned %d DB records, pruned %d Slack files, status=success)",
                job_id,
                duration_ms,
                active_model,
                tokens.get("prompt", 0),
                tokens.get("completion", 0),
                tokens.get("total", 0),
                deleted_count,
                deleted_slack_files,
            )

            return {
                "status": "success",
                "job_id": job_id,
                "report": report,
                "deleted_count": deleted_count,
                "deleted_slack_files": deleted_slack_files,
                "metrics": metrics_7d,
                "duration_ms": duration_ms,
            }

        except Exception as exc:
            duration_ms = int((time.monotonic() - start_ts) * 1000)
            logger.error("Admin maintenance failed for job %s: %s", job_id, exc, exc_info=True)
            try:
                await self.task_service.acomplete_task(
                    task_id=job_id,
                    status="failed",
                    duration_ms=duration_ms,
                    error_message=str(exc),
                )
            except Exception as complete_err:
                logger.warning("Failed to record admin task failure in registry: %s", complete_err)
            return {
                "status": "error",
                "job_id": job_id,
                "error": str(exc),
                "report": f"⚠️ Administrative maintenance failed: {exc}",
                "deleted_count": 0,
                "deleted_slack_files": 0,
            }


_admin_singleton: AdminAgent | None = None


def get_admin_agent() -> AdminAgent:
    """Return singleton AdminAgent instance."""
    global _admin_singleton
    if _admin_singleton is None:
        _admin_singleton = AdminAgent()
    return _admin_singleton
