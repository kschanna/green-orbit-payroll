from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.models.payroll_readiness_run import PayrollReadinessRun
from app.payroll_readiness_service import run_payroll_readiness

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = lambda request: request.session.get("csrf_token", "")


@router.get("/ui/payroll-readiness", response_class=HTMLResponse)
def latest_readiness(request: Request):
    with SessionLocal() as db:
        run = db.scalar(select(PayrollReadinessRun).order_by(PayrollReadinessRun.id.desc()).limit(1))
    if run is None:
        return templates.TemplateResponse(request=request, name="payroll_readiness.html", context={"run": None})
    return RedirectResponse(f"/ui/payroll-readiness/{run.id}", status_code=303)


@router.get("/ui/payroll-readiness/{run_id}", response_class=HTMLResponse)
def readiness_report(request: Request, run_id: int):
    with SessionLocal() as db:
        run = db.get(PayrollReadinessRun, run_id)
        if run is None:
            raise HTTPException(404, "Payroll readiness run not found")
        db.expunge(run)
    return templates.TemplateResponse(request=request, name="payroll_readiness.html", context={"run": run})


@router.post("/ui/payroll-readiness/run")
def run_readiness(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    with SessionLocal() as db:
        run = run_payroll_readiness(db, triggered_by_user_id=user_id)
    return RedirectResponse(f"/ui/payroll-readiness/{run.id}", status_code=303)
