import os
import socket
from collections.abc import Sequence
from typing import Any

from app.ai.provider import (
    AIConfigurationError,
    AIProviderError,
    AIProviderResult,
    AITool,
    AITimeoutError,
    ConversationMessage,
)


DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_TOKENS = 1024
MAX_TOOL_ROUNDS = 3

SYSTEM_INSTRUCTION = """You are the Green Orbit AI Assistant.
Help users understand workforce management, timesheet, payroll, and invoicing
information clearly and accurately. You may read Green Orbit business data
only by calling the provided tools. Never claim to have retrieved data unless
a tool returned it. You cannot create, update, delete, submit, approve, send,
or otherwise change anything. Do not request or expose passwords, API keys,
TFNs, bank details, or other highly sensitive information. When tool results
are empty or ambiguous, say so rather than guessing. Mention when a result was
truncated.
When business data is returned, tell a concise narrative: lead with the main
answer, explain the most important totals or trends in plain language, then
add supporting detail and any data caveats. Do not simply repeat raw JSON or
turn every result into a long table.
For totals, trends, a business story, or charts about one assignment, call
get_assignment_business_summary directly. For the same questions about one
worker, call get_worker_business_summary directly. Do not also call a detail
tool or the global payroll summary when one of those scoped summary tools can
answer the question. Omit date_from and date_to unless the user specified a
date range; the tool will apply its documented default period. Never invent a
date range.
For payroll readiness, missing setup data, or timesheet exceptions across the
workforce, call get_payroll_readiness directly. Treat its issue codes and
severity as authoritative; do not infer that a missing item exists from other
tools.
"""


class GeminiAIProvider:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    @classmethod
    def from_environment(cls) -> "GeminiAIProvider":
        return cls(
            api_key=os.getenv("GEMINI_API_KEY", ""),
            model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        )

    def generate(
        self,
        messages: Sequence[ConversationMessage],
        tools: Sequence[AITool] = (),
        context: str | None = None,
    ) -> AIProviderResult:
        if not self.api_key.strip():
            raise AIConfigurationError("Gemini API key is not configured")

        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:
            raise AIConfigurationError(
                "Google Gen AI SDK is not installed"
            ) from exc

        contents = [
            types.Content(
                role="model" if message.role == "assistant" else "user",
                parts=[types.Part.from_text(text=message.content)],
            )
            for message in messages
        ]
        charts: list[dict[str, Any]] = []
        chart_titles: set[str] = set()
        sources: list[dict[str, Any]] = []
        source_keys: set[tuple[str, str]] = set()

        tool_map = {tool.name: tool for tool in tools}
        gemini_tools = []
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters_json_schema=tool.parameters_json_schema,
                )
                for tool in tools
            ]
            gemini_tools = [types.Tool(function_declarations=declarations)]

        system_instruction = SYSTEM_INSTRUCTION
        if context:
            system_instruction += (
                "\nThe application has verified this current screen context: "
                f"{context}. Use it only to resolve references such as 'this' or "
                "'here'. Do not claim the user is viewing anything else."
            )
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=self.max_output_tokens,
            tools=gemini_tools or None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )

        try:
            with genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    timeout=self.timeout_seconds * 1000,
                ),
            ) as client:
                for tool_round in range(MAX_TOOL_ROUNDS + 1):
                    response = client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    function_calls = response.function_calls or []
                    if not function_calls:
                        break
                    if tool_round == MAX_TOOL_ROUNDS:
                        return AIProviderResult(
                            text=(
                                "I couldn’t complete that lookup within the allowed "
                                "number of read-only tool calls. Please ask again "
                                "with a specific record type and ID."
                            ),
                            charts=tuple(charts),
                        )

                    contents.append(response.candidates[0].content)
                    response_parts = []
                    for function_call in function_calls:
                        tool = tool_map.get(function_call.name)
                        if tool is None:
                            result = {"error": "Unsupported tool"}
                        else:
                            try:
                                result = tool.execute(dict(function_call.args or {}))
                            except (TypeError, ValueError):
                                result = {"error": "Invalid tool arguments"}
                            except Exception:
                                result = {"error": "Tool temporarily unavailable"}
                        if isinstance(result, dict):
                            chart_items = result.get("_charts", [])
                            if isinstance(chart_items, list):
                                for item in chart_items:
                                    if not isinstance(item, dict):
                                        continue
                                    title = item.get("title")
                                    if isinstance(title, str) and title in chart_titles:
                                        continue
                                    charts.append(item)
                                    if isinstance(title, str):
                                        chart_titles.add(title)
                            source_items = result.get("_sources", [])
                            if isinstance(source_items, list):
                                for item in source_items:
                                    if not isinstance(item, dict):
                                        continue
                                    key = (str(item.get("type", "")), str(item.get("id", "")))
                                    if key in source_keys:
                                        continue
                                    source_keys.add(key)
                                    sources.append(item)
                            result = {
                                key: value for key, value in result.items()
                                if key not in {"_charts", "_sources"}
                            }
                        response_parts.append(types.Part.from_function_response(
                            name=function_call.name,
                            response={"result": result},
                        ))
                    # The Gemini generateContent endpoint expects function
                    # responses in a user turn. The SDK's newer interaction
                    # examples use a dedicated tool role, which this endpoint
                    # rejects with INVALID_ARGUMENT.
                    contents.append(types.Content(role="user", parts=response_parts))
        except (TimeoutError, socket.timeout) as exc:
            raise AITimeoutError("Gemini request timed out") from exc
        except errors.APIError as exc:
            if getattr(exc, "code", None) in {408, 504}:
                raise AITimeoutError("Gemini request timed out") from exc
            raise AIProviderError("Gemini request failed") from exc
        except Exception as exc:
            # Transport libraries can expose different timeout subclasses.
            if "timeout" in type(exc).__name__.lower():
                raise AITimeoutError("Gemini request timed out") from exc
            raise AIProviderError("Gemini request failed") from exc

        try:
            text = response.text
        except Exception as exc:
            raise AIProviderError("Gemini returned an invalid response") from exc

        if not text or not text.strip():
            raise AIProviderError("Gemini returned an empty response")
        return AIProviderResult(
            text=text,
            charts=tuple(charts),
            sources=tuple(sources),
        )

    def generate_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Generate a schema-constrained JSON object without tools."""
        if not self.api_key.strip():
            raise AIConfigurationError("Gemini API key is not configured")
        try:
            from google import genai
            from google.genai import errors, types
        except ImportError as exc:
            raise AIConfigurationError(
                "Google Gen AI SDK is not installed"
            ) from exc
        config = types.GenerateContentConfig(
            system_instruction=(
                "Return concise, accurate end-user guidance using only the "
                "facts and permitted actions supplied. Do not invent details."
            ),
            response_mime_type="application/json",
            response_json_schema=schema,
            max_output_tokens=max(self.max_output_tokens, 2048),
            temperature=0.1,
        )
        try:
            with genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    timeout=self.timeout_seconds * 1000,
                ),
            ) as client:
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
            value = response.parsed
            if value is None:
                import json
                value = json.loads(response.text)
            if not isinstance(value, dict):
                raise AIProviderError("Gemini returned invalid structured output")
            return value
        except (TimeoutError, socket.timeout) as exc:
            raise AITimeoutError("Gemini request timed out") from exc
        except errors.APIError as exc:
            if getattr(exc, "code", None) in {408, 504}:
                raise AITimeoutError("Gemini request timed out") from exc
            raise AIProviderError("Gemini request failed") from exc
        except AIProviderError:
            raise
        except Exception as exc:
            if "timeout" in type(exc).__name__.lower():
                raise AITimeoutError("Gemini request timed out") from exc
            raise AIProviderError("Gemini returned invalid structured output") from exc
