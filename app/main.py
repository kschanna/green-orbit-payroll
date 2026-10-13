import os
from pathlib import Path
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware
from datetime import date
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func, select
from app.database import SessionLocal
from app.models.organisation import Organisation
from app.models.employee import Employee
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.payroll.pay_run_processor import PayRunProcessor
from app.payroll.pay_run_lifecycle import PayRunLifecycle
from app.reports.payslip_pdf import PayslipPDFGenerator
from app.models.employment_agreement import EmploymentAgreement
from fastapi import Form
from fastapi.responses import RedirectResponse
from app.models.user import User
from app.security import verify_password
from fastapi.responses import JSONResponse
import secrets
from fastapi.responses import PlainTextResponse
import secrets
from fastapi.responses import PlainTextResponse

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
    version="0.1.0"
)

session_secret = os.environ.get("SESSION_SECRET")

if not session_secret:
    raise RuntimeError("SESSION_SECRET environment variable is required")

# ============================================================
# SECURITY
# ============================================================

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
    public_paths = {"/login", "/health"}

    if request.url.path in public_paths or request.url.path.startswith("/static/"):
        return await call_next(request)

    user_id = request.session.get("user_id")
    authenticated = False

    if user_id is not None:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            authenticated = user is not None and user.is_active

    if not authenticated:
        request.session.clear()

        if request.url.path.startswith("/api/") or request.url.path in {
            "/docs", "/redoc", "/openapi.json"
        }:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        return RedirectResponse("/login", status_code=303)

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
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


# ============================================================
# WEB UI — DASHBOARD
# ============================================================

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):

    with SessionLocal() as session:

        employee_count = session.scalar(
            select(func.count(Employee.id))
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
            .order_by(PayRun.payment_date.desc())
            .limit(10)
        ).all()

        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "employee_count": employee_count,
                "pay_run_count": pay_run_count,
                "completed_count": completed_count,
                "pay_runs": pay_runs
            }
        )


# ============================================================
# EMPLOYEE API
# ============================================================

@app.get("/employees")
def get_employees():

    with SessionLocal() as session:

        employees = session.scalars(
            select(Employee).order_by(Employee.id)
        ).all()

        return [
            {
                "id": employee.id,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "email": employee.email,
                "organisation_id": employee.organisation_id
            }
            for employee in employees
        ]


# ============================================================
# PAY RUN API
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
            select(Payslip, Employee)
            .join(
                Employee,
                Payslip.employee_id == Employee.id
            )
            .where(Payslip.pay_run_id == pay_run_id)
            .order_by(Employee.id)
        ).all()

        return [
            {
                "payslip_id": payslip.id,
                "employee_id": employee.id,
                "employee_name": (
                    f"{employee.first_name} {employee.last_name}"
                ),
                "gross_pay": payslip.gross_pay,
                "payg_withholding": payslip.payg_withholding,
                "net_pay": payslip.net_pay,
                "superannuation": payslip.superannuation
            }
            for payslip, employee in rows
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
            select(Payslip, Employee)
            .join(
                Employee,
                Payslip.employee_id == Employee.id
            )
            .where(Payslip.pay_run_id == pay_run_id)
            .order_by(Employee.id)
        ).all()

        payslips = [
            {
                "employee_id": employee.id,
                "employee_name": (
                    f"{employee.first_name} {employee.last_name}"
                ),
                "gross_pay": str(payslip.gross_pay),
                "payg_withholding": str(payslip.payg_withholding),
                "net_pay": str(payslip.net_pay),
                "superannuation": str(payslip.superannuation)
            }
            for payslip, employee in rows
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

@app.get("/payslips/{payslip_id}/pdf")
def download_payslip_pdf(payslip_id: int):

    with SessionLocal() as session:

        payslip = session.get(Payslip, payslip_id)

        if payslip is None:
            raise HTTPException(
                status_code=404,
                detail="Payslip not found"
            )

        employee = session.get(
            Employee,
            payslip.employee_id
        )

        pay_run = session.get(
            PayRun,
            payslip.pay_run_id
        )

        organisation = session.get(
            Organisation,
            pay_run.organisation_id
        )

        pdf_buffer = PayslipPDFGenerator().generate(
            payslip=payslip,
            employee=employee,
            organisation=organisation,
            pay_run=pay_run
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
@app.get("/ui/employees", response_class=HTMLResponse)
def employees_page(request: Request):

    with SessionLocal() as session:

        employees = session.scalars(
            select(Employee)
            .order_by(Employee.last_name, Employee.first_name)
        ).all()

        # Prepare the data while the database session is open
        employee_data = [
            {
                "id": employee.id,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "email": employee.email,
                "organisation": {
                    "name": employee.organisation.name
                }
            }
            for employee in employees
        ]

    return templates.TemplateResponse(
        request=request,
        name="employees.html",
        context={"employees": employee_data}
    )

@app.get("/ui/employees/{employee_id}", response_class=HTMLResponse)
def employee_detail_page(request: Request, employee_id: int):

    with SessionLocal() as session:

        employee = session.get(Employee, employee_id)

        if employee is None:
            raise HTTPException(
                status_code=404,
                detail="Employee not found"
            )

        organisation = session.get(
            Organisation,
            employee.organisation_id
        )

        agreements = session.scalars(
            select(EmploymentAgreement)
            .where(EmploymentAgreement.employee_id == employee_id)
            .order_by(EmploymentAgreement.start_date.desc())
        ).all()

        employee_data = {
            "id": employee.id,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "email": employee.email,
            "organisation_name": organisation.name
        }

        agreement_data = [
            {
                "employment_type": agreement.employment_type,
                "pay_basis": agreement.pay_basis,
                "hourly_rate": float(agreement.hourly_rate),
                "ordinary_hours_per_week": agreement.ordinary_hours_per_week,
                "pay_frequency": agreement.pay_frequency,
                "start_date": agreement.start_date,
                "end_date": agreement.end_date
            }
            for agreement in agreements
        ]

    return templates.TemplateResponse(
        request=request,
        name="employee_detail.html",
        context={
            "employee": employee_data,
            "agreements": agreement_data
        }
    )

@app.get("/ui/pay-runs", response_class=HTMLResponse)
def pay_runs_page(request: Request):

    with SessionLocal() as session:

        pay_runs = session.scalars(
            select(PayRun)
            .order_by(PayRun.payment_date.desc())
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
        context={
            "pay_runs": run_data
        }
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
        context={
            "organisations": organisation_data
        }
    )



@app.get("/ui/pay-runs/{pay_run_id}", response_class=HTMLResponse)
def pay_run_detail_page(request: Request, pay_run_id: int):

    with SessionLocal() as session:

        # Retrieve pay run
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

        # Retrieve employee payslips
        rows = session.execute(
            select(Payslip, Employee)
            .join(Employee, Payslip.employee_id == Employee.id)
            .where(Payslip.pay_run_id == pay_run_id)
            .order_by(Employee.last_name, Employee.first_name)
        ).all()

        payslip_data = [
            {
                "id": payslip.id,
                "employee_id": employee.id,
                "employee_name": (
                    f"{employee.first_name} {employee.last_name}"
                ),
                "gross_pay": payslip.gross_pay,
                "payg_withholding": payslip.payg_withholding,
                "net_pay": payslip.net_pay,
                "superannuation": payslip.superannuation
            }
            for payslip, employee in rows
        ]

        # Calculate payroll totals
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

    return templates.TemplateResponse(
        request=request,
        name="pay_run_detail.html",
        context={
            "pay_run": pay_run_data,
            "payslips": payslip_data,
            "totals": totals
        }
    )

@app.get("/ui/organisations", response_class=HTMLResponse)
def organisations_page(request: Request):

    with SessionLocal() as session:

        rows = session.execute(
            select(
                Organisation,
                func.count(Employee.id).label("employee_count")
            )
            .outerjoin(
                Employee,
                Employee.organisation_id == Organisation.id
            )
            .group_by(Organisation.id)
            .order_by(Organisation.name)
        ).all()

        organisation_data = [
            {
                "id": org.id,
                "name": org.name,
                "abn": org.abn,
                "country": org.country,
                "employee_count": employee_count
            }
            for org, employee_count in rows
        ]

    return templates.TemplateResponse(
        request=request,
        name="organisations.html",
        context={"organisations": organisation_data}
    )

@app.get("/ui/agreements", response_class=HTMLResponse)
def agreements_page(request: Request):

    with SessionLocal() as session:

        rows = session.execute(
            select(EmploymentAgreement, Employee)
            .join(
                Employee,
                EmploymentAgreement.employee_id == Employee.id
            )
            .order_by(Employee.last_name, Employee.first_name)
        ).all()

        today = date.today()

        agreement_data = [
            {
                "id": agreement.id,
                "employee_id": employee.id,
                "employee_name": (
                    f"{employee.first_name} {employee.last_name}"
                ),
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
            for agreement, employee in rows
        ]

    return templates.TemplateResponse(
        request=request,
        name="agreements.html",
        context={
            "agreements": agreement_data
        }
    )

@app.get("/ui/payslips", response_class=HTMLResponse)
def payslips_page(request: Request):

    with SessionLocal() as session:

        rows = session.execute(
            select(Payslip, Employee, PayRun)
            .join(
                Employee,
                Payslip.employee_id == Employee.id
            )
            .join(
                PayRun,
                Payslip.pay_run_id == PayRun.id
            )
            .order_by(
                PayRun.payment_date.desc(),
                Employee.last_name,
                Employee.first_name
            )
        ).all()

        payslip_data = [
            {
                "id": payslip.id,
                "employee_id": employee.id,
                "employee_name": (
                    f"{employee.first_name} {employee.last_name}"
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
            for payslip, employee, pay_run in rows
        ]

    return templates.TemplateResponse(
        request=request,
        name="payslips.html",
        context={
            "payslips": payslip_data
        }
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

        if not user or not verify_password(password, user.password_hash):
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