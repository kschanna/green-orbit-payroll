import re
from datetime import date
from decimal import Decimal
from io import BytesIO

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.database import SessionLocal
from app.employee_tfn_router import require_csrf
from app.models.aba_profile import ABAProfile
from app.models.aba_file import ABAFile
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.models.payment_batch import PaymentBatch
from app.models.payment_instruction import PaymentInstruction
from app.models.worker import Worker
from app.payments.service import PaymentBatchService
from app.ai.error_explainer import explain_payment_error
from app.pagination import build_pagination

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["date_au"] = (
    lambda value: value.strftime("%d/%m/%Y") if value else "—"
)
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)


@router.get("/ui/organisations/{organisation_id}/aba", response_class=HTMLResponse)
def aba_profile_page(request: Request, organisation_id: int):
    with SessionLocal() as db:
        organisation = db.get(Organisation, organisation_id)
        if organisation is None:
            raise HTTPException(404, "Organisation not found")
        profile = db.scalar(select(ABAProfile).where(
            ABAProfile.organisation_id == organisation_id
        ))
        data = None if profile is None else {
            "financial_institution": profile.financial_institution,
            "user_name": profile.user_name,
            "apca_user_id": profile.apca_user_id,
            "file_description": profile.file_description,
            "source_bsb": profile.source_bsb,
            "source_account_number": profile.source_account_number,
            "source_account_name": profile.source_account_name,
            "remitter_name": profile.remitter_name,
            "transaction_code": profile.transaction_code,
            "balancing_entry_required": profile.balancing_entry_required,
        }
    return templates.TemplateResponse(
        request=request, name="aba_profile.html",
        context={"organisation": organisation, "profile": data},
    )


@router.post("/ui/organisations/{organisation_id}/aba")
def save_aba_profile(
    request: Request, organisation_id: int,
    financial_institution: str = Form(...), user_name: str = Form(...),
    apca_user_id: str = Form(...), file_description: str = Form(...),
    source_bsb: str = Form(...), source_account_number: str = Form(...),
    source_account_name: str = Form(...), remitter_name: str = Form(...),
    transaction_code: str = Form("53"),
    balancing_entry_required: bool = Form(False),
    csrf_token: str = Form(...),
):
    require_csrf(request, csrf_token)
    financial_institution = financial_institution.strip().upper()
    apca_user_id = re.sub(r"\s", "", apca_user_id)
    source_bsb = re.sub(r"[-\s]", "", source_bsb)
    source_account_number = re.sub(r"\s", "", source_account_number)
    if not re.fullmatch(r"[A-Z0-9]{3}", financial_institution):
        raise HTTPException(422, "Financial institution code must be 3 characters")
    if not re.fullmatch(r"\d{6}", apca_user_id):
        raise HTTPException(422, "APCA user ID must contain 6 digits")
    if not re.fullmatch(r"\d{6}", source_bsb):
        raise HTTPException(422, "Source BSB must contain 6 digits")
    if not re.fullmatch(r"\d{4,9}", source_account_number):
        raise HTTPException(422, "Source account number must contain 4–9 digits")
    if not re.fullmatch(r"\d{2}", transaction_code):
        raise HTTPException(422, "Transaction code must contain 2 digits")
    required = (user_name, file_description, source_account_name, remitter_name)
    if any(not value.strip() for value in required):
        raise HTTPException(422, "All ABA text fields are required")

    with SessionLocal() as db:
        if db.get(Organisation, organisation_id) is None:
            raise HTTPException(404, "Organisation not found")
        profile = db.scalar(select(ABAProfile).where(
            ABAProfile.organisation_id == organisation_id
        ))
        if profile is None:
            profile = ABAProfile(organisation_id=organisation_id)
            db.add(profile)
        profile.financial_institution = financial_institution
        profile.user_name = user_name.strip()[:26]
        profile.apca_user_id = apca_user_id
        profile.file_description = file_description.strip()[:12]
        profile.source_bsb = source_bsb
        profile.source_account_number = source_account_number
        profile.source_account_name = source_account_name.strip()[:32]
        profile.remitter_name = remitter_name.strip()[:16]
        profile.transaction_code = transaction_code
        profile.balancing_entry_required = balancing_entry_required
        profile.active = True
        db.commit()
    return RedirectResponse(
        f"/ui/organisations/{organisation_id}/aba", status_code=303
    )


@router.post("/ui/pay-runs/{pay_run_id}/payments/prepare")
def prepare_payments(request: Request, pay_run_id: int, csrf_token: str = Form(...)):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        try:
            batch = PaymentBatchService.prepare_from_pay_run(db, pay_run_id)
            db.commit()
            batch_id = batch.id
        except ValueError as error:
            db.rollback()
            pay_run = db.get(PayRun, pay_run_id)
            detail = explain_payment_error(
                error=str(error),
                pay_run_id=pay_run_id,
                payment_date=pay_run.payment_date if pay_run else None,
            )
            raise HTTPException(409, detail) from error
    return RedirectResponse(f"/ui/payment-batches/{batch_id}", status_code=303)


@router.get("/ui/payment-batches/{batch_id}", response_class=HTMLResponse)
def payment_batch_page(request: Request, batch_id: int):
    with SessionLocal() as db:
        batch = db.get(PaymentBatch, batch_id)
        if batch is None:
            raise HTTPException(404, "Payment batch not found")
        organisation = db.get(Organisation, batch.organisation_id)
        lines = db.scalars(select(PaymentInstruction).where(
            PaymentInstruction.payment_batch_id == batch.id
        ).order_by(PaymentInstruction.id)).all()
        workers = {
            worker.id: worker for worker in db.scalars(select(Worker).where(
                Worker.id.in_([line.worker_id for line in lines if line.worker_id])
            )).all()
        }
        line_data = [{
            "id": line.id, "payslip_id": line.payslip_id,
            "worker_name": (
                f"{workers[line.worker_id].first_name} {workers[line.worker_id].last_name}"
                if line.worker_id in workers else "Manual payment"
            ),
            "source_type": line.source_type,
            "amount": line.amount,
            "account_name": line.recipient_account_name,
            "bsb": f"{line.recipient_bsb[:3]}-{line.recipient_bsb[3:]}",
            "account_number": "****" + line.recipient_account_number[-4:],
            "reference": line.lodgement_reference,
            "reason": line.manual_entry_reason,
        } for line in lines]
        context = {
            "batch": batch, "organisation": organisation,
            "lines": line_data, "editable": batch.status == "draft",
        }
    return templates.TemplateResponse(
        request=request, name="payment_batch.html", context=context
    )


@router.post("/ui/payment-batches/{batch_id}/manual-lines")
def add_manual_payment_line(
    request: Request, batch_id: int,
    account_name: str = Form(...), bsb: str = Form(...),
    account_number: str = Form(...), amount: Decimal = Form(...),
    lodgement_reference: str = Form(...), reason: str = Form(...),
    csrf_token: str = Form(...),
):
    require_csrf(request, csrf_token)
    bsb = re.sub(r"[-\s]", "", bsb)
    account_number = re.sub(r"\s", "", account_number)
    with SessionLocal() as db:
        batch = db.get(PaymentBatch, batch_id)
        if batch is None:
            raise HTTPException(404, "Payment batch not found")
        if batch.status != "draft":
            raise HTTPException(409, "Exported payment batches cannot be edited")
        profile = db.get(ABAProfile, batch.aba_profile_id)
        line = PaymentInstruction(
            payment_batch_id=batch.id, payslip_id=None, worker_id=None,
            source_type="manual", amount=amount,
            recipient_account_name=account_name.strip(), recipient_bsb=bsb,
            recipient_account_number=account_number,
            transaction_code=profile.transaction_code,
            lodgement_reference=lodgement_reference.strip(),
            trace_bsb=profile.source_bsb,
            trace_account_number=profile.source_account_number,
            remitter_name=profile.remitter_name, status="pending",
            manual_entry_reason=reason.strip(),
        )
        try:
            PaymentBatchService._validate_line(line)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if not reason.strip():
            raise HTTPException(422, "Manual payment reason is required")
        db.add(line)
        db.flush()
        PaymentBatchService.recalculate(db, batch)
        db.commit()
    return RedirectResponse(f"/ui/payment-batches/{batch_id}", status_code=303)


@router.post("/ui/payment-batches/{batch_id}/aba")
def download_aba(request: Request, batch_id: int, csrf_token: str = Form(...)):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        batch = db.get(PaymentBatch, batch_id)
        if batch is None:
            raise HTTPException(404, "Payment batch not found")
        try:
            content = PaymentBatchService.render_aba(db, batch)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        batch.exported_by_user_id = request.session.get("user_id")
        filename = f"payrun-{batch.pay_run_id or batch.id}-{batch.processing_date:%Y%m%d}.aba"
        db.add(ABAFile(
            payment_batch_id=batch.id,
            filename=filename,
            content=content,
            checksum=batch.file_checksum,
            byte_size=len(content),
            created_by_user_id=request.session.get("user_id"),
        ))
        db.commit()
    return StreamingResponse(
        BytesIO(content), media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/ui/aba-files", response_class=HTMLResponse)
def aba_files_page(
    request: Request, page: int = 1, page_size: int = 25,
):
    with SessionLocal() as db:
        total = int(db.scalar(select(func.count(ABAFile.id))) or 0)
        pagination = build_pagination(
            total=total, page=page, page_size=page_size, path="/ui/aba-files"
        )
        rows = db.execute(
            select(ABAFile, PaymentBatch, Organisation)
            .join(
                PaymentBatch,
                PaymentBatch.id == ABAFile.payment_batch_id,
            )
            .join(
                Organisation,
                Organisation.id == PaymentBatch.organisation_id,
            )
            .order_by(ABAFile.id.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        ).all()
        files = [{
            "id": aba_file.id,
            "filename": aba_file.filename,
            "batch_id": batch.id,
            "organisation_name": organisation.name,
            "created_at": aba_file.created_at,
            "byte_size": aba_file.byte_size,
            "checksum": aba_file.checksum,
        } for aba_file, batch, organisation in rows]
    return templates.TemplateResponse(
        request=request,
        name="aba_files.html",
        context={"files": files, "pagination": pagination},
    )


@router.get("/ui/aba-files/{aba_file_id}/download")
def download_saved_aba_file(aba_file_id: int):
    with SessionLocal() as db:
        aba_file = db.get(ABAFile, aba_file_id)
        if aba_file is None:
            raise HTTPException(404, "ABA file not found")
        content = bytes(aba_file.content)
        filename = aba_file.filename
    return StreamingResponse(
        BytesIO(content),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
