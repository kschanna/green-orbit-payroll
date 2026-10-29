from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Literal, Protocol, Sequence


@dataclass(frozen=True)
class ConversationMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class AITool:
    name: str
    description: str
    parameters_json_schema: dict[str, Any]
    execute: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AIProviderResult:
    text: str
    charts: tuple[dict[str, Any], ...] = ()
    sources: tuple[dict[str, Any], ...] = ()


class AIProvider(Protocol):
    def generate(
        self,
        messages: Sequence[ConversationMessage],
        tools: Sequence[AITool] = (),
        context: str | None = None,
    ) -> AIProviderResult:
        """Generate an assistant reply for a validated conversation."""


class AIProviderError(RuntimeError):
    """A safe base error for AI provider failures."""


class AIConfigurationError(AIProviderError):
    """The AI provider is not configured for use."""


class AITimeoutError(AIProviderError):
    """The AI provider did not respond within the configured timeout."""
