from typing import Optional

from pydantic import BaseModel


class QuestionAnswerSchema(BaseModel):
    """Schema representing a question, hint, and evaluation score."""
    id: int
    question: str
    hint: str = ""
    score: Optional[float] = None
