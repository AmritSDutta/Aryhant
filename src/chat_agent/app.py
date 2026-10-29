from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from chat_agent.agents.runner import run_agent
from chat_agent.communicate.router import router as communicate_router
from chat_agent.config import (
    llm_ready,
    settings,
    setup_logging,
    slack_http_ready,
)
from chat_agent.config.auth0_config import auth0, get_user_profile
from chat_agent.config.grafana_config import setup_grafana
from chat_agent.config.rate_limiter import Duration, Limiter, Rate, RateLimiter
from chat_agent.slack.slack_http import handle_slack_payload
from chat_agent.utils.input_validation import scan_for_vulnerability
from chat_agent.webhooks import authorize_webhook

setup_logging()
logger = logging.getLogger("chat_agent.app")

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


@asynccontextmanager
async def lifespan(app_ins: FastAPI):
    logger.info("Starting %s v%s", app_ins.title, app_ins.version)
    if settings.AUTH0_DOMAIN:
        try:
            from chat_agent.config.auth0_config import get_jwks

            await get_jwks()
        except Exception as e:
            logger.warning("Auth0 JWKS prefetch skipped or failed: %s", e)

    async def _pre_warm_backends() -> None:
        if settings.ARYHANT_REDIS_URL:
            try:
                from chat_agent.services.redis_session_store import get_redis_session_store

                await get_redis_session_store().pre_warm()
            except Exception as e:
                logger.warning("Redis session store pre-warm skipped or failed: %s", e)

        if settings.ARYHANT_TURSO_DATABASE_URL or settings.TURSO_LOCAL_DB_PATH:
            try:
                from chat_agent.services.turso_memory_service import get_turso_memory_service

                await get_turso_memory_service().apre_warm()
            except Exception as e:
                logger.warning("Turso memory service pre-warm skipped or failed: %s", e)

    prewarm_task = asyncio.create_task(_pre_warm_backends())
    _BACKGROUND_TASKS.add(prewarm_task)
    prewarm_task.add_done_callback(_BACKGROUND_TASKS.discard)
    yield
    logger.info("Shutting down %s", app_ins.title)
    try:
        from chat_agent.services.redis_session_store import get_redis_session_store

        await get_redis_session_store().close()
    except Exception:
        pass


app = FastAPI(
    title="ADK Slack Chat Agent",
    description="Low-cost Google ADK Slack and email chat agent API",
    version="0.1.0",
    lifespan=lifespan,
)

setup_grafana(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://experiments.amritai.org",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    user_id: str = "web-user"
    session_id: str = "web-session"
    channel: str = "web"


class ChatResponse(BaseModel):
    reply: str
    model: str
    channel: str


@app.get("/", dependencies=[
    Depends(RateLimiter(limiter=Limiter(Rate(30, Duration.MINUTE))))])
async def root() -> dict:
    return {
        "name": "Private Chat Agent",
        "version": "0.1.0"
    }


@app.get("/api/health", dependencies=[
    Depends(RateLimiter(limiter=Limiter(Rate(60, Duration.MINUTE))))])
async def health() -> dict:
    return {
        "status": "healthy",
        "version": "0.1.0",
        "ok": True
    }


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    dependencies=[
        Depends(RateLimiter(limiter=Limiter(Rate(20, Duration.MINUTE)))),
    ],
)
async def chat(
        payload: ChatRequest,
        auth_info: dict = Depends(auth0.require_auth()),
        token: HTTPAuthorizationCredentials | None = Security(HTTPBearer(auto_error=False)),
) -> ChatResponse:
    if settings.REQUIRE_AUTH:
        await get_user_profile(
            access_token=token.credentials if token else "",
            decoded_payload=auth_info.get("payload"),
        )
    if not await scan_for_vulnerability(payload.message):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Input validation failed: Potentially unsafe content detected.",
        )

    prompt = f"[channel={payload.channel}]\n{payload.message}"
    if not llm_ready():
        reply = (
            "Demo mode (no USER_LLM_API_KEY). "
            "In Slack, mention the bot or DM it. Email works if EMAIL_ENABLED=true. "
            f"You said: {payload.message[:280]}"
        )
        return ChatResponse(reply=reply, model="demo", channel=payload.channel)
    reply = await run_agent(payload.user_id, payload.session_id, prompt)
    return ChatResponse(reply=reply, model=settings.model, channel=payload.channel)


@app.post("/webhooks/slack", response_model=None)
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> dict | JSONResponse:
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}
    authorize_webhook(request, body)
    if not slack_http_ready():
        logger.error("Slack event rejected: ARYHANT_SLACK_BOT_TOKEN is not configured.")
        return JSONResponse({"error": "Service unavailable"}, status_code=503)
    background_tasks.add_task(handle_slack_payload, payload)
    return {"ok": True}

app.include_router(communicate_router)
