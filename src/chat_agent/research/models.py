from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class ResearchMode(str, Enum):
    """Execution mode for research and deliberation."""
    TECHNICAL = "technical"
    DELIBERATE = "deliberate"


class TaskStatus(str, Enum):
    """Status lifecycle for individual research tasks."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TodoItem(BaseModel):
    """Individual milestone item in the research TODO board."""
    id: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    details: str = ""
    updated_at: float = 0.0


class ResearchSource(BaseModel):
    """Normalized research citation source."""
    title: str = "Source"
    url: str = ""
    snippet: str = ""
    provider: str = ""


class ToolOutputEntry(BaseModel):
    """Cached execution result for an individual intelligence or generation tool."""
    status: Literal["ok", "failed", "skipped"] = "ok"
    fetched_at: float = 0.0
    data: Any = None
    error: str = ""


class ModelUsage(BaseModel):
    """Token metrics and cost estimation for an individual model execution."""
    model_name: str
    provider: str
    role: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    is_estimated: bool = True


class TokenEconomics(BaseModel):
    """Aggregated token economics across all models and tools used in a job."""
    models_used: list[ModelUsage] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_estimated_cost_usd: float = 0.0
    is_estimated: bool = True


class ResearchJobState(BaseModel):
    """Complete persistent state for a research or deliberation job."""
    job_id: str
    command: Literal["/research", "/deliberate"] = "/research"
    topic: str
    mode: ResearchMode = ResearchMode.TECHNICAL
    target_word_count: int = 2500
    channel_id: str = ""
    thread_ts: str = ""
    status_msg_ts: str = ""
    user_id: str = ""
    status: TaskStatus = TaskStatus.IN_PROGRESS
    todos: list[TodoItem] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    executive_summary: str = ""
    full_report_markdown: str = ""
    pdf_path: str = ""
    word_count: int = 0
    token_economics: TokenEconomics = Field(default_factory=TokenEconomics)
    checkpoint: str = "initial"
    attempt: int = 1
    tool_outputs: dict[str, ToolOutputEntry] = Field(default_factory=dict)
    error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
