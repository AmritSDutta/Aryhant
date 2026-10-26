from __future__ import annotations

from chat_agent.question_generator.base_question_generator import BaseQuestionGenerator
from chat_agent.question_generator.gemini_question_generator import GeminiQuestionGenerator
from chat_agent.question_generator.nebius_question_generator import NebiusQuestionGenerator

QuestionGenerator = BaseQuestionGenerator

__all__ = [
    "BaseQuestionGenerator",
    "GeminiQuestionGenerator",
    "NebiusQuestionGenerator",
    "QuestionGenerator",
]
