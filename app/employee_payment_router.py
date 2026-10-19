from app.engagement_resolver import resolve_engagement_id, resolve_worker_id
from datetime import date
import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.models.employee_payment_detail import EmployeePaymentDetail

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)






# Worker-native Payment administration.
from app.models.worker import Worker


@router.get(
    "/ui/workers/{worker_id}/payment",
    response_class=HTMLResponse,
)
def worker_payment_details_page(request: Request, worker_id: int):
    if not request.session.get("user_id"):
        raise HTTPException(401, "Authentication required")

    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        profiles = db.scalars(
            select(EmployeePaymentDetail)
            .where(EmployeePaymentDetail.worker_id == worker_id)
            .order_by(EmployeePaymentDetail.effective_from.desc())
        ).all()

        profile_data = [
            {
                "payment_method": p.payment_method,
                "account_name": p.account_name,
                "bsb": p.bsb,
                "account_number": (
                    "****" + p.account_number[-4:]
                    if p.account_number else None
                ),
                "effective_from": p.effective_from.isoformat(),
                "effective_to": (
                    p.effective_to.isoformat()
                    if p.effective_to else None
                ),
            }
            for p in profiles
        ]

        worker_data = {
            "id": worker.id,
            "name": f"{worker.first_name} {worker.last_name}",
        }

    return templates.TemplateResponse(
        request=request,
        name="employee_payment.html",
        context={
            "employee": worker_data,
            "profiles": profile_data,
            "worker_mode": True,
        },
    )


@router.post("/ui/workers/{worker_id}/payment")
def save_worker_payment_details(
    request: Request,
    worker_id: int,
    payment_method: str = Form(...),
    account_name: str = Form(""),
    bsb: str = Form(""),
    account_number: str = Form(""),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
    csrf_token: str = Form(...),
):
    from app.employee_tfn_router import require_csrf

    if not request.session.get("user_id"):
        raise HTTPException(401, "Authentication required")

    require_csrf(request, csrf_token)

    if payment_method not in {"bank_transfer", "cash", "cheque"}:
        raise HTTPException(422, "Invalid payment method")

    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "Invalid effective date range")

    if payment_method == "bank_transfer":
        bsb = bsb.replace("-", "").replace(" ", "")
        account_number = account_number.replace(" ", "")

        if not account_name.strip():
            raise HTTPException(422, "Account name required")

        if not re.fullmatch(r"[0-9]{6}", bsb):
            raise HTTPException(422, "BSB must contain six digits")

        if not re.fullmatch(r"[0-9]{4,10}", account_number):
            raise HTTPException(
                422,
                "Account number must contain 4–10 digits",
            )
    else:
        account_name = ""
        bsb = ""
        account_number = ""

    with SessionLocal() as db:
        if db.get(Worker, worker_id) is None:
            raise HTTPException(404, "Worker not found")

        existing = db.scalars(
            select(EmployeePaymentDetail)
            .where(EmployeePaymentDetail.worker_id == worker_id)
        ).all()

        for profile in existing:
            overlaps = (
                (effective_to is None or profile.effective_from <= effective_to)
                and
                (profile.effective_to is None or effective_from <= profile.effective_to)
            )

            if overlaps:
                raise HTTPException(
                    409,
                    "Payment profile dates overlap an existing profile",
                )

        db.add(
            EmployeePaymentDetail(
                worker_id=worker_id,
                employee_id=None,
                engagement_id=None,
                payment_method=payment_method,
                account_name=account_name or None,
                bsb=bsb or None,
                account_number=account_number or None,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
        db.commit()

    return RedirectResponse(
        f"/ui/workers/{worker_id}/payment",
        status_code=303,
    )
