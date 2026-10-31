import json
from datetime import date

from app.ai.error_explainer import explain_payment_error
from app.ai.gemini import GeminiAIProvider
from app.ai.provider import AIProviderError


def test_payment_error_is_sent_to_gemini_as_json(monkeypatch):
    captured = {}

    class FakeProvider:
        timeout_seconds = 30
        max_output_tokens = 1024

        def generate_json(self, prompt, schema):
            captured["prompt"] = prompt
            captured["schema"] = schema
            return {
                "message": "[WORKER] needs one active payment profile.",
                "explanation": "There is no single profile valid on the payment date.",
                "steps": [
                    "Open [WORKER]'s worker record.",
                    "Open Payment Details.",
                    "Add one effective bank-transfer profile.",
                ],
            }

    monkeypatch.setattr(
        GeminiAIProvider, "from_environment", classmethod(lambda cls: FakeProvider())
    )
    result = explain_payment_error(
        error="Expected exactly one effective payment profile for Riley Singh",
        pay_run_id=27,
        payment_date=date(2026, 10, 30),
    )

    assert result["message"] == "Riley Singh needs one active payment profile."
    json_input = json.loads(captured["prompt"].split("Input:\n", 1)[1])
    assert json_input["technical_error"].endswith("[WORKER]")
    assert "Riley Singh" not in captured["prompt"]
    assert "pay_run_id" not in json_input
    assert json_input["payment_date"] == "2026-10-30"


def test_payment_error_has_actionable_fallback_when_gemini_fails(monkeypatch):
    class FailingProvider:
        timeout_seconds = 30
        max_output_tokens = 1024

        def generate_json(self, prompt, schema):
            raise AIProviderError("unavailable")

    monkeypatch.setattr(
        GeminiAIProvider,
        "from_environment",
        classmethod(lambda cls: FailingProvider()),
    )
    result = explain_payment_error(
        error=(
            "Expected exactly one effective payment profile for "
            "Riley Singh Demo 199"
        ),
        pay_run_id=27,
        payment_date=date(2026, 10, 30),
    )

    assert "Riley Singh Demo 199" in result["message"]
    assert "30/10/2026" in result["explanation"]
    assert any("Payment Details" in step for step in result["steps"])
