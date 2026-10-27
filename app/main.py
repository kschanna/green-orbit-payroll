from typing import Literal
from collections import defaultdict
from app.engagement_resolver import resolve_worker_id
from app.workers_router import router as workers_router
from app.employee_super_router import router as employee_super_router
from app.employee_payment_router import router as employee_payment_router
from app.assignment_components_router import router as assignment_components_router
from app.employee_tax_router import router as employee_tax_router
from app.employee_tfn_router import router as employee_tfn_router
from app.components_router import router as components_router
from app.leave_router import router as leave_router
from app.payments_router import router as payments_router
from app.pbt_router import router as pbt_router
from app.timesheet_run_router import router as timesheet_run_router
from app.ai_router import router as ai_router
from app.worker_documents_router import router as worker_documents_router
from app.worker_portal_router import router as worker_portal_router
import os
from pathlib import Path
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware
from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from app.database import SessionLocal
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.payroll.pay_run_processor import PayRunProcessor
from app.payroll.pay_run_lifecycle import PayRunLifecycle
from app.reports.payslip_pdf import PayslipPDFGenerator
from app.models.work_pattern import WorkPattern
from fastapi import Form
from fastapi.responses import RedirectResponse
from app.models.user import User
from app.security import verify_password
from fastapi.responses import JSONResponse
import secrets
from fastapi.responses import PlainTextResponse
from app.models.timesheet import Timesheet
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.invoice import Invoice
from app.models.assignment import Assignment
from app.models.engagement import Engagement
from app.models.worker import Worker
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.invoice_component import InvoiceComponent
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily
from app.models.assignment_component import AssignmentComponent
from app.reports.invoice_pdf import InvoicePDFGenerator
from app.invoicing.engine import delete_draft_invoice, generate_invoice
from app.models.timesheet_header import TimesheetHeader
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.pbt_schedule_rule import PBTScheduleRule
from app.pagination import build_pagination


# ============================================================
# SESSION AND ENVIRONMENT
# ============================================================

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

app = FastAPI(
    title="Green Orbit Payroll API",
    description="Australian Payroll Engine",
    version="0.5.0"
)

app.router.include_router(components_router)
app.router.include_router(workers_router)
app.router.include_router(employee_tax_router)
app.router.include_router(employee_super_router)
app.router.include_router(employee_payment_router)
app.router.include_router(assignment_components_router)
app.router.include_router(employee_tfn_router)
app.router.include_router(leave_router)
app.router.include_router(payments_router)
app.router.include_router(pbt_router)
app.router.include_router(timesheet_run_router)
app.router.include_router(ai_router)
app.router.include_router(worker_documents_router)
app.router.include_router(worker_portal_router)

session_secret = os.environ.get("SESSION_SECRET")

if not session_secret:
    raise RuntimeError("SESSION_SECRET environment variable is required")

# ============================================================
# SECURITY
# ============================================================

from app.worker_service import WorkerService
from app.workers_router import worker_data

# Worker Engagement creation UI/API


class NewEngagementInput(BaseModel):
    organisation_id: int
    engagement_type: Literal["payg_employee", "payg_contractor", "company_contractor"]
    status: str = Field(default="active", min_length=1, max_length=20)
    start_date: date = Field(default_factory=date.today)
    end_date: date | None = None


class EngagementDatesInput(BaseModel):
    start_date: date
    end_date: date | None = None


@app.get("/ui/workers/{worker_id}/engagements/new", response_class=HTMLResponse)
def new_worker_engagement_page(request: Request, worker_id: int):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)
        if worker is None:
            raise HTTPException(404, "Worker not found")
        organisations = db.scalars(
            select(Organisation).order_by(Organisation.name)
        ).all()
        return templates.TemplateResponse(
            request=request,
            name="worker_engagement_form.html",
            context={
                "worker": worker_data(worker),
                "organisations": [
                    {"id": o.id, "name": o.name} for o in organisations
                ],
                "today": date.today().isoformat(),
            },
        )


@app.post("/api/workers/{worker_id}/engagements", status_code=201)
def create_worker_engagement(worker_id: int, data: NewEngagementInput):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)
        if worker is None:
            raise HTTPException(404, "Worker not found")
        if db.get(Organisation, data.organisation_id) is None:
            raise HTTPException(422, "Organisation not found")
        if data.end_date and data.start_date and data.end_date < data.start_date:
            raise HTTPException(422, "End date cannot precede start date")
        engagement = Engagement(
            worker_id=worker_id,
            organisation_id=data.organisation_id,
            engagement_type=data.engagement_type.strip(),
            status=data.status.strip(),
            start_date=data.start_date,
            end_date=data.end_date,
        )
        db.add(engagement)
        db.commit()
        db.refresh(engagement)
        return {"id": engagement.id, "worker_id": worker_id}


@app.patch("/api/workers/{worker_id}/engagements/{engagement_id}")
def update_worker_engagement_dates(
    worker_id: int,
    engagement_id: int,
    data: EngagementDatesInput,
):
    with SessionLocal() as db:
        engagement = db.get(Engagement, engagement_id)
        if engagement is None or engagement.worker_id != worker_id:
            raise HTTPException(404, "Engagement not found")
        if data.end_date is not None and data.end_date < data.start_date:
            raise HTTPException(422, "End date cannot precede start date")
        engagement.start_date = data.start_date
        engagement.end_date = data.end_date
        db.commit()
        return {
            "id": engagement.id,
            "worker_id": worker_id,
            "start_date": engagement.start_date,
            "end_date": engagement.end_date,
        }


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        expected_token = request.session.get("csrf_token")
        supplied_token = request.headers.get("X-CSRF-Token")

        if not supplied_token:
            content_type = request.headers.get("content-type", "")

            if content_type.startswith("application/x-www-form-urlencoded"):
                from urllib.parse import parse_qs

                body = await request.body()
                fields = parse_qs(body.decode("utf-8"))
                supplied_token = fields.get("csrf_token", [None])[0]

        if (
            not expected_token
            or not isinstance(supplied_token, str)
            or not secrets.compare_digest(expected_token, supplied_token)
        ):
            return PlainTextResponse(
                "Invalid or missing CSRF token",
                status_code=403
            )

    return await call_next(request)


@app.middleware("http")
async def require_login(request: Request, call_next):
    public_paths = {"/login", "/portal/login", "/health"}

    if request.url.path in public_paths or request.url.path.startswith("/static/"):
        return await call_next(request)

    user_id = request.session.get("user_id")
    user = None

    if user_id is not None:
        with SessionLocal() as db:
            candidate = db.get(User, user_id)
            if candidate is not None and candidate.is_active:
                user = candidate

    if user is None:
        request.session.pop("user_id", None)

        if request.url.path.startswith("/api/") or request.url.path in {
            "/docs", "/redoc", "/openapi.json"
        }:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        login_path = "/portal/login" if request.url.path.startswith("/portal") else "/login"
        return RedirectResponse(login_path, status_code=303)

    is_portal_path = request.url.path.startswith("/portal")
    if is_portal_path:
        if user.role != "worker" or user.worker_id is None:
            return RedirectResponse("/dashboard", status_code=303)
        if (
            user.must_change_password
            and request.url.path not in {"/portal/change-password", "/portal/logout"}
        ):
            return RedirectResponse("/portal/change-password", status_code=303)
    elif user.role != "admin":
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=403, content={"detail": "Administrator access required"})
        return RedirectResponse("/portal", status_code=303)

    return await call_next(request)


# SessionMiddleware must be registered AFTER require_login.
# FastAPI executes the last registered middleware first.

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="green_orbit_session",
    same_site="lax",
    https_only=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
    max_age=3600,
)

# ============================================================
# WEB UI CONFIGURATION
# ============================================================

app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static"
)

templates = Jinja2Templates(
    directory="app/templates"
)

# ============================================================

# GLOBAL DATE FORMATTING

# ============================================================

def format_date_au(value):

    if value is None:

        return "—"

    if isinstance(value, (date,)):

        return value.strftime("%d/%m/%Y")

    try:

        return date.fromisoformat(str(value)).strftime("%d/%m/%Y")

    except (ValueError, TypeError):

        return str(value)

templates.env.filters["date_au"] = format_date_au

templates.env.globals["csrf_token"] = lambda request: request.session.get(
    "csrf_token", ""
)


# ============================================================
# REQUEST MODELS
# ============================================================

class PayRunCreate(BaseModel):
    organisation_id: int
    period_start: date
    period_end: date
    payment_date: date


# ============================================================
# APPLICATION HEALTH
# ============================================================

@app.get("/")
def home():
    return {
        "application": "Green Orbit Payroll Engine",
        "version": "0.5.0",
        "status": "running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# ============================================================
# WEB UI — DASHBOARD
# ============================================================

@app.get("/ui/help", response_class=HTMLResponse)
def help_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="help.html",
        context={}
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    with SessionLocal() as session:

        worker_count = session.scalar(
            select(func.count(Worker.id))
        )

        pay_run_count = session.scalar(
            select(func.count(PayRun.id))
        )

        completed_count = session.scalar(
            select(func.count(PayRun.id))
            .where(PayRun.status == "completed")
        )

        pay_runs = session.scalars(
            select(PayRun)
            .order_by(PayRun.id.desc())
            .limit(10)
        ).all()

        worker_status_rows = session.execute(
            select(Worker.active, func.count(Worker.id))
            .group_by(Worker.active)
        ).all()
        worker_status_counts = {
            bool(is_active): count
            for is_active, count in worker_status_rows
        }

        pay_run_status_rows = session.execute(
            select(PayRun.status, func.count(PayRun.id))
            .group_by(PayRun.status)
            .order_by(PayRun.status)
        ).all()

        completed_value_rows = session.execute(
            select(
                PayRun.id,
                PayRun.payment_date,
                func.coalesce(func.sum(Payslip.gross_pay), 0),
                func.coalesce(func.sum(Payslip.net_pay), 0),
            )
            .outerjoin(Payslip, Payslip.pay_run_id == PayRun.id)
            .where(PayRun.status == "completed")
            .group_by(PayRun.id, PayRun.payment_date)
            .order_by(PayRun.id.desc())
            .limit(6)
        ).all()
        completed_value_rows.reverse()

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "worker_count": worker_count,
                "pay_run_count": pay_run_count,
                "completed_count": completed_count,
                "pay_runs": pay_runs,
                "worker_chart": {
                    "labels": ["Active", "Inactive"],
                    "values": [
                        worker_status_counts.get(True, 0),
                        worker_status_counts.get(False, 0),
                    ],
                },
                "pay_run_chart": {
                    "labels": [
                        status.replace("_", " ").title()
                        for status, _ in pay_run_status_rows
                    ],
                    "values": [
                        count for _, count in pay_run_status_rows
                    ],
                },
                "completed_value_chart": {
                    "labels": [
                        f"Run #{run_id} · {payment_date.strftime('%d/%m/%Y')}"
                        for run_id, payment_date, _, _
                        in completed_value_rows
                    ],
                    "gross_values": [
                        float(gross)
                        for _, _, gross, _ in completed_value_rows
                    ],
                    "net_values": [
                        float(net)
                        for _, _, _, net in completed_value_rows
                    ],
                },
            }
        )


# ============================================================
# EMPLOYEE API
# ============================================================



@app.get("/pay-runs")
def get_pay_runs():

    with SessionLocal() as session:

        pay_runs = session.scalars(
            select(PayRun).order_by(PayRun.id)
        ).all()

        return [
            {
                "id": pay_run.id,
                "organisation_id": pay_run.organisation_id,
                "period_start": pay_run.period_start,
                "period_end": pay_run.period_end,
                "payment_date": pay_run.payment_date,
                "status": pay_run.status
            }
            for pay_run in pay_runs
        ]


@app.get("/pay-runs/{pay_run_id}/payslips")
def get_pay_run_payslips(pay_run_id: int):

    with SessionLocal() as session:

        pay_run = session.get(PayRun, pay_run_id)

        if pay_run is None:
            raise HTTPException(
                status_code=404,
                detail="Pay run not found"
            )

        rows = session.execute(
            select(Payslip, Engagement, Worker)
            .join(Engagement, Payslip.engagement_id == Engagement.id)
            .join(Worker, Engagement.worker_id == Worker.id)
            .where(Payslip.pay_run_id == pay_run_id)
            .order_by(Worker.id)
        ).all()

        return [
            {
                "payslip_id": payslip.id,
                "worker_id": worker.id,
                "worker_name": (
                    f"{worker.first_name} {worker.last_name}"
                ),
                "gross_pay": payslip.gross_pay,
                "payg_withholding": payslip.payg_withholding,
                "net_pay": payslip.net_pay,
                "superannuation": payslip.superannuation
            }
            for payslip, engagement, worker in rows
        ]


@app.get("/pay-runs/{pay_run_id}/summary")
def get_pay_run_summary(pay_run_id: int):

    with SessionLocal() as session:

        pay_run = session.get(PayRun, pay_run_id)

        if pay_run is None:
            raise HTTPException(
                status_code=404,
                detail="Pay run not found"
            )

        rows = session.execute(
            select(Payslip, Engagement, Worker)
            .join(Engagement, Payslip.engagement_id == Engagement.id)
            .join(Worker, Engagement.worker_id == Worker.id)
            .where(Payslip.pay_run_id == pay_run_id)
            .order_by(Worker.id)
        ).all()

        payslips = [
            {
                "worker_id": worker.id,
                "worker_name": (
                    f"{worker.first_name} {worker.last_name}"
                ),
                "gross_pay": str(payslip.gross_pay),
                "payg_withholding": str(payslip.payg_withholding),
                "net_pay": str(payslip.net_pay),
                "superannuation": str(payslip.superannuation)
            }
            for payslip, engagement, worker in rows
        ]

        totals = session.execute(
            select(
                func.count(Payslip.id),
                func.sum(Payslip.gross_pay),
                func.sum(Payslip.payg_withholding),
                func.sum(Payslip.net_pay),
                func.sum(Payslip.superannuation)
            )
            .where(Payslip.pay_run_id == pay_run_id)
        ).one()

        count, gross, payg, net, super_amount = totals

        gross = gross or Decimal("0.00")
        payg = payg or Decimal("0.00")
        net = net or Decimal("0.00")
        super_amount = super_amount or Decimal("0.00")

        return {
            "pay_run": {
                "id": pay_run.id,
                "organisation_id": pay_run.organisation_id,
                "period_start": pay_run.period_start,
                "period_end": pay_run.period_end,
                "payment_date": pay_run.payment_date,
                "status": pay_run.status
            },
            "payslips": payslips,
            "totals": {
                "employees_paid": count,
                "gross_pay": str(gross),
                "payg_withholding": str(payg),
                "net_pay": str(net),
                "superannuation": str(super_amount),
                "total_employer_cost": str(
                    gross + super_amount
                )
            }
        }


# ============================================================
# TIMESHEETS
# ============================================================

class WeeklyTimesheetEntry(BaseModel):
    work_date: date
    assignment_id: int | None = None
    component_definition_id: int | None = None
    hours_worked: Decimal = Field(
        ge=0,
        le=24,
        max_digits=6,
        decimal_places=2
    )


class WeeklyTimesheetCreate(BaseModel):
    engagement_id: int
    week_start: date
    entries: list[WeeklyTimesheetEntry]


class TimesheetCreate(BaseModel):
    engagement_id: int
    work_date: date
    assignment_id: int | None = None
    hours_worked: Decimal = Field(
        ge=0,
        le=24,
        max_digits=6,
        decimal_places=2
    )



# ============================================================
# GENERATE INVOICE FROM APPROVED TIMESHEET
# ============================================================

class TimesheetInvoiceInput(BaseModel):
    period_type: str
    timesheet_id: int
    engagement_id: int


@app.post("/api/timesheets/invoice")
def create_invoice_from_timesheet(data: TimesheetInvoiceInput):

    with SessionLocal() as db:

        if data.period_type == "daily":
            timesheet = db.get(Timesheet, data.timesheet_id)

            if timesheet is None or timesheet.timesheet_header_id is not None:
                raise HTTPException(
                    status_code=404,
                    detail="Daily timesheet not found"
                )

            timesheet_ids = [timesheet.id]

        elif data.period_type == "weekly":
            header = db.get(TimesheetHeader, data.timesheet_id)

            if header is None or header.period_type != "weekly":
                raise HTTPException(
                    status_code=404,
                    detail="Weekly timesheet not found"
                )

            if header.status != "approved":
                raise HTTPException(
                    status_code=409,
                    detail="Weekly timesheet must be approved"
                )

            entries = db.scalars(
                select(Timesheet)
                .where(Timesheet.timesheet_header_id == header.id)
                .order_by(Timesheet.work_date)
            ).all()

            expected_dates = {
                header.period_start + timedelta(days=i) for i in range(7)
            }
            if {entry.work_date for entry in entries} != expected_dates:
                raise HTTPException(
                    status_code=409,
                    detail="Weekly timesheet must cover Monday through Sunday"
                )

            timesheet_ids = [entry.id for entry in entries]

        elif data.period_type == "scheduled":
            header = db.get(TimesheetHeader, data.timesheet_id)
            if header is None or header.period_type != "scheduled":
                raise HTTPException(404, "Scheduled timesheet not found")
            if header.status != "approved":
                raise HTTPException(409, "Scheduled timesheet must be approved")
            if header.assignment_id != data.engagement_id:
                raise HTTPException(409, "Scheduled timesheet assignment mismatch")

            entries = db.scalars(
                select(Timesheet)
                .where(Timesheet.timesheet_header_id == header.id)
                .order_by(Timesheet.work_date, Timesheet.id)
            ).all()
            expected_dates = {
                header.period_start + timedelta(days=offset)
                for offset in range(
                    (header.period_end - header.period_start).days + 1
                )
            }
            if {entry.work_date for entry in entries} != expected_dates:
                raise HTTPException(
                    409, "Scheduled timesheet must cover its complete PBT period"
                )
            if any(entry.status != "approved" for entry in entries):
                raise HTTPException(409, "All timesheet entries must be approved")

            assignment = db.get(Assignment, header.assignment_id)
            invoice_period = db.scalar(
                select(PBTSchedulePeriod)
                .where(
                    PBTSchedulePeriod.pbt_schedule_id
                    == assignment.pbt_schedule_id,
                    PBTSchedulePeriod.schedule_type == "invoice",
                    PBTSchedulePeriod.period_start <= header.period_end,
                    PBTSchedulePeriod.period_end >= header.period_end,
                )
                .order_by(PBTSchedulePeriod.period_start)
                .limit(1)
            )
            if invoice_period is None:
                raise HTTPException(
                    409,
                    "No PBT invoice period covers this timesheet period end date",
                )
            timesheet_ids = [entry.id for entry in entries]
            scheduled_invoice_dates = {
                "issue_date": invoice_period.event_date,
                "due_date": invoice_period.customer_payment_due_date,
                "pbt_schedule_period_id": invoice_period.id,
            }

        else:
            raise HTTPException(
                status_code=422,
                detail="Invalid timesheet period type"
            )

    from app.invoicing.engine import generate_invoice_for_timesheet

    try:
        return generate_invoice_for_timesheet(
            engagement_id=data.engagement_id,
            timesheet_ids=timesheet_ids,
            **(
                scheduled_invoice_dates
                if data.period_type == "scheduled" else {}
            ),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error)
        )


def timesheet_worker_name(db, engagement_id):
    """Resolve a timesheet's canonical Worker name without Employee."""
    if engagement_id is None:
        return "Unknown"
    engagement = db.get(Engagement, engagement_id)
    if engagement is None or engagement.worker is None:
        return "Unknown"
    return f"{engagement.worker.first_name} {engagement.worker.last_name}"




# ============================================================
# PAYG CONTRACTOR PAYROLL — WEEKLY TIMESHEET
# ============================================================

def _prepare_contractor_payroll(db, header_id):

    from datetime import timedelta
    from decimal import Decimal

    from app.models.employee_tax_profile import EmployeeTaxProfile
    from app.models.employee_super_profile import EmployeeSuperProfile
    from app.models.payslip_timesheet import PayslipTimesheet

    from app.payroll.assignment_earnings import AssignmentEarningsCalculator
    from app.payroll.payg_withholding import PAYGWithholdingCalculator
    from app.payroll.superannuation import SuperannuationCalculator

    header = db.get(TimesheetHeader, header_id)

    if header is None or header.period_type != "weekly":
        raise HTTPException(404, "Weekly Timesheet not found")

    if header.status != "approved":
        raise HTTPException(409, "Timesheet must be approved")

    engagement = db.get(Engagement, header.engagement_id)

    if engagement is None:
        raise HTTPException(409, "Timesheet Engagement missing")

    if engagement.engagement_type != "payg_contractor":
        raise HTTPException(
            409,
            "Timesheet payroll is available only for PAYG Contractors",
        )

    if engagement.status != "active" or not engagement.worker.active:
        raise HTTPException(409, "Worker or Engagement inactive")

    if header.period_start.weekday() != 0:
        raise HTTPException(409, "Weekly period must begin on Monday")

    if header.period_end != (
        header.period_start + timedelta(days=6)
    ):
        raise HTTPException(409, "Weekly period must end on Sunday")

    if (
        engagement.start_date is not None
        and engagement.start_date > header.period_start
    ):
        raise HTTPException(409, "Partial-period payroll not supported")

    if (
        engagement.end_date is not None
        and engagement.end_date < header.period_end
    ):
        raise HTTPException(409, "Engagement ends during pay period")

    entries = db.scalars(
        select(Timesheet)
        .where(Timesheet.timesheet_header_id == header.id)
        .order_by(Timesheet.work_date)
    ).all()

    expected_dates = [
        header.period_start + timedelta(days=i)
        for i in range(7)
    ]

    if {entry.work_date for entry in entries} != set(expected_dates):
        raise HTTPException(
            409,
            "Weekly Timesheet must cover Monday through Sunday",
        )

    for entry in entries:
        if entry.status != "approved":
            raise HTTPException(409, "All daily entries must be approved")

        if entry.engagement_id != engagement.id:
            raise HTTPException(409, "Timesheet Engagement mismatch")

        if entry.assignment_id is None:
            raise HTTPException(409, "Timesheet Assignment missing")

    # Prevent overlapping payment periods for the same Engagement.
    overlapping = db.scalar(
        select(Payslip.id)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(
            Payslip.engagement_id == engagement.id,
            PayRun.period_start <= header.period_end,
            PayRun.period_end >= header.period_start,
        )
        .limit(1)
    )

    if overlapping is not None:
        raise HTTPException(
            409,
            "An overlapping Payslip already exists for this Engagement",
        )

    # Prevent paying individual daily entries more than once.
    already_paid = db.scalar(
        select(PayslipTimesheet.timesheet_id)
        .where(
            PayslipTimesheet.timesheet_id.in_(
                [entry.id for entry in entries]
            )
        )
        .limit(1)
    )

    if already_paid is not None:
        raise HTTPException(
            409,
            "One or more Timesheet entries are already linked to a Payslip",
        )

    try:
        earnings = AssignmentEarningsCalculator().calculate(
            session=db,
            engagement=engagement,
            timesheets=entries,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    gross = earnings["gross_pay"]

    if gross <= 0:
        raise HTTPException(409, "Gross earnings must be positive")

    payment_date = header.period_end + timedelta(days=1)

    tax_profiles = db.scalars(
        select(EmployeeTaxProfile).where(
            EmployeeTaxProfile.worker_id == engagement.worker_id,
            EmployeeTaxProfile.effective_from <= payment_date,
            (
                EmployeeTaxProfile.effective_to.is_(None)
                | (EmployeeTaxProfile.effective_to >= payment_date)
            ),
        )
    ).all()

    if len(tax_profiles) != 1:
        raise HTTPException(409, "Expected one effective Tax Profile")

    tax = tax_profiles[0]

    if (
        tax.residency_status != "resident"
        or tax.has_study_loan
        or not tax.tfn_declaration_received
    ):
        raise HTTPException(409, "Tax Profile incomplete or unsupported")

    try:
        payg = PAYGWithholdingCalculator().calculate(
            session=db,
            gross_pay=gross,
            pay_frequency="weekly",
            claims_tax_free_threshold=tax.claims_tax_free_threshold,
            payment_date=payment_date,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    super_profiles = db.scalars(
        select(EmployeeSuperProfile).where(
            EmployeeSuperProfile.worker_id == engagement.worker_id,
            EmployeeSuperProfile.effective_from <= payment_date,
            (
                EmployeeSuperProfile.effective_to.is_(None)
                | (EmployeeSuperProfile.effective_to >= payment_date)
            ),
        )
    ).all()

    if len(super_profiles) != 1:
        raise HTTPException(409, "Expected one effective Super Profile")

    additional_rate = (
        super_profiles[0].additional_employer_rate
        or Decimal("0")
    )

    if additional_rate < 0:
        raise HTTPException(409, "Invalid additional super rate")

    statutory_super = SuperannuationCalculator().calculate(
        ordinary_time_earnings=gross
    )

    additional_super = SuperannuationCalculator().calculate(
        ordinary_time_earnings=gross,
        rate=additional_rate / Decimal("100"),
    )

    return {
        "header_id": header.id,
        "engagement_id": engagement.id,
        "organisation_id": engagement.organisation_id,
        "worker_name": (
            f"{engagement.worker.first_name} "
            f"{engagement.worker.last_name}"
        ),
        "period_start": header.period_start,
        "period_end": header.period_end,
        "payment_date": payment_date,
        "hours": sum(
            (entry.hours_worked for entry in entries),
            Decimal("0"),
        ),
        "gross": gross,
        "payg": payg,
        "net": gross - payg,
        "statutory_super": statutory_super,
        "additional_super": additional_super,
        "total_super": statutory_super + additional_super,
        "earnings_lines": earnings["lines"],
        "timesheet_ids": [entry.id for entry in entries],
    }


@app.get(
    "/ui/timesheets/weekly/{header_id}/payroll/preview",
    response_class=HTMLResponse,
)
def preview_contractor_payroll(request: Request, header_id: int):

    with SessionLocal() as db:

        payroll = _prepare_contractor_payroll(db, header_id)

        return templates.TemplateResponse(
            request=request,
            name="contractor_payroll_preview.html",
            context={"payroll": payroll},
        )


@app.post(
    "/ui/timesheets/weekly/{header_id}/payroll/generate",
)
def generate_contractor_payroll(
    request: Request,
    header_id: int,
    expected_period_start: str = Form(...),
):

    from sqlalchemy import text

    from app.models.payroll_component import PayrollComponent
    from app.models.component_definition import ComponentDefinition
    from app.models.payslip_timesheet import PayslipTimesheet

    with SessionLocal() as db:

        try:
            # Serialise payroll generation for this Engagement.
            header = db.get(TimesheetHeader, header_id)

            if header is None or header.engagement_id is None:
                raise HTTPException(404, "Timesheet Engagement not found")

            if db.bind.dialect.name != "postgresql":
                raise HTTPException(
                    409,
                    "Contractor payroll generation requires PostgreSQL",
                )

            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": 800000000 + header.engagement_id},
            )

            # Recalculate and revalidate immediately before committing.
            payroll = _prepare_contractor_payroll(db, header_id)

            if payroll["period_start"].isoformat() != expected_period_start:
                raise HTTPException(
                    409,
                    "Timesheet period has changed; refresh preview",
                )

            required_codes = {
                "ORDINARY_HOURS",
                "PAYG_WITHHOLDING",
                "SUPER_GUARANTEE",
                "SUPER_EMPLOYER_EXTRA",
            }

            definitions = {
                definition.code: definition
                for definition in db.scalars(
                    select(ComponentDefinition).where(
                        ComponentDefinition.code.in_(required_codes)
                    )
                )
            }

            if required_codes - definitions.keys():
                raise HTTPException(
                    409,
                    "Required payroll component definitions missing",
                )

            pay_run = PayRun(
                organisation_id=payroll["organisation_id"],
                period_start=payroll["period_start"],
                period_end=payroll["period_end"],
                payment_date=payroll["payment_date"],
                status="draft",
            )

            db.add(pay_run)
            db.flush()

            payslip = Payslip(
                pay_run_id=pay_run.id,
                engagement_id=payroll["engagement_id"],
                employee_id=None,
                gross_pay=payroll["gross"],
                payg_withholding=payroll["payg"],
                net_pay=payroll["net"],
                superannuation=payroll["total_super"],
            )

            db.add(payslip)
            db.flush()

            from decimal import Decimal

            for line in payroll["earnings_lines"]:
                db.add(
                    PayrollComponent(
                        payslip_id=payslip.id,
                        component_definition_id=line[
                            "component_definition_id"
                        ],
                        quantity=line["quantity"],
                        rate=line["rate"],
                        amount=line["amount"],
                    )
                )

            statutory_components = (
                (
                    "PAYG_WITHHOLDING",
                    Decimal("1"),
                    payroll["payg"],
                    payroll["payg"],
                ),
                (
                    "SUPER_GUARANTEE",
                    payroll["gross"],
                    Decimal("0.12"),
                    payroll["statutory_super"],
                ),
                (
                    "SUPER_EMPLOYER_EXTRA",
                    payroll["gross"],
                    (
                        payroll["additional_super"]
                        / payroll["gross"]
                        if payroll["gross"]
                        else Decimal("0")
                    ),
                    payroll["additional_super"],
                ),
            )

            for code, quantity, rate, amount in statutory_components:
                db.add(
                    PayrollComponent(
                        payslip_id=payslip.id,
                        component_definition_id=definitions[code].id,
                        quantity=quantity,
                        rate=rate,
                        amount=amount,
                    )
                )

            for timesheet_id in payroll["timesheet_ids"]:
                db.add(
                    PayslipTimesheet(
                        payslip_id=payslip.id,
                        timesheet_id=timesheet_id,
                    )
                )

            db.flush()
            db.commit()

        except Exception:
            db.rollback()
            raise

    return RedirectResponse(
        url="/ui/timesheets",
        status_code=303,
    )


@app.get("/ui/timesheets", response_class=HTMLResponse)
def list_timesheets(
    request: Request, page: int = 1, page_size: int = 25,
):

    with SessionLocal() as db:

        # Retrieve every header-based timesheet, including PBT-scheduled
        # weekly, fortnightly, monthly and semi-monthly periods.
        pagination = build_pagination(
            total=int(db.scalar(select(func.count(TimesheetHeader.id))) or 0),
            page=page, page_size=page_size, path="/ui/timesheets",
        )
        period_headers = db.scalars(
            select(TimesheetHeader)
            .order_by(TimesheetHeader.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).all()

        header_ids = [header.id for header in period_headers]
        entry_map = defaultdict(list)
        if header_ids:
            for entry in db.scalars(select(Timesheet).where(
                Timesheet.timesheet_header_id.in_(header_ids)
            )).all():
                entry_map[entry.timesheet_header_id].append(entry)
        invoiced_header_ids = set()
        if header_ids:
            invoiced_header_ids = set(db.scalars(
                select(Timesheet.timesheet_header_id)
                .join(
                    InvoiceTimesheet,
                    InvoiceTimesheet.timesheet_id == Timesheet.id,
                )
                .where(Timesheet.timesheet_header_id.in_(header_ids))
                .distinct()
            ).all())
        engagement_ids = {
            header.engagement_id for header in period_headers
            if header.engagement_id is not None
        }
        worker_names = {}
        if engagement_ids:
            worker_names = {
                engagement_id: f"{first_name} {last_name}"
                for engagement_id, first_name, last_name in db.execute(
                    select(Engagement.id, Worker.first_name, Worker.last_name)
                    .join(Worker, Worker.id == Engagement.worker_id)
                    .where(Engagement.id.in_(engagement_ids))
                ).all()
            }
        period_ids = {
            header.pbt_schedule_period_id for header in period_headers
            if header.pbt_schedule_period_id is not None
        }
        period_frequencies = {}
        if period_ids:
            period_frequencies = dict(db.execute(
                select(PBTSchedulePeriod.id, PBTScheduleRule.frequency)
                .join(
                    PBTScheduleRule,
                    PBTScheduleRule.id == PBTSchedulePeriod.rule_id,
                )
                .where(PBTSchedulePeriod.id.in_(period_ids))
            ).all())

        period_timesheets = []

        for header in period_headers:
            entries = entry_map[header.id]
            is_invoiced = header.id in invoiced_header_ids
            type_label = header.period_type.replace("_", " ").title()
            if header.period_type == "scheduled":
                frequency = (
                    period_frequencies.get(
                        header.pbt_schedule_period_id, "scheduled"
                    ).replace("_", " ").title()
                )
                type_label = f"PBT {frequency}"

            period_timesheets.append({
                "id": header.id,
                "engagement_id": header.engagement_id,
                "assignment_id": header.assignment_id,
                "employee_name": worker_names.get(
                    header.engagement_id, "Historical worker"
                ),
                "period_type": header.period_type,
                "type_label": type_label,
                "period_start": header.period_start,
                "period_end": header.period_end,
                "total_hours": sum(
                    (entry.hours_worked for entry in entries),
                    Decimal("0.00")
                ),
                "status": header.status,
                "is_invoiced": is_invoiced,
            })

        # Retrieve standalone daily timesheets only
        daily_timesheets = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id.is_(None))
            .order_by(Timesheet.id.desc())
        ).all()

        daily_data = [
            {
                "id": timesheet.id,
                "engagement_id": timesheet.engagement_id,
                "employee_name": (
                    (timesheet_worker_name(db, timesheet.engagement_id))
                ),
                "work_date": timesheet.work_date,
                "hours": timesheet.hours_worked,
                "status": timesheet.status,
                "is_invoiced": db.scalar(
                    select(InvoiceTimesheet.id)
                    .where(InvoiceTimesheet.timesheet_id == timesheet.id)
                    .limit(1)
                ) is not None,
            }
            for timesheet in daily_timesheets
        ]

        return templates.TemplateResponse(
            request=request,
            name="timesheet_list.html",
            context={
                "period_timesheets": period_timesheets,
                "daily_timesheets": daily_data,
                "pagination": pagination,
                "engagement_options": [
                    {
                        "id": engagement.id,
                        "engagement_id": engagement.engagement_id,
                        "customer_name": engagement.customer.name,
                        "billing_rate": str(engagement.billing_rate)
                    }
                    for engagement in db.scalars(
                        select(Assignment)
                        .order_by(Assignment.id)
                    ).all()
                ]
            }
        )

@app.get(
    "/ui/timesheets/weekly/{header_id}/preview",
    response_class=HTMLResponse,
)
def preview_weekly_timesheet(request: Request, header_id: int):

    with SessionLocal() as db:

        header = db.get(TimesheetHeader, header_id)

        if header is None:
            raise HTTPException(
                status_code=404,
                detail="Timesheet not found",
            )

        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header_id)
            .order_by(Timesheet.work_date)
        ).all()

        total_hours = sum(
            (entry.hours_worked for entry in entries),
            Decimal("0.00"),
        )
        definitions = {
            definition.id: definition
            for definition in db.scalars(select(ComponentDefinition)).all()
        }
        ordinary = next(
            (
                definition for definition in definitions.values()
                if definition.code == "ORDINARY_HOURS"
            ),
            None,
        )
        component_totals = {}
        entry_data = []
        for entry in entries:
            definition = (
                definitions.get(entry.component_definition_id)
                if entry.component_definition_id is not None else ordinary
            )
            component_name = (
                definition.name if definition else "Ordinary Hours"
            )
            entry_data.append({
                "work_date": entry.work_date,
                "component": component_name,
                "hours_worked": entry.hours_worked,
            })
            component_totals[component_name] = (
                component_totals.get(component_name, Decimal("0"))
                + entry.hours_worked
            )

        return templates.TemplateResponse(
            request=request,
            name="timesheet_preview.html",
            context={
                "timesheet_id": header.id,
                "worker_name": (
                    timesheet_worker_name(db, header.engagement_id)
                ),
                "period_type": header.period_type,
                "period_start": header.period_start,
                "period_end": header.period_end,
                "status": header.status,
                "entries": entry_data,
                "component_totals": component_totals,
                "total_hours": total_hours,
            },
        )


@app.get(
    "/ui/timesheets/daily/{timesheet_id}/preview",
    response_class=HTMLResponse,
)
def preview_daily_timesheet(request: Request, timesheet_id: int):

    with SessionLocal() as db:

        timesheet = db.get(Timesheet, timesheet_id)

        if timesheet is None or timesheet.timesheet_header_id is not None:
            raise HTTPException(
                status_code=404,
                detail="Daily timesheet not found",
            )

        return templates.TemplateResponse(
            request=request,
            name="timesheet_preview.html",
            context={
                "timesheet_id": timesheet.id,
                "worker_name": (
                    timesheet_worker_name(db, timesheet.engagement_id)
                ),
                "period_type": "daily",
                "period_start": timesheet.work_date,
                "period_end": timesheet.work_date,
                "status": timesheet.status,
                "entries": [
                    {
                        "work_date": timesheet.work_date,
                        "component": "Ordinary Hours",
                        "hours_worked": timesheet.hours_worked,
                    }
                ],
                "total_hours": timesheet.hours_worked,
                "component_totals": {
                    "Ordinary Hours": timesheet.hours_worked,
                },
            },
        )

@app.get("/ui/timesheets/{timesheet_id}/edit", response_class=HTMLResponse)
def edit_timesheet_page(request: Request, timesheet_id: int):
    with SessionLocal() as db:
        timesheet = db.get(Timesheet, timesheet_id)

        if timesheet is None:
            raise HTTPException(
                status_code=404,
                detail="Timesheet not found"
            )

        # Weekly entries must be edited through their parent timesheet
        if timesheet.timesheet_header_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Weekly timesheet entries cannot be edited individually"
            )

        if timesheet.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Approved timesheets cannot be edited"
            )

        engagements = db.scalars(
            select(Engagement).order_by(Engagement.id)
        ).all()

        return templates.TemplateResponse(
            request=request,
            name="timesheet_create.html",
            context={
                "engagements": engagements,
                "timesheet": timesheet,
                "assignments": db.scalars(
                    select(Assignment).order_by(Assignment.id)
                ).all()
            }
        )

@app.get("/ui/timesheets/weekly/{header_id}/edit", response_class=HTMLResponse)
def edit_weekly_timesheet_page(request: Request, header_id: int):

    with SessionLocal() as db:
        header = db.get(TimesheetHeader, header_id)

        if header is None:
            raise HTTPException(
                status_code=404,
                detail="Weekly timesheet not found"
            )

        if header.period_type != "weekly":
            raise HTTPException(
                status_code=409,
                detail="Timesheet is not weekly"
            )

        if header.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Only draft weekly timesheets can be edited"
            )

        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header_id)
            .order_by(Timesheet.work_date)
        ).all()

        expected_dates = {
            header.period_start + timedelta(days=i) for i in range(7)
        }
        if {entry.work_date for entry in entries} != expected_dates:
            raise HTTPException(
                status_code=409,
                detail="Weekly timesheet must cover Monday through Sunday"
            )

        engagements = db.scalars(
            select(Engagement).order_by(Engagement.id)
        ).all()

        return templates.TemplateResponse(
            request=request,
            name="timesheet_weekly.html",
            context={
                "engagements": engagements,
                "header": header,
                "entries": entries,
                "edit_mode": True,
                "assignments": db.scalars(
                    select(Assignment).order_by(Assignment.id)
                ).all()
            }
        )

@app.get("/ui/timesheets/weekly", response_class=HTMLResponse)
def new_weekly_timesheet_page(request: Request):
    with SessionLocal() as db:
        engagements = db.scalars(
            select(Engagement).order_by(Engagement.id)
        ).all()

        return templates.TemplateResponse(
            request=request,
            name="timesheet_weekly.html",
            context={
                "engagements": engagements,
                "assignments": db.scalars(
                    select(Assignment).order_by(Assignment.id)
                ).all()
            }
        )


@app.get("/ui/timesheets/new", response_class=HTMLResponse)
def new_timesheet_page(request: Request):
    with SessionLocal() as db:
        engagements = db.scalars(
            select(Engagement).order_by(Engagement.id)
        ).all()

        return templates.TemplateResponse(
            request=request,
            name="timesheet_create.html",
            context={
                "engagements": engagements,
                "timesheet": None,
                "assignments": db.scalars(
                    select(Assignment).order_by(Assignment.id)
                ).all()
            }
        )


def validate_timesheet_engagement(db, engagement_id):
    engagement = db.get(Engagement, engagement_id)

    if engagement is None:
        raise HTTPException(
            status_code=404,
            detail="Engagement not found"
        )

    return engagement


def validate_timesheet_assignment(db, assignment_id, engagement_id):
    if assignment_id is None:
        return

    assignment = db.get(Assignment, assignment_id)

    if assignment is None:
        raise HTTPException(
            status_code=422,
            detail="Selected assignment does not exist"
        )

    if assignment.engagement_id != engagement_id:
        raise HTTPException(
            status_code=422,
            detail="Selected assignment does not belong to this Engagement"
        )

    return assignment


def timesheet_component_options(db, assignment_id, work_date):
    from app.models.leave_plan import LeavePlan

    assignment = db.get(Assignment, assignment_id)
    rows = db.execute(
        select(ComponentDefinition, ComponentFamily)
        .join(
            ComponentFamily,
            ComponentFamily.id == ComponentDefinition.family_id,
        )
        .join(
            AssignmentComponent,
            AssignmentComponent.component_definition_id
            == ComponentDefinition.id,
        )
        .where(
            AssignmentComponent.assignment_id == assignment_id,
            AssignmentComponent.effective_from <= work_date,
            (
                AssignmentComponent.effective_to.is_(None)
                | (AssignmentComponent.effective_to >= work_date)
            ),
            AssignmentComponent.applies_to.in_(("payroll", "invoice", "both")),
            ComponentDefinition.active.is_(True),
            ComponentFamily.code == "EARNINGS",
            ComponentDefinition.code != "GST",
        )
        .order_by(ComponentFamily.name, ComponentDefinition.name)
    ).all()
    options = []
    for definition, family in rows:
        options.append({
            "id": definition.id,
            "name": definition.name,
            "family": family.name,
            "leave_plan_id": None,
        })
    if assignment is not None:
        leave_rows = db.execute(
            select(LeavePlan, ComponentDefinition, ComponentFamily)
            .join(
                ComponentDefinition,
                ComponentDefinition.id
                == LeavePlan.component_definition_id,
            )
            .join(
                ComponentFamily,
                ComponentFamily.id == ComponentDefinition.family_id,
            )
            .where(
                LeavePlan.engagement_id == assignment.engagement_id,
                LeavePlan.status == "active",
                LeavePlan.effective_from <= work_date,
                (
                    LeavePlan.effective_to.is_(None)
                    | (LeavePlan.effective_to >= work_date)
                ),
                ComponentDefinition.active.is_(True),
                ComponentFamily.code == "LEAVE",
            )
            .order_by(ComponentDefinition.name)
        ).all()
        for plan, definition, family in leave_rows:
            options.append({
                "id": definition.id,
                "name": definition.name,
                "family": family.name,
                "leave_plan_id": plan.id,
            })
    return options


def validate_timesheet_component(
    db, assignment_id, component_definition_id, work_date,
):
    # NULL remains valid for historical/API compatibility and means ordinary.
    if component_definition_id is None:
        return None
    options = timesheet_component_options(db, assignment_id, work_date)
    if component_definition_id not in {option["id"] for option in options}:
        raise HTTPException(
            status_code=422,
            detail=(
                "Selected component is not active and configured for this "
                "Assignment on the work date"
            ),
        )
    return next(
        option["leave_plan_id"]
        for option in options
        if option["id"] == component_definition_id
    )


def validate_weekly_entries(entries, expected_dates):
    submitted_dates = {entry.work_date for entry in entries}
    if submitted_dates != set(expected_dates):
        raise HTTPException(
            status_code=422,
            detail="Entries must cover Monday through Sunday",
        )
    for work_date in expected_dates:
        total = sum(
            (
                entry.hours_worked for entry in entries
                if entry.work_date == work_date
            ),
            Decimal("0"),
        )
        if total > Decimal("24"):
            raise HTTPException(
                status_code=422,
                detail=f"Total hours for {work_date} cannot exceed 24",
            )


@app.get("/api/assignments/{assignment_id}/timesheet-components")
def list_timesheet_components(assignment_id: int, work_date: date):
    with SessionLocal() as db:
        if db.get(Assignment, assignment_id) is None:
            raise HTTPException(404, "Assignment not found")
        return timesheet_component_options(db, assignment_id, work_date)


@app.post("/api/timesheets/weekly", status_code=201)
def create_weekly_timesheet(data: WeeklyTimesheetCreate):

    # Validate week starts on Monday
    if data.week_start.weekday() != 0:
        raise HTTPException(
            status_code=422,
            detail="Week must start on Monday"
        )

    # Validate consecutive dates, Monday through Sunday
    from datetime import timedelta

    expected_dates = [
        data.week_start + timedelta(days=i)
        for i in range(7)
    ]

    validate_weekly_entries(data.entries, expected_dates)

    with SessionLocal() as db:

        validate_timesheet_engagement(db, data.engagement_id)

        # Prevent duplicate entries
        existing = db.scalars(
            select(Timesheet).where(
                Timesheet.engagement_id == data.engagement_id,
                Timesheet.work_date.in_(expected_dates)
            )
        ).all()

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Timesheet entries already exist for this week"
            )

        # Create one weekly timesheet header
        header = TimesheetHeader(
            engagement_id=data.engagement_id,
            employee_id=None,
            period_type="weekly",
            period_start=data.week_start,
            period_end=expected_dates[-1],
            status="draft"
        )

        db.add(header)
        db.flush()

        for entry in data.entries:
            assignment = validate_timesheet_assignment(
                db, entry.assignment_id, data.engagement_id
            )
            if assignment is None:
                if entry.component_definition_id is not None:
                    raise HTTPException(422, "Assignment is required")
                continue
            validate_timesheet_component(
                db,
                assignment.id,
                entry.component_definition_id,
                entry.work_date,
            )

        # Create seven daily entries linked to the header
        timesheets = [
            Timesheet(
                engagement_id=data.engagement_id,
                employee_id=None,
                timesheet_header_id=header.id,
                assignment_id=entry.assignment_id,
                component_definition_id=entry.component_definition_id,
                leave_plan_id=validate_timesheet_component(
                    db,
                    entry.assignment_id,
                    entry.component_definition_id,
                    entry.work_date,
                ),
                work_date=entry.work_date,
                hours_worked=entry.hours_worked,
                status="draft"
            )
            for entry in data.entries
        ]

        db.add_all(timesheets)
        db.commit()

        return {
            "message": "Weekly timesheet saved successfully",
            "timesheet_header_id": header.id,
            "engagement_id": data.engagement_id,
            "week_start": data.week_start,
            "lines_created": len(timesheets),
            "days_created": len({entry.work_date for entry in data.entries}),
            "total_hours": sum(
                entry.hours_worked for entry in data.entries
            )
        }


@app.patch("/api/timesheets/weekly/{header_id}")
def update_weekly_timesheet(
    header_id: int,
    data: WeeklyTimesheetCreate
):
    from datetime import timedelta

    with SessionLocal() as db:

        header = db.get(TimesheetHeader, header_id)

        if header is None:
            raise HTTPException(
                status_code=404,
                detail="Weekly timesheet not found"
            )

        if header.period_type != "weekly":
            raise HTTPException(
                status_code=409,
                detail="Timesheet is not weekly"
            )

        if header.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Only draft weekly timesheets can be edited"
            )

        if data.engagement_id != header.engagement_id:
            raise HTTPException(
                status_code=422,
                detail="Cannot change the Engagement"
            )

        if data.week_start != header.period_start:
            raise HTTPException(
                status_code=422,
                detail="Cannot change the week commencing date"
            )

        expected_dates = [
            header.period_start + timedelta(days=i)
            for i in range(7)
        ]

        validate_weekly_entries(data.entries, expected_dates)

        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header_id)
            .order_by(Timesheet.work_date)
        ).all()

        if {entry.work_date for entry in entries} != set(expected_dates):
            raise HTTPException(
                status_code=409,
                detail="Weekly timesheet has incomplete daily entries"
            )

        if any(entry.status != "draft" for entry in entries):
            raise HTTPException(
                status_code=409,
                detail="Cannot edit approved daily entries"
            )

        for submitted in data.entries:
            assignment = validate_timesheet_assignment(
                db, submitted.assignment_id, data.engagement_id
            )
            if assignment is None:
                if submitted.component_definition_id is not None:
                    raise HTTPException(422, "Assignment is required")
                continue
            validate_timesheet_component(
                db,
                assignment.id,
                submitted.component_definition_id,
                submitted.work_date,
            )

        for existing in entries:
            db.delete(existing)
        db.flush()
        db.add_all([
            Timesheet(
                engagement_id=data.engagement_id,
                employee_id=None,
                timesheet_header_id=header.id,
                assignment_id=submitted.assignment_id,
                component_definition_id=submitted.component_definition_id,
                leave_plan_id=validate_timesheet_component(
                    db,
                    submitted.assignment_id,
                    submitted.component_definition_id,
                    submitted.work_date,
                ),
                work_date=submitted.work_date,
                hours_worked=submitted.hours_worked,
                status="draft",
            )
            for submitted in data.entries
        ])

        db.commit()

        return {
            "timesheet_header_id": header.id,
            "status": header.status,
            "lines_updated": len(data.entries),
            "days_updated": len({entry.work_date for entry in data.entries}),
            "total_hours": sum(
                entry.hours_worked for entry in data.entries
            )
        }

@app.post("/api/timesheets", status_code=201)
def create_timesheet(data: TimesheetCreate):

    with SessionLocal() as db:

        validate_timesheet_engagement(db, data.engagement_id)

        validate_timesheet_assignment(
            db, data.assignment_id, data.engagement_id
        )

        # Create the timesheet
        timesheet = Timesheet(
            engagement_id=data.engagement_id,
            employee_id=None,
            assignment_id=data.assignment_id,
            work_date=data.work_date,
            hours_worked=data.hours_worked,
            status="draft"
        )

        db.add(timesheet)
        db.commit()
        db.refresh(timesheet)

        return {
            "id": timesheet.id,
            "engagement_id": timesheet.engagement_id,
            "work_date": timesheet.work_date,
            "hours_worked": timesheet.hours_worked,
            "status": timesheet.status
        }



@app.post("/api/timesheets/weekly/{header_id}/approve")
def approve_weekly_timesheet(header_id: int):

    with SessionLocal() as db:

        # Retrieve weekly timesheet header
        header = db.get(TimesheetHeader, header_id)

        if header is None:
            raise HTTPException(
                status_code=404,
                detail="Weekly timesheet not found"
            )

        if header.period_type != "weekly":
            raise HTTPException(
                status_code=409,
                detail="Timesheet is not weekly"
            )

        if header.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Only draft weekly timesheets can be approved"
            )

        # Retrieve all daily entries
        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header_id)
            .order_by(Timesheet.work_date)
        ).all()

        expected_dates = {
            header.period_start + timedelta(days=i) for i in range(7)
        }
        if {entry.work_date for entry in entries} != expected_dates:
            raise HTTPException(
                status_code=409,
                detail="Weekly timesheet must cover Monday through Sunday"
            )

        if any(entry.status != "draft" for entry in entries):
            raise HTTPException(
                status_code=409,
                detail="All daily entries must be in draft status"
            )

        from app.leave.service import LeaveService
        try:
            LeaveService.validate_timesheets(db, header.engagement_id, entries)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))

        # Approve header and all daily entries
        header.status = "approved"

        for entry in entries:
            entry.status = "approved"

        db.commit()

        return {
            "timesheet_header_id": header.id,
            "status": header.status,
            "lines_approved": len(entries),
            "days_approved": len({entry.work_date for entry in entries}),
            "total_hours": sum(
                entry.hours_worked for entry in entries
            )
        }


@app.post("/api/timesheets/{timesheet_id}/approve")
def approve_timesheet(timesheet_id: int):
    with SessionLocal() as db:
        timesheet = db.get(Timesheet, timesheet_id)

        if timesheet is None:
            raise HTTPException(
                status_code=404,
                detail="Timesheet not found"
            )

        # Weekly entries must be approved through their header
        if timesheet.timesheet_header_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Weekly timesheet entries must be approved together"
            )

        if timesheet.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Only draft timesheets can be approved"
            )

        timesheet.status = "approved"
        db.commit()

        return {
            "id": timesheet.id,
            "status": timesheet.status
        }


@app.patch("/api/timesheets/{timesheet_id}")
def update_timesheet(timesheet_id: int, data: TimesheetCreate):
    with SessionLocal() as db:
        timesheet = db.get(Timesheet, timesheet_id)

        if timesheet is None:
            raise HTTPException(
                status_code=404,
                detail="Timesheet not found"
            )

        # Weekly entries must be edited through their parent timesheet
        if timesheet.timesheet_header_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Weekly timesheet entries cannot be edited individually"
            )


        if timesheet.status != "draft":
            raise HTTPException(
                status_code=409,
                detail="Approved timesheets cannot be edited"
            )

        validate_timesheet_engagement(db, data.engagement_id)

        validate_timesheet_assignment(
            db, data.assignment_id, data.engagement_id
        )

        timesheet.engagement_id = data.engagement_id
        timesheet.employee_id = None
        timesheet.assignment_id = data.assignment_id
        timesheet.work_date = data.work_date
        timesheet.hours_worked = data.hours_worked

        db.commit()

        return {"id": timesheet.id, "status": timesheet.status}


# ============================================================
# CREATE PAY RUN
# ============================================================

@app.post("/pay-runs", status_code=201)
def create_pay_run(data: PayRunCreate):

    if data.period_end < data.period_start:
        raise HTTPException(
            status_code=400,
            detail="Pay period end cannot precede start"
        )

    if data.payment_date < data.period_end:
        raise HTTPException(
            status_code=400,
            detail="Payment date cannot precede pay period end"
        )

    with SessionLocal() as session:

        organisation = session.get(
            Organisation,
            data.organisation_id
        )

        if organisation is None:
            raise HTTPException(
                status_code=404,
                detail="Organisation not found"
            )

        pay_run = PayRun(
            organisation_id=data.organisation_id,
            period_start=data.period_start,
            period_end=data.period_end,
            payment_date=data.payment_date,
            status="draft"
        )

        session.add(pay_run)
        session.commit()
        session.refresh(pay_run)

        return {
            "id": pay_run.id,
            "organisation_id": pay_run.organisation_id,
            "period_start": pay_run.period_start,
            "period_end": pay_run.period_end,
            "payment_date": pay_run.payment_date,
            "status": pay_run.status
        }


# ============================================================
# PROCESS PAY RUN
# ============================================================

@app.post("/pay-runs/{pay_run_id}/process")
def process_pay_run_api(pay_run_id: int):

    with SessionLocal() as session:

        try:
            result = PayRunProcessor().process(
                session=session,
                pay_run_id=pay_run_id
            )

            return {
                "pay_run_id": pay_run_id,
                "status": "processed",
                "employees_processed": result["processed"],
                "employees_skipped": result["skipped"]
            }

        except ValueError as error:
            session.rollback()

            raise HTTPException(
                status_code=400,
                detail=str(error)
            )


# ============================================================
# APPROVE PAY RUN
# ============================================================

@app.post("/pay-runs/{pay_run_id}/approve")
def approve_pay_run_api(pay_run_id: int):

    with SessionLocal() as session:

        pay_run = session.get(PayRun, pay_run_id)

        if pay_run is None:
            raise HTTPException(
                status_code=404,
                detail="Pay run not found"
            )

        payslip_count = session.scalar(
            select(func.count(Payslip.id))
            .where(Payslip.pay_run_id == pay_run_id)
        )

        if payslip_count == 0:
            raise HTTPException(
                status_code=400,
                detail="Cannot approve a pay run without payslips"
            )

        try:
            # Serialise pay run completion within this organisation
            session.execute(
                select(Organisation.id)
                .where(Organisation.id == pay_run.organisation_id)
                .with_for_update()
            ).scalar_one()

            PayRunLifecycle().transition(
                pay_run=pay_run,
                new_status="approved"
            )

            session.commit()

        except ValueError as error:
            session.rollback()

            raise HTTPException(
                status_code=400,
                detail=str(error)
            )

        return {
            "pay_run_id": pay_run.id,
            "status": pay_run.status,
            "payslips": payslip_count,
            "message": "Pay run approved successfully"
        }


# ============================================================
# COMPLETE PAY RUN
# ============================================================

@app.post("/pay-runs/{pay_run_id}/complete")
def complete_pay_run_api(pay_run_id: int):

    with SessionLocal() as session:

        pay_run = session.get(PayRun, pay_run_id)

        if pay_run is None:
            raise HTTPException(
                status_code=404,
                detail="Pay run not found"
            )

        try:
            # Lock the organisation row to prevent
            # concurrent payroll completion
            session.execute(
                select(Organisation.id)
                .where(Organisation.id == pay_run.organisation_id)
                .with_for_update()
            ).scalar_one()

            # Find timesheets in this pay run that have
            # already been included in a completed pay run
            duplicate_timesheet_ids = session.scalars(
                select(PayslipTimesheet.timesheet_id)
                .join(
                    Payslip,
                    Payslip.id == PayslipTimesheet.payslip_id
                )
                .join(
                    PayRun,
                    PayRun.id == Payslip.pay_run_id
                )
                .where(
                    PayRun.status == "completed",
                    PayRun.id != pay_run.id,
                    PayslipTimesheet.timesheet_id.in_(
                        select(PayslipTimesheet.timesheet_id)
                        .join(
                            Payslip,
                            Payslip.id == PayslipTimesheet.payslip_id
                        )
                        .where(
                            Payslip.pay_run_id == pay_run.id
                        )
                    )
                )
            ).all()

            if duplicate_timesheet_ids:
                raise ValueError(
                    "Cannot complete pay run: timesheets already paid "
                    f"{sorted(set(duplicate_timesheet_ids))}"
                )

            from app.leave.service import LeaveService
            LeaveService.post_pay_run(session, pay_run)

            PayRunLifecycle().transition(
                pay_run=pay_run,
                new_status="completed"
            )

            session.commit()

        except ValueError as error:
            session.rollback()

            raise HTTPException(
                status_code=400,
                detail=str(error)
            )

        return {
            "pay_run_id": pay_run.id,
            "status": pay_run.status,
            "message": "Pay run completed successfully"
        }


# ============================================================
# PDF PAYSLIP DOWNLOAD
# ============================================================



@app.get(
    "/ui/payslips/{payslip_id}/preview",
    response_class=HTMLResponse,
)
def preview_payslip_page(request: Request, payslip_id: int):

    from app.models.payroll_component import PayrollComponent
    from app.models.component_definition import ComponentDefinition
    from app.models.leave_plan import LeavePlan
    from app.models.payment_batch import PaymentBatch
    from app.models.payment_instruction import PaymentInstruction
    from app.leave.service import LeaveService

    with SessionLocal() as db:

        payslip = db.get(Payslip, payslip_id)

        if payslip is None:
            raise HTTPException(404, "Payslip not found")

        engagement = db.get(
            Engagement,
            payslip.engagement_id,
        )

        if engagement is None or engagement.worker is None:
            raise HTTPException(
                409,
                "Payslip has no valid Worker Engagement",
            )

        pay_run = db.get(PayRun, payslip.pay_run_id)

        if pay_run is None:
            raise HTTPException(
                409,
                "Payslip has no Pay Run",
            )

        organisation = db.get(
            Organisation,
            pay_run.organisation_id,
        )

        if organisation is None:
            raise HTTPException(
                409,
                "Pay Run organisation not found",
            )

        worker = engagement.worker

        # Read the actual saved payroll components.
        # Do not recalculate historical earnings.
        rows = db.execute(
            select(PayrollComponent, ComponentDefinition)
            .join(
                ComponentDefinition,
                PayrollComponent.component_definition_id
                == ComponentDefinition.id,
            )
            .where(
                PayrollComponent.payslip_id == payslip.id
            )
            .order_by(PayrollComponent.id)
        ).all()

        components = [
            {
                "code": definition.code,
                "name": definition.name,
                "quantity": component.quantity,
                "rate": component.rate,
                "amount": component.amount,
            }
            for component, definition in rows
        ]

        ordinary_hours = sum(
            (
                Decimal(component.quantity)
                for component, definition in rows
                if definition.code == "ORDINARY_HOURS"
            ),
            Decimal("0"),
        )
        paid_leave_hours = sum(
            (
                Decimal(component.quantity)
                for component, definition in rows
                if definition.code in {"ANNUAL_LEAVE", "PERSONAL_LEAVE"}
            ),
            Decimal("0"),
        )
        leave_plans = db.execute(
            select(LeavePlan, ComponentDefinition)
            .join(
                ComponentDefinition,
                ComponentDefinition.id
                == LeavePlan.component_definition_id,
            )
            .where(
                LeavePlan.engagement_id == engagement.id,
                LeavePlan.status == "active",
                LeavePlan.effective_from <= pay_run.payment_date,
                (
                    LeavePlan.effective_to.is_(None)
                    | (LeavePlan.effective_to >= pay_run.payment_date)
                ),
            )
            .order_by(ComponentDefinition.name)
        ).all()
        leave_summary = []
        for plan, definition in leave_plans:
            balance = LeaveService.balance(db, plan.id)
            basis = ordinary_hours
            if plan.accrues_during_paid_leave:
                basis += paid_leave_hours
            projected_accrual = Decimal("0")
            if pay_run.status != "completed":
                projected_accrual = (
                    basis * Decimal(plan.accrual_rate_per_hour)
                ).quantize(Decimal("0.0001"))
            leave_summary.append({
                "name": definition.name,
                "current_balance": balance,
                "projected_accrual": projected_accrual,
                "projected_balance": balance + projected_accrual,
            })

        payment_rows = db.execute(
            select(PaymentInstruction, PaymentBatch)
            .join(
                PaymentBatch,
                PaymentBatch.id == PaymentInstruction.payment_batch_id,
            )
            .where(PaymentInstruction.payslip_id == payslip.id)
            .order_by(PaymentBatch.id.desc(), PaymentInstruction.id.desc())
        ).all()
        payment_instructions = [{
            "id": instruction.id,
            "batch_id": batch.id,
            "batch_status": batch.status,
            "processing_date": batch.processing_date,
            "source_type": instruction.source_type,
            "status": instruction.status,
            "amount": instruction.amount,
            "account_name": instruction.recipient_account_name,
            "bsb": (
                f"{instruction.recipient_bsb[:3]}-"
                f"{instruction.recipient_bsb[3:]}"
            ),
            "account_number": (
                "****" + instruction.recipient_account_number[-4:]
            ),
            "reference": instruction.lodgement_reference,
        } for instruction, batch in payment_rows]

        return templates.TemplateResponse(
            request=request,
            name="payslip_preview.html",
            context={
                "payslip": payslip,
                "pay_run": pay_run,
                "worker": worker,
                "engagement": engagement,
                "organisation": organisation,
                "components": components,
                "leave_summary": leave_summary,
                "payment_instructions": payment_instructions,
            },
        )


@app.get("/payslips/{payslip_id}/pdf")
def download_payslip_pdf(payslip_id: int):

    with SessionLocal() as session:

        payslip = session.get(Payslip, payslip_id)

        if payslip is None:
            raise HTTPException(
                status_code=404,
                detail="Payslip not found"
            )

        engagement = session.get(Engagement, payslip.engagement_id)
        if engagement is None or engagement.worker is None:
            raise HTTPException(status_code=500, detail="Payslip Worker link missing")
        worker = engagement.worker

        pay_run = session.get(
            PayRun,
            payslip.pay_run_id
        )

        organisation = session.get(
            Organisation,
            pay_run.organisation_id
        )

        from app.models.payroll_component import PayrollComponent
        from app.models.component_definition import ComponentDefinition
        from app.models.payslip_timesheet import PayslipTimesheet
        from app.models.timesheet import Timesheet
        from sqlalchemy import select

        components = session.scalars(
            select(PayrollComponent).where(
                PayrollComponent.payslip_id == payslip.id
            ).order_by(PayrollComponent.id)
        ).all()

        linked_timesheets = session.scalars(
            select(Timesheet)
            .join(
                PayslipTimesheet,
                PayslipTimesheet.timesheet_id == Timesheet.id
            )
            .where(PayslipTimesheet.payslip_id == payslip.id)
        ).all()

        assignment_ids = sorted({
            ts.assignment_id
            for ts in linked_timesheets
            if ts.assignment_id is not None
        })

        # The current payroll component records do not store
        # assignment_id directly. A single linked assignment
        # can be identified unambiguously; multiple assignments
        # cannot yet be attributed to individual component lines.
        assignment_label = (
            f"#{assignment_ids[0]}"
            if len(assignment_ids) == 1
            else "Multiple" if assignment_ids
            else "—"
        )

        earnings_lines = []
        withholding_lines = []
        employer_super_lines = []

        from app.models.component_family import ComponentFamily

        earnings_families = {
            "EARNINGS",
            "ALLOWANCE",
            "LEAVE",
            "TERMINATION",
            "REIMBURSEMENT",
        }

        for component in components:
            definition = session.get(
                ComponentDefinition,
                component.component_definition_id
            )

            if definition is None:
                raise HTTPException(
                    status_code=500,
                    detail="Payroll component definition missing"
                )

            family = session.get(
                ComponentFamily,
                definition.family_id
            )

            if family is None:
                raise HTTPException(
                    status_code=500,
                    detail="Payroll component family missing"
                )

            line = {
                "assignment": assignment_label,
                "component": definition.name,
                "quantity": component.quantity,
                "rate": component.rate,
                "amount": component.amount,
            }

            if family.code in earnings_families:
                earnings_lines.append(line)

            elif definition.code in {
                "PAYG_WITHHOLDING",
                "ETP_WITHHOLDING",
            }:
                withholding_lines.append(line)

            elif definition.code in {
                "SUPER_GUARANTEE",
                "SUPER_EMPLOYER_EXTRA",
            }:
                employer_super_lines.append(line)

            else:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Payslip PDF does not yet support "
                        f"component {definition.code}"
                    )
                )

        from app.models.leave_plan import LeavePlan
        from app.leave.service import LeaveService

        component_rows = [
            (
                component,
                session.get(
                    ComponentDefinition,
                    component.component_definition_id,
                ),
            )
            for component in components
        ]
        ordinary_hours = sum(
            (
                Decimal(component.quantity)
                for component, definition in component_rows
                if definition is not None
                and definition.code == "ORDINARY_HOURS"
            ),
            Decimal("0"),
        )
        paid_leave_hours = sum(
            (
                Decimal(component.quantity)
                for component, definition in component_rows
                if definition is not None
                and definition.code in {"ANNUAL_LEAVE", "PERSONAL_LEAVE"}
            ),
            Decimal("0"),
        )
        leave_plans = session.execute(
            select(LeavePlan, ComponentDefinition)
            .join(
                ComponentDefinition,
                ComponentDefinition.id
                == LeavePlan.component_definition_id,
            )
            .where(
                LeavePlan.engagement_id == engagement.id,
                LeavePlan.status == "active",
                LeavePlan.effective_from <= pay_run.payment_date,
                (
                    LeavePlan.effective_to.is_(None)
                    | (LeavePlan.effective_to >= pay_run.payment_date)
                ),
            )
            .order_by(ComponentDefinition.name)
        ).all()
        leave_summary = []
        for plan, definition in leave_plans:
            balance = LeaveService.balance(session, plan.id)
            basis = ordinary_hours
            if plan.accrues_during_paid_leave:
                basis += paid_leave_hours
            projected_accrual = Decimal("0")
            if pay_run.status != "completed":
                projected_accrual = (
                    basis * Decimal(plan.accrual_rate_per_hour)
                ).quantize(Decimal("0.0001"))
            leave_summary.append({
                "name": definition.name,
                "current_balance": balance,
                "projected_accrual": projected_accrual,
                "projected_balance": balance + projected_accrual,
            })

        pdf_buffer = PayslipPDFGenerator().generate(
            payslip=payslip,
            employee=worker,
            organisation=organisation,
            pay_run=pay_run,
            earnings_lines=earnings_lines,
            withholding_lines=withholding_lines,
            employer_super_lines=employer_super_lines,
            leave_summary=leave_summary,
        )

        filename = f"payslip_{payslip.id}.pdf"

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{filename}"'
            }
        )














@app.get("/ui/pay-runs", response_class=HTMLResponse)
def pay_runs_page(
    request: Request, page: int = 1, page_size: int = 25,
):

    with SessionLocal() as session:

        pagination = build_pagination(
            total=int(session.scalar(select(func.count(PayRun.id))) or 0),
            page=page, page_size=page_size, path="/ui/pay-runs",
        )
        pay_runs = session.scalars(
            select(PayRun)
            .order_by(PayRun.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).all()

        run_data = [
            {
                "id": run.id,
                "period_start": run.period_start,
                "period_end": run.period_end,
                "payment_date": run.payment_date,
                "status": run.status
            }
            for run in pay_runs
        ]

    return templates.TemplateResponse(
        request=request,
        name="pay_runs.html",
        context={"pay_runs": run_data, "pagination": pagination}
    )


@app.get("/ui/pay-runs/new", response_class=HTMLResponse)
def create_pay_run_page(request: Request):

    with SessionLocal() as session:

        organisations = session.scalars(
            select(Organisation).order_by(Organisation.name)
        ).all()

        organisation_data = [
            {
                "id": organisation.id,
                "name": organisation.name
            }
            for organisation in organisations
        ]

    return templates.TemplateResponse(
        request=request,
        name="pay_run_create.html",
        context={"organisations": organisation_data}
    )


@app.get("/ui/pay-runs/{pay_run_id}", response_class=HTMLResponse)
def pay_run_detail_page(request: Request, pay_run_id: int):

    with SessionLocal() as session:

        pay_run = session.get(PayRun, pay_run_id)

        if pay_run is None:
            raise HTTPException(
                status_code=404,
                detail="Pay run not found"
            )

        organisation = session.get(
            Organisation,
            pay_run.organisation_id
        )

        rows = session.execute(
            select(Payslip, Engagement, Worker)
            .join(Engagement, Payslip.engagement_id == Engagement.id)
            .join(Worker, Engagement.worker_id == Worker.id)
            .where(Payslip.pay_run_id == pay_run_id)
            .order_by(Worker.last_name, Worker.first_name)
        ).all()

        payslip_data = [
            {
                "id": payslip.id,
                "worker_id": worker.id,
                "worker_name": (
                    f"{worker.first_name} {worker.last_name}"
                ),
                "gross_pay": payslip.gross_pay,
                "payg_withholding": payslip.payg_withholding,
                "net_pay": payslip.net_pay,
                "superannuation": payslip.superannuation
            }
            for payslip, engagement, worker in rows
        ]

        totals = {
            "employees_paid": len(payslip_data),
            "gross_pay": sum(
                (p["gross_pay"] for p in payslip_data),
                Decimal("0.00")
            ),
            "payg_withholding": sum(
                (p["payg_withholding"] for p in payslip_data),
                Decimal("0.00")
            ),
            "net_pay": sum(
                (p["net_pay"] for p in payslip_data),
                Decimal("0.00")
            ),
            "superannuation": sum(
                (p["superannuation"] for p in payslip_data),
                Decimal("0.00")
            )
        }

        pay_run_data = {
            "id": pay_run.id,
            "organisation_name": organisation.name,
            "period_start": pay_run.period_start,
            "period_end": pay_run.period_end,
            "payment_date": pay_run.payment_date,
            "status": pay_run.status
        }
        from app.models.aba_profile import ABAProfile
        from app.models.payment_batch import PaymentBatch
        payment_batch = session.scalar(select(PaymentBatch).where(
            PaymentBatch.pay_run_id == pay_run.id
        ))
        aba_profile = session.scalar(select(ABAProfile).where(
            ABAProfile.organisation_id == pay_run.organisation_id,
            ABAProfile.active.is_(True),
        ))
        payment_data = {
            "batch_id": payment_batch.id if payment_batch else None,
            "batch_status": payment_batch.status if payment_batch else None,
            "aba_configured": aba_profile is not None,
            "organisation_id": pay_run.organisation_id,
        }

    return templates.TemplateResponse(
        request=request,
        name="pay_run_detail.html",
        context={
            "pay_run": pay_run_data,
            "payslips": payslip_data,
            "totals": totals,
            "payment_data": payment_data,
        }
    )


@app.get("/ui/organisations", response_class=HTMLResponse)
def organisations_page(request: Request):

    with SessionLocal() as session:

        rows = session.execute(
            select(
                Organisation,
                func.count(func.distinct(Engagement.worker_id)).label("worker_count")
            )
            .outerjoin(
                Engagement,
                Engagement.organisation_id == Organisation.id
            )
            .group_by(Organisation.id)
            .order_by(Organisation.id.desc())
        ).all()

        organisation_data = [
            {
                "id": org.id,
                "name": org.name,
                "abn": org.abn,
                "country": org.country,
                "worker_count": worker_count
            }
            for org, worker_count in rows
        ]

    return templates.TemplateResponse(
        request=request,
        name="organisations.html",
        context={"organisations": organisation_data}
    )


class OrganisationInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    abn: str
    country: str = "AU"


def validate_organisation(data: OrganisationInput):
    if not data.name.strip():
        raise HTTPException(422, "Organisation name is required")

    abn = "".join(data.abn.split())

    if len(abn) != 11 or not abn.isdigit():
        raise HTTPException(422, "ABN must contain 11 digits")

    if data.country != "AU":
        raise HTTPException(422, "Only Australian organisations are supported")

    return abn


@app.get("/ui/organisations/new", response_class=HTMLResponse)
def new_organisation_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="organisation_form.html",
        context={"organisation": None}
    )


@app.get("/ui/organisations/{organisation_id}/edit", response_class=HTMLResponse)
def edit_organisation_page(request: Request, organisation_id: int):
    with SessionLocal() as db:
        organisation = db.get(Organisation, organisation_id)

        if organisation is None:
            raise HTTPException(404, "Organisation not found")

        data = {
            "id": organisation.id,
            "name": organisation.name,
            "abn": organisation.abn,
            "country": organisation.country
        }

    return templates.TemplateResponse(
        request=request,
        name="organisation_form.html",
        context={"organisation": data}
    )


@app.post("/api/organisations", status_code=201)
def create_organisation(data: OrganisationInput):
    from sqlalchemy.exc import IntegrityError

    abn = validate_organisation(data)

    with SessionLocal() as db:
        organisation = Organisation(
            name=data.name.strip(),
            abn=abn,
            country="AU"
        )
        db.add(organisation)

        try:
            db.commit()
            db.refresh(organisation)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Organisation ABN already exists")

        return {"id": organisation.id, "status": "created"}


@app.patch("/api/organisations/{organisation_id}")
def update_organisation(organisation_id: int, data: OrganisationInput):
    from sqlalchemy.exc import IntegrityError

    abn = validate_organisation(data)

    with SessionLocal() as db:
        organisation = db.get(Organisation, organisation_id)

        if organisation is None:
            raise HTTPException(404, "Organisation not found")

        organisation.name = data.name.strip()
        organisation.abn = abn
        organisation.country = "AU"

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Organisation ABN already exists")

        return {"id": organisation_id, "status": "updated"}


# ============================================================
# EMPLOYMENT AGREEMENT VIEW AND EDIT
# ============================================================

class WorkPatternUpdate(BaseModel):
    employment_type: str
    pay_basis: str
    hourly_rate: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    ordinary_hours_per_week: Decimal = Field(
        gt=0, le=168, max_digits=5, decimal_places=2
    )
    pay_frequency: str
    start_date: date
    end_date: date | None = None





@app.get(
    "/ui/workers/{worker_id}/engagements/{engagement_id}/work-patterns",
    response_class=HTMLResponse,
)
def engagement_work_patterns_page(
    request: Request,
    worker_id: int,
    engagement_id: int,
):
    with SessionLocal() as db:

        engagement = db.get(Engagement, engagement_id)

        if engagement is None or engagement.worker_id != worker_id:
            raise HTTPException(
                status_code=404,
                detail="Worker Engagement not found",
            )

        if engagement.engagement_type not in (
            "payg_employee",
            "employee",
        ):
            raise HTTPException(
                status_code=409,
                detail="Work Patterns are available only for PAYG Employees",
            )

        patterns = db.scalars(
            select(WorkPattern)
            .where(WorkPattern.engagement_id == engagement_id)
            .order_by(WorkPattern.start_date.desc(), WorkPattern.id.desc())
        ).all()


        # Payslips for this Engagement, newest first.
        payslip_rows = db.execute(
            select(Payslip, PayRun)
            .join(
                PayRun,
                Payslip.pay_run_id == PayRun.id
            )
            .where(
                Payslip.engagement_id == engagement_id
            )
            .order_by(Payslip.id.desc())
        ).all()

        payslip_data = [
            {
                "id": payslip.id,
                "period_start": pay_run.period_start,
                "period_end": pay_run.period_end,
                "payment_date": pay_run.payment_date,
                "gross_pay": payslip.gross_pay,
                "payg_withholding": payslip.payg_withholding,
                "net_pay": payslip.net_pay,
                "superannuation": payslip.superannuation,
                "status": pay_run.status,
            }
            for payslip, pay_run in payslip_rows
        ]

        return templates.TemplateResponse(
            request=request,
            name="engagement_work_patterns.html",
            context={
                "worker_id": worker_id,
                "worker_name": (
                    f"{engagement.worker.first_name} "
                    f"{engagement.worker.last_name}"
                ),
                "engagement_id": engagement.id,
                "organisation_name": engagement.organisation.name,
                "patterns": patterns,
                "payslips": payslip_data,
            },
        )




# ============================================================
# WORK PATTERN PAYROLL SHORTCUT
# ============================================================

def _prepare_work_pattern_payroll(db, worker_id, engagement_id):
    """
    Prepare the next weekly PAYG Employee payroll.

    This function performs no database writes.
    """

    from datetime import timedelta
    from decimal import Decimal, ROUND_HALF_UP

    from app.models.employee_tax_profile import EmployeeTaxProfile
    from app.models.employee_super_profile import EmployeeSuperProfile
    from app.payroll.payg_withholding import PAYGWithholdingCalculator
    from app.payroll.superannuation import SuperannuationCalculator

    engagement = db.get(Engagement, engagement_id)

    if engagement is None or engagement.worker_id != worker_id:
        raise HTTPException(404, "Worker Engagement not found")

    if engagement.engagement_type != "payg_employee":
        raise HTTPException(
            409,
            "Generate Payroll is available only for PAYG Employees",
        )

    if engagement.status != "active" or not engagement.worker.active:
        raise HTTPException(409, "Worker or Engagement is inactive")

    # Find the latest existing payslip by pay period.
    latest = db.execute(
        select(Payslip, PayRun)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(Payslip.engagement_id == engagement_id)
        .order_by(
            PayRun.period_end.desc(),
            Payslip.id.desc(),
        )
    ).first()

    patterns = db.scalars(
        select(WorkPattern)
        .where(WorkPattern.engagement_id == engagement_id)
        .order_by(
            WorkPattern.start_date.desc(),
            WorkPattern.id.desc(),
        )
    ).all()

    if not patterns:
        raise HTTPException(409, "No Work Pattern configured")

    # Current shortcut supports weekly Work Patterns.
    weekly_patterns = [
        pattern for pattern in patterns
        if pattern.pay_frequency == "weekly"
    ]

    if not weekly_patterns:
        raise HTTPException(
            409,
            "Weekly Work Pattern required for this payroll shortcut",
        )

    if latest:
        period_start = latest[1].period_end + timedelta(days=1)

        if period_start.weekday() != 0:
            raise HTTPException(
                409,
                "Latest payslip does not end on Sunday. "
                "Review payroll periods before proceeding.",
            )

    else:
        # First payroll: start on the first Monday on or
        # after the Engagement and Work Pattern commencement.
        starts = [
            value for value in (
                engagement.start_date,
                weekly_patterns[-1].start_date,
            )
            if value is not None
        ]

        first_day = max(starts)

        # Do not silently skip an initial partial work week.
        if first_day.weekday() not in (0, 6):
            raise HTTPException(
                409,
                "Initial partial-week payroll requires manual review",
            )

        period_start = first_day + timedelta(
            days=(7 - first_day.weekday()) % 7
        )

    period_end = period_start + timedelta(days=6)
    payment_date = period_end + timedelta(days=1)

    if (
        engagement.start_date is not None
        and engagement.start_date > period_start
    ):
        raise HTTPException(409, "Engagement starts after pay period")

    if (
        engagement.end_date is not None
        and engagement.end_date < period_end
    ):
        raise HTTPException(
            409,
            "Partial final pay period requires manual review",
        )

    applicable = [
        pattern for pattern in patterns
        if pattern.start_date <= period_start
        and (
            pattern.end_date is None
            or pattern.end_date >= period_end
        )
    ]

    if len(applicable) != 1:
        raise HTTPException(
            409,
            "Expected exactly one Work Pattern covering next pay period",
        )

    pattern = applicable[0]

    if pattern.pay_frequency != "weekly":
        raise HTTPException(409, "Work Pattern is not weekly")

    if pattern.pay_basis != "hourly":
        raise HTTPException(
            409,
            "This shortcut currently supports hourly Work Patterns",
        )

    hours = Decimal(pattern.ordinary_hours_per_week)
    rate = Decimal(pattern.hourly_rate)

    if hours <= 0 or rate <= 0:
        raise HTTPException(409, "Invalid Work Pattern remuneration")

    gross = (hours * rate).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    # Check overlapping payroll history.
    overlapping = db.scalar(
        select(Payslip.id)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(
            Payslip.engagement_id == engagement_id,
            PayRun.period_start <= period_end,
            PayRun.period_end >= period_start,
        )
        .limit(1)
    )

    if overlapping is not None:
        raise HTTPException(
            409,
            "A payslip already exists for this pay period",
        )

    # Tax profile effective on payment date.
    tax_profiles = db.scalars(
        select(EmployeeTaxProfile).where(
            EmployeeTaxProfile.worker_id == worker_id,
            EmployeeTaxProfile.effective_from <= payment_date,
            (
                EmployeeTaxProfile.effective_to.is_(None)
                | (
                    EmployeeTaxProfile.effective_to >= payment_date
                )
            ),
        )
    ).all()

    if len(tax_profiles) != 1:
        raise HTTPException(
            409,
            "Expected exactly one effective Tax Profile",
        )

    tax = tax_profiles[0]

    if (
        tax.residency_status != "resident"
        or tax.has_study_loan
        or not tax.tfn_declaration_received
    ):
        raise HTTPException(
            409,
            "Tax Profile is not supported or incomplete",
        )

    payg = PAYGWithholdingCalculator().calculate(
        session=db,
        gross_pay=gross,
        pay_frequency="weekly",
        claims_tax_free_threshold=tax.claims_tax_free_threshold,
        payment_date=payment_date,
    )

    # Super profile effective on payment date.
    super_profiles = db.scalars(
        select(EmployeeSuperProfile).where(
            EmployeeSuperProfile.worker_id == worker_id,
            EmployeeSuperProfile.effective_from <= payment_date,
            (
                EmployeeSuperProfile.effective_to.is_(None)
                | (
                    EmployeeSuperProfile.effective_to >= payment_date
                )
            ),
        )
    ).all()

    if len(super_profiles) != 1:
        raise HTTPException(
            409,
            "Expected exactly one effective Super Profile",
        )

    additional_rate = (
        super_profiles[0].additional_employer_rate
        or Decimal("0")
    )

    if additional_rate < 0:
        raise HTTPException(409, "Invalid additional super rate")

    statutory_super = SuperannuationCalculator().calculate(
        ordinary_time_earnings=gross
    )

    additional_super = SuperannuationCalculator().calculate(
        ordinary_time_earnings=gross,
        rate=additional_rate / Decimal("100"),
    )

    return {
        "worker_id": worker_id,
        "worker_name": (
            f"{engagement.worker.first_name} "
            f"{engagement.worker.last_name}"
        ),
        "engagement_id": engagement_id,
        "organisation_id": engagement.organisation_id,
        "organisation_name": engagement.organisation.name,
        "pattern_id": pattern.id,
        "period_start": period_start,
        "period_end": period_end,
        "payment_date": payment_date,
        "hours": hours,
        "rate": rate,
        "gross": gross,
        "payg": payg,
        "net": gross - payg,
        "statutory_super": statutory_super,
        "additional_super": additional_super,
        "total_super": statutory_super + additional_super,
    }


@app.get(
    "/ui/workers/{worker_id}/engagements/{engagement_id}/payroll/preview",
    response_class=HTMLResponse,
)
def preview_work_pattern_payroll(
    request: Request,
    worker_id: int,
    engagement_id: int,
):
    with SessionLocal() as db:
        preview = _prepare_work_pattern_payroll(
            db,
            worker_id,
            engagement_id,
        )

        return templates.TemplateResponse(
            request=request,
            name="work_pattern_payroll_preview.html",
            context={"payroll": preview},
        )


@app.post(
    "/ui/workers/{worker_id}/engagements/{engagement_id}/payroll/generate",
)
def generate_work_pattern_payroll(
    request: Request,
    worker_id: int,
    engagement_id: int,
    expected_period_start: str = Form(...),
):
    """
    Generate a draft Pay Run for ONE PAYG Employee Engagement.

    Never process every worker in the organisation here.
    """

    from sqlalchemy import text
    from app.payroll.pay_run_processor import PayRunProcessor

    with SessionLocal() as db:

        try:
            # Serialise payroll generation for this Engagement.
            # This prevents concurrent requests generating duplicates.
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": 700000000 + engagement_id},
            )

            # Recalculate everything immediately before generation.
            preview = _prepare_work_pattern_payroll(
                db,
                worker_id,
                engagement_id,
            )

            if preview["period_start"].isoformat() != expected_period_start:
                raise HTTPException(
                    409,
                    "Payroll period has changed. Refresh the preview.",
                )

            pay_run = PayRun(
                organisation_id=preview["organisation_id"],
                period_start=preview["period_start"],
                period_end=preview["period_end"],
                payment_date=preview["payment_date"],
                status="draft",
            )

            db.add(pay_run)
            db.flush()

            engagement = db.get(Engagement, engagement_id)

            # IMPORTANT:
            # Process only this Engagement, NOT the whole Organisation.
            result = PayRunProcessor()._process_payg_employee_weekly(
                session=db,
                pay_run=pay_run,
                engagement=engagement,
            )

            if result != 1:
                raise HTTPException(
                    409,
                    "Selected Engagement was not processed",
                )

            payslip = db.scalar(
                select(Payslip).where(
                    Payslip.pay_run_id == pay_run.id,
                    Payslip.engagement_id == engagement_id,
                )
            )

            if payslip is None:
                raise HTTPException(
                    500,
                    "Payroll processing did not create a Payslip",
                )

            db.commit()

        except Exception:
            db.rollback()
            raise

    return RedirectResponse(
        url=(
            f"/ui/workers/{worker_id}/engagements/"
            f"{engagement_id}/work-patterns"
        ),
        status_code=303,
    )


@app.get(
    "/ui/engagements/{engagement_id}/agreements/new",
    response_class=HTMLResponse,
)
def new_work_pattern_page(request: Request, engagement_id: int):
    with SessionLocal() as db:
        engagement = db.get(Engagement, engagement_id)
        if engagement is None or engagement.worker is None:
            raise HTTPException(404, "Engagement not found")

        form_data = {
            "id": engagement.id,
            "worker_name": (
                f"{engagement.worker.first_name} "
                f"{engagement.worker.last_name}"
            ),
            "organisation_name": engagement.organisation.name,
            "worker_id": engagement.worker_id,
        }

    return templates.TemplateResponse(
        request=request,
        name="agreement_create.html",
        context={"engagement": form_data},
    )


@app.post("/api/engagements/{engagement_id}/agreements", status_code=201)
def create_work_pattern(engagement_id: int, data: WorkPatternUpdate):
    if data.employment_type not in {
        "full_time", "part_time", "casual", "fixed_term"
    }:
        raise HTTPException(422, "Invalid employment type")

    if data.pay_basis not in {"hourly", "salary"}:
        raise HTTPException(422, "Invalid pay basis")

    if data.pay_frequency not in {"weekly", "fortnightly", "monthly"}:
        raise HTTPException(422, "Invalid pay frequency")

    if data.end_date is not None and data.end_date < data.start_date:
        raise HTTPException(422, "End date cannot be before start date")

    with SessionLocal() as db:
        engagement = db.get(Engagement, engagement_id)
        if engagement is None or engagement.worker is None:
            raise HTTPException(404, "Engagement not found")

        agreement = WorkPattern(
            engagement_id=engagement_id,
            employee_id=None,
            employment_type=data.employment_type,
            pay_basis=data.pay_basis,
            hourly_rate=data.hourly_rate,
            ordinary_hours_per_week=data.ordinary_hours_per_week,
            pay_frequency=data.pay_frequency,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        db.add(agreement)
        db.commit()
        db.refresh(agreement)
        return {"id": agreement.id, "status": "created"}






@app.get("/ui/agreements/{agreement_id}", response_class=HTMLResponse)
def view_work_pattern(request: Request, agreement_id: int):

    with SessionLocal() as db:

        agreement = db.get(WorkPattern, agreement_id)

        if agreement is None:
            raise HTTPException(
                status_code=404,
                detail="Employment agreement not found"
            )

        engagement = db.get(Engagement, agreement.engagement_id)

        if engagement is None or engagement.worker is None:
            raise HTTPException(
                status_code=409,
                detail="Work pattern requires a valid Engagement and Worker"
            )

        worker = engagement.worker

        return templates.TemplateResponse(
            request=request,
            name="agreement_detail.html",
            context={
                "agreement": agreement,
                "worker_name": f"{worker.first_name} {worker.last_name}",
                "is_active": (
                    agreement.start_date <= date.today()
                    and (
                        agreement.end_date is None
                        or agreement.end_date >= date.today()
                    )
                )
            }
        )


@app.get("/ui/agreements/{agreement_id}/edit", response_class=HTMLResponse)
def edit_work_pattern(request: Request, agreement_id: int):

    with SessionLocal() as db:

        agreement = db.get(WorkPattern, agreement_id)

        if agreement is None:
            raise HTTPException(
                status_code=404,
                detail="Employment agreement not found"
            )

        engagement = db.get(Engagement, agreement.engagement_id)

        if engagement is None or engagement.worker is None:
            raise HTTPException(
                status_code=409,
                detail="Work pattern requires a valid Engagement and Worker"
            )

        worker = engagement.worker

        return templates.TemplateResponse(
            request=request,
            name="agreement_edit.html",
            context={
                "agreement": agreement,
                "worker_name": f"{worker.first_name} {worker.last_name}"
            }
        )


@app.patch("/api/agreements/{agreement_id}")
def update_work_pattern(
    agreement_id: int,
    data: WorkPatternUpdate
):

    if data.employment_type not in {
        "full_time", "part_time", "casual", "fixed_term"
    }:
        raise HTTPException(
            status_code=422,
            detail="Invalid employment type"
        )

    if data.pay_basis not in {"hourly", "salary"}:
        raise HTTPException(
            status_code=422,
            detail="Invalid pay basis"
        )

    if data.pay_frequency not in {
        "weekly", "fortnightly", "monthly"
    }:
        raise HTTPException(
            status_code=422,
            detail="Invalid pay frequency"
        )

    if data.end_date is not None and data.end_date < data.start_date:
        raise HTTPException(
            status_code=422,
            detail="End date cannot be before start date"
        )

    with SessionLocal() as db:

        agreement = db.get(WorkPattern, agreement_id)

        if agreement is None:
            raise HTTPException(
                status_code=404,
                detail="Employment agreement not found"
            )

        agreement.employment_type = data.employment_type
        agreement.pay_basis = data.pay_basis
        agreement.hourly_rate = data.hourly_rate
        agreement.ordinary_hours_per_week = data.ordinary_hours_per_week
        agreement.pay_frequency = data.pay_frequency
        agreement.start_date = data.start_date
        agreement.end_date = data.end_date

        db.commit()

        return {
            "id": agreement_id,
            "status": "updated"
        }

@app.get("/ui/agreements", response_class=HTMLResponse)
def agreements_page(
    request: Request, page: int = 1, page_size: int = 25,
):

    with SessionLocal() as session:

        pagination = build_pagination(
            total=int(session.scalar(select(func.count(WorkPattern.id))) or 0),
            page=page, page_size=page_size, path="/ui/agreements",
        )
        rows = session.execute(
            select(WorkPattern, Engagement, Worker)
            .join(Engagement, WorkPattern.engagement_id == Engagement.id)
            .join(Worker, Engagement.worker_id == Worker.id)
            .order_by(Worker.last_name, Worker.first_name)
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).all()

        today = date.today()

        agreement_data = [
            {
                "id": agreement.id,
                "worker_id": worker.id,
                "worker_name": f"{worker.first_name} {worker.last_name}",
                "employment_type": agreement.employment_type,
                "pay_basis": agreement.pay_basis,
                "hourly_rate": agreement.hourly_rate,
                "ordinary_hours_per_week": agreement.ordinary_hours_per_week,
                "pay_frequency": agreement.pay_frequency,
                "start_date": agreement.start_date,
                "end_date": agreement.end_date,
                "is_active": (
                    agreement.start_date <= today
                    and (
                        agreement.end_date is None
                        or agreement.end_date >= today
                    )
                )
            }
            for agreement, engagement, worker in rows
        ]

    return templates.TemplateResponse(
        request=request,
        name="agreements.html",
        context={"agreements": agreement_data, "pagination": pagination}
    )


@app.get("/ui/payslips", response_class=HTMLResponse)
def payslips_page(
    request: Request, page: int = 1, page_size: int = 25,
):

    with SessionLocal() as session:

        pagination = build_pagination(
            total=int(session.scalar(select(func.count(Payslip.id))) or 0),
            page=page, page_size=page_size, path="/ui/payslips",
        )
        rows = session.execute(
            select(Payslip, Engagement, Worker, PayRun)
            .join(Engagement, Payslip.engagement_id == Engagement.id)
            .join(Worker, Engagement.worker_id == Worker.id)
            .join(PayRun, Payslip.pay_run_id == PayRun.id)
            .order_by(
                PayRun.id.desc(),
                Payslip.id.desc()
            )
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).all()

        payslip_data = [
            {
                "id": payslip.id,
                "worker_id": worker.id,
                "worker_name": (
                    f"{worker.first_name} {worker.last_name}"
                ),
                "pay_run_id": pay_run.id,
                "period_start": pay_run.period_start,
                "period_end": pay_run.period_end,
                "payment_date": pay_run.payment_date,
                "gross_pay": payslip.gross_pay,
                "payg_withholding": payslip.payg_withholding,
                "net_pay": payslip.net_pay,
                "superannuation": payslip.superannuation
            }
            for payslip, engagement, worker, pay_run in rows
        ]

    return templates.TemplateResponse(
        request=request,
        name="payslips.html",
        context={"payslips": payslip_data, "pagination": pagination}
    )


# ============================================================
# INVOICING
# ============================================================


# ============================================================
# WORKER ENGAGEMENT MANAGEMENT
# ============================================================

class AssignmentInput(BaseModel):
    engagement_id: int
    customer_id: int
    pbt_schedule_id: int | None = None
    host_organisation_id: int | None = None
    billing_rate: Decimal
    start_date: date | None = None
    end_date: date | None = None




@app.get(
    "/ui/workers/{worker_id}/engagements/{engagement_id}/assignments",
    response_class=HTMLResponse,
)
def worker_engagement_assignments_page(
    request: Request,
    worker_id: int,
    engagement_id: int,
):
    with SessionLocal() as db:

        engagement = db.get(Engagement, engagement_id)

        if engagement is None or engagement.worker_id != worker_id:
            raise HTTPException(
                status_code=404,
                detail="Worker Engagement not found",
            )

        assignments = db.scalars(
            select(Assignment)
            .where(Assignment.engagement_id == engagement_id)
            .order_by(Assignment.id)
        ).all()

        return templates.TemplateResponse(
            request=request,
            name="engagement_assignments.html",
            context={
                "worker_id": worker_id,
                "worker_name": (
                    f"{engagement.worker.first_name} "
                    f"{engagement.worker.last_name}"
                ),
                "engagement_id": engagement.id,
                "engagement_type": engagement.engagement_type,
                "organisation_name": engagement.organisation.name,
                "assignments": [
                    {
                        "id": assignment.id,
                        "customer": assignment.customer.name,
                        "host_organisation": (
                            assignment.host_organisation.name
                            if assignment.host_organisation
                            else "Not assigned"
                        ),
                        "pbt_schedule": (
                            assignment.pbt_schedule.name
                            if assignment.pbt_schedule else "Not assigned"
                        ),
                        "billing_rate": assignment.billing_rate,
                    }
                    for assignment in assignments
                ],
            },
        )




# ============================================================
# ASSIGNMENT PREVIEW
# ============================================================

@app.get(
    "/ui/workers/{worker_id}/engagements/{engagement_id}/assignments/{assignment_id}/preview",
    response_class=HTMLResponse,
)
def assignment_preview_page(
    request: Request,
    worker_id: int,
    engagement_id: int,
    assignment_id: int,
):
    from decimal import Decimal

    from app.models.invoice_timesheet import InvoiceTimesheet
    from app.models.payslip_timesheet import PayslipTimesheet

    with SessionLocal() as db:

        # --------------------------------------------------
        # Validate Worker -> Engagement -> Assignment.
        # --------------------------------------------------

        engagement = db.get(Engagement, engagement_id)

        if engagement is None or engagement.worker_id != worker_id:
            raise HTTPException(
                status_code=404,
                detail="Worker Engagement not found",
            )

        assignment = db.get(Assignment, assignment_id)

        if assignment is None or assignment.engagement_id != engagement_id:
            raise HTTPException(
                status_code=404,
                detail="Assignment not found for this Engagement",
            )

        worker = engagement.worker
        organisation = engagement.organisation
        customer = assignment.customer
        customer_options = db.scalars(
            select(Organisation).order_by(Organisation.name)
        ).all()
        pbt_schedule_options = db.scalars(
            select(PBTSchedule).order_by(PBTSchedule.name, PBTSchedule.id)
        ).all()

        definitions = db.scalars(
            select(ComponentDefinition)
            .order_by(ComponentDefinition.name)
        ).all()
        families = db.scalars(
            select(ComponentFamily).order_by(ComponentFamily.name)
        ).all()
        family_names = {
            family.id: family.name for family in families
        }
        definition_lookup = {
            definition.id: definition for definition in definitions
        }
        component_groups = {}

        for definition in definitions:
            if not definition.active:
                continue
            family_name = family_names.get(definition.family_id, "Other")
            component_groups.setdefault(family_name, []).append({
                "id": definition.id,
                "name": definition.name,
            })

        configured_components = db.scalars(
            select(AssignmentComponent)
            .where(AssignmentComponent.assignment_id == assignment_id)
            .order_by(
                AssignmentComponent.effective_from.desc(),
                AssignmentComponent.id.desc(),
            )
        ).all()
        component_history = []

        for component in configured_components:
            definition = definition_lookup.get(
                component.component_definition_id
            )
            component_history.append({
                "id": component.id,
                "component_definition_id": (
                    component.component_definition_id
                ),
                "name": definition.name if definition else "Unknown",
                "calculation_type": (
                    definition.calculation_type if definition else ""
                ),
                "applies_to": component.applies_to,
                "pay_rate": component.pay_rate,
                "bill_rate": component.bill_rate,
                "effective_from": component.effective_from,
                "effective_to": component.effective_to,
            })

        # --------------------------------------------------
        # TIMESHEETS
        #
        # Retrieve only daily entries linked to this
        # Assignment, then group weekly entries by header.
        # This ensures hours are Assignment-specific.
        # --------------------------------------------------

        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.assignment_id == assignment_id)
            .order_by(Timesheet.id.desc())
        ).all()

        timesheet_groups = {}

        for entry in entries:

            if entry.timesheet_header_id is not None:

                header = db.get(
                    TimesheetHeader,
                    entry.timesheet_header_id,
                )

                if header is None:
                    raise HTTPException(
                        409,
                        "Timesheet references a missing weekly header",
                    )

                key = ("weekly", header.id)

                if key not in timesheet_groups:
                    timesheet_groups[key] = {
                        "id": header.id,
                        "sort_id": header.id,
                        "type": "Weekly",
                        "period_start": header.period_start,
                        "period_end": header.period_end,
                        "hours": Decimal("0.00"),
                        "status": header.status,
                        "url": (
                            f"/ui/timesheets/weekly/"
                            f"{header.id}/preview"
                        ),
                    }

            else:

                key = ("daily", entry.id)

                timesheet_groups[key] = {
                    "id": entry.id,
                    "sort_id": entry.id,
                    "type": "Daily",
                    "period_start": entry.work_date,
                    "period_end": entry.work_date,
                    "hours": Decimal("0.00"),
                    "status": entry.status,
                    "url": (
                        f"/ui/timesheets/daily/"
                        f"{entry.id}/preview"
                    ),
                }

            timesheet_groups[key]["hours"] += entry.hours_worked

        timesheet_data = sorted(
            timesheet_groups.values(),
            key=lambda row: row["sort_id"],
            reverse=True,
        )

        # --------------------------------------------------
        # CUSTOMER INVOICES
        #
        # IMPORTANT:
        # Invoice.engagement_id is the historical column
        # name and references assignments.id.
        #
        # Do not confuse this with a canonical Engagement ID.
        # --------------------------------------------------

        invoices = db.scalars(
            select(Invoice)
            .where(Invoice.engagement_id == assignment_id)
            .order_by(Invoice.id.desc())
        ).all()

        invoice_data = [
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "issue_date": invoice.issue_date,
                "due_date": invoice.due_date,
                "subtotal": invoice.subtotal,
                "gst": invoice.gst,
                "total": invoice.total,
                "status": invoice.status,
            }
            for invoice in invoices
        ]

        # --------------------------------------------------
        # PAYSLIPS
        #
        # Use PayslipTimesheet -> Timesheet -> Assignment.
        # A Payslip may cover multiple Assignments.
        #
        # Do not attribute the full Payslip amount as
        # revenue/cost solely for this Assignment.
        # --------------------------------------------------

        payslip_rows = db.execute(
            select(Payslip, PayRun)
            .join(
                PayslipTimesheet,
                PayslipTimesheet.payslip_id == Payslip.id,
            )
            .join(
                Timesheet,
                Timesheet.id == PayslipTimesheet.timesheet_id,
            )
            .join(
                PayRun,
                PayRun.id == Payslip.pay_run_id,
            )
            .where(
                Timesheet.assignment_id == assignment_id,
                Payslip.engagement_id == engagement_id,
            )
            .distinct()
            .order_by(Payslip.id.desc())
        ).all()

        payslip_data = [
            {
                "id": payslip.id,
                "period_start": pay_run.period_start,
                "period_end": pay_run.period_end,
                "payment_date": pay_run.payment_date,
                "gross_pay": payslip.gross_pay,
                "payg_withholding": payslip.payg_withholding,
                "net_pay": payslip.net_pay,
                "superannuation": payslip.superannuation,
                "status": pay_run.status,
            }
            for payslip, pay_run in payslip_rows
        ]

        return templates.TemplateResponse(
            request=request,
            name="assignment_preview.html",
            context={
                "worker_id": worker_id,
                "engagement_id": engagement_id,
                "assignment_id": assignment_id,
                "worker_name": (
                    f"{worker.first_name} {worker.last_name}"
                ),
                "organisation_name": organisation.name,
                "customer_name": customer.name,
                "engagement_type": engagement.engagement_type,
                "billing_rate": assignment.billing_rate,
                "assignment_start_date": assignment.start_date,
                "assignment_end_date": assignment.end_date,
                "assignment_customer_id": assignment.customer_id,
                "assignment_pbt_schedule_id": assignment.pbt_schedule_id,
                "assignment_pbt_schedule_name": (
                    assignment.pbt_schedule.name
                    if assignment.pbt_schedule else None
                ),
                "assignment_host_organisation_id": (
                    assignment.host_organisation_id
                ),
                "assignment_host_organisation_name": (
                    assignment.host_organisation.name
                    if assignment.host_organisation else None
                ),
                "customer_options": [
                    {"id": option.id, "name": option.name}
                    for option in customer_options
                ],
                "pbt_schedule_options": [
                    {
                        "id": option.id,
                        "customer_id": option.customer_organisation_id,
                        "name": option.name,
                        "status": option.status,
                    }
                    for option in pbt_schedule_options
                ],
                "component_groups": component_groups,
                "component_history": component_history,
                "timesheets": timesheet_data,
                "invoices": invoice_data,
                "payslips": payslip_data,
            },
        )


@app.get("/ui/engagements", response_class=HTMLResponse)
def assignments_page(
    request: Request, page: int = 1, page_size: int = 25,
):
    with SessionLocal() as db:
        pagination = build_pagination(
            total=int(db.scalar(select(func.count(Assignment.id))) or 0),
            page=page, page_size=page_size, path="/ui/engagements",
        )
        assignments = db.scalars(
            select(Assignment).order_by(Assignment.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).all()
        assignment_data = [
            {
                "id": assignment.id,
                "engagement_id": assignment.engagement_id,
                "worker_id": (
                    assignment.engagement.worker_id
                    if assignment.engagement is not None
                    else None
                ),
                "customer_id": assignment.customer_id,
                "pbt_schedule_id": assignment.pbt_schedule_id,
                "pbt_schedule_name": (
                    assignment.pbt_schedule.name
                    if assignment.pbt_schedule else "Not assigned"
                ),
                "host_organisation_id": assignment.host_organisation_id,
                "host_organisation_name": (
                    assignment.host_organisation.name
                    if assignment.host_organisation else "Not assigned"
                ),
                "employee_name": (
                    f"{assignment.engagement.worker.first_name} "
                    f"{assignment.engagement.worker.last_name}"
                    if assignment.engagement is not None
                    else "Historical assignment (Engagement link missing)"
                ),
                "customer_name": assignment.customer.name,
                "billing_rate": str(assignment.billing_rate),
                "start_date": (
                    assignment.start_date.isoformat()
                    if assignment.start_date else ""
                ),
                "start_date_display": (
                    assignment.start_date.strftime("%d/%m/%Y")
                    if assignment.start_date else "Not set"
                ),
                "end_date": (
                    assignment.end_date.isoformat()
                    if assignment.end_date else ""
                ),
                "end_date_display": (
                    assignment.end_date.strftime("%d/%m/%Y")
                    if assignment.end_date else "Ongoing"
                ),
            }
            for assignment in assignments
        ]
        engagements = db.scalars(
            select(Engagement).order_by(Engagement.id)
        ).all()
        engagement_options = [
            {
                "id": engagement.id,
                "name": (
                    f"{engagement.worker.first_name} "
                    f"{engagement.worker.last_name} — "
                    f"{engagement.organisation.name}"
                ),
            }
            for engagement in engagements
        ]
        customers = db.scalars(
            select(Organisation).order_by(Organisation.name)
        ).all()
        pbt_schedules = db.scalars(
            select(PBTSchedule).order_by(PBTSchedule.name, PBTSchedule.id)
        ).all()

    return templates.TemplateResponse(
        request=request,
        name="engagements.html",
        context={
            "engagements": assignment_data,
            "engagement_options": engagement_options,
            "customers": [
                {"id": customer.id, "name": customer.name}
                for customer in customers
            ],
            "pbt_schedules": [
                {
                    "id": schedule.id,
                    "customer_id": schedule.customer_organisation_id,
                    "name": schedule.name,
                    "status": schedule.status,
                }
                for schedule in pbt_schedules
            ],
            "pagination": pagination,
        },
    )


def validate_engagement_input(db, data):
    if (
        data.start_date is not None
        and data.end_date is not None
        and data.end_date < data.start_date
    ):
        raise HTTPException(422, "End date cannot be before start date")
    if not data.billing_rate.is_finite() or data.billing_rate <= 0:
        raise HTTPException(422, "Billing rate must be greater than zero")
    if data.billing_rate.as_tuple().exponent < -2:
        raise HTTPException(422, "Billing rate cannot have more than two decimal places")
    if data.billing_rate > Decimal("99999999.99"):
        raise HTTPException(422, "Billing rate exceeds the maximum allowed")
    if db.get(Engagement, data.engagement_id) is None:
        raise HTTPException(404, "Engagement not found")
    if db.get(Organisation, data.customer_id) is None:
        raise HTTPException(404, "Customer organisation not found")
    if data.pbt_schedule_id is not None:
        pbt_schedule = db.get(PBTSchedule, data.pbt_schedule_id)
        if pbt_schedule is None:
            raise HTTPException(404, "PBT schedule not found")
        if pbt_schedule.customer_organisation_id != data.customer_id:
            raise HTTPException(
                422,
                "PBT schedule must belong to the assignment customer",
            )
    if (
        data.host_organisation_id is not None
        and db.get(Organisation, data.host_organisation_id) is None
    ):
        raise HTTPException(404, "Host organisation not found")


@app.post("/api/engagements")
def create_engagement(data: AssignmentInput):
    # Compatibility URL: this endpoint actually creates an Assignment.
    with SessionLocal() as db:
        validate_engagement_input(db, data)
        assignment = Assignment(
            engagement_id=data.engagement_id,
            employee_id=None,
            customer_id=data.customer_id,
            pbt_schedule_id=data.pbt_schedule_id,
            host_organisation_id=data.host_organisation_id,
            billing_rate=data.billing_rate,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return {"id": assignment.id}


@app.patch("/api/engagements/{engagement_id}")
def update_engagement(engagement_id: int, data: AssignmentInput):
    # Compatibility URL: engagement_id path value is an Assignment ID.
    with SessionLocal() as db:
        assignment = db.get(Assignment, engagement_id)
        if assignment is None:
            raise HTTPException(404, "Assignment not found")
        validate_engagement_input(db, data)
        assignment.engagement_id = data.engagement_id
        assignment.employee_id = None
        assignment.customer_id = data.customer_id
        assignment.pbt_schedule_id = data.pbt_schedule_id
        assignment.host_organisation_id = data.host_organisation_id
        assignment.billing_rate = data.billing_rate
        assignment.start_date = data.start_date
        assignment.end_date = data.end_date
        db.commit()
        return {"id": assignment.id}


@app.post("/ui/engagements/create")
def create_assignment(
    engagement_id: int = Form(...),
    customer_id: int = Form(...),
    pbt_schedule_id: int | None = Form(None),
    host_organisation_id: int | None = Form(None),
    billing_rate: Decimal = Form(...),
    start_date: date | None = Form(None),
    end_date: date | None = Form(None),
):
    data = AssignmentInput(
        engagement_id=engagement_id,
        customer_id=customer_id,
        pbt_schedule_id=pbt_schedule_id,
        host_organisation_id=host_organisation_id,
        billing_rate=billing_rate,
        start_date=start_date,
        end_date=end_date,
    )
    with SessionLocal() as db:
        validate_engagement_input(db, data)
        assignment = Assignment(
            engagement_id=data.engagement_id,
            employee_id=None,
            customer_id=data.customer_id,
            pbt_schedule_id=data.pbt_schedule_id,
            host_organisation_id=data.host_organisation_id,
            billing_rate=data.billing_rate,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        db.add(assignment)
        db.commit()
    return RedirectResponse(url="/ui/invoices", status_code=303)


@app.post("/ui/invoices/generate")
def generate_invoice_from_ui(
    request: Request,
    engagement_id: int = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...)
):
    try:
        generate_invoice(
            engagement_id=engagement_id,
            start_date=start_date,
            end_date=end_date
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    return RedirectResponse(
        url="/ui/invoices",
        status_code=303
    )


@app.post("/ui/invoices/{invoice_id}/status")
def update_invoice_status(
    invoice_id: int,
    status: str = Form(...)
):
    allowed_transitions = {
        "draft": "issued",
        "issued": "paid",
    }

    with SessionLocal() as session:
        invoice = session.get(Invoice, invoice_id)

        if invoice is None:
            raise HTTPException(
                status_code=404,
                detail="Invoice not found"
            )

        expected_status = allowed_transitions.get(invoice.status)

        if status != expected_status:
            raise HTTPException(
                status_code=400,
                detail="Invalid invoice status transition"
            )

        invoice.status = status
        session.commit()

    return RedirectResponse(
        url="/ui/invoices",
        status_code=303
    )


@app.post("/ui/invoices/{invoice_id}/delete")
def delete_invoice(invoice_id: int):
    try:
        delete_draft_invoice(invoice_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/ui/invoices", status_code=303)


@app.get("/ui/invoices", response_class=HTMLResponse)
def invoices_page(
    request: Request, page: int = 1, page_size: int = 25,
):
    with SessionLocal() as session:
        assignments = session.scalars(
            select(Assignment).order_by(Assignment.id)
        ).all()
        engagement_data = [
            {
                "id": assignment.id,
                "label": (
                    f"{assignment.engagement.worker.first_name} "
                    f"{assignment.engagement.worker.last_name} — "
                    f"{assignment.customer.name} "
                    f"(${assignment.billing_rate:.2f}/hr)"
                ) if assignment.engagement is not None
                  else f"Historical assignment #{assignment.id}",
            }
            for assignment in assignments
        ]
        pagination = build_pagination(
            total=int(session.scalar(select(func.count(Invoice.id))) or 0),
            page=page, page_size=page_size, path="/ui/invoices",
        )
        invoices = session.scalars(
            select(Invoice).order_by(Invoice.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).all()
        invoice_data = []
        for invoice in invoices:
            # Invoice.engagement_id is a historical name for Assignment ID.
            assignment = session.get(Assignment, invoice.engagement_id)
            if assignment is None:
                raise HTTPException(409, f"Invoice {invoice.id} has no Assignment")
            worker = (
                assignment.engagement.worker
                if assignment.engagement is not None else None
            )
            payroll_payslip_id = session.scalar(
                select(PayslipTimesheet.payslip_id)
                .join(
                    InvoiceTimesheet,
                    InvoiceTimesheet.timesheet_id
                    == PayslipTimesheet.timesheet_id,
                )
                .where(InvoiceTimesheet.invoice_id == invoice.id)
                .limit(1)
            )
            engagement = assignment.engagement
            payroll_unavailable_reason = None
            if payroll_payslip_id is not None:
                payroll_unavailable_reason = (
                    f"Payroll already exists (payslip #{payroll_payslip_id})"
                )
            elif engagement is None:
                payroll_unavailable_reason = "Invoice has no canonical engagement"
            elif engagement.engagement_type != "payg_contractor":
                payroll_unavailable_reason = (
                    "Invoice payroll is available only for PAYG contractors"
                )
            elif invoice.status not in {"issued", "paid"}:
                payroll_unavailable_reason = (
                    "Issue the invoice before generating payroll"
                )
            elif engagement.status != "active" or not engagement.worker.active:
                payroll_unavailable_reason = "Worker or engagement is inactive"
            invoice_data.append({
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "issue_date": invoice.issue_date,
                "due_date": invoice.due_date,
                "customer": assignment.customer.name,
                "worker": (
                    f"{worker.first_name} {worker.last_name}"
                    if worker is not None else "Historical worker"
                ),
                "subtotal": invoice.subtotal,
                "gst": invoice.gst,
                "total": invoice.total,
                "status": invoice.status,
                "payroll_payslip_id": payroll_payslip_id,
                "payroll_selectable": payroll_unavailable_reason is None,
                "payroll_unavailable_reason": payroll_unavailable_reason,
            })

    return templates.TemplateResponse(
        request=request,
        name="invoices.html",
        context={
            "invoices": invoice_data,
            "engagements": engagement_data,
            "pagination": pagination,
        },
    )




@app.get(
    "/ui/invoices/{invoice_id}/preview",
    response_class=HTMLResponse,
)
def preview_invoice_page(request: Request, invoice_id: int):

    with SessionLocal() as session:

        invoice = session.get(Invoice, invoice_id)

        if invoice is None:
            raise HTTPException(
                status_code=404,
                detail="Invoice not found",
            )

        # Historical database field name:
        # Invoice.engagement_id references assignments.id.
        assignment = session.get(
            Assignment,
            invoice.engagement_id,
        )

        if assignment is None or assignment.engagement is None:
            raise HTTPException(
                status_code=409,
                detail="Invoice Assignment has no canonical Engagement",
            )

        worker = assignment.engagement.worker
        supplier = assignment.engagement.organisation
        customer = assignment.customer

        timesheets = session.scalars(
            select(Timesheet)
            .join(
                InvoiceTimesheet,
                InvoiceTimesheet.timesheet_id == Timesheet.id,
            )
            .where(InvoiceTimesheet.invoice_id == invoice.id)
            .order_by(Timesheet.work_date)
        ).all()

        hours = sum(
            (entry.hours_worked for entry in timesheets),
            Decimal("0.00"),
        )

        component_rows = session.execute(
            select(InvoiceComponent, ComponentDefinition)
            .outerjoin(
                ComponentDefinition,
                ComponentDefinition.id
                == InvoiceComponent.component_definition_id,
            )
            .where(InvoiceComponent.invoice_id == invoice.id)
            .order_by(InvoiceComponent.processing_order, InvoiceComponent.id)
        ).all()
        line_items = [
            {
                "description": component.component_name or (definition.name if definition else "Services provided"),
                "calculation_type": (
                    "percentage" if component.calculation_method == "percentage_of_value"
                    else "hourly" if component.calculation_method == "amount_per_unit"
                    else "fixed" if (component.calculation_method or "").startswith("fixed_per_")
                    else (definition.calculation_type if definition else "hourly")
                ),
                "quantity": component.quantity,
                "rate": component.rate,
                "amount": component.amount,
                "base_amount": component.base_amount,
                "explanation": component.explanation,
                "calculation_method": component.calculation_method,
                "unit_type": component.unit_type or "hours",
            }
            for component, definition in component_rows
        ]

        return templates.TemplateResponse(
            request=request,
            name="invoice_preview.html",
            context={
                "invoice": invoice,
                "assignment": assignment,
                "worker": worker,
                "supplier": supplier,
                "customer": customer,
                "hours": hours,
                "timesheets": timesheets,
                "line_items": line_items,
            },
        )




# ============================================================
# PROTOTYPE: PAYG CONTRACTOR PAYROLL FROM CUSTOMER INVOICE
#
# The customer invoice is used ONLY to identify approved work.
# Payroll uses Assignment payroll rates, NOT customer billing.
#
# Production contractor-issued invoices require a separate
# supplier invoice/payment obligation workflow.
# ============================================================

def _prepare_invoice_contractor_payroll(db, invoice_id):

    from datetime import timedelta
    from decimal import Decimal

    from app.models.invoice_timesheet import InvoiceTimesheet
    from app.models.payslip_timesheet import PayslipTimesheet

    from app.models.employee_tax_profile import EmployeeTaxProfile
    from app.models.employee_super_profile import EmployeeSuperProfile

    from app.payroll.assignment_earnings import AssignmentEarningsCalculator
    from app.payroll.payg_withholding import PAYGWithholdingCalculator
    from app.payroll.superannuation import SuperannuationCalculator

    invoice = db.get(Invoice, invoice_id)

    if invoice is None:
        raise HTTPException(404, "Invoice not found")

    if invoice.status not in ("issued", "paid"):
        raise HTTPException(
            409,
            "Customer invoice must be issued before payroll generation",
        )

    # Historical field name: Invoice.engagement_id
    # actually contains an Assignment ID.
    assignment = db.get(
        Assignment,
        invoice.engagement_id,
    )

    if assignment is None or assignment.engagement is None:
        raise HTTPException(
            409,
            "Invoice has no valid Assignment and Engagement",
        )

    engagement = assignment.engagement

    if engagement.engagement_type != "payg_contractor":
        raise HTTPException(
            409,
            "Invoice-linked payroll is available only for PAYG Contractors",
        )

    if engagement.status != "active" or not engagement.worker.active:
        raise HTTPException(
            409,
            "Worker or Engagement is inactive",
        )

    invoice_entries = db.scalars(
        select(Timesheet)
        .join(
            InvoiceTimesheet,
            InvoiceTimesheet.timesheet_id == Timesheet.id,
        )
        .where(InvoiceTimesheet.invoice_id == invoice.id)
        .order_by(Timesheet.work_date, Timesheet.id)
    ).all()

    if not invoice_entries:
        raise HTTPException(
            409,
            "Invoice has no linked Timesheets",
        )

    header_ids = {
        entry.timesheet_header_id
        for entry in invoice_entries
    }

    if not header_ids or None in header_ids:
        raise HTTPException(
            409,
            "Invoice must reference header-based Timesheets",
        )

    headers = db.scalars(
        select(TimesheetHeader)
        .where(TimesheetHeader.id.in_(header_ids))
        .order_by(TimesheetHeader.period_start, TimesheetHeader.id)
    ).all()
    if len(headers) != len(header_ids):
        raise HTTPException(
            409,
            "One or more linked Timesheet headers are invalid",
        )
    if any(header.period_type not in {"weekly", "scheduled"} for header in headers):
        raise HTTPException(
            409,
            "Invoice contains an unsupported Timesheet type",
        )
    if any(header.status != "approved" for header in headers):
        raise HTTPException(
            409,
            "All linked Timesheets must be approved",
        )
    if any(header.engagement_id != engagement.id for header in headers):
        raise HTTPException(409, "Timesheet Engagement mismatch")

    # Customer invoices exclude leave-family rows. Once their headers are
    # identified, payroll reloads every row so paid leave remains included.
    entries = db.scalars(
        select(Timesheet)
        .where(Timesheet.timesheet_header_id.in_(header_ids))
        .order_by(Timesheet.work_date, Timesheet.id)
    ).all()
    for header in headers:
        header_entries = [
            entry for entry in entries
            if entry.timesheet_header_id == header.id
        ]
        expected_dates = {
            header.period_start + timedelta(days=offset)
            for offset in range(
                (header.period_end - header.period_start).days + 1
            )
        }
        if {entry.work_date for entry in header_entries} != expected_dates:
            raise HTTPException(
                409,
                f"Timesheet #{header.id} does not cover its complete period",
            )

    payroll_period_start = min(header.period_start for header in headers)
    payroll_period_end = max(header.period_end for header in headers)

    for entry in entries:

        if entry.status != "approved":
            raise HTTPException(
                409,
                f"Timesheet entry {entry.id} is not approved",
            )

        if entry.assignment_id != assignment.id:
            raise HTTPException(
                409,
                "Invoice contains work for a different Assignment",
            )

        if entry.engagement_id != engagement.id:
            raise HTTPException(
                409,
                "Timesheet Engagement mismatch",
            )

    # Prevent an overlapping payslip, including one created
    # by the separate weekly Timesheet payroll workflow.
    overlapping = db.scalar(
        select(Payslip.id)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(
            Payslip.engagement_id == engagement.id,
            PayRun.period_start <= payroll_period_end,
            PayRun.period_end >= payroll_period_start,
        )
        .limit(1)
    )

    if overlapping is not None:
        raise HTTPException(
            409,
            "An overlapping Payslip already exists",
        )

    # Also prevent paying any underlying daily entry twice.
    already_paid = db.scalar(
        select(PayslipTimesheet.timesheet_id)
        .where(
            PayslipTimesheet.timesheet_id.in_(
                [entry.id for entry in entries]
            )
        )
        .limit(1)
    )

    if already_paid is not None:
        raise HTTPException(
            409,
            "One or more Timesheet entries have already been paid",
        )

    try:
        earnings = AssignmentEarningsCalculator().calculate(
            session=db,
            engagement=engagement,
            timesheets=entries,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    gross = earnings["gross_pay"]

    if gross <= 0:
        raise HTTPException(
            409,
            "Calculated gross earnings must be positive",
        )

    payment_period = None
    pay_frequency = "weekly"
    if assignment.pbt_schedule_id is not None:
        payment_period = db.scalar(
            select(PBTSchedulePeriod)
            .where(
                PBTSchedulePeriod.pbt_schedule_id == assignment.pbt_schedule_id,
                PBTSchedulePeriod.schedule_type == "payment",
                PBTSchedulePeriod.period_start <= payroll_period_end,
                PBTSchedulePeriod.period_end >= payroll_period_end,
            )
            .order_by(PBTSchedulePeriod.period_start)
            .limit(1)
        )
    if payment_period is not None:
        payment_date = payment_period.event_date
        payment_rule = payment_period.rule
        pay_frequency = (
            "fortnightly"
            if payment_rule.frequency == "semi_monthly"
            else payment_rule.frequency
        )
    else:
        payment_date = payroll_period_end + timedelta(days=1)

    # Tax profile
    tax_profiles = db.scalars(
        select(EmployeeTaxProfile).where(
            EmployeeTaxProfile.worker_id == engagement.worker_id,
            EmployeeTaxProfile.effective_from <= payment_date,
            (
                EmployeeTaxProfile.effective_to.is_(None)
                | (
                    EmployeeTaxProfile.effective_to >= payment_date
                )
            ),
        )
    ).all()

    if len(tax_profiles) != 1:
        raise HTTPException(
            409,
            "Expected exactly one effective Tax Profile",
        )

    tax = tax_profiles[0]

    if (
        tax.residency_status != "resident"
        or tax.has_study_loan
        or not tax.tfn_declaration_received
    ):
        raise HTTPException(
            409,
            "Tax Profile is incomplete or unsupported",
        )

    try:
        payg = PAYGWithholdingCalculator().calculate(
            session=db,
            gross_pay=gross,
            pay_frequency=pay_frequency,
            claims_tax_free_threshold=tax.claims_tax_free_threshold,
            payment_date=payment_date,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    # Superannuation profile
    super_profiles = db.scalars(
        select(EmployeeSuperProfile).where(
            EmployeeSuperProfile.worker_id == engagement.worker_id,
            EmployeeSuperProfile.effective_from <= payment_date,
            (
                EmployeeSuperProfile.effective_to.is_(None)
                | (
                    EmployeeSuperProfile.effective_to >= payment_date
                )
            ),
        )
    ).all()

    if len(super_profiles) != 1:
        raise HTTPException(
            409,
            "Expected exactly one effective Superannuation Profile",
        )

    additional_rate = (
        super_profiles[0].additional_employer_rate
        or Decimal("0")
    )

    if additional_rate < 0:
        raise HTTPException(
            409,
            "Invalid additional employer super rate",
        )

    statutory_super = SuperannuationCalculator().calculate(
        ordinary_time_earnings=gross
    )

    additional_super = SuperannuationCalculator().calculate(
        ordinary_time_earnings=gross,
        rate=additional_rate / Decimal("100"),
    )

    total_super = statutory_super + additional_super

    earnings_definition_ids = {
        line["component_definition_id"] for line in earnings["lines"]
    }
    statutory_codes = {
        "PAYG_WITHHOLDING", "SUPER_GUARANTEE", "SUPER_EMPLOYER_EXTRA"
    }
    definition_rows = db.execute(
        select(ComponentDefinition, ComponentFamily)
        .join(
            ComponentFamily,
            ComponentFamily.id == ComponentDefinition.family_id,
        )
        .where(
            (ComponentDefinition.id.in_(earnings_definition_ids))
            | (ComponentDefinition.code.in_(statutory_codes))
        )
    ).all()
    definition_details = {
        definition.id: (definition, family)
        for definition, family in definition_rows
    }
    definitions_by_code = {
        definition.code: (definition, family)
        for definition, family in definition_rows
    }
    missing_statutory = statutory_codes - definitions_by_code.keys()
    if missing_statutory:
        raise HTTPException(
            409,
            f"Missing payroll component definitions: "
            f"{sorted(missing_statutory)}",
        )

    grouped_components = {}

    def add_component(definition, family, quantity, rate, amount):
        group = grouped_components.setdefault(
            family.code,
            {
                "code": family.code,
                "name": family.name,
                "items": [],
                "subtotal": Decimal("0.00"),
            },
        )
        group["items"].append({
            "name": definition.name,
            "calculation_type": definition.calculation_type,
            "quantity": quantity,
            "rate": rate,
            "amount": amount,
        })
        group["subtotal"] += amount

    for line in earnings["lines"]:
        details = definition_details.get(line["component_definition_id"])
        if details is None:
            raise HTTPException(409, "Payroll component definition not found")
        add_component(
            *details, line["quantity"], line["rate"], line["amount"]
        )

    payg_definition, payg_family = definitions_by_code["PAYG_WITHHOLDING"]
    add_component(
        payg_definition, payg_family, Decimal("1"), payg, payg
    )
    guarantee_definition, guarantee_family = definitions_by_code[
        "SUPER_GUARANTEE"
    ]
    add_component(
        guarantee_definition, guarantee_family, gross, Decimal("0.12"),
        statutory_super,
    )
    extra_definition, extra_family = definitions_by_code[
        "SUPER_EMPLOYER_EXTRA"
    ]
    add_component(
        extra_definition, extra_family, gross,
        additional_rate / Decimal("100"), additional_super,
    )

    family_order = {
        "EARNINGS": 0, "LEAVE": 1, "TAX": 2, "SUPERANNUATION": 3
    }
    component_groups = sorted(
        grouped_components.values(),
        key=lambda group: (family_order.get(group["code"], 99), group["name"]),
    )

    hours = sum(
        (entry.hours_worked for entry in entries),
        Decimal("0"),
    )

    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_total": invoice.total,
        "worker_id": engagement.worker_id,
        "worker_name": (
            f"{engagement.worker.first_name} "
            f"{engagement.worker.last_name}"
        ),
        "engagement_id": engagement.id,
        "assignment_id": assignment.id,
        "organisation_id": engagement.organisation_id,
        "header_id": headers[0].id,
        "timesheet_headers": [
            {
                "id": header.id,
                "period_type": header.period_type,
                "period_start": header.period_start,
                "period_end": header.period_end,
            }
            for header in headers
        ],
        "period_start": payroll_period_start,
        "period_end": payroll_period_end,
        "payment_date": payment_date,
        "pay_frequency": pay_frequency,
        "hours": hours,
        "gross": gross,
        "payg": payg,
        "net": gross - payg,
        "statutory_super": statutory_super,
        "additional_super": additional_super,
        "total_super": total_super,
        "component_groups": component_groups,
        "earnings_lines": earnings["lines"],
        "timesheet_ids": [entry.id for entry in entries],
    }


@app.get(
    "/ui/invoices/{invoice_id}/payroll/preview",
    response_class=HTMLResponse,
)
def preview_invoice_contractor_payroll(
    request: Request,
    invoice_id: int,
):

    with SessionLocal() as db:

        payroll = _prepare_invoice_contractor_payroll(
            db,
            invoice_id,
        )

        return templates.TemplateResponse(
            request=request,
            name="invoice_payroll_preview.html",
            context={"payroll": payroll},
        )


@app.post(
    "/ui/invoices/{invoice_id}/payroll/generate",
)
def generate_invoice_contractor_payroll(
    request: Request,
    invoice_id: int,
    expected_period_start: str = Form(...),
):

    from sqlalchemy import text

    from app.models.payroll_component import PayrollComponent
    from app.models.component_definition import ComponentDefinition
    from app.models.payslip_timesheet import PayslipTimesheet

    from decimal import Decimal

    with SessionLocal() as db:

        try:
            invoice = db.get(Invoice, invoice_id)

            if invoice is None:
                raise HTTPException(404, "Invoice not found")

            assignment = db.get(
                Assignment,
                invoice.engagement_id,
            )

            if assignment is None or assignment.engagement_id is None:
                raise HTTPException(
                    409,
                    "Invoice Assignment has no Engagement",
                )

            if db.bind.dialect.name != "postgresql":
                raise HTTPException(
                    409,
                    "Invoice-linked payroll requires PostgreSQL",
                )

            # Same advisory-lock namespace as weekly
            # Timesheet contractor payroll.
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": 800000000 + assignment.engagement_id},
            )

            # Revalidate everything while holding the lock.
            payroll = _prepare_invoice_contractor_payroll(
                db,
                invoice_id,
            )

            if payroll["period_start"].isoformat() != expected_period_start:
                raise HTTPException(
                    409,
                    "Payroll period changed. Refresh the preview.",
                )

            required_codes = {
                "ORDINARY_HOURS",
                "PAYG_WITHHOLDING",
                "SUPER_GUARANTEE",
                "SUPER_EMPLOYER_EXTRA",
            }

            definitions = {
                definition.code: definition
                for definition in db.scalars(
                    select(ComponentDefinition).where(
                        ComponentDefinition.code.in_(required_codes)
                    )
                )
            }

            missing = required_codes - definitions.keys()

            if missing:
                raise HTTPException(
                    409,
                    f"Missing payroll component definitions: {sorted(missing)}",
                )

            # Create a draft Pay Run for this Engagement's payroll.
            # Do NOT process the whole organisation.
            pay_run = PayRun(
                organisation_id=payroll["organisation_id"],
                period_start=payroll["period_start"],
                period_end=payroll["period_end"],
                payment_date=payroll["payment_date"],
                status="draft",
            )

            db.add(pay_run)
            db.flush()

            payslip = Payslip(
                pay_run_id=pay_run.id,
                engagement_id=payroll["engagement_id"],
                employee_id=None,
                gross_pay=payroll["gross"],
                payg_withholding=payroll["payg"],
                net_pay=payroll["net"],
                superannuation=payroll["total_super"],
            )

            db.add(payslip)
            db.flush()

            # Realised earning components
            for line in payroll["earnings_lines"]:
                db.add(
                    PayrollComponent(
                        payslip_id=payslip.id,
                        component_definition_id=line[
                            "component_definition_id"
                        ],
                        quantity=line["quantity"],
                        rate=line["rate"],
                        amount=line["amount"],
                    )
                )

            # Statutory payroll components
            statutory_components = (
                (
                    "PAYG_WITHHOLDING",
                    Decimal("1"),
                    payroll["payg"],
                    payroll["payg"],
                ),
                (
                    "SUPER_GUARANTEE",
                    payroll["gross"],
                    Decimal("0.12"),
                    payroll["statutory_super"],
                ),
                (
                    "SUPER_EMPLOYER_EXTRA",
                    payroll["gross"],
                    (
                        payroll["additional_super"] / payroll["gross"]
                        if payroll["gross"]
                        else Decimal("0")
                    ),
                    payroll["additional_super"],
                ),
            )

            for code, quantity, rate, amount in statutory_components:
                db.add(
                    PayrollComponent(
                        payslip_id=payslip.id,
                        component_definition_id=definitions[code].id,
                        quantity=quantity,
                        rate=rate,
                        amount=amount,
                    )
                )

            for timesheet_id in payroll["timesheet_ids"]:
                db.add(
                    PayslipTimesheet(
                        payslip_id=payslip.id,
                        timesheet_id=timesheet_id,
                    )
                )

            db.flush()
            db.commit()

            created_payslip_id = payslip.id

        except Exception:
            db.rollback()
            raise

    return RedirectResponse(
        url=f"/ui/payslips/{created_payslip_id}/preview",
        status_code=303,
    )


@app.get("/invoices/{invoice_id}/pdf")
def download_invoice_pdf(invoice_id: int):
    with SessionLocal() as session:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            raise HTTPException(404, "Invoice not found")

        # The legacy Invoice.engagement_id column references assignments.id.
        assignment = session.get(Assignment, invoice.engagement_id)
        if assignment is None or assignment.engagement is None:
            raise HTTPException(409, "Invoice Assignment has no canonical Engagement")
        worker = assignment.engagement.worker
        supplier = assignment.engagement.organisation
        customer = assignment.customer
        timesheets = session.scalars(
            select(Timesheet)
            .join(
                InvoiceTimesheet,
                InvoiceTimesheet.timesheet_id == Timesheet.id,
            )
            .where(InvoiceTimesheet.invoice_id == invoice.id)
        ).all()
        hours = sum(t.hours_worked for t in timesheets)
        component_rows = session.execute(
            select(InvoiceComponent, ComponentDefinition)
            .outerjoin(
                ComponentDefinition,
                ComponentDefinition.id
                == InvoiceComponent.component_definition_id,
            )
            .where(InvoiceComponent.invoice_id == invoice.id)
            .order_by(InvoiceComponent.processing_order, InvoiceComponent.id)
        ).all()
        line_items = [
            {
                "description": component.component_name or (definition.name if definition else "Services provided"),
                "calculation_type": (
                    "percentage" if component.calculation_method == "percentage_of_value"
                    else "hourly" if component.calculation_method == "amount_per_unit"
                    else "fixed" if (component.calculation_method or "").startswith("fixed_per_")
                    else (definition.calculation_type if definition else "hourly")
                ),
                "quantity": component.quantity,
                "rate": component.rate,
                "amount": component.amount,
                "base_amount": component.base_amount,
                "explanation": component.explanation,
                "calculation_method": component.calculation_method,
                "unit_type": component.unit_type or "hours",
            }
            for component, definition in component_rows
        ]
        pdf = InvoicePDFGenerator().generate(
            invoice=invoice,
            engagement=assignment,
            worker=worker,
            supplier=supplier,
            customer=customer,
            hours=hours,
            line_items=line_items,
        )
        return StreamingResponse(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'inline; filename="{invoice.invoice_number}.pdf"'
            },
        )


# ============================================================
# AUTHENTICATION
# ============================================================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)

    if not request.session.get("csrf_token"):
        request.session["csrf_token"] = secrets.token_urlsafe(32)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None}
    )


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with SessionLocal() as db:
        user = db.query(User).filter(
            User.email == email.strip().lower(),
            User.is_active == True
        ).first()

        if (
            not user
            or user.role != "admin"
            or not verify_password(password, user.password_hash)
        ):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"error": "Invalid email or password"},
                status_code=401
            )

        request.session.clear()
        request.session["user_id"] = user.id
        request.session["csrf_token"] = secrets.token_urlsafe(32)

    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


