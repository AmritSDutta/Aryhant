import logging
import re

logger = logging.getLogger(__name__)


def clean_text_response(text: str) -> str:
    """Remove emojis, special symbols, control characters, and excess whitespace."""
    if not text:
        return ""
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27BF\u2300-\u23FF\u2B00-\u2BFF]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_openai_summary(fluffy_data: str, model_name: str = "gpt-5-nano") -> str:
    """Summarize fluffy text using OpenAI or fallback to cleaned text."""
    if not fluffy_data:
        return ""

    cleaned_input = clean_text_response(fluffy_data)
    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini" if model_name == "gpt-5-nano" else model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise research text summarizer. "
                        "Synthesize and summarize the input clearly, eliminating fluff and repetition."
                    ),
                },
                {"role": "user", "content": cleaned_input},
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
        return clean_text_response(content)
    except Exception as e:
        logger.warning("OpenAI summary failed: %s. Falling back to cleaned text.", e)
        return cleaned_input


def generate_summaries(fluffy_data: str) -> str:
    """Convenience alias using OpenAI for summarization."""
    return generate_openai_summary(fluffy_data, model_name="gpt-5-nano")


async def generate_openai_summary_async(fluffy_data: str, model_name: str = "gpt-5-nano") -> str:
    """Summarize fluffy text asynchronously using OpenAI or fallback to cleaned text."""
    if not fluffy_data:
        return ""

    cleaned_input = clean_text_response(fluffy_data)
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI()
        response = await client.chat.completions.create(
            model="gpt-4o-mini" if model_name == "gpt-5-nano" else model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise research text summarizer. "
                        "Synthesize and summarize the input clearly, eliminating fluff and repetition."
                    ),
                },
                {"role": "user", "content": cleaned_input},
            ],
            temperature=0.0,
        )
        content = response.choices[0].message.content or ""
        return clean_text_response(content)
    except Exception as e:
        logger.warning("OpenAI async summary failed: %s. Falling back to cleaned text.", e)
        return cleaned_input

