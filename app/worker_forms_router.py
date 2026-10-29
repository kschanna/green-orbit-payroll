from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.document_profile_service import apply_document_values
from app.models.notification import Notification
from app.models.user import User
from app.models.worker import Worker
from app.models.worker_form_submission import WorkerFormSubmission
from app.employee_tfn_router import require_tfn_admin
from app.worker_form_service import (
    FORM_SCHEMAS, approval_values, declaration_hash, decrypt_payload,
    encrypt_payload, validate_submission,
)
from app.worker_portal_router import mark_tfn_declaration_received


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = lambda request: request.session.get("csrf_token", "")


def _worker_user(request: Request, db) -> User:
    user = db.get(User, request.session.get("user_id"))
    if user is None or user.role != "worker" or user.worker_id is None:
        raise HTTPException(403, "Worker portal access required")
    return user


@router.get("/portal/payroll-setup/{form_type}", response_class=HTMLResponse)
def worker_form_page(request: Request, form_type: str, error: str | None = None):
    schema = FORM_SCHEMAS.get(form_type)
    if schema is None:
        raise HTTPException(404, "Payroll form not found")
    with SessionLocal() as db:
        user = _worker_user(request, db)
        worker = db.get(Worker, user.worker_id)
        existing = db.scalar(select(WorkerFormSubmission).where(
            WorkerFormSubmission.worker_id == user.worker_id,
            WorkerFormSubmission.form_type == form_type,
            WorkerFormSubmission.status == "submitted",
        ).order_by(WorkerFormSubmission.id.desc()).limit(1))
    return templates.TemplateResponse(request=request, name="portal_worker_form.html", context={
        "schema": schema, "form_type": form_type, "worker": worker,
        "existing": existing, "error": error,
    })


@router.post("/portal/payroll-setup/{form_type}")
async def submit_worker_form(request: Request, form_type: str):
    schema = FORM_SCHEMAS.get(form_type)
    if schema is None:
        raise HTTPException(404, "Payroll form not found")
    form = await request.form()
    values = validate_submission(form_type, {
        key: value for key, value in form.items() if key != "csrf_token"
    })
    try:
        encrypted = encrypt_payload(values)
    except RuntimeError as exc:
        raise HTTPException(503, "Secure form encryption is not configured") from exc

    with SessionLocal() as db:
        user = _worker_user(request, db)
        worker = db.get(Worker, user.worker_id)
        existing = db.scalar(select(WorkerFormSubmission.id).where(
            WorkerFormSubmission.worker_id == user.worker_id,
            WorkerFormSubmission.form_type == form_type,
            WorkerFormSubmission.status == "submitted",
        ).limit(1))
        if existing is not None:
            raise HTTPException(409, "This form is already awaiting review")
        metadata = {
            "signature_name": values["signature_name"],
            "last_three": values["tfn"][-3:] if form_type == "tfn_declaration" else None,
            "fund_type": values.get("fund_type"),
        }
        submission = WorkerFormSubmission(
            worker_id=user.worker_id, submitted_by_user_id=user.id,
            form_type=form_type, schema_version=schema["version"], status="submitted",
            submission_metadata=metadata, encrypted_payload=encrypted,
            declaration_hash=declaration_hash(form_type, schema["version"], values),
        )
        db.add(submission)
        if form_type == "tfn_declaration":
            mark_tfn_declaration_received(db, user.worker_id)
        db.flush()
        label = schema["title"]
        admins = db.scalars(select(User).where(User.role == "admin", User.is_active.is_(True))).all()
        for admin in admins:
            db.add(Notification(
                recipient_user_id=admin.id,
                notification_type="document_ready_for_review",
                title=f"{worker.first_name} {worker.last_name} submitted {label}",
                message=f"{worker.first_name} {worker.last_name}'s secure {label} is ready for review and validation.",
                action_url=f"/ui/worker-forms/{submission.id}/review",
            ))
        db.commit()
    return RedirectResponse("/portal?form_submitted=1#payroll-setup", status_code=303)


@router.get("/ui/worker-forms/{submission_id}/review", response_class=HTMLResponse)
def review_worker_form_page(request: Request, submission_id: int):
    require_tfn_admin(request)
    with SessionLocal() as db:
        submission = db.get(WorkerFormSubmission, submission_id)
        if submission is None:
            raise HTTPException(404, "Form submission not found")
        worker = db.get(Worker, submission.worker_id)
        try:
            values = decrypt_payload(submission.encrypted_payload)
        except Exception as exc:
            raise HTTPException(503, "Secure form data could not be decrypted") from exc
        data = {
            "id": submission.id, "form_type": submission.form_type,
            "schema_version": submission.schema_version, "status": submission.status,
            "submitted_at": submission.submitted_at,
            "review_notes": submission.review_notes,
        }
    return templates.TemplateResponse(request=request, name="worker_form_review.html", context={
        "submission": data, "worker": worker, "values": values,
        "schema": FORM_SCHEMAS[submission.form_type],
    })


@router.post("/ui/worker-forms/{submission_id}/review")
def decide_worker_form(
    request: Request, submission_id: int, decision: str = Form(...), notes: str = Form(""),
):
    actor_id = require_tfn_admin(request)
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "Decision must be approved or rejected")
    if decision == "rejected" and not notes.strip():
        raise HTTPException(422, "A rejection reason is required")
    with SessionLocal() as db:
        user = db.get(User, actor_id)
        if user is None or user.role != "admin":
            raise HTTPException(403, "Administrator access required")
        submission = db.get(WorkerFormSubmission, submission_id)
        if submission is None:
            raise HTTPException(404, "Form submission not found")
        if submission.status != "submitted":
            raise HTTPException(409, "This form has already been reviewed")
        values = decrypt_payload(submission.encrypted_payload)
        if decision == "approved":
            apply_document_values(
                db, document_type=submission.form_type, worker_id=submission.worker_id,
                actor_user_id=user.id, values=approval_values(submission.form_type, values),
            )
        submission.status = decision
        submission.reviewed_by_user_id = user.id
        submission.reviewed_at = datetime.now(timezone.utc)
        submission.review_notes = notes.strip() or None
        worker_user = db.scalar(select(User).where(User.worker_id == submission.worker_id, User.role == "worker"))
        if worker_user is not None:
            db.add(Notification(
                recipient_user_id=worker_user.id,
                notification_type=f"worker_form_{decision}",
                title=f"{FORM_SCHEMAS[submission.form_type]['title']} {decision}",
                message=("Your payroll form has been approved." if decision == "approved" else f"Your payroll form needs changes: {notes.strip()}"),
                action_url="/portal#payroll-setup",
            ))
        db.commit()
    return RedirectResponse(f"/ui/worker-forms/{submission_id}/review", status_code=303)
