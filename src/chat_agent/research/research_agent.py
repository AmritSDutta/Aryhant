from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.genai import types

from chat_agent.agents.model_runner import get_model_runner
from chat_agent.config import settings
from chat_agent.infographics.notes_builder import get_reports_dir
from chat_agent.research.dispatcher import release_user_job_slot
from chat_agent.research.engine import gather_research_intelligence, generate_subqueries
from chat_agent.research.models import (
    ModelUsage,
    ResearchJobState,
    ResearchMode,
    TaskStatus,
    TokenEconomics,
)
from chat_agent.research.pdf_builder import build_research_pdf
from chat_agent.research.todo_tracker import initialize_default_todos, render_slack_todo_board
from chat_agent.services.redis_research_store import get_research_store
from chat_agent.tools.tool_factory import _upload_file_to_slack_sync
from chat_agent.utils.multimodal import build_adk_multimodal_content

logger = logging.getLogger(__name__)

TECHNICAL_SYSTEM_PROMPT = """You are a Principal Systems Architect and Senior Research Scientist.
Your objective is to produce a rigorous, publication-grade technical whitepaper (~2,500 words) on the requested topic.
This is getting executed as of: {current_date}.

Mandatory Structure & Word Quotas (Aim for ~2,500 words total):
1. Executive Summary & Problem Scope (~300 words)
2. Architectural & Foundational Mechanics (~600 words)
3. Concrete Implementation & Verified Code Patterns (~600 words) - Incorporate provided Context7 code and Nebius sandbox execution results.
4. Failure Modes, Edge Cases & Bottlenecks (~450 words)
5. Quantitative Benchmarks & Trade-offs (~350 words)
6. Production Best Practices & References (~200 words)

Guidelines:
- Ground your analysis in the provided Google AI Overview, Tavily Mini-Research, and verified Context7 code snippets.
- If visual evidence or diagrams are provided, explicitly analyze their architectural components.
- Output clean Markdown with headers (#, ##, ###), tables, and syntax-highlighted code blocks.
"""

DELIBERATION_SYSTEM_PROMPT = """You are an expert Strategic Consumer Advisor, Financial Evaluator, and Decision Analyst.
Your objective is to produce a practical, authoritative, multi-perspective Decision & Buying Guide (~1,500 words) for the user's query.
This is getting executed as of: {current_date}.

Mandatory Structure & Word Quotas (Aim for ~1,500 words total):
1. Executive Verdict & Bottom-Line Recommendation (~250 words)
2. Evaluation Criteria & Comparison Matrix Table (~350 words) - Include a Markdown table comparing top 3-4 contenders on Price, Quality, Value, and Risk.
3. Detailed Contender Breakdown (~500 words) - Deep dive into top choices with Pros, Cons, and True Costs.
4. Hidden Catches, Fine Print & Pitfalls (~250 words) - Address marketing traps, policy fine print, volatility, or ingredients.
5. Action Plan & Step-by-Step Buying Guide (~150 words) - Concrete decision checklist.

Guidelines:
- Ground recommendations in the provided Google AI Overview and Tavily Mini-Research intelligence.
- If product images or price charts are provided, reference their details.
- Output clean Markdown with tables, bullet lists, and clear bold headings.
"""


async def compute_job_token_economics(
    job_id: str,
    raw_report: str = "",
    prompt_text: str = "",
    has_visual: bool = False,
    mode: ResearchMode = ResearchMode.TECHNICAL,
    visual_notes: str = "",
) -> TokenEconomics:
    """Extract real LLM token counts from response metadata stored in Redis for the session."""
    from chat_agent.services.redis_research_store import get_session_token_usage

    models: list[ModelUsage] = []

    # 1. Vision Stage
    if has_visual:
        v_usage = await get_session_token_usage(f"vision-{job_id}")
        if v_usage:
            m_name = str(v_usage.get("model_name", "gemini-2.5-flash"))
            prov = str(v_usage.get("provider", "Google GenAI"))
            p_tok = int(v_usage.get("prompt_tokens", 0))
            c_tok = int(v_usage.get("completion_tokens", 0))
            t_tok = int(v_usage.get("total_tokens", p_tok + c_tok))
            cost = round((p_tok * 0.000000075) + (c_tok * 0.00000030), 6)
            models.append(
                ModelUsage(
                    model_name=m_name,
                    provider=prov,
                    role="Multimodal Vision Analysis",
                    input_tokens=p_tok,
                    output_tokens=c_tok,
                    total_tokens=t_tok,
                    estimated_cost_usd=cost,
                    is_estimated=False,
                )
            )

    # 2. Synthesis Stage
    s_usage = await get_session_token_usage(f"synth-{job_id}")
    if s_usage:
        m_name = str(s_usage.get("model_name", "gemini-2.5-pro"))
        prov = str(s_usage.get("provider", "Google GenAI"))
        p_tok = int(s_usage.get("prompt_tokens", 0))
        c_tok = int(s_usage.get("completion_tokens", 0))
        t_tok = int(s_usage.get("total_tokens", p_tok + c_tok))
        if "flash" in m_name.lower():
            rate_in, rate_out = 0.000000075, 0.00000030
        elif "nebius" in prov.lower() or "llama" in m_name.lower():
            rate_in, rate_out = 0.00000013, 0.00000040
        else:
            rate_in, rate_out = 0.00000125, 0.00000500
        cost = round((p_tok * rate_in) + (c_tok * rate_out), 6)
        models.append(
            ModelUsage(
                model_name=m_name,
                provider=prov,
                role="Long-Form Publication Synthesis",
                input_tokens=p_tok,
                output_tokens=c_tok,
                total_tokens=t_tok,
                estimated_cost_usd=cost,
                is_estimated=False,
            )
        )

    if not models:
        return TokenEconomics(models_used=[], is_estimated=True)

    tot_in = sum(m.input_tokens for m in models)
    tot_out = sum(m.output_tokens for m in models)
    tot_all = sum(m.total_tokens for m in models)
    tot_cost = round(sum(m.estimated_cost_usd for m in models), 4)

    return TokenEconomics(
        models_used=models,
        total_input_tokens=tot_in,
        total_output_tokens=tot_out,
        total_tokens=tot_all,
        total_estimated_cost_usd=tot_cost,
        is_estimated=False,
    )


class DualResearchAgent:
    """Orchestrates technical research (/research) and deliberation (/deliberate) workflows."""

    def __init__(self) -> None:
        self.store = get_research_store()

    async def _inspect_visual_attachments(
        self,
        topic: str,
        attachments: list[tuple[bytes, str]],
        session_id: str = "",
    ) -> str:
        """Inspect attached images/diagrams using vision model and extract architectural context."""
        valid_images = [a for a in attachments if a[1].startswith("image/")]
        if not valid_images:
            return ""

        prompt = (
            f"Analyze the attached visual evidence for the topic '{topic}'. "
            "Transcribe all visible architecture components, data flows, labels, numbers, and system interfaces. "
            "Provide a dense, factual 2-3 paragraph summary of what the diagram or image shows."
        )
        content = build_adk_multimodal_content(prompt, valid_images)
        runner = get_model_runner()
        try:
            return await runner.run(
                user_id="research-vision",
                session_id=session_id or f"vision-{int(time.time())}",
                content=content,
                system_instruction="You are an expert visual technical diagram and system architecture inspector. Transcribe all visible architecture components, data flows, labels, numbers, and system interfaces. Provide a dense, factual summary.",
                enable_tools=False,
            )
        except Exception as exc:
            logger.warning("Visual attachment inspection failed: %s", exc)
            return "Visual diagram inspection was attempted but failed to parse."

    async def execute_job(
        self,
        job_id: str,
        command: str,
        topic: str,
        channel_id: str,
        thread_ts: str,
        user_id: str,
        attachments: list[tuple[bytes, str]],
        client: Any,
    ) -> None:
        """Run the complete research or deliberation pipeline."""
        is_tech = command == "/research"
        mode = ResearchMode.TECHNICAL if is_tech else ResearchMode.DELIBERATE
        target_words = 2500 if is_tech else 1500

        job = ResearchJobState(
            job_id=job_id,
            command="/research" if is_tech else "/deliberate",
            topic=topic,
            mode=mode,
            target_word_count=target_words,
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            status=TaskStatus.IN_PROGRESS,
            todos=initialize_default_todos(mode),
            queries=generate_subqueries(topic, mode),
            created_at=time.time(),
        )

        status_msg_ts = ""
        try:
            blocks = render_slack_todo_board(job)
            post_kwargs: dict[str, Any] = {
                "channel": channel_id,
                "text": f"Started {command} for `{topic}`",
                "blocks": blocks,
            }
            if thread_ts:
                post_kwargs["thread_ts"] = thread_ts
            resp = await client.chat_postMessage(**post_kwargs)
            status_msg_ts = resp.get("ts") or ""
            job.status_msg_ts = status_msg_ts
        except Exception as post_err:
            logger.warning("Failed to post initial Slack status board: %s", post_err)

        await self.store.save_job(job)

        async def _update_slack(task_id: str, status: TaskStatus, details: str = "") -> None:
            updated_job = await self.store.update_todo_status(job_id, task_id, status, details, existing_job=job)
            display_job = updated_job or job
            if client and channel_id and status_msg_ts:
                try:
                    await client.chat_update(
                        channel=channel_id,
                        ts=status_msg_ts,
                        text=f"Progress update for {command}",
                        blocks=render_slack_todo_board(display_job),
                    )
                except Exception as update_err:
                    logger.debug("Slack chat_update notice: %s", update_err)

        try:
            # Milestone 1: Visual Inspection & Planning
            await _update_slack("plan", TaskStatus.IN_PROGRESS, "Inspecting visual evidence & planning")
            visual_notes = ""
            saved_image_paths: list[str] = []

            valid_images = [a for a in attachments if a[1].startswith("image/")]
            if valid_images:
                visual_notes = await self._inspect_visual_attachments(
                    topic,
                    valid_images,
                    session_id=f"vision-{job_id}",
                )
                assets_dir = get_reports_dir() / "assets"
                assets_dir.mkdir(parents=True, exist_ok=True)
                for i, (b_data, mime) in enumerate(valid_images):
                    ext = "png" if "png" in mime else "jpg"
                    img_file = assets_dir / f"{job_id}_img_{i}.{ext}"
                    await asyncio.to_thread(img_file.write_bytes, b_data)
                    saved_image_paths.append(str(img_file))

            await _update_slack("plan", TaskStatus.COMPLETED)

            # Milestone 2: Multi-Source Intelligence Gathering
            await _update_slack("gather", TaskStatus.IN_PROGRESS, "Querying Google AI Overview & Tavily")

            async def _on_tavily_status(msg: str) -> None:
                await _update_slack("gather", TaskStatus.IN_PROGRESS, msg)

            intel = await gather_research_intelligence(
                topic=topic,
                mode=mode,
                session_id=job_id,
                user_id=user_id,
                visual_notes=visual_notes,
                on_status_update=_on_tavily_status,
            )
            job.sources = intel.get("sources", [])
            await _update_slack("gather", TaskStatus.COMPLETED)

            # Milestone 3 (Technical only): Sandbox Verification
            if is_tech:
                candidate_code = intel.get("candidate_code", "")
                if candidate_code:
                    await _update_slack("sandbox", TaskStatus.IN_PROGRESS, "Testing code in Nebius microVM")
                    from chat_agent.tools.sandbox_tool import execute_code_in_sandbox
                    sb_out = await execute_code_in_sandbox(candidate_code)
                    sb_status = sb_out.get("status", "unknown")
                    sb_reason = sb_out.get("reason", "")
                    if sb_status in ("success", "failed"):
                        exit_code = sb_out.get("exit_code", 0)
                        await _update_slack("sandbox", TaskStatus.COMPLETED, f"executed in microVM (exit code {exit_code})")
                        sb_block = [
                            "### Nebius Sandbox Execution Results",
                            f"- Status: {sb_status.upper()} (exit code {exit_code})",
                            f"- Execution Time: {sb_out.get('duration_sec')}s",
                            f"- Stdout: {sb_out.get('stdout', '').strip() or 'None'}",
                            f"- Stderr: {sb_out.get('stderr', '').strip() or 'None'}",
                        ]
                        intel["dossier"] = intel.get("dossier", "") + "\n\n" + "\n".join(sb_block)
                    elif sb_status == "error":
                        err_label = f"execution error ({sb_reason})" if sb_reason else "execution error"
                        await _update_slack("sandbox", TaskStatus.COMPLETED, err_label)
                    else:
                        skip_label = f"skipped ({sb_reason})" if sb_reason else "skipped (unconfigured)"
                        await _update_slack("sandbox", TaskStatus.COMPLETED, skip_label)
                else:
                    await _update_slack("sandbox", TaskStatus.COMPLETED, "skipped (no verified code snippet)")

            # Milestone 4: Long-Form Synthesis
            await _update_slack("synthesize", TaskStatus.IN_PROGRESS, f"Drafting ~{target_words} words")
            current_date_str = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%B %Y")
            base_prompt = TECHNICAL_SYSTEM_PROMPT if is_tech else DELIBERATION_SYSTEM_PROMPT
            system_prompt = base_prompt.replace("{current_date}", current_date_str)
            user_synthesis_prompt = (
                f"Topic: {topic}\n\n"
                f"Evidence Dossier:\n{intel.get('dossier', '')}\n\n"
                f"Synthesize the complete publication following the mandatory structure (~{target_words} words)."
            )

            runner = get_model_runner()
            synthesis_content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_synthesis_prompt)],
            )
            raw_report = await runner.run(
                user_id=user_id,
                session_id=f"synth-{job_id}",
                content=synthesis_content,
                system_instruction=system_prompt,
                enable_tools=False,
            )

            word_count = len(re.findall(r"\b\w+\b", raw_report))
            job.full_report_markdown = raw_report
            job.word_count = word_count
            job.token_economics = await compute_job_token_economics(
                job_id=job_id,
                raw_report=raw_report,
                prompt_text=f"{system_prompt}\n\n{user_synthesis_prompt}",
                has_visual=bool(visual_notes),
            )
            await _update_slack("synthesize", TaskStatus.COMPLETED)

            # Milestone 5: PDF Compilation & Delivery
            await _update_slack("deliver", TaskStatus.IN_PROGRESS, "Compiling publication PDF")
            pdf_path = await asyncio.to_thread(
                build_research_pdf,
                topic=topic,
                mode=mode,
                markdown_content=raw_report,
                word_count=word_count,
                sources=job.sources,
                image_paths=saved_image_paths,
                token_economics=job.token_economics,
            )
            job.pdf_path = pdf_path

            upload_target_thread = thread_ts or status_msg_ts
            upload_title = f"{'Technical Whitepaper' if is_tech else 'Decision Guide'}: {topic[:80]}"
            token = getattr(settings, "aryhant_slack_bot_token", "")
            upload_res = await asyncio.to_thread(
                _upload_file_to_slack_sync,
                pdf_path,
                channel_id,
                upload_target_thread,
                upload_title,
                f"📄 *Generated Publication:* `{os.path.basename(pdf_path)}` ({word_count} words)",
                token,
            )

            if upload_res.get("status") == "error":
                err_msg = upload_res.get("error", "Unknown upload error")
                logger.error("Failed to upload research PDF to Slack: %s", err_msg)
                await _update_slack("deliver", TaskStatus.FAILED, f"Upload error: {err_msg[:60]}")
            else:
                await _update_slack("deliver", TaskStatus.COMPLETED, "Delivered to Slack thread")

            # Extract 2-3 paragraph Executive Summary for thread reply
            summary_paras = [p.strip() for p in raw_report.split("\n\n") if p.strip() and not p.startswith("#")]
            executive_summary = "\n\n".join(summary_paras[:2]) if summary_paras else "Executive Summary generated in attached PDF."
            job.executive_summary = executive_summary

            if client:
                await client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=upload_target_thread,
                    text=f"*{'Executive Summary' if is_tech else 'Executive Verdict'}:*\n{executive_summary[:2800]}",
                )

            # Finalize and persist complete state to Redis
            job.status = TaskStatus.COMPLETED
            await self.store.save_job(job)

        except Exception as job_err:
            logger.error("Job %s (%s) encountered failure: %s", job_id, command, job_err, exc_info=True)
            job.error = str(job_err)
            job.status = TaskStatus.FAILED
            await self.store.save_job(job)
            if client and channel_id and status_msg_ts:
                try:
                    await client.chat_update(
                        channel=channel_id,
                        ts=status_msg_ts,
                        text=f"Error executing {command}",
                        blocks=render_slack_todo_board(job),
                    )
                except Exception:
                    pass
        finally:
            await release_user_job_slot(user_id)


_agent_singleton: DualResearchAgent | None = None


def get_research_agent() -> DualResearchAgent:
    """Return singleton DualResearchAgent instance."""
    global _agent_singleton
    if _agent_singleton is None:
        _agent_singleton = DualResearchAgent()
    return _agent_singleton
