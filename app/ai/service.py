from collections.abc import Sequence

from app.ai.provider import AIProvider, AIProviderResult, AITool, ConversationMessage


class AIService:
    def __init__(self, provider: AIProvider, tools: Sequence[AITool] = ()):
        self.provider = provider
        self.tools = tools

    def reply(self, messages: Sequence[ConversationMessage]) -> AIProviderResult:
        response = self.provider.generate(messages, self.tools)
        text = response.text.strip()
        if not text:
            raise ValueError("AI provider returned an empty response")
        return AIProviderResult(text=text, charts=response.charts)
