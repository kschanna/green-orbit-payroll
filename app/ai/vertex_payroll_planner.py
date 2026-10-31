import json
import os


ALLOWED_STEPS = [
    "plan", "create_timesheet", "confirm_hours", "readiness",
    "approve_timesheet", "draft_invoice", "draft_payroll", "reconcile", "handoff",
]


def build_payroll_plan(*, assignment_id: int, period_start: str, period_end: str) -> dict:
    """Ask Vertex for non-authoritative planning context, or use the policy template."""
    template = {
        "planner": "approved_template",
        "summary": "Create and confirm hours, validate readiness, create both drafts, reconcile, and hand off.",
        "steps": ALLOWED_STEPS,
        "policy": "human_confirm_hours_and_financial_drafts",
    }
    if os.getenv("VERTEX_AI_PLANNING_ENABLED", "").lower() != "true":
        return template
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "australia-southeast1")
    model = os.getenv("VERTEX_AI_PLANNING_MODEL", "")
    if not project or not model:
        return {**template, "fallback_reason": "vertex_configuration_incomplete"}
    try:
        from google import genai
        from google.genai import types

        prompt = (
            "Create a concise execution rationale for a payroll draft workflow. "
            "Do not add, remove, reorder, or execute steps. Do not request personal data. "
            f"Assignment ID: {assignment_id}; period: {period_start} to {period_end}; "
            f"required steps: {', '.join(ALLOWED_STEPS)}. Return JSON with a summary string."
        )
        with genai.Client(
            vertexai=True, project=project, location=location,
            http_options=types.HttpOptions(timeout=10_000),
        ) as client:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                        "required": ["summary"],
                        "additionalProperties": False,
                    },
                    max_output_tokens=256,
                ),
            )
        planned = json.loads(response.text)
        return {
            **template,
            "planner": "vertex_ai",
            "model": model,
            "summary": planned["summary"][:1000],
        }
    except Exception:
        return {**template, "fallback_reason": "vertex_temporarily_unavailable"}
