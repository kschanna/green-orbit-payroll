import json
import re
from datetime import date

from app.ai.gemini import GeminiAIProvider
from app.ai.provider import AIProviderError


def _payment_fallback(error: str, payment_date: date | None) -> dict:
    date_text = payment_date.strftime("%d/%m/%Y") if payment_date else "the payment date"
    worker_match = re.search(
        r"payment profile for (.+)$", error, flags=re.IGNORECASE
    )
    worker = worker_match.group(1) if worker_match else "the affected worker"
    if "exactly one effective payment profile" in error.lower():
        return {
            "message": f"{worker} does not have one valid payment profile.",
            "explanation": (
                f"Payment preparation needs exactly one bank-transfer profile "
                f"effective on {date_text}. None exists, or multiple profiles overlap."
            ),
            "steps": [
                f"Open {worker}'s worker record.",
                "Open Payment Details.",
                f"Add or update a bank-transfer profile effective on {date_text}.",
                "If profiles overlap, end-date the older profile so only one is effective.",
                "Return to this pay run and select Prepare Payments again.",
            ],
        }
    return {
        "message": error,
        "explanation": "The payment batch was not created because a required payroll setup check failed.",
        "steps": [
            "Review the affected worker and pay-run setup.",
            "Correct the item named in the error.",
            "Return to this pay run and select Prepare Payments again.",
        ],
    }


def explain_payment_error(
    *, error: str, pay_run_id: int, payment_date: date | None,
) -> dict:
    fallback = _payment_fallback(error, payment_date)
    worker_match = re.search(
        r"payment profile for (.+)$", error, flags=re.IGNORECASE
    )
    worker_name = worker_match.group(1) if worker_match else None
    redacted_error = (
        error.replace(worker_name, "[WORKER]") if worker_name else error
    )
    payload = {
        "operation": "prepare_payments",
        "payment_date": payment_date.isoformat() if payment_date else None,
        "technical_error": redacted_error,
        "available_user_action": (
            "Open the worker record, select Payment Details, and maintain "
            "effective-dated bank-transfer profiles."
        ),
    }
    prompt = (
        "Rewrite this payroll application error for an end user. Return JSON only "
        "with keys message (one sentence), explanation (one or two sentences), and "
        "steps (an array of 3 to 5 short imperative instructions). Preserve placeholders "
        "such as [WORKER] exactly. Preserve dates supplied. Do not invent screens, records, causes, or "
        "actions. Do not mention AI or JSON. Input:\n"
        + json.dumps(payload)
    )
    try:
        result = GeminiAIProvider.from_environment()
        result.timeout_seconds = min(result.timeout_seconds, 20)
        parsed = result.generate_json(prompt, {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "explanation": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 5,
                },
            },
            "required": ["message", "explanation", "steps"],
            "additionalProperties": False,
        })
        message = parsed.get("message")
        explanation = parsed.get("explanation")
        steps = parsed.get("steps")
        if (
            not isinstance(message, str)
            or not isinstance(explanation, str)
            or not isinstance(steps, list)
            or not 3 <= len(steps) <= 5
            or not all(isinstance(step, str) and step.strip() for step in steps)
        ):
            return fallback
        def restore_worker(value: str) -> str:
            return (
                value.replace("[WORKER]", worker_name)
                if worker_name else value
            )

        return {
            "message": restore_worker(message.strip()),
            "explanation": restore_worker(explanation.strip()),
            "steps": [restore_worker(step.strip()) for step in steps],
        }
    except (AIProviderError, json.JSONDecodeError, TypeError, ValueError):
        return fallback
