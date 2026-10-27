import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from app.database import SessionLocal
from app.document_service import (
    DOCUMENT_TYPES,
    MAX_DOCUMENT_BYTES,
    DocumentService,
    DocumentValidationError,
)
from app.document_storage import get_document_storage
from app.models.user import User
from app.models.worker import Worker
from app.models.worker_document import WorkerDocument
from app.models.assignment import Assignment
from app.models.component_definition import ComponentDefinition
from app.models.engagement import Engagement
from app.models.leave_plan import LeavePlan
from app.models.notification import Notification
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.leave.service import LeaveService
from app.security import hash_password, verify_password
from app.worker_documents_router import middle_ellipsis


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)
templates.env.filters["middle_ellipsis"] = middle_ellipsis
templates.env.filters["date_au"] = (
    lambda value: value.strftime("%d/%m/%Y") if value else "—"
)


def _portal_user(request: Request, db) -> User:
    user = db.get(User, request.session.get("user_id"))
    if user is None or user.role != "worker" or user.worker_id is None:
        raise HTTPException(403, "Worker portal access required")
    return user


@router.get("/portal/login", response_class=HTMLResponse)
def portal_login_page(request: Request):
    user_id = request.session.get("user_id")
    if user_id:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user and user.role == "worker":
                destination = (
                    "/portal/change-password"
                    if user.must_change_password else "/portal"
                )
                return RedirectResponse(destination, status_code=303)
            if user and user.role == "admin":
                return RedirectResponse("/dashboard", status_code=303)
    if not request.session.get("csrf_token"):
        request.session["csrf_token"] = secrets.token_urlsafe(32)
    return templates.TemplateResponse(
        request=request,
        name="portal_login.html",
        context={"error": None},
    )


@router.post("/portal/login")
def portal_login(request: Request, email: str = Form(...), password: str = Form(...)):
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(
                User.email == email.strip().lower(),
                User.is_active.is_(True),
                User.role == "worker",
            )
        )
        if not user or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                request=request,
                name="portal_login.html",
                context={"error": "Invalid email or password"},
                status_code=401,
            )
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        must_change = user.must_change_password
        request.session.clear()
        request.session["user_id"] = user.id
        request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse(
        "/portal/change-password" if must_change else "/portal",
        status_code=303,
    )


@router.post("/portal/logout")
def portal_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/portal/login", status_code=303)


@router.get("/portal/change-password", response_class=HTMLResponse)
def portal_change_password_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="portal_change_password.html",
        context={"error": None},
    )


@router.post("/portal/change-password")
def portal_change_password(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    error = None
    if len(new_password) < 12:
        error = "Password must be at least 12 characters"
    elif new_password != confirm_password:
        error = "Passwords do not match"
    if error:
        return templates.TemplateResponse(
            request=request,
            name="portal_change_password.html",
            context={"error": error},
            status_code=422,
        )
    with SessionLocal() as db:
        user = _portal_user(request, db)
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        db.commit()
    return RedirectResponse("/portal", status_code=303)


@router.get("/portal/documents", response_class=HTMLResponse)
def portal_documents_page(request: Request, error: str | None = None):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        worker = db.get(Worker, user.worker_id)
        documents = DocumentService.list_for_worker(db, user.worker_id)
    return templates.TemplateResponse(
        request=request,
        name="portal_documents.html",
        context={
            "worker": worker,
            "documents": documents,
            "document_types": DOCUMENT_TYPES,
            "error": error,
        },
    )


@router.post("/portal/documents")
async def portal_upload_document(
    request: Request,
    document_type: str = Form(...),
    issued_on: date | None = Form(None),
    expires_on: date | None = Form(None),
    document: UploadFile = File(...),
):
    content = await document.read(MAX_DOCUMENT_BYTES + 1)
    try:
        with SessionLocal() as db:
            user = _portal_user(request, db)
            DocumentService.create(
                db,
                get_document_storage(),
                worker_id=user.worker_id,
                user_id=user.id,
                document_type=document_type,
                filename=document.filename,
                content_type=document.content_type,
                content=content,
                issued_on=issued_on,
                expires_on=expires_on,
            )
    except DocumentValidationError as exc:
        return RedirectResponse(
            f"/portal/documents?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse("/portal/documents", status_code=303)


@router.get("/portal/documents/{document_id}/download")
def portal_download_document(request: Request, document_id: int):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        document = db.get(WorkerDocument, document_id)
        if document is None or document.worker_id != user.worker_id:
            raise HTTPException(404, "Document not found")
        content = get_document_storage().get(document.storage_key)
    filename = quote(document.original_filename)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


@router.post("/portal/documents/{document_id}/delete")
def portal_delete_document(request: Request, document_id: int):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        document = db.get(WorkerDocument, document_id)
        if document is None or document.worker_id != user.worker_id:
            raise HTTPException(404, "Document not found")
        if document.status not in {"uploaded", "failed", "rejected"}:
            raise HTTPException(409, "This document can no longer be deleted by the worker")
        get_document_storage().delete(document.storage_key)
        db.delete(document)
        db.commit()
    return RedirectResponse("/portal/documents", status_code=303)


def _worker_engagement_ids(db, worker_id: int):
    return select(Engagement.id).where(Engagement.worker_id == worker_id)


@router.get("/portal", response_class=HTMLResponse)
def portal_dashboard(request: Request):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        worker = db.get(Worker, user.worker_id)
        engagement_ids = _worker_engagement_ids(db, user.worker_id)
        latest_payslip = db.scalar(
            select(Payslip)
            .where(Payslip.engagement_id.in_(engagement_ids))
            .join(PayRun, PayRun.id == Payslip.pay_run_id)
            .order_by(PayRun.payment_date.desc(), Payslip.id.desc())
            .limit(1)
        )
        recent_timesheets = db.scalars(
            select(TimesheetHeader)
            .where(TimesheetHeader.engagement_id.in_(engagement_ids))
            .order_by(TimesheetHeader.period_end.desc())
            .limit(5)
        ).all()
        leave_rows = db.execute(
            select(LeavePlan, ComponentDefinition)
            .join(ComponentDefinition, ComponentDefinition.id == LeavePlan.component_definition_id)
            .where(LeavePlan.worker_id == user.worker_id, LeavePlan.status == "active")
            .order_by(ComponentDefinition.name)
        ).all()
        leave_balances = [
            {"name": definition.name, "hours": LeaveService.balance(db, plan.id)}
            for plan, definition in leave_rows
        ]
        unread_count = db.scalar(
            select(func.count(Notification.id)).where(
                Notification.recipient_user_id == user.id,
                Notification.read_at.is_(None),
            )
        ) or 0
        action_documents = db.scalars(
            select(WorkerDocument).where(
                WorkerDocument.worker_id == user.worker_id,
                or_(
                    WorkerDocument.status.in_(["failed", "rejected"]),
                    WorkerDocument.expires_on <= date.today() + timedelta(days=30),
                ),
            ).order_by(WorkerDocument.expires_on)
        ).all()
    return templates.TemplateResponse(
        request=request,
        name="portal_dashboard.html",
        context={
            "worker": worker,
            "latest_payslip": latest_payslip,
            "recent_timesheets": recent_timesheets,
            "leave_balances": leave_balances,
            "unread_count": unread_count,
            "action_documents": action_documents,
        },
    )


@router.get("/portal/payslips", response_class=HTMLResponse)
def portal_payslips(request: Request, year: int | None = None):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        query = (
            select(Payslip, PayRun, Organisation)
            .join(PayRun, PayRun.id == Payslip.pay_run_id)
            .join(Organisation, Organisation.id == PayRun.organisation_id)
            .where(Payslip.engagement_id.in_(_worker_engagement_ids(db, user.worker_id)))
        )
        if year:
            query = query.where(func.extract("year", PayRun.payment_date) == year)
        rows = db.execute(query.order_by(PayRun.payment_date.desc())).all()
        years = sorted({row.PayRun.payment_date.year for row in rows}, reverse=True)
        totals = {
            "gross": sum((row.Payslip.gross_pay for row in rows), Decimal("0")),
            "payg": sum((row.Payslip.payg_withholding for row in rows), Decimal("0")),
            "net": sum((row.Payslip.net_pay for row in rows), Decimal("0")),
            "super": sum((row.Payslip.superannuation for row in rows), Decimal("0")),
        }
    return templates.TemplateResponse(request=request, name="portal_payslips.html", context={
        "rows": rows, "years": years, "selected_year": year, "totals": totals,
    })


@router.get("/portal/timesheets", response_class=HTMLResponse)
def portal_timesheets(request: Request, created: bool = False):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        headers = db.scalars(
            select(TimesheetHeader)
            .where(TimesheetHeader.engagement_id.in_(_worker_engagement_ids(db, user.worker_id)))
            .order_by(TimesheetHeader.period_end.desc())
        ).all()
        totals = dict(db.execute(
            select(Timesheet.timesheet_header_id, func.sum(Timesheet.hours_worked))
            .where(Timesheet.timesheet_header_id.in_([item.id for item in headers] or [-1]))
            .group_by(Timesheet.timesheet_header_id)
        ).all())
        engagements = db.scalars(
            select(Engagement).where(
                Engagement.worker_id == user.worker_id,
                Engagement.status == "active",
            ).order_by(Engagement.start_date.desc())
        ).all()
        assignments = db.execute(
            select(Assignment, Organisation)
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Organisation, Organisation.id == Assignment.customer_id)
            .where(Engagement.worker_id == user.worker_id)
            .order_by(Organisation.name)
        ).all()
    return templates.TemplateResponse(request=request, name="portal_timesheets.html", context={
        "headers": headers, "totals": totals, "engagements": engagements,
        "assignments": assignments, "created": created,
    })


@router.post("/portal/timesheets")
def portal_create_timesheet(
    request: Request,
    engagement_id: int = Form(...),
    assignment_id: int = Form(...),
    week_start: date = Form(...),
    hours: list[Decimal] = Form(...),
):
    if week_start.weekday() != 0:
        raise HTTPException(422, "The timesheet week must start on a Monday")
    if len(hours) != 7 or any(value < 0 or value > 24 for value in hours):
        raise HTTPException(422, "Enter seven daily hour values between 0 and 24")
    with SessionLocal() as db:
        user = _portal_user(request, db)
        engagement = db.get(Engagement, engagement_id)
        assignment = db.get(Assignment, assignment_id)
        if engagement is None or engagement.worker_id != user.worker_id:
            raise HTTPException(404, "Engagement not found")
        if assignment is None or assignment.engagement_id != engagement.id:
            raise HTTPException(422, "Assignment does not belong to this engagement")
        existing = db.scalar(select(TimesheetHeader).where(
            TimesheetHeader.engagement_id == engagement.id,
            TimesheetHeader.period_type == "weekly",
            TimesheetHeader.period_start == week_start,
        ))
        if existing is not None:
            raise HTTPException(409, "A timesheet already exists for this week")
        ordinary = db.scalar(select(ComponentDefinition).where(ComponentDefinition.code == "ORDINARY_HOURS"))
        header = TimesheetHeader(
            engagement_id=engagement.id,
            assignment_id=assignment.id,
            period_type="weekly",
            period_start=week_start,
            period_end=week_start + timedelta(days=6),
            status="draft",
            source="worker",
        )
        db.add(header)
        db.flush()
        for offset, value in enumerate(hours):
            db.add(Timesheet(
                engagement_id=engagement.id,
                assignment_id=assignment.id,
                component_definition_id=ordinary.id if ordinary else None,
                timesheet_header_id=header.id,
                work_date=week_start + timedelta(days=offset),
                hours_worked=value,
                status="draft",
            ))
        admins = db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all()
        worker = db.get(Worker, user.worker_id)
        for admin in admins:
            db.add(Notification(
                recipient_user_id=admin.id,
                notification_type="worker_timesheet_submitted",
                title=f"Timesheet entered by {worker.first_name} {worker.last_name}",
                message=f"Week commencing {week_start:%d/%m/%Y} · {sum(hours):,.2f} hours · ready for review.",
                action_url=f"/ui/timesheets/weekly/{header.id}/preview",
            ))
        db.commit()
    return RedirectResponse("/portal/timesheets?created=true", status_code=303)


@router.get("/portal/leave", response_class=HTMLResponse)
def portal_leave(request: Request, sent: bool = False):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        rows = db.execute(
            select(LeavePlan, ComponentDefinition)
            .join(ComponentDefinition, ComponentDefinition.id == LeavePlan.component_definition_id)
            .where(LeavePlan.worker_id == user.worker_id, LeavePlan.status == "active")
            .order_by(ComponentDefinition.name)
        ).all()
        plans = [{"plan": plan, "name": definition.name, "balance": LeaveService.balance(db, plan.id)} for plan, definition in rows]
    return templates.TemplateResponse(request=request, name="portal_leave.html", context={"plans": plans, "sent": sent})


@router.post("/portal/leave/request")
def portal_leave_request(request: Request, leave_plan_id: int = Form(...), start_date: date = Form(...), end_date: date = Form(...), hours: Decimal = Form(...), notes: str = Form("")):
    if end_date < start_date or hours <= 0:
        raise HTTPException(422, "Enter valid leave dates and hours")
    with SessionLocal() as db:
        user = _portal_user(request, db)
        plan = db.get(LeavePlan, leave_plan_id)
        if plan is None or plan.worker_id != user.worker_id:
            raise HTTPException(404, "Leave plan not found")
        worker = db.get(Worker, user.worker_id)
        admins = db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all()
        for admin in admins:
            db.add(Notification(recipient_user_id=admin.id, notification_type="worker_leave_request", title=f"Leave request from {worker.first_name} {worker.last_name}", message=f"{start_date:%d/%m/%Y} to {end_date:%d/%m/%Y} · {hours:,.2f} hours" + (f" · {notes.strip()}" if notes.strip() else ""), action_url=f"/ui/workers/{worker.id}/leave"))
        db.add(Notification(recipient_user_id=user.id, notification_type="leave_request_submitted", title="Leave request submitted", message=f"Your request for {hours:,.2f} hours has been sent to payroll.", action_url="/portal/leave"))
        db.commit()
    return RedirectResponse("/portal/leave?sent=true", status_code=303)


@router.get("/portal/assignments", response_class=HTMLResponse)
def portal_assignments(request: Request):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        rows = db.execute(
            select(Assignment, Engagement, Organisation)
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Organisation, Organisation.id == Assignment.customer_id)
            .where(Engagement.worker_id == user.worker_id)
            .order_by(Assignment.start_date.desc())
        ).all()
    return templates.TemplateResponse(request=request, name="portal_assignments.html", context={"rows": rows})


@router.get("/portal/profile", response_class=HTMLResponse)
def portal_profile(request: Request, saved: bool = False):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        worker = db.get(Worker, user.worker_id)
    return templates.TemplateResponse(request=request, name="portal_profile.html", context={"worker": worker, "saved": saved})


@router.post("/portal/profile")
def portal_update_profile(request: Request, phone: str = Form("")):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        worker = db.get(Worker, user.worker_id)
        worker.phone = phone.strip() or None
        db.commit()
    return RedirectResponse("/portal/profile?saved=true", status_code=303)


@router.get("/portal/notifications", response_class=HTMLResponse)
def portal_notifications(request: Request):
    with SessionLocal() as db:
        user = _portal_user(request, db)
        notifications = db.scalars(select(Notification).where(Notification.recipient_user_id == user.id).order_by(Notification.created_at.desc()).limit(100)).all()
        for item in notifications:
            if item.read_at is None:
                item.read_at = datetime.now(timezone.utc)
        db.commit()
    return templates.TemplateResponse(request=request, name="portal_notifications.html", context={"notifications": notifications})


@router.get("/portal/help", response_class=HTMLResponse)
def portal_help(request: Request, sent: bool = False):
    return templates.TemplateResponse(request=request, name="portal_help.html", context={"sent": sent})


@router.post("/portal/help")
def portal_help_request(request: Request, category: str = Form(...), message: str = Form(...)):
    if not message.strip():
        raise HTTPException(422, "Enter a message")
    with SessionLocal() as db:
        user = _portal_user(request, db)
        worker = db.get(Worker, user.worker_id)
        admins = db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all()
        for admin in admins:
            db.add(Notification(recipient_user_id=admin.id, notification_type="worker_support_request", title=f"{category.title()} enquiry from {worker.first_name} {worker.last_name}", message=message.strip()[:2000], action_url=f"/ui/workers/{worker.id}"))
        db.add(Notification(recipient_user_id=user.id, notification_type="support_request_submitted", title="Enquiry submitted", message=f"Your {category} enquiry has been sent to payroll.", action_url="/portal/help"))
        db.commit()
    return RedirectResponse("/portal/help?sent=true", status_code=303)


@router.get("/ui/workers/{worker_id}/portal-access", response_class=HTMLResponse)
def worker_portal_access_page(request: Request, worker_id: int):
    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)
        if worker is None:
            raise HTTPException(404, "Worker not found")
        account = db.scalar(select(User).where(User.worker_id == worker_id))
    return templates.TemplateResponse(
        request=request,
        name="worker_portal_access.html",
        context={"worker": worker, "account": account, "temporary_password": None},
    )


@router.post("/ui/workers/{worker_id}/portal-access", response_class=HTMLResponse)
def enable_worker_portal_access(request: Request, worker_id: int):
    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)
        if worker is None:
            raise HTTPException(404, "Worker not found")
        portal_email = worker.email.strip().lower()
        account = db.scalar(select(User).where(User.worker_id == worker_id))
        email_owner = db.scalar(select(User).where(User.email == portal_email))
        if email_owner is not None and email_owner is not account:
            raise HTTPException(409, "The worker email is already used by another account")
        temporary_password = f"GO-{secrets.token_urlsafe(9)}"
        if account is None:
            account = User(
                email=portal_email,
                password_hash=hash_password(temporary_password),
                is_active=True,
                role="worker",
                worker_id=worker.id,
                must_change_password=True,
            )
            db.add(account)
        else:
            account.email = portal_email
            account.password_hash = hash_password(temporary_password)
            account.is_active = True
            account.role = "worker"
            account.must_change_password = True
        db.commit()
        # commit() expires ORM attributes. Refresh both objects because the
        # response template is rendered after this session has closed.
        db.refresh(worker)
        db.refresh(account)
    return templates.TemplateResponse(
        request=request,
        name="worker_portal_access.html",
        context={
            "worker": worker,
            "account": account,
            "temporary_password": temporary_password,
        },
    )
