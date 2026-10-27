import logging
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Only load .env if NOT running under Infisical
RUNNING_UNDER_INFISICAL = os.getenv("INFISICAL_INJECTED") == "1"

if not RUNNING_UNDER_INFISICAL:
    # Support for Secret Manager: Allow override of .env file location
    DOTENV_LOCATION = os.getenv('DOTENV_LOCATION', None)
    if DOTENV_LOCATION:
        # Cloud Run/Secret Manager: Load from specified absolute path
        load_dotenv(dotenv_path=Path(DOTENV_LOCATION))
        logger.info(f"Loaded environment from DOTENV_LOCATION: {DOTENV_LOCATION}")
    else:
        # Local dev: Load from project root
        DOTENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
        load_dotenv(dotenv_path=DOTENV_PATH)
        logger.info(f"Loaded environment from project root: {DOTENV_PATH}")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core App & LLM
    APP_NAME: str = "aryhant"
    MODEL_PROVIDER: str = "nebius"  #"gemini"
    USER_LLM_MODEL: str = "gemini-flash-lite-latest"
    INFERENCE_MODEL: str = "gemini-flash-lite-latest"
    FALLBACK_MODEL: str = "gemini-3.1-flash-lite"
    USER_LLM_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    NEBIUS_API_KEY: str = ""
    NEBIUS_BASE_URL: str = "https://api.tokenfactory.nebius.com/v1"
    NEBIUS_MODEL: str = "nvidia/Nemotron-3.5-Super-VL"
    QUESTION_GENERATOR_PROVIDER: str = "nebius"  #"gemini"
    QUESTION_GENERATOR_MODEL: str = "gemini-flash-lite-latest"
    NEBIUS_QUESTION_MODEL: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    NEBIUS_QUESTION_FALLBACK_MODEL: str = "nvidia/nemotron-3-super-120b-a12b"
    MAX_INPUT_CHARS: int = 5000
    MAX_OUTPUT_TOKENS: int = 8000
    REPLY_ONLY_TO_MENTIONS: bool = True

    # Slack Integration
    ARYHANT_SLACK_BOT_TOKEN: str = ""
    ARYHANT_SLACK_APP_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""
    MAX_SINGLE_ATTACHMENT_SIZE_KB: int = 500
    MAX_CUMULATIVE_ATTACHMENT_SIZE_MB: int = 2
    MAX_ATTACHMENTS_PER_MESSAGE: int = 5
    MULTIMODAL_ENABLED: bool = True

    # Webhook Integration
    WEBHOOK_SHARED_SECRET: str = ""
    WEBHOOK_URL: str = ""

    # Email Integration (IMAP / SMTP)
    EMAIL_ENABLED: bool = False
    EMAIL_IMAP_HOST: str = "imap.gmail.com"
    EMAIL_IMAP_PORT: int = 993
    EMAIL_SMTP_HOST: str = "smtp.gmail.com"
    EMAIL_SMTP_PORT: int = 587
    EMAIL_ADDRESS: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_POLL_SECONDS: int = 60
    EMAIL_ALLOWED_SENDERS: str = ""
    EMAIL_MAX_BODY_CHARS: int = 4000

    # Search & External API Keys
    DEFAULT_SEARCH_PROVIDER: str = "random"
    TAVILY_API_KEY: str = ""
    EXA_API_KEY: str = ""
    FIRECRAWL_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    NVIDIA_API_KEY: str = ""
    OLLAMA_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    MARKDOWN_API_KEY: str = ""
    BREVO_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # Search Parameters & Cost Controls
    DUCKDUCKGO_MAX_RESULTS: int = 5
    SEARCH_MAX_SNIPPET_LENGTH: int = 500
    SUBTASK_MAX_LENGTH_FOR_CONSIDERATION: int = 1000
    INFERENCE_MAX_RETRY: int = 3
    MODERATION_API_CHECK_REQ: bool = False
    COST_SPREADING_FACTOR: float = 0.03
    LLM_PRE_CALL_DELAY_SECONDS: float = 5.0
    TOKEN_USAGE_LOG_BASE: float = 100.0
    FORMULA_WEIGHT_CALL_COUNT: float = 0.5
    FORMULA_WEIGHT_TOKEN_COUNT: float = 0.5

    # LangSmith & Ollama
    ENABLE_LANGSMITH_TRACING_V2: str = "false"
    LANGSMITH_PROJECT: str = "task-graph-execution"
    USE_OLLAMA_CLOUD_URL: bool = True
    OLLAMA_CLOUD_URL: str = "https://ollama.com"
    MODEL_COST_CSV_PATH: str = "model_costs.csv"
    MODEL_CAPABILITY_CSV_PATH: str = "model_capabilities.csv"

    # API Authentication & Auth0
    API_KEY: str = ""
    REQUIRE_AUTH: bool = False
    AUTH0_DOMAIN: str = ""
    AUTH0_AUDIENCE: str = ""
    LOG_USER_INFO: bool = True
    ARYHANT_ALLOWED_EMAILS: str = ""

    # Database & Telemetry
    ARYHANT_TURSO_DATABASE_URL: str = ""
    ARYHANT_TURSO_AUTH_TOKEN: str = ""
    ARYHANT_REDIS_URL: str = ""
    TURSO_DATABASE_NAME: str = "aryhant"
    TURSO_LOCAL_DB_PATH: str = "aryhant.db"
    GRAFANA_API_TOKEN: str = ""
    GRAFANA_USER_ID: str = "GRAFANA_USER_ID_2629876"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    OTEL_EXPORTER_OTLP_PROTOCOL: str = ""
    REDIS_TTL_SEC: int = 86400
    OPENSEARCH_URL_AIVEN: str = ""
    OPENSEARCH_INDEX_NAME: str = "llm_waste"
    TYPESAFE_API_KEY: str = ""

    FIRST_CHOICE_MODELS: list[str] = [
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest"
    ]

    FALLBACK_MODELS: list[str] = [
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    ]

    FALLBACK_GPT_MODEL: str = "gpt-6-luna"
    IS_GEMINI_MODERATION_ENOUGH: bool = True
    QSTASH_CURRENT_SIGNING_KEY: str = ''
    QSTASH_NEXT_SIGNING_KEY: str = ''

    def model_post_init(self, __context: object) -> None:
        """Propagate GEMINI_API_KEY to os.environ for SDKs if unset."""
        api_key = self.api_key
        if api_key and not os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = api_key

    @property
    def app_name(self) -> str:
        return self.APP_NAME

    @property
    def model(self) -> str:
        return self.USER_LLM_MODEL or self.INFERENCE_MODEL or "gemini-flash-lite-latest"

    @property
    def api_key(self) -> str:
        return self.USER_LLM_API_KEY or self.GEMINI_API_KEY or self.GOOGLE_API_KEY or ""

    @property
    def max_input_chars(self) -> int:
        return self.MAX_INPUT_CHARS

    @property
    def max_output_tokens(self) -> int:
        return self.MAX_OUTPUT_TOKENS

    @property
    def aryhant_slack_bot_token(self) -> str:
        return self.ARYHANT_SLACK_BOT_TOKEN or os.getenv("ARYHANT_SLACK_BOT_TOKEN", "")

    @property
    def aryhant_slack_app_token(self) -> str:
        return self.ARYHANT_SLACK_APP_TOKEN or os.getenv("ARYHANT_SLACK_APP_TOKEN", "")

    @property
    def slack_signing_secret(self) -> str:
        return self.SLACK_SIGNING_SECRET or os.getenv("SLACK_SIGNING_SECRET", "")

    @property
    def webhook_shared_secret(self) -> str:
        return self.WEBHOOK_SHARED_SECRET or os.getenv("WEBHOOK_SHARED_SECRET", "")

    @property
    def email_enabled(self) -> bool:
        return self.EMAIL_ENABLED

    @property
    def email_imap_host(self) -> str:
        return self.EMAIL_IMAP_HOST

    @property
    def email_imap_port(self) -> int:
        return self.EMAIL_IMAP_PORT

    @property
    def email_smtp_host(self) -> str:
        return self.EMAIL_SMTP_HOST

    @property
    def email_smtp_port(self) -> int:
        return self.EMAIL_SMTP_PORT

    @property
    def email_address(self) -> str:
        return self.EMAIL_ADDRESS

    @property
    def email_password(self) -> str:
        return self.EMAIL_PASSWORD

    @property
    def email_poll_seconds(self) -> int:
        return self.EMAIL_POLL_SECONDS

    @property
    def email_max_body_chars(self) -> int:
        return self.EMAIL_MAX_BODY_CHARS

    @property
    def email_allowed_senders_list(self) -> List[str]:
        if not self.EMAIL_ALLOWED_SENDERS:
            return []
        return [
            item.strip().lower()
            for item in self.EMAIL_ALLOWED_SENDERS.split(",")
            if item.strip()
        ]

    @property
    def allowed_emails_list(self) -> list[str]:
        raw = (os.getenv("ARYHANT_ALLOWED_EMAILS") or self.ARYHANT_ALLOWED_EMAILS or "").strip()
        if not raw:
            return []
        return [
            item.strip().lower()
            for item in raw.split(",")
            if item.strip()
        ]

    def is_email_allowed(self, email: str) -> bool:
        """Check if an email is permitted. If ARYHANT_ALLOWED_EMAILS is empty, all emails are allowed."""
        allowed = self.allowed_emails_list
        if not allowed:
            return True
        if not email:
            return False
        return email.strip().lower() in allowed

    @property
    def llm_ready(self) -> bool:
        return bool(self.api_key)

    @property
    def nebius_ready(self) -> bool:
        return bool(self.NEBIUS_API_KEY or os.getenv("NEBIUS_API_KEY", ""))

    @property
    def slack_ready(self) -> bool:
        return bool(self.aryhant_slack_bot_token and self.aryhant_slack_app_token)

    @property
    def slack_http_ready(self) -> bool:
        return bool(self.aryhant_slack_bot_token)

    @property
    def webhook_auth_ready(self) -> bool:
        return bool(self.webhook_shared_secret or self.slack_signing_secret)

    @property
    def resolved_turso_db_path(self) -> Path:
        """Return the absolute path to the local Turso replica database."""
        p = Path(self.TURSO_LOCAL_DB_PATH)
        if p.is_absolute():
            return p
        root_dir = Path(__file__).resolve().parent.parent.parent.parent
        return root_dir / p

    @property
    def email_ready(self) -> bool:
        return bool(self.EMAIL_ENABLED and self.EMAIL_ADDRESS and self.EMAIL_PASSWORD)

    @property
    def qstash_current_signing_key(self) -> str:
        return self.QSTASH_CURRENT_SIGNING_KEY

    @property
    def qstash_next_signing_key(self) -> str:
        return self.QSTASH_NEXT_SIGNING_KEY

    @property
    def nebius_api_key(self) -> str:
        return self.NEBIUS_API_KEY or os.getenv("NEBIUS_API_KEY", "")

    @property
    def openai_api_key(self) -> str:
        return self.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")

    @property
    def fallback_gpt_model(self) -> str:
        return self.FALLBACK_GPT_MODEL

    @property
    def typesafe_api_key(self) -> str:
        return self.TYPESAFE_API_KEY

    @property
    def typesafe_ready(self) -> bool:
        return bool(self.typesafe_api_key)

    @property
    def qstash_ready(self) -> bool:
        return bool(self.QSTASH_CURRENT_SIGNING_KEY)

    @property
    def grafana_user_id(self) -> str:
        return self.GRAFANA_USER_ID or os.getenv("GRAFANA_USER_ID", "")

    @property
    def question_generator_provider(self) -> str:
        return self.QUESTION_GENERATOR_PROVIDER

    @property
    def question_generator_model(self) -> str:
        return self.QUESTION_GENERATOR_MODEL or "gemini-flash-lite-latest"

    @property
    def nebius_question_model(self) -> str:
        return self.NEBIUS_QUESTION_MODEL

    @property
    def nebius_question_fallback_model(self) -> str:
        return self.NEBIUS_QUESTION_FALLBACK_MODEL


settings = Settings()


