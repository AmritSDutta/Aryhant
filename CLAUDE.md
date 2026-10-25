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
python -m uvicorn chat_agent.app:app --host 127.0.0.1 --port 8000   # FastAPI server
python -m chat_agent.main serve     # Slack Socket Mode
python -m chat_agent.main chat --message "hi"   # one-shot local chat
# other subcommands: slack | chat
python -m pytest -q                 # all tests
python -m pytest -q tests/test_slack.py                # one file
python -m pytest -q tests/test_slack.py::test_name     # one test
```

Requires `USER_LLM_API_KEY` (Google AI Studio) in `.env` for real agent replies; without it API endpoints return demo responses. Without the editable install, add `--app-dir src` to uvicorn or set `PYTHONPATH=src`.

## Architecture

Direct Google GenAI & OpenAI model execution engine behind every channel:

- `src/chat_agent/agents/prompt.py` — Mitra persona: versatile daily AI companion and assistant (general inquiries, planning, writing, problem-solving, coding last) with specialized St. Xavier's Grade 5 ICSE pedagogical capabilities (plain-text math `3/5`, `cm²`, `+`, `-`, `x`, `÷`, 5–10 numbered practice questions, answer keys at end) and universal visual PDF notes generation across any topic.
- `src/chat_agent/agents/runner.py` — `run_agent()` is the single async entry point: text + optional `attachments: list[tuple[bytes, str]]` → moderation → `google.genai.types.Content`. Executes up to 3 randomized attempts across `FIRST_CHOICE_MODELS` via direct `google.genai.Client` with manual tool execution loop (`_execute_tool_call`), falling back to direct `FALLBACK_GPT_MODEL` (`gpt-6-luna`) via `AsyncOpenAI` / `httpx`. In-memory conversation history is managed with bounded deque and prior-turn binary attachment pruning.
- `src/chat_agent/infographics/` — ReportLab handwritten notebook-style study notes (`notes_builder.py`), lesson infographic posters (`builder.py`), procedural math & science diagrams (`diagrams.py`), and styling/branding (`theme.py`, `branding.json`).
- `src/chat_agent/tools/tool_factory.py` — Direct tools: `get_current_time` (IST), `search_web` (multi-provider weighted search pool with fallback), `generate_study_notes_pdf` & `generate_infographic_pdf` (compile PDF and auto-upload to Slack in a background thread), and `upload_file_to_slack` (Slack external file upload API).
- Channels (all call `run_agent`): `slack/slack_app.py` (Slack Bolt Socket Mode with `AsyncSocketModeHandler`), `slack/slack_http.py` (webhook events, threaded replies), `app.py` (FastAPI `/api/*`, `/webhooks/*`, rate limiting, QStash signature verification via `qstash_authentication.py`; webhook auth via `webhooks.py`), `main.py` (CLI orchestrator).
- Multimodal flow in `utils/multimodal.py`: `extract_slack_files` → `download_slack_file` (Bearer bot token) → `validate_multimodal_payload` (regex + Groq prompt guard + OpenAI omni-moderation in `utils/input_validation.py`) → `build_adk_multimodal_content` (`types.Part.from_bytes`). Limits in settings: `MULTIMODAL_ENABLED`, `MAX_SINGLE_ATTACHMENT_SIZE_KB`, `MAX_CUMULATIVE_ATTACHMENT_SIZE_MB`, `MAX_ATTACHMENTS_PER_MESSAGE`.
- Config: `config/settings.py` — single pydantic-settings `Settings` from env; `*_ready` properties (`llm_ready`, `slack_ready`, `email_ready`, `qstash_ready`, ...) gate which channels start. `config/__init__.py` re-exports them.
- Math Formatting in `utils/math_formatter.py` — converts LaTeX markup into clean, readable plain-text school math.
- Tests are hermetic (all HTTP/LLM/Slack calls mocked); `tests/conftest.py` provides `mock_settings` and a FastAPI `TestClient`. pytest config (pythonpath/testpaths) lives in `pyproject.toml`.
- `docs/` is a docs7 documentation site (`docs.json` + `.mdx`).