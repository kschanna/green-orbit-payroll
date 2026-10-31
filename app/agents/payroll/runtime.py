"""Google ADK runtime for the policy-controlled payroll coordinator."""

import asyncio
import os
from typing import Any

from google.adk import Runner
from google.adk.agents import Agent
from google.adk.sessions import InMemorySessionService, VertexAiSessionService
from google.genai import types


APP_NAME = "green_orbit_payroll"
_LOCAL_SESSIONS = InMemorySessionService()


def adk_enabled() -> bool:
    return os.getenv("PAYROLL_AGENT_ADK_ENABLED", "").lower() == "true"


def _session_service():
    engine_id = os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", "").strip()
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.getenv(
        "GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", "australia-southeast1"
    ).strip()
    if engine_id and project:
        return VertexAiSessionService(
            project=project, location=location, agent_engine_id=engine_id
        ), "vertex_managed_session"
    return _LOCAL_SESSIONS, "local_adk_session"


def _snapshot(run_id: int) -> dict[str, Any]:
    """Return non-sensitive workflow state for ADK reasoning."""
    # Ensure every SQLAlchemy relationship target is registered when this
    # runtime is invoked from a worker or CLI rather than the web process.
    import app.main  # noqa: F401

    from app.database import SessionLocal
    from app.models.payroll_agent_run import PayrollAgentRun
    from app.models.payroll_agent_step import PayrollAgentStep
    from sqlalchemy import select

    with SessionLocal() as db:
        run = db.get(PayrollAgentRun, run_id)
        if run is None:
            return {"error": "run_not_found"}
        steps = list(db.scalars(select(PayrollAgentStep).where(
            PayrollAgentStep.run_id == run_id
        ).order_by(PayrollAgentStep.sequence)))
        return {
            "run_id": run.id,
            "status": run.status,
            "current_step": run.current_step,
            "blockers": run.blockers,
            "record_ids": dict(run.records or {}),
            "steps": [
                {"key": step.step_key, "status": step.status}
                for step in steps
            ],
        }


def _agent(run_id: int, *, hours_review_verified: bool) -> Agent:
    def inspect_payroll_run(target_run_id: int) -> dict:
        """Inspect current non-sensitive state for the specified payroll run."""
        if target_run_id != run_id:
            return {"error": "run_out_of_scope"}
        return _snapshot(target_run_id)

    def advance_payroll_workflow(target_run_id: int) -> dict:
        """Advance the scoped workflow using deterministic, idempotent domain tools.

        This tool cannot approve the final invoice or payroll. Hours are treated as
        reviewed only when the Green Orbit server verified that human action.
        """
        if target_run_id != run_id:
            return {"error": "run_out_of_scope"}
        from app.payroll_agent_service import _advance_payroll_agent_run

        _advance_payroll_agent_run(
            target_run_id, hours_confirmed=hours_review_verified
        )
        return _snapshot(target_run_id)

    return Agent(
        name="green_orbit_payroll_agent",
        model=os.getenv("PAYROLL_AGENT_ADK_MODEL", "gemini-3.8-flash"),
        description="Coordinates a resumable payroll draft workflow.",
        instruction=f"""
You are the Green Orbit Payroll Agent coordinating run {run_id}.
First call inspect_payroll_run for run {run_id}. Then decide whether the run can
advance. Call advance_payroll_workflow for run {run_id} when deterministic tools
can safely do more work. Never use another run ID.

This turn was explicitly requested by the Green Orbit server. If the inspected
status is running, failed, or waiting_for_requirements, call
advance_payroll_workflow so its bounded checks can start or recheck the run. If
hours-review authority below is true, also call it for waiting_for_human. Do not
call it for completed, cancelled, or awaiting_human_approval runs.

The application, not you, calculates hours, tax, super, invoices, or payroll.
You may not invent business facts, alter tool arguments to claim human approval,
expose TFNs or bank values, approve financial drafts, complete payments, or bypass
a blocker. If a tool pauses for missing requirements or human review, explain the
pause and stop. If drafts are ready, hand them to a human and stop.

Server-verified hours-review authority for this invocation: {hours_review_verified}.
""",
        tools=[inspect_payroll_run, advance_payroll_workflow],
    )


async def _run(run_id: int, *, hours_review_verified: bool) -> dict[str, Any]:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for the payroll ADK agent")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
    os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv(
        "PAYROLL_AGENT_VERTEX_LOCATION", "australia-southeast1"
    )

    session_service, session_mode = _session_service()
    user_id = "green-orbit-system"
    session_id = f"payroll-run-{run_id}"
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if session is None:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={"payroll_run_id": run_id},
        )

    runner = Runner(
        agent=_agent(run_id, hours_review_verified=hours_review_verified),
        app_name=APP_NAME,
        session_service=session_service,
    )
    message = types.Content(
        role="user",
        parts=[types.Part.from_text(
            text=f"Observe payroll run {run_id} and take the next safe action."
        )],
    )
    trace: list[dict[str, Any]] = []
    advanced = False
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        calls = []
        for call in event.get_function_calls() or []:
            calls.append({"name": call.name, "args": dict(call.args or {})})
            if call.name == "advance_payroll_workflow":
                advanced = True
        responses = [
            {"name": response.name, "result": response.response}
            for response in (event.get_function_responses() or [])
        ]
        if calls or responses:
            trace.append({"author": event.author, "calls": calls, "responses": responses})
        if event.is_final_response() and event.content and event.content.parts:
            final_text = " ".join(
                part.text for part in event.content.parts if getattr(part, "text", None)
            )[:2000]

    return {
        "runtime": "google_adk_vertex",
        "model": os.getenv("PAYROLL_AGENT_ADK_MODEL", "gemini-3.8-flash"),
        "session_mode": session_mode,
        "session_id": session_id,
        "advanced": advanced,
        "events": trace[-20:],
        "final_response": final_text,
    }


def run_payroll_agent(run_id: int, *, hours_review_verified: bool = False) -> dict[str, Any]:
    """Run one ADK reasoning turn for a payroll workflow."""
    return asyncio.run(_run(run_id, hours_review_verified=hours_review_verified))
