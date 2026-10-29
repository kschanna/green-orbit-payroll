from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.agents.timesheet.agent import root_agent
from app.database import SessionLocal
from app.models.agent_action import AgentAction
from app.models.agent_run import AgentRun
from app.models.agent_task import AgentTask
from app.models.user import User
from app.models.worker import Worker
from app.timesheet_agent_service import AGENT_NAME


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = lambda request: request.session.get("csrf_token", "")


def _duration_ms(run: AgentRun, now: datetime) -> int | None:
    if run.created_at is None:
        return None
    start = run.created_at
    end = run.completed_at or (now if run.status == "running" else None)
    if end is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, round((end - start).total_seconds() * 1000))


@router.get("/ui/agent-monitor", response_class=HTMLResponse)
def agent_monitor(request: Request):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user_id = request.session.get("user_id")
        user = db.get(User, user_id) if user_id is not None else None
        if user is None:
            raise HTTPException(401, "Authentication required")
        if user.role != "admin":
            raise HTTPException(403, "Administrator access required")

        runs = list(db.scalars(
            select(AgentRun)
            .where(AgentRun.agent_name == AGENT_NAME)
            .order_by(AgentRun.id.desc())
            .limit(50)
        ))
        tasks = list(db.scalars(
            select(AgentTask)
            .where(AgentTask.agent_name == AGENT_NAME)
            .order_by(AgentTask.updated_at.desc(), AgentTask.id.desc())
            .limit(50)
        ))
        actions = list(db.scalars(
            select(AgentAction)
            .join(AgentRun, AgentAction.run_id == AgentRun.id)
            .where(AgentRun.agent_name == AGENT_NAME)
            .order_by(AgentAction.id.desc())
            .limit(50)
        ))
        worker_ids = {task.worker_id for task in tasks if task.worker_id is not None}
        workers = {
            worker.id: worker
            for worker in db.scalars(select(Worker).where(Worker.id.in_(worker_ids)))
        } if worker_ids else {}

        counts = dict(db.execute(
            select(AgentTask.status, func.count(AgentTask.id))
            .where(AgentTask.agent_name == AGENT_NAME)
            .group_by(AgentTask.status)
        ).all())
        failures_24h = db.scalar(
            select(func.count(AgentRun.id)).where(
                AgentRun.agent_name == AGENT_NAME,
                AgentRun.status == "failed",
                AgentRun.created_at >= now - timedelta(hours=24),
            )
        ) or 0

    try:
        adk_version = version("google-adk")
    except PackageNotFoundError:
        adk_version = "not installed"

    run_rows = [{"run": run, "duration_ms": _duration_ms(run, now)} for run in runs]
    health = "degraded" if failures_24h else "healthy"
    tool_names = [getattr(tool, "__name__", tool.__class__.__name__) for tool in root_agent.tools]
    return templates.TemplateResponse(
        request=request,
        name="agent_monitor.html",
        context={
            "agent_name": AGENT_NAME,
            "adk_version": adk_version,
            "model_name": str(root_agent.model),
            "tool_names": tool_names,
            "health": health,
            "counts": counts,
            "failures_24h": failures_24h,
            "runs": run_rows,
            "tasks": tasks,
            "actions": actions,
            "workers": workers,
            "last_refreshed": now,
        },
    )
