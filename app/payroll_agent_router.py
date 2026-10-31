from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.engagement import Engagement
from app.models.organisation import Organisation
from app.models.payroll_agent_run import PayrollAgentRun
from app.models.payroll_agent_step import PayrollAgentStep
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.user import User
from app.models.worker import Worker
from app.payroll_agent_service import (
    advance_payroll_agent_run,
    approve_payroll_agent_handoff,
    start_payroll_agent_run,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = lambda request: request.session.get("csrf_token", "")


def _admin(request, db):
    user = db.get(User, request.session.get("user_id"))
    if user is None:
        raise HTTPException(401, "Authentication required")
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


@router.get("/ui/payroll-agent", response_class=HTMLResponse)
def payroll_agent_page(request: Request):
    with SessionLocal() as db:
        _admin(request, db)
        candidates = db.execute(
            select(Assignment, PBTSchedulePeriod, Worker, Organisation)
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Worker, Worker.id == Engagement.worker_id)
            .join(Organisation, Organisation.id == Assignment.customer_id)
            .join(PBTSchedulePeriod, PBTSchedulePeriod.pbt_schedule_id == Assignment.pbt_schedule_id)
            .where(PBTSchedulePeriod.schedule_type == "timesheet")
            .order_by(
                Worker.last_name,
                Worker.first_name,
                PBTSchedulePeriod.period_start.desc(),
            )
            .limit(100)
        ).all()
        runs = list(db.scalars(
            select(PayrollAgentRun).order_by(PayrollAgentRun.id.desc()).limit(50)
        ))
        worker_ids = {run.worker_id for run in runs}
        workers = {item.id: item for item in db.scalars(
            select(Worker).where(Worker.id.in_(worker_ids))
        )} if worker_ids else {}
    return templates.TemplateResponse(request=request, name="payroll_agent.html", context={
        "candidates": candidates, "runs": runs, "workers": workers,
    })


@router.post("/ui/payroll-agent/runs")
def start_run(
    request: Request,
    assignment_id: int = Form(...),
    period_id: int = Form(...),
):
    with SessionLocal() as db:
        user = _admin(request, db)
        user_id = user.id
    run = start_payroll_agent_run(
        assignment_id, period_id, triggered_by_user_id=user_id
    )
    return RedirectResponse(f"/ui/payroll-agent/runs/{run.id}", status_code=303)


@router.get("/ui/payroll-agent/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: int):
    with SessionLocal() as db:
        _admin(request, db)
        run = db.get(PayrollAgentRun, run_id)
        if run is None:
            raise HTTPException(404, "Payroll agent run not found")
        steps = list(db.scalars(select(PayrollAgentStep).where(
            PayrollAgentStep.run_id == run.id
        ).order_by(PayrollAgentStep.sequence)))
        worker = db.get(Worker, run.worker_id)
        assignment = db.get(Assignment, run.assignment_id)
        customer = db.get(Organisation, assignment.customer_id)
        period = db.get(PBTSchedulePeriod, run.pbt_schedule_period_id)
    return templates.TemplateResponse(request=request, name="payroll_agent_run.html", context={
        "run": run, "steps": steps, "worker": worker,
        "assignment": assignment, "customer": customer, "period": period,
    })


@router.post("/ui/payroll-agent/runs/{run_id}/confirm-hours")
def confirm_hours(request: Request, run_id: int):
    with SessionLocal() as db:
        _admin(request, db)
    try:
        advance_payroll_agent_run(run_id, hours_confirmed=True)
    except Exception:
        pass
    return RedirectResponse(f"/ui/payroll-agent/runs/{run_id}", status_code=303)


@router.post("/ui/payroll-agent/runs/{run_id}/retry")
def retry_run(request: Request, run_id: int):
    with SessionLocal() as db:
        _admin(request, db)
    try:
        advance_payroll_agent_run(run_id, hours_confirmed=True)
    except Exception:
        pass
    return RedirectResponse(f"/ui/payroll-agent/runs/{run_id}", status_code=303)


@router.post("/ui/payroll-agent/runs/{run_id}/approve-handoff")
def approve_handoff(request: Request, run_id: int):
    with SessionLocal() as db:
        user = _admin(request, db)
        user_id = user.id
    try:
        approve_payroll_agent_handoff(run_id, approved_by_user_id=user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/ui/payroll-agent/runs/{run_id}", status_code=303)
