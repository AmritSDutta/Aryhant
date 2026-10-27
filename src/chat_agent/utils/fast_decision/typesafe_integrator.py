import asyncio
import logging
from typing import Optional

from typesafe_sdk import AsyncTypeSafeClient, Noul

from chat_agent.config import settings
from chat_agent.schema.fundamental_schema import QuestionAnswerSchema

logger = logging.getLogger(__name__)
_async_typesafe_client: Optional[AsyncTypeSafeClient] = None
_client_lock: asyncio.Lock = asyncio.Lock()


async def get_client() -> AsyncTypeSafeClient:
    """Return a thread-safe singleton AsyncTypeSafeClient instance."""
    global _async_typesafe_client
    if _async_typesafe_client is None:
        async with _client_lock:
            if _async_typesafe_client is None:
                _async_typesafe_client = AsyncTypeSafeClient(api_key=settings.typesafe_api_key)
    return _async_typesafe_client


async def get_feedback(
    qnah: list[QuestionAnswerSchema],
    user_input: str = "",
) -> list[QuestionAnswerSchema]:
    """Evaluate hint quality using TypeSafe Noul probability (0.0 to 1.0) and return top 10 by score."""
    logger.info(f"[Decision model] Question and Answer with hint: Total {len(qnah)}")
    if not qnah:
        return []

    client: AsyncTypeSafeClient = await get_client()

    state: dict[str, object] = {
        f"item_{item.id}": {
            "id": item.id,
            "question": item.question,
            "hint": item.hint,
        }
        for item in qnah
    }
    if user_input:
        state["user_query"] = user_input

    questions: dict[str, Noul] = {
        f"hint_eval_{item.id}": Noul(
            instructions=(
                f"""Score how helpful, clear, and pedagogically effective `item_{item.id}.hint` is 
                for a Grade 5 student attempting `item_{item.id}.question`. 
                Return 1.0 for maximally helpful (process-focused, age-appropriate, not giving away the answer), 
                0.0 for unhelpful or misleading. Consider `user_query` if present.
            """
            )
        )
        for item in qnah
    }

    response = await client.system_one(
        state=state,
        questions=questions,
    )

    results: list[QuestionAnswerSchema] = []
    for item in qnah:
        key: str = f"hint_eval_{item.id}"
        score_val: Optional[float] = None
        if key in response.nouls:
            score_val = round(response.nouls[key].noul, 4)

        results.append(item.model_copy(update={"score": score_val}))

    results.sort(key=lambda item: item.score if item.score is not None else -1.0, reverse=True)
    logger.info('Completed Decision model based evaluation')
    return results[:10]
