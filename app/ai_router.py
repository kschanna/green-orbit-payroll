import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai import (
    AIConfigurationError,
    AIProviderError,
    AIService,
    AITimeoutError,
    ConversationMessage,
)
from app.ai.gemini import GeminiAIProvider
from app.ai.tools import read_only_tools


MAX_CONVERSATION_CHARACTERS = 24_000

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be blank")
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_conversation(self) -> "ChatRequest":
        if self.messages[0].role != "user":
            raise ValueError("Conversation must start with a user message")
        if self.messages[-1].role != "user":
            raise ValueError("Conversation must end with a user message")

        for previous, current in zip(self.messages, self.messages[1:]):
            if previous.role == current.role:
                raise ValueError("Conversation message roles must alternate")

        total_characters = sum(len(message.content) for message in self.messages)
        if total_characters > MAX_CONVERSATION_CHARACTERS:
            raise ValueError("Conversation is too large")
        return self


class ChartDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    values: list[float] = Field(min_length=1, max_length=24)


class ChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["bar", "line"]
    title: str = Field(min_length=1, max_length=120)
    labels: list[str] = Field(min_length=1, max_length=24)
    datasets: list[ChartDataset] = Field(min_length=1, max_length=4)
    value_format: Literal["currency", "number"] = "number"

    @model_validator(mode="after")
    def dataset_lengths_match_labels(self) -> "ChartSpec":
        if any(len(dataset.values) != len(self.labels) for dataset in self.datasets):
            raise ValueError("Chart dataset length must match labels")
        return self


class ChatResponse(BaseModel):
    message: ChatMessage
    charts: list[ChartSpec] = Field(default_factory=list)


def get_ai_service() -> AIService:
    return AIService(GeminiAIProvider.from_environment(), read_only_tools())


def get_worker_ai_service() -> AIService:
    # Worker conversations intentionally have no database tools. This keeps
    # the assistant useful for explanations without risking cross-worker data.
    return AIService(GeminiAIProvider.from_environment())


@router.get("/ui/ai-assistant", response_class=HTMLResponse)
def ai_assistant_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="ai_assistant.html",
        context={},
    )


@router.get("/portal/ai-assistant", response_class=HTMLResponse)
def worker_ai_assistant_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="ai_assistant.html",
        context={
            "assistant_base": "portal_base.html",
            "chat_endpoint": "/portal/api/ai/chat",
            "conversation_storage_key": "green-orbit-worker-ai-conversation",
            "worker_mode": True,
        },
    )


@router.post("/api/ai/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    service: AIService = Depends(get_ai_service),
):
    messages = [
        ConversationMessage(role=message.role, content=message.content)
        for message in data.messages
    ]

    try:
        response = await asyncio.to_thread(service.reply, messages)
    except AIConfigurationError:
        raise HTTPException(503, "AI Assistant is not configured")
    except AITimeoutError:
        raise HTTPException(504, "AI Assistant request timed out")
    except (AIProviderError, ValueError):
        raise HTTPException(502, "AI Assistant is temporarily unavailable")

    return ChatResponse(
        message=ChatMessage(role="assistant", content=response.text),
        charts=list(response.charts),
    )


@router.post("/portal/api/ai/chat", response_model=ChatResponse)
async def worker_chat(
    data: ChatRequest,
    service: AIService = Depends(get_worker_ai_service),
):
    messages = [
        ConversationMessage(role=message.role, content=message.content)
        for message in data.messages
    ]
    try:
        response = await asyncio.to_thread(service.reply, messages)
    except AIConfigurationError:
        raise HTTPException(503, "AI Assistant is not configured")
    except AITimeoutError:
        raise HTTPException(504, "AI Assistant request timed out")
    except (AIProviderError, ValueError):
        raise HTTPException(502, "AI Assistant is temporarily unavailable")
    return ChatResponse(
        message=ChatMessage(role="assistant", content=response.text),
        charts=list(response.charts),
    )
