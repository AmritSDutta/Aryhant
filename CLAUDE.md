# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Token efficiency

- Work in the most token-efficient way possible. No subagents.
- Search before reading; read only the specific files and line ranges needed.
- Batch independent reads, searches, and commands into one call instead of serializing turns.
- Never echo file contents, plans, or command output back to the user; report only the conclusion.
- Keep answers and summaries short.

## Secrets: off limits

- Never open, read, print, grep, diff, or copy `.env` or any `.env*` file (this includes `.env.example`).
- Never read or print environment variables by any means (`$env:`, `Get-ChildItem Env:`, `printenv`, `env`, `set`, `os.environ`, `process.env`, dotenv dumps).
- Do not add code whose only purpose is to dump or log environment values.
- When configuration details are needed, rely on the key names and defaults visible in source (for example `src/chat_agent/config/settings.py`) and ask the user rather than inspecting the environment.

## Git: read-only

- Allowed: `git status` only.
- Forbidden: `git commit`, `git stash`, `git pull`, `git push`, and every other state-changing git command (also no branches, tags, merges, rebases, resets, or checkouts).
- Never stage, amend, or rewrite history on the user behalf.

## Commands

```powershell
python -m pip install -e .          # first-time setup; editable install makes src/ importable (required for pytest too)
python -m uvicorn chat_agent.app:app --host 127.0.0.1 --port 8000   # FastAPI server (or infisical run -- python -m uvicorn ...)
cd ui; infisical run -- npm run dev                             # React UI dev server on http://localhost:5173
python -m chat_agent.main serve     # Slack Socket Mode
python -m chat_agent.main chat --message "hi"   # one-shot local chat
# other subcommands: slack | chat
python -m pytest -q                 # all tests (197 passing tests)
python -m pytest -q tests/test_slack.py                # one file
python -m pytest -q tests/test_slack.py::test_name     # one test
```

Requires `USER_LLM_API_KEY` (Google AI Studio) in `.env` for real agent replies; without it API endpoints return demo responses. Without the editable install, add `--app-dir src` to uvicorn or set `PYTHONPATH=src`.

## Folder Structure

```text
├── docs/                           # docs7 documentation site (docs.json, *.mdx)
├── proxies/                        # Edge proxies (Cloudflare Worker Slack ACK & QStash forwarder)
├── ui/                             # React 18 + Vite static web UI (Cloudflare Pages)
├── src/chat_agent/                 # Primary application package
│   ├── agents/                     # Aryhant persona, prompts, question generator, runners, admin
│   │   ├── admin_agent.py          # Role 4: Autonomous administrative auditor (15d prune, 7d metrics, tools)
│   │   ├── gemini_model_runner.py  # Direct Gemini model runner (3x retries, OpenAI fallback, tool loops)
│   │   ├── model_runner.py         # ModelRunner Protocol & get_model_runner() factory
│   │   ├── nebius_model_runner.py  # Nebius OpenAI-compatible model runner
│   │   ├── prompt.py               # Persona & ICSE Grade 5 pedagogical system instructions
│   │   ├── question_generator.py   # Practice question generator agent (facade)
│   │   └── runner.py               # Orchestrator: text clipping, multimodal validation, model delegation
│   ├── research/                   # Role 3: Resilient deep research agent and whitepaper generation
│   │   ├── engine.py               # 4 concurrent intelligence streams with per-tool status & cache reuse
│   │   ├── faq_engine.py           # Concurrent async FAQ generation with 24h caching
│   │   ├── intake.py               # Scope formulation, clarity check & 30s grace window
│   │   ├── jev_validator.py        # Multi-dimension JEV/Noul quality evaluator with critique retry loop
│   │   ├── models.py               # ResearchJobState, ToolOutputEntry, TaskStatus schemas
│   │   ├── pdf_builder.py          # 2,500-word ReportLab publication whitepaper & decision guide generator
│   │   ├── research_agent.py       # Orchestrator with 24h resume, retry loop & [INTERNAL] thread updates
│   │   ├── safety_guard.py         # Dual-layer pre-flight regex & JEV safety screening (status=rejected)
│   │   └── todo_tracker.py         # Live dynamic Block Kit TODO board updater
│   ├── config/                     # Settings, Auth0, rate limiting, QStash auth, logging, Grafana
│   ├── infographics/               # ReportLab PDF builders (study notes, infographics, diagrams, theme)
│   │   ├── builder.py              # Lesson infographic posters
│   │   ├── canvas.py               # Custom ReportLab canvas
│   │   ├── config.py               # Infographic layout constants & styles
│   │   ├── diagrams.py             # Procedural math & science vector diagrams
│   │   ├── notes_builder.py        # Handwritten notebook-style study notes PDF generator
│   │   └── theme.py                # Color palettes and branding definitions
│   ├── question_generator/         # Dedicated question generation package (Base, Gemini, Nebius)
│   │   ├── base_question_generator.py # Abstract base class & shared completion helpers
│   │   ├── gemini_question_generator.py # Google GenAI structured question generator
│   │   ├── nebius_question_generator.py # Nebius OpenAI-compatible question generator
│   │   └── __init__.py             # Factory & curation pipeline
│   ├── schema/                     # Pydantic schemas and data models
│   ├── services/                   # Redis session store, Turso memory service, SessionTaskService, RedisResearchStore
│   │   ├── redis_session_store.py  # Tier 1: 20-turn sliding window conversation history
│   │   ├── redis_research_store.py # Role 3: 24h research checkpointing & secondary indexing (find_active_job)
│   │   ├── turso_memory_service.py # Tier 2: Relational memory & learning preferences
│   │   └── session_task_service.py # Tier 2: Persistent session_tasks lifecycle & operational metrics
│   ├── slack/                      # Slack Bolt Socket Mode, HTTP events API, Block Kit formatting
│   ├── tools/                      # Agent tools (web search, PDF generators, Slack uploader, time)
│   ├── utils/                      # Input validation, math formatter, multimodal, fast decision
│   ├── app.py                      # FastAPI server (/api/chat, /api/health, /webhooks/*)
│   ├── main.py                     # CLI entry point (serve, chat, slack subcommands)
│   └── webhooks.py                 # Webhook authentication & endpoints
├── tests/                          # Hermetic test suite with mocked external services (197 tests)
├── .github/workflows/ci.yml        # GitHub Actions CI (ruff non-blocking, pytest blocking)
├── Dockerfile                      # Production container image definition
└── pyproject.toml                  # Project metadata, dependencies, and pytest configuration
```

## Architecture

## Four-Role Agent Architecture

1. **Role 1: Primary Chat & ICSE Pedagogical Companion** (src/chat_agent/agents/runner.py, prompt.py)
   - Handles everyday conversations, multi-turn dialogue, multimodal attachments, and St. Xavier Grade 5 ICSE syllabus guidance.
2. **Role 2: Practice Question Generator & Evaluator** (src/chat_agent/question_generator/)
   - Structured generation of 15-20 questions/hints with TypeSafe AI System One (Noul) top-10 curation.
3. **Role 3: Deep Technical Research & Deliberation** (src/chat_agent/research/research_agent.py, engine.py, redis_research_store.py)
   - 24-hour resilient research pipeline with secondary index failover resume (`find_active_job`).
   - Dual-layer pre-flight safety screening (`safety_guard.py`) recording rejections to `session_tasks`.
   - 4 concurrent intelligence streams (SerpApi, Tavily, Context7, WebSearchToolPool) with poison-free caching.
   - Nebius microVM code verification, concurrent FAQ generation (`faq_engine.py`), and JEV multi-dimension quality loop (`jev_validator.py`).
   - ~2,500-word ReportLab PDF whitepaper compilation and single-thread `[INTERNAL]` notifications.
4. **Role 4: Autonomous Administrative & Telemetry Auditor** (src/chat_agent/agents/admin_agent.py)
   - Deterministic 15-day data retention pruning (`delete_records_older_than(15)`).
   - 7-day operational telemetry aggregation (`get_table_metrics(7)`).
   - Failure diagnostics via `ADMIN_TOOLS` (search_context7, search_web) and multi-turn Nebius/Gemini dispatch.
   - Triggered via Slack `/admin`, `/audit`, or app mentions.


Direct Google GenAI, Nebius & OpenAI model execution engine behind every channel:

- `src/chat_agent/agents/prompt.py` — Aryhant persona: versatile daily AI companion and assistant with specialized St. Xavier's Grade 5 ICSE pedagogical capabilities (plain-text math `3/5`, `cm²`, `+`, `-`, `x`, `÷`, 5–10 numbered practice questions, answer keys at end) and universal visual PDF notes generation across any topic.
- `src/chat_agent/agents/model_runner.py` & `src/chat_agent/agents/gemini_model_runner.py` / `nebius_model_runner.py` — Decoupled model execution: `ModelRunner` interface protocol with `get_model_runner()` factory dispatching to `NebiusModelRunner` (default) or `GeminiModelRunner` (executes 3 randomized attempts across `FIRST_CHOICE_MODELS` with tool loop and `FALLBACK_GPT_MODEL` failover). `runner.py` acts as pure orchestrator for clipping, moderation, and dispatch.
- `src/chat_agent/services/redis_session_store.py` — Private Upstash Redis session store: strict `aryhant:` prefix enforcement (`format_session_key`), 20-turn sliding window (`LTRIM`), and 24-hour TTL (`REDIS_TTL_SEC`) with seamless in-memory fallback.
- `src/chat_agent/services/redis_research_store.py` — Resilient research job store with secondary indexing (`find_active_job`) on `(channel_id, thread_ts)` and `(user_id, topic_hash)` with 24-hour sliding TTL.
- `src/chat_agent/services/turso_memory_service.py` — Remote Turso libSQL memory & preferences engine: connects directly via `libsql.connect(self.database_url, auth_token=self.auth_token)`. Stores `user_profiles` (with `email`) and multi-script memories with keyword overlap reinforcement. Background distillation extracts learning habits using `NEBIUS_QUESTION_MODEL` with `{"statement": null}` guard.
- `src/chat_agent/services/session_task_service.py` — Persistent SQLite/libSQL operational task lifecycle tracking for research and admin audit workflows.
- `src/chat_agent/slack/slack_app.py` & `slack_http.py` — Slack Bolt Socket Mode and webhook events. Enforces `ARYHANT_ALLOWED_EMAILS` allowlist via `client.users_info` (`users:read.email` scope). Unauthorized callers receive immediate deterministic polite denial without invoking the LLM runner. `/preferences` slash command opens interactive modal with real-time deletion.
- `src/chat_agent/utils/text_formatter.py` — Semantically interprets raw Markdown into clean human-consumable text with blank lines and emoji preservation (`interpret_markdown`), un-gluing headings and numbers.
- `src/chat_agent/infographics/` — ReportLab handwritten notebook-style study notes (`notes_builder.py`), lesson infographic posters (`builder.py`), procedural math & science diagrams (`diagrams.py`), and styling/branding (`theme.py`, `branding.json`).
- `src/chat_agent/tools/tool_factory.py` — Direct tools: `get_current_time` (IST), `search_web` (multi-provider weighted search pool with fallback), `generate_study_notes_pdf` & `generate_infographic_pdf` (compile PDF and auto-upload to Slack in a background thread), and `upload_file_to_slack` (Slack external file upload API).
- Channels (all call `run_agent`): `slack/slack_app.py` (Slack Bolt Socket Mode with `AsyncSocketModeHandler`), `slack/slack_http.py` (webhook events, threaded replies), `app.py` (FastAPI `/api/*`, `/webhooks/*`, rate limiting, QStash signature verification via `qstash_authentication.py`; webhook auth via `webhooks.py`), `main.py` (CLI orchestrator).
- Multimodal flow in `utils/multimodal.py`: `extract_slack_files` → `download_slack_file` (Bearer bot token) → `validate_multimodal_payload` (regex + Groq prompt guard + OpenAI omni-moderation in `utils/input_validation.py`) → `build_adk_multimodal_content` (`types.Part.from_bytes`). Limits in settings: `MULTIMODAL_ENABLED`, `MAX_SINGLE_ATTACHMENT_SIZE_KB`, `MAX_CUMULATIVE_ATTACHMENT_SIZE_MB`, `MAX_ATTACHMENTS_PER_MESSAGE`.
- Config: `config/settings.py` — single pydantic-settings `Settings` from env; strictly standardizes on `ARYHANT_TURSO_DATABASE_URL`, `ARYHANT_TURSO_AUTH_TOKEN`, `ARYHANT_REDIS_URL`, and `ARYHANT_ALLOWED_EMAILS`. No legacy fallback aliases.
- Tests are hermetic (all HTTP/LLM/Slack calls mocked; 197 tests pass with zero external keys); `tests/conftest.py` provides `mock_settings` and a FastAPI `TestClient`. pytest config lives in `pyproject.toml`.
- `docs/` is a docs7 documentation site (`docs.json` + `*.mdx`).
