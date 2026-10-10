"""Abstract base class cho LLM provider."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class LLMMessage:
    role: str
    content: str = ''
    tool_calls: Optional[List[dict]] = None
    tool_name: str = ''
    tool_payload: Optional[dict] = None


@dataclass
class LLMResult:
    text: str = ''
    tool_calls: List[dict] = field(default_factory=list)
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    model_name: str = ''
    latency_ms: int = 0
    raw: Any = None


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, messages: List[LLMMessage], tools: List[dict]) -> LLMResult:
        """Gọi LLM và trả về LLMResult.

        ``messages`` là danh sách ``LLMMessage`` với role ``user``/``assistant``/``tool``.
        ``tools`` là danh sách schema theo format nội bộ ``chatbot.schemas.TOOL_SCHEMAS``.
        """
        raise NotImplementedError
