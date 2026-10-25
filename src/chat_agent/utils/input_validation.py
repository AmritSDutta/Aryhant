import base64
import logging
import os
import re
from typing import Any, Dict, List, Optional, Union

from chat_agent.config import settings

logger = logging.getLogger(__name__)

# Patterns for potentially malicious content
MALICIOUS_PATTERNS = {
    # Shell command injection patterns
    "shell_injection": [
        r";\s*(rm|mv|cp|dd|chmod|chown|cat|ls)\s+",  # Command chaining with dangerous commands
        r"\|\s*(rm|mv|cp|dd|chmod|chown|cat|ls|grep)\s+",  # Pipe to dangerous commands
        r"`.*\$.*`",  # Backtick command substitution with variables
        r"\$\(.*\)",  # Command substitution
        r"&&\s*(rm|mv|dd|chmod|cat|sudo)",  # AND operator with dangerous commands
        r"\|\|\s*(rm|mv|dd|cat|sudo)",  # OR operator with dangerous commands
        r"&&\s*sudo\s+",  # AND operator with sudo
        r"\|\|\s*sudo\s+",  # OR operator with sudo
    ],
    # Docker commands that could be abused
    "docker_abuse": [
        r"docker\s+(exec|run)\s+.*-v\s*/",  # Volume mounting with root
        r"docker\s+exec.*sudo",  # Docker exec with sudo
        r"docker\s+run.*--privileged",  # Privileged mode
        r"docker\s+run.*--pid=host",  # Host PID namespace
        r"docker\s+run.*--network=host",  # Host network
        r"docker\s+exec.*chmod",  # Docker exec with chmod
        r"docker\s+exec.*sh",  # Shell access in container
        r"docker\s+exec.*bash",  # Bash access in container
    ],
    # SQL injection patterns
    "sql_injection": [
        r"(\%27)|(\')|(\-\-)|(\%23)|(#)",  # SQL comment characters
        r"(\bor\b\s*\d+\s*=\s*\d+)",  # SQL bypass with OR
        r"(\band\b\s*\d+\s*=\s*\d+)",  # SQL bypass with AND
        r"union\s+select",  # UNION SELECT injection
        r"exec\s*\(",  # Command execution in SQL
    ],
    # Path traversal attempts
    "path_traversal": [
        r"\.\./",  # Parent directory traversal
        r"\.\.\\",  # Windows parent directory
        r"%2e%2e",  # URL encoded parent directory
        r"~root",  # Root home directory access
        r"/etc/passwd",  # Accessing password file
        r"/etc/shadow",  # Accessing shadow file
        r"C:\\Windows\\System32",  # Windows system directory
    ],
    # System commands and dangerous operations
    "system_commands": [
        r"\brm\s+-rf\s+/",  # Delete root filesystem
        r"\bdd\s+if=/dev/zero",  # Disk wipe
        r"\bmkfs\.",  # Format filesystem
        r"\bshutdown\b",  # Shutdown command
        r"\breboot\b",  # Reboot command
        r"\bsystemctl\s+(stop|disable|restart)",  # System service control
        r"\bservice\s+\w+\s+stop",  # Stop services
        r"\bkill\s+-9\s+\d+",  # Kill processes
        r"\bkillall\b",  # Kill all processes
        r"\binit\s+\d",  # Change runlevel
        r"\bnc\s+.*-e",  # Netcat with execute
        r"\bbash\s+-i",  # Interactive bash
        r"\bcurl\s+.*\|\s*bash",  # Curl pipe to bash
        r"\bwget\s+.*\|\s*sh",  # Wget pipe to shell
        r"\bchmod\s+777",  # Dangerous permission change
        r"\bchmod\s+-R",  # Recursive permission change
        r"\bsudo\s+(su|bash|sh)",  # Privilege escalation
    ],
    # Script/Code execution patterns
    "code_execution": [
        r"<script[^>]*>",  # Script tags
        r"javascript:",  # JavaScript protocol
        r"onload\s*=",  # Event handler injection
        r"onerror\s*=",  # Error handler injection
        r"eval\s*\(",  # Eval function
        r"exec\s*\(",  # Exec function
        r"system\s*\(",  # System function
        r"__import__\(",  # Python import injection
    ],
    # Known malicious keywords
    "malicious_keywords": [
        "malware",
        "virus",
        "trojan",
        "ransomware",
        "spyware",
        "keylogger",
        "backdoor",
        "rootkit",
        "botnet",
        "exploit",
        "payload",
        "shellcode",
        "injection",
        "bypass",
    ],
}

# Compile all regex patterns for better performance
COMPILED_PATTERNS: Dict[str, List[re.Pattern]] = {}
for category, patterns in MALICIOUS_PATTERNS.items():
    if category == "malicious_keywords":
        continue
    if isinstance(patterns, list):
        COMPILED_PATTERNS[category] = [re.compile(p, re.IGNORECASE) for p in patterns]


_groq_client: Optional[Any] = None
_openai_client: Optional[Any] = None


def get_groq_client() -> Any:
    """Return cached AsyncGroq singleton client."""
    global _groq_client
    if _groq_client is None:
        from groq import AsyncGroq

        api_key = getattr(settings, "GROQ_API_KEY", "") or None
        _groq_client = AsyncGroq(api_key=api_key)
    return _groq_client


def get_openai_client() -> Any:
    """Return cached AsyncOpenAI singleton client."""
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI

        api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client


async def get_groq_prompt_guard_feedback(prompt: str) -> bool:
    """Check text input using Groq's meta-llama/llama-prompt-guard-2-22m model."""
    if not prompt:
        return True
    try:
        client = get_groq_client()
        completion = await client.chat.completions.create(
            model="meta-llama/llama-prompt-guard-2-22m",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        raw_content = (completion.choices[0].message.content or "").strip().lower()
        if "unsafe" in raw_content or "jailbreak" in raw_content:
            logger.warning("Groq prompt guard flagged input: %s", raw_content)
            return False
        logger.info("Groq prompt guard passed for prompt: %s...", prompt[:50])
        return True
    except Exception as e:
        logger.warning("Groq prompt guard check skipped or failed: %s", e)
        return True


async def get_LLM_feedback_on_input(
    prompt: str = "",
    media_type: Optional[str] = None,
    media_data: Optional[Union[str, bytes]] = None,
) -> bool:
    """Check image or audio multimodal input using OpenAI's omni-moderation-latest model."""
    try:
        inputs: List[Dict[str, Any]] = []
        formatted_media: Optional[str] = None

        if media_data is not None:
            if isinstance(media_data, bytes):
                b64_encoded = base64.b64encode(media_data).decode("utf-8")
                if media_type and ("image" in media_type or media_type.startswith("image/")):
                    formatted_media = f"data:{media_type};base64,{b64_encoded}"
                else:
                    formatted_media = b64_encoded
            else:
                formatted_media = str(media_data)

        if media_type and ("image" in media_type or media_type.startswith("image/")) and formatted_media:
            inputs.append({
                "type": "image_url",
                "image_url": {"url": formatted_media},
            })
        elif media_type and ("audio" in media_type or media_type.startswith("audio/")) and formatted_media:
            normalized_type = media_type.lower()
            if "mp3" in normalized_type or "mpeg" in normalized_type:
                audio_format = "mp3"
            elif "wav" in normalized_type:
                audio_format = "wav"
            else:
                logger.info(
                    "Audio format '%s' is not supported by OpenAI omni-moderation audio formats (mp3/wav only). Skipping audio moderation check.",
                    media_type,
                )
                audio_format = None

            if audio_format:
                inputs.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": formatted_media,
                        "format": audio_format,
                    },
                })
        elif prompt:
            inputs.append({"type": "text", "text": prompt})

        if not inputs:
            return True

        api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        if not api_key:
            if settings.MODERATION_API_CHECK_REQ:
                logger.warning("MODERATION_API_CHECK_REQ is True but OPENAI_API_KEY is missing. Failing closed.")
                return False
            logger.info("OpenAI API key not configured, skipping moderation check.")
            return True

        logger.info("Calling OpenAI omni-moderation API for multimodal inputs (type=%s)", media_type)
        client = get_openai_client()
        response = await client.moderations.create(
            model="omni-moderation-latest",
            input=inputs if len(inputs) > 1 or media_type else prompt,
        )

        for res in response.results:
            if res.flagged:
                logger.warning(
                    "Multimodal input flagged by OpenAI moderation. Categories: %s", res.categories
                )
                return False

        logger.info("Multimodal input passed OpenAI moderation check")
        return True

    except Exception as e:
        logger.warning("OpenAI multimodal moderation check failed: %s", e)
        if settings.MODERATION_API_CHECK_REQ:
            return False
        return True


async def scan_for_vulnerability(
    user_message: str,
    media_type: Optional[str] = None,
    media_data: Optional[Union[str, bytes]] = None,
) -> bool:
    """Scan user text and optional image/audio media for malicious or unsafe content."""
    logger.info("Scanning for vulnerabilities...")
    if not user_message and not media_data:

        return True

    if user_message and isinstance(user_message, str):
        message_lower = user_message.lower()

        # Check regex categories
        for category, patterns in COMPILED_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(user_message):
                    logger.warning(
                        "Malicious content detected in category '%s': %s...",
                        category,
                        user_message[:100],
                    )
                    return False

        # Check keywords in context
        keywords = MALICIOUS_PATTERNS.get("malicious_keywords", [])
        for keyword in keywords:
            if keyword in message_lower:
                suspicious_prefixes = [
                    "create",
                    "write",
                    "build",
                    "deploy",
                    "install",
                    "execute",
                    "run",
                    "download",
                ]
                suspicious_suffixes = ["script", "code", "payload", "attack"]

                has_suspicious_context = False
                words = message_lower.split()

                for i, word in enumerate(words):
                    if word == keyword or keyword in word:
                        window_start = max(0, i - 3)
                        window_end = min(len(words), i + 4)
                        context_window = " ".join(words[window_start:window_end])

                        if any(prefix in context_window for prefix in suspicious_prefixes):
                            has_suspicious_context = True
                            break
                        if any(suffix in context_window for suffix in suspicious_suffixes):
                            has_suspicious_context = True
                            break

                if has_suspicious_context:
                    logger.warning(
                        "Malicious keyword '%s' detected in suspicious context: %s...",
                        keyword,
                        user_message[:100],
                    )
                    return False

        # Groq Prompt Guard check for text
        if settings.MODERATION_API_CHECK_REQ or getattr(settings, "GROQ_API_KEY", ""):
            groq_status = await get_groq_prompt_guard_feedback(user_message)
            if not groq_status:
                return False

    # OpenAI multimodal check for image or audio inputs
    if media_type or media_data:
        multimodal_status = await get_LLM_feedback_on_input(
            prompt=user_message, media_type=media_type, media_data=media_data
        )
        if not multimodal_status:
            return False

    logger.info("Input passed vulnerability scan: %s...", user_message[:50] if user_message else "media")
    return True


async def get_vulnerability_details(user_message: str) -> Dict[str, Any]:
    """Get detailed information about detected vulnerabilities."""
    result: Dict[str, Any] = {
        "is_safe": True,
        "detected_issues": [],
        "risk_level": "none",
    }

    if not user_message or not isinstance(user_message, str):
        return result

    message_lower = user_message.lower()

    for category, patterns in COMPILED_PATTERNS.items():
        if category == "malicious_keywords":
            continue

        for pattern in patterns:
            if pattern.search(user_message):
                result["is_safe"] = False
                result["detected_issues"].append((category, pattern.pattern))

    keywords = MALICIOUS_PATTERNS.get("malicious_keywords", [])
    for keyword in keywords:
        if keyword in message_lower:
            suspicious_prefixes = [
                "create",
                "write",
                "build",
                "deploy",
                "install",
                "execute",
                "run",
                "download",
            ]
            suspicious_suffixes = ["script", "code", "payload", "attack"]

            has_suspicious_context = False
            words = message_lower.split()

            for i, word in enumerate(words):
                if word == keyword or keyword in word:
                    window_start = max(0, i - 3)
                    window_end = min(len(words), i + 4)
                    context_window = " ".join(words[window_start:window_end])

                    if any(prefix in context_window for prefix in suspicious_prefixes):
                        has_suspicious_context = True
                        break
                    if any(suffix in context_window for suffix in suspicious_suffixes):
                        has_suspicious_context = True
                        break

            if has_suspicious_context:
                result["is_safe"] = False
                result["detected_issues"].append(("malicious_keyword", keyword))

    if not result["is_safe"]:
        issue_count = len(result["detected_issues"])
        high_risk_categories = {"system_commands", "docker_abuse", "shell_injection"}

        has_high_risk = any(cat in high_risk_categories for cat, _ in result["detected_issues"])

        if has_high_risk or issue_count >= 3:
            result["risk_level"] = "high"
        elif issue_count >= 2:
            result["risk_level"] = "medium"
        else:
            result["risk_level"] = "low"

    return result
