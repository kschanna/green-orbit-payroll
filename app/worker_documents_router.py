from datetime import date, datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.database import SessionLocal
from app.document_service import (
    DOCUMENT_TYPES,
    MAX_DOCUMENT_BYTES,
    DocumentService,
    DocumentValidationError,
)
from app.document_profile_service import (
    apply_document_values,
    redact_sensitive_values,
    review_values,
)
from app.document_storage import get_document_storage
from app.models.worker import Worker
from app.models.worker_document import WorkerDocument
from app.models.document_extraction import DocumentExtraction
from app.models.document_review import DocumentReview
from app.models.notification import Notification
from app.models.user import User
from app.models.engagement import Engagement
from app.timesheet_agent_service import process_timesheet_created
from sqlalchemy import delete, func, or_, select, update


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)


def middle_ellipsis(value: str, max_length: int = 30) -> str:
    if len(value) <= max_length:
        return value
    marker = "..."
    available = max_length - len(marker)
    start_length = (available + 1) // 2
    end_length = available - start_length
    return f"{value[:start_length]}{marker}{value[-end_length:]}"


templates.env.filters["middle_ellipsis"] = middle_ellipsis


@router.get("/ui/workers/{worker_id}/documents", response_class=HTMLResponse)
def worker_documents_page(request: Request, worker_id: int, error: str | None = None):
    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)
        if worker is None:
            raise HTTPException(404, "Worker not found")
        documents = DocumentService.list_for_worker(db, worker_id)

    return templates.TemplateResponse(
        request=request,
        name="worker_documents.html",
        context={
            "worker": worker,
            "documents": documents,
            "document_types": DOCUMENT_TYPES,
            "error": error,
        },
    )


@router.post("/ui/workers/{worker_id}/documents")
async def upload_worker_document(
    request: Request,
    worker_id: int,
    document_type: str = Form(...),
    issued_on: date | None = Form(None),
    expires_on: date | None = Form(None),
    document: UploadFile = File(...),
):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Authentication required")

    content = await document.read(MAX_DOCUMENT_BYTES + 1)
    try:
        with SessionLocal() as db:
            if db.get(Worker, worker_id) is None:
                raise HTTPException(404, "Worker not found")
            DocumentService.create(
                db,
                get_document_storage(),
                worker_id=worker_id,
                user_id=user_id,
                document_type=document_type,
                filename=document.filename,
                content_type=document.content_type,
                content=content,
                issued_on=issued_on,
                expires_on=expires_on,
            )
    except DocumentValidationError as exc:
        return RedirectResponse(
            f"/ui/workers/{worker_id}/documents?error={quote(str(exc))}",
            status_code=303,
        )

    return RedirectResponse(f"/ui/workers/{worker_id}/documents", status_code=303)


@router.get("/ui/workers/{worker_id}/documents/{document_id}/download")
def download_worker_document(worker_id: int, document_id: int):
    with SessionLocal() as db:
        document = db.get(WorkerDocument, document_id)
        if document is None or document.worker_id != worker_id:
            raise HTTPException(404, "Document not found")
        try:
            content = get_document_storage().get(document.storage_key)
        except FileNotFoundError as exc:
            raise HTTPException(404, "Document file not found") from exc

    filename = quote(document.original_filename)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


@router.post("/ui/workers/{worker_id}/documents/{document_id}/delete")
def delete_worker_document(worker_id: int, document_id: int):
    with SessionLocal() as db:
        document = db.get(WorkerDocument, document_id)
        if document is None or document.worker_id != worker_id:
            raise HTTPException(404, "Document not found")

        try:
            get_document_storage().delete(document.storage_key)
        except Exception as exc:
            return RedirectResponse(
                f"/ui/workers/{worker_id}/documents?error="
                f"{quote('The document file could not be deleted. Please try again.')}",
                status_code=303,
            )

        review_url = f"/ui/workers/{worker_id}/documents/{document_id}/review"
        db.execute(delete(Notification).where(Notification.action_url == review_url))
        db.delete(document)
        db.commit()

    return RedirectResponse(f"/ui/workers/{worker_id}/documents", status_code=303)


@router.get(
    "/ui/workers/{worker_id}/documents/{document_id}/review",
    response_class=HTMLResponse,
)
def review_worker_document_page(request: Request, worker_id: int, document_id: int):
    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)
        document = db.get(WorkerDocument, document_id)
        if worker is None or document is None or document.worker_id != worker_id:
            raise HTTPException(404, "Document not found")
        extraction = db.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.document_id == document_id
            )
        )
        review = db.scalar(
            select(DocumentReview).where(DocumentReview.document_id == document_id)
        )
        values = review_values(document.document_type, (
            review.corrected_values
            if review and review.corrected_values
            else extraction.proposed_values if extraction else {}
        ))

    return templates.TemplateResponse(
        request=request,
        name="worker_document_review.html",
        context={
            "worker": worker,
            "document": document,
            "extraction": extraction,
            "review": review,
            "values": values,
            "document_type_label": DOCUMENT_TYPES.get(
                document.document_type, document.document_type.replace("_", " ").title()
            ),
        },
    )


@router.post("/ui/workers/{worker_id}/documents/{document_id}/review")
def decide_worker_document(
    request: Request,
    worker_id: int,
    document_id: int,
    decision: str = Form(...),
    field_name: list[str] = Form(default=[]),
    field_value: list[str] = Form(default=[]),
    notes: str | None = Form(None),
):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    if decision not in {"approved", "rejected"}:
        raise HTTPException(422, "Decision must be approved or rejected")
    if decision == "rejected" and not (notes or "").strip():
        raise HTTPException(422, "A rejection reason is required")
    if len(field_name) != len(field_value):
        raise HTTPException(422, "Extracted field data is invalid")
    corrected_values = {
        name.strip(): value.strip()
        for name, value in zip(field_name, field_value)
        if name.strip()
    }

    with SessionLocal() as db:
        document = db.get(WorkerDocument, document_id)
        if document is None or document.worker_id != worker_id:
            raise HTTPException(404, "Document not found")
        if document.status != "ready_for_review":
            raise HTTPException(409, "This document has already been reviewed")
        sync_message = None
        if decision == "approved":
            sync_message = apply_document_values(
                db,
                document_type=document.document_type,
                worker_id=worker_id,
                actor_user_id=user_id,
                values=corrected_values,
            )
            corrected_values = redact_sensitive_values(
                document.document_type, corrected_values
            )
        review = db.scalar(
            select(DocumentReview).where(DocumentReview.document_id == document_id)
        )
        if review is None:
            review = DocumentReview(document_id=document_id)
            db.add(review)
        review.reviewer_user_id = user_id
        review.decision = decision
        review.corrected_values = corrected_values
        review.notes = (notes or "").strip() or None
        review.reviewed_at = datetime.now(timezone.utc)
        document.status = decision
        if decision == "approved" and document.document_type == "tfn_declaration":
            engagement_ids = db.scalars(select(Engagement.id).where(
                Engagement.worker_id == worker_id,
                Engagement.status == "active",
                Engagement.engagement_type.in_(("employee", "payg_employee")),
            )).all()
            for engagement_id in engagement_ids:
                process_timesheet_created(
                    db,
                    engagement_id=engagement_id,
                    as_of=date.today(),
                    event_type="tfn_document_approved",
                    request_popup=False,
                )
        review_url = f"/ui/workers/{worker_id}/documents/{document_id}/review"
        db.execute(delete(Notification).where(Notification.action_url == review_url))
        db.commit()

    return RedirectResponse(
        f"/ui/workers/{worker_id}/documents/{document_id}/review"
        + ("?synced=1" if sync_message else ""),
        status_code=303,
    )


def _visible_notifications(user_id: int):
    return or_(
        Notification.recipient_user_id.is_(None),
        Notification.recipient_user_id == user_id,
    )


@router.get("/api/agent-alerts/document-review")
def next_document_review_alert(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or user.role != "admin":
            raise HTTPException(403, "Administrator access required")
        notification = db.scalar(
            select(Notification).where(
                Notification.recipient_user_id == user.id,
                Notification.notification_type == "document_ready_for_review",
                Notification.read_at.is_(None),
            ).order_by(Notification.id).limit(1)
        )
        if notification is None:
            return JSONResponse({"alert": None})
        notification.read_at = datetime.now(timezone.utc)
        alert = {
            "code": "document_ready_for_review",
            "content": notification.message,
            "action": {
                "label": "Review document",
                "url": notification.action_url,
            },
        }
        db.commit()
    return JSONResponse({"alert": alert})


@router.get("/ui/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, view: str = "unread"):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    view = "all" if view == "all" else "unread"
    with SessionLocal() as db:
        visibility = _visible_notifications(user_id)
        query = select(Notification).where(visibility)
        if view == "unread":
            query = query.where(Notification.read_at.is_(None))
        notifications = db.scalars(
            query
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(100)
        ).all()
        unread_count = db.scalar(
            select(func.count(Notification.id)).where(
                visibility, Notification.read_at.is_(None)
            )
        ) or 0
    return templates.TemplateResponse(
        request=request,
        name="notifications.html",
        context={
            "notifications": notifications,
            "notification_view": view,
            "unread_count": unread_count,
        },
    )


@router.get("/ui/notifications/{notification_id}/open")
def open_notification(request: Request, notification_id: int):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    with SessionLocal() as db:
        notification = db.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                _visible_notifications(user_id),
            )
        )
        if notification is None:
            raise HTTPException(404, "Notification not found")
        if notification.read_at is None:
            notification.read_at = datetime.now(timezone.utc)
            db.commit()
        target = notification.action_url

    if not target or not target.startswith("/") or target.startswith("//"):
        target = "/ui/notifications?view=all"
    return RedirectResponse(target, status_code=303)


@router.post("/ui/notifications/read-all")
def mark_all_notifications_read(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Authentication required")
    with SessionLocal() as db:
        db.execute(
            update(Notification)
            .where(_visible_notifications(user_id), Notification.read_at.is_(None))
            .values(read_at=datetime.now(timezone.utc))
        )
        db.commit()
    return RedirectResponse("/ui/notifications?view=all", status_code=303)
