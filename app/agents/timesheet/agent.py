"""Google ADK definition for the policy-controlled Timesheet Agent."""

import os
from datetime import date

from google.adk.agents import Agent

from app.database import SessionLocal
from app.tfn_declaration_agent import missing_tfn_declaration_alert


def inspect_tfn_declaration(engagement_id: int, as_of: str) -> dict:
    """Check TFN declaration readiness without returning sensitive values."""
    check_date = date.fromisoformat(as_of)
    with SessionLocal() as db:
        alert = missing_tfn_declaration_alert(
            db, engagement_id, as_of=check_date
        )
    return {
        "ready": alert is None,
        "issue": alert,
    }


root_agent = Agent(
    name="green_orbit_timesheet_agent",
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    description=(
        "Investigates timesheet readiness and safely coordinates compliance tasks."
    ),
    instruction="""
You are the Green Orbit Timesheet Agent. Keep timesheets ready for payroll.
Use tools for all business facts. Never request, reveal, or infer a TFN or bank
account value. You may investigate and recommend actions. You must not approve
timesheets, change worker records, process payroll, or release payments.
When a declaration is missing, explain the blocker and hand it to a human.
""",
    tools=[inspect_tfn_declaration],
)
