# Aryhant: AI Daily Companion & ICSE Teaching Assistant

A versatile, direct Google GenAI and OpenAI daily AI assistant for Slack, email, and REST API chat endpoints. Aryhant assists with everyday life, planning, writing, problem-solving, and learning, while specializing as an expert AI teaching companion for **St. Xavier's Grade 5 students under the ICSE curriculum**. Features automated universal handwritten-style Study Notes PDF compilation, Lesson Infographic posters, and autonomous deep technical research with 24-hour failover resume.

> **Status:** Slack (Socket Mode & HTTP events API), REST API, CLI, multimodal attachment handling, multi-provider web search, universal Study Notes / Infographics PDF generation, and 24-hour resilient deep research whitepapers are fully implemented.

## What works today

| Capability | Current state |
| --- | --- |
| Daily Companion & Assistant | Broad day-to-day assistance for inquiries, personal organization, writing, explanations, research, and practical advice (with coding placed last) |
| Grade 5 ICSE Teaching Specialization | Tailored for St. Xavier's Grade 5 ICSE syllabus: plain-text math (`3/5`, `cm²`, `+`, `-`, `x`, `÷`), 5–10 numbered practice questions, and answer keys grouped at the end |
| Question Generation & TypeSafe Curation | Generates 15–20 candidate practice questions and hints via secondary LLM agent (`QA_GENERATOR_INSTRUCTION`), and uses TypeSafe AI System One (`Noul`) for parallel hint scoring and top-10 curation |
| Universal PDF Notes & Infographics | ReportLab handwritten notebook notes (`generate_study_notes_pdf`) and visual posters (`generate_infographic_pdf`) on **any topic** compiled on background threads and auto-uploaded to Slack threads |
| Resilient Deep Research & Deliberation (Role 3) | Autonomous research pipeline (`/research`, `/deliberate`) delivering ~2,500-word ReportLab PDF whitepapers, 4-stream intelligence gathering, Nebius sandbox microVM code verification, concurrent FAQ formulation, JEV quality loop, and 24-hour checkpoint failover resume |
| Direct Multi-Model Engine | Direct Google GenAI SDK (`google.genai.Client`) with 3 random attempts across `FIRST_CHOICE_MODELS` and automatic failover to `FALLBACK_GPT_MODEL` (`gpt-6-luna`) via `AsyncOpenAI` / `httpx` |
| Procedural Diagrams | Dynamic math and science diagram generator (parabolas, waves, geometric figures, circuits, biological structures) |
| Multimodal Handling | Ingests Slack images, audio, PDFs, and documents with size budgets and prior-turn binary attachment pruning |
| Multi-Provider Web Search | Weighted random search pool across DuckDuckGo, Exa, Firecrawl, Tavily, and Serper with GPT summarization for large contexts |
| Slack Locally | Native Slack Bolt Socket Mode with `AsyncSocketModeHandler` and `ARYHANT_ALLOWED_EMAILS` deterministic authorization |
| Slack Over HTTP | Event filtering, threaded replies, and scale-to-zero proxying via Cloudflare Worker and Upstash QStash |
| REST API | FastAPI `/api/chat` (Auth0 protected when `REQUIRE_AUTH=true`, 5/min rate limit), `/api/health`, `/webhooks/slack` |
| Email | IMAP unread-message polling and SMTP replies |
| Conversation State (Tier 1) | Private Upstash Redis with strict `aryhant:` prefix enforcement, 20-turn sliding window (`LTRIM`), and 24-hour TTL |
| Personal Memory & Skills (Tier 2) | Remote Turso (libSQL) long-term memory engine with multi-script tokenization (English, Hindi, Bengali), user email persistence, and interactive `/preferences` Slack modal |
| Autonomous Telemetry & Data Hygiene (Role 4) | Autonomous AdminAgent running deterministic 15-day retention pruning, 7-day metric aggregation, and Context7 / web failure diagnostics via /admin and /audit |

## Recommended cloud architecture

```mermaid
sequenceDiagram
    autonumber
    actor User as Slack User
    participant Slack as Slack API Events
    participant CF as Cloudflare Worker (proxies/cloudflare-slack-ack.js)
    participant QStash as Upstash QStash
    participant Run as Cloud Run (chat_agent.app:app)
    participant Engine as Direct GenAI / GPT Engine
    participant Notes as Background Notes Engine
    participant SlackAPI as Slack Web API
    User->>Slack: @Aryhant "Generate study notes on Fractions"
    Slack->>CF: POST event (expects 200 within 3s)
    CF-->>Slack: HTTP 200 OK (Instant ACK)
    CF->>QStash: Enqueue event (POST /v2/publish/...)
    QStash->>Run: POST /webhooks/slack (retries on cold start)
    Run->>Run: authorize_webhook() verifies secret
    Run-->>QStash: HTTP 200 {"ok": true}
    Run->>Engine: BackgroundTasks -> handle_slack_payload -> run_agent()
    Engine->>Notes: generate_study_notes_pdf() [Background Thread]
    Engine->>SlackAPI: chat.postMessage(channel, text_reply, thread_ts)
    SlackAPI-->>User: Bot replies immediately in Slack thread
    Notes->>Notes: Compile PDF with ReportLab & diagrams
    Notes->>SlackAPI: upload_file_to_slack() -> files.uploadExternal
    SlackAPI-->>User: PDF Study Notes delivered to thread
```

### Scale-to-Zero Slack Setup (Cloudflare + Upstash QStash)

1. **Obtain Upstash QStash Credentials**:
   - In [Upstash Console](https://console.upstash.com/) $\rightarrow$ **QStash**, copy `QSTASH_TOKEN`, `QSTASH_CURRENT_SIGNING_KEY`, and `QSTASH_NEXT_SIGNING_KEY`.
2. **Generate `ARYHANT_WEBHOOK_SHARED_SECRET`**:
   - Generate a pre-shared 32-byte secret in your terminal:
     ```bash
     python -c "import secrets; print(secrets.token_hex(32))"
     ```
   - Add `ARYHANT_WEBHOOK_SHARED_SECRET`, `QSTASH_CURRENT_SIGNING_KEY`, and `QSTASH_NEXT_SIGNING_KEY` to your Cloud Run `.env` or GCP Secret Manager.
3. **Deploy the Cloudflare Worker**:
   - Deploy [`proxies/cloudflare-slack-ack.js`](proxies/cloudflare-slack-ack.js) to Cloudflare Workers.
   - Configure Worker Variables & Secrets:
     - `QSTASH_TOKEN`: your Upstash QStash token.
     - `CLOUD_RUN_WEBHOOK`: `https://<YOUR_CLOUD_RUN_URL>/webhooks/slack`.
     - `ARYHANT_WEBHOOK_SHARED_SECRET`: the same secret generated in Step 2.
4. **Configure Slack Event Subscriptions**:
   - In [Slack App Console](https://api.slack.com/apps) $\rightarrow$ **Event Subscriptions**, set **Request URL** to `https://<your-worker>.<subdomain>.workers.dev`.
   - Subscribe to `app_mention` and `message.im`. Save changes.
5. **Disable Socket Mode & Reinstall**:
   - In [Slack App Console](https://api.slack.com/apps) $\rightarrow$ **Socket Mode**, toggle **Enable Socket Mode** to **Off** (Socket Mode disables HTTP webhooks).
   - In **Install App**, click **Reinstall to Workspace**.

Cloud Run's HTTPS endpoint remains reachable even when no application container is running. A request from QStash causes Cloud Run to start an instance and deliver the request to the app.

## Local quickstart

Run these commands from the repository root. The code uses a `src/` layout: the application package is [`src/chat_agent`](src/chat_agent), and dependencies are defined in [requirements.txt](requirements.txt).

### 1. Create an isolated environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Set `USER_LLM_API_KEY` in `.env` to your Google AI Studio key. If testing OpenAI fallback, set `OPENAI_API_KEY`.

### 2. Start the web preview

```bash
python -m uvicorn chat_agent.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. `GET /api/health` reports configuration readiness.

### 3. Try a one-shot prompt

```bash
python -m chat_agent.main chat --message "Give me 5 practice questions on plant life for Grade 5 ICSE."
```

### 4. Connect Slack locally

Create an app at <https://api.slack.com/apps>:

- Enable Socket Mode.
- Add Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `files:write`, `users:read.email`.
- Subscribe to `app_mention` and `message.im` bot events.
- Create an app-level token with `connections:write`.
- Install the app and set `ARYHANT_SLACK_BOT_TOKEN` and `ARYHANT_SLACK_APP_TOKEN` in `.env`.
- (Optional) Set `ARYHANT_ALLOWED_EMAILS` (comma-separated list of permitted emails) to enforce access control.
- (Optional) Set `ARYHANT_TURSO_DATABASE_URL`, `ARYHANT_TURSO_AUTH_TOKEN`, and `ARYHANT_REDIS_URL` for durable long-term memory and session persistence.

```bash
python -m chat_agent.main slack
```

DM the bot or mention it in a joined channel.

## Project layout

```text
src/chat_agent/          direct runner, prompt, config, tools, research, infographics, Slack, webhooks
src/chat_agent/app.py    FastAPI app: /api/*, /webhooks/*
proxies/                 Cloudflare Worker source
docs/                    docs7 documentation site
tests/                   pytest hermetic test suite (197 tests)
```

## Code map and tests

| Component | Source |
| --- | --- |
| System prompt (Daily AI companion & ICSE Grade 5) | [Prompt](src/chat_agent/agents/prompt.py) |
| Direct GenAI & OpenAI runner with tool loop | [Runner](src/chat_agent/agents/runner.py) |
| Secondary question & hint generator | [Question Generator](src/chat_agent/agents/question_generator.py) |
| TypeSafe AI System One decision engine | [TypeSafe Integrator](src/chat_agent/utils/fast_decision/typesafe_integrator.py) |
| Data schemas & Pydantic models | [Schema](src/chat_agent/schema/fundamental_schema.py) |
| Handwritten study notes builder | [Notes Builder](src/chat_agent/infographics/notes_builder.py) |
| Lesson infographic poster builder | [Infographics Builder](src/chat_agent/infographics/builder.py) |
| Procedural math & science diagrams | [Diagrams](src/chat_agent/infographics/diagrams.py) |
| Resilient research orchestrator (Role 3) | [Research Agent](src/chat_agent/research/research_agent.py) |
| Pre-flight safety screening & audit persistence | [Safety Guard](src/chat_agent/research/safety_guard.py) |
| 4-stream intelligence engine & poison-free cache | [Research Engine](src/chat_agent/research/engine.py) |
| Concurrent FAQ generation engine | [FAQ Engine](src/chat_agent/research/faq_engine.py) |
| JEV multi-dimension quality evaluator | [JEV Validator](src/chat_agent/research/jev_validator.py) |
| 24-hour research checkpoint store & secondary indexing | [Redis Research Store](src/chat_agent/services/redis_research_store.py) |
| Tool pool (time, web search, PDF notes & posters, Slack file upload) | [Tool Factory](src/chat_agent/tools/tool_factory.py) |
| Math formatter (plain-text ICSE math) | [Math Formatter](src/chat_agent/utils/math_formatter.py) |
| Multimodal attachments & moderation | [Multimodal](src/chat_agent/utils/multimodal.py) |
| Environment configuration | [Config](src/chat_agent/config/settings.py) |
| Upstash Redis session store (`aryhant:` prefix) | [Redis Store](src/chat_agent/services/redis_session_store.py) |
| Turso libSQL personal memory & skills engine | [Turso Memory](src/chat_agent/services/turso_memory_service.py) |
| Autonomous Admin & Session Task Service | [Admin Agent](src/chat_agent/agents/admin_agent.py), [Session Tasks](src/chat_agent/services/session_task_service.py) |
| Local CLI | [Main](src/chat_agent/main.py) |
| Slack Socket Mode (Slack Bolt) / HTTP | [Socket integration](src/chat_agent/slack/slack_app.py), [HTTP handler](src/chat_agent/slack/slack_http.py) |
| Slack Block Kit generator | [Post generator](src/chat_agent/slack/post_generator.py) |
| FastAPI app and webhook authorization | [App](src/chat_agent/app.py), [Authorization](src/chat_agent/webhooks.py) |
| Slack-to-QStash forwarding | [Cloudflare Worker](proxies/cloudflare-slack-ack.js) |
| Unit tests (197 tests) | [Tests](tests/test_agent.py) |

Run tests:

```bash
python -m pytest -q
```
