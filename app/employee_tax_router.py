from app.engagement_resolver import resolve_engagement_id, resolve_worker_id
from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.employee_tfn import EmployeeTFN
from app.tfn_security import mask_tfn
from app.employee_tfn_router import require_tfn_admin

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = lambda request: request.session.get(
    "csrf_token", ""
)






# Worker-native Tax administration.
from app.models.worker import Worker


@router.get("/ui/workers/{worker_id}/tax", response_class=HTMLResponse)
def worker_tax_details_page(request: Request, worker_id: int):
    require_tfn_admin(request)

    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        profiles = db.scalars(
            select(EmployeeTaxProfile)
            .where(EmployeeTaxProfile.worker_id == worker_id)
            .order_by(EmployeeTaxProfile.effective_from.desc())
        ).all()

        tfn_record = db.get(EmployeeTFN, worker_id)
        masked_tfn = (
            mask_tfn(tfn_record.last_three)
            if tfn_record else None
        )

        profile_data = [
            {
                "id": p.id,
                "residency_status": p.residency_status,
                "claims_tax_free_threshold": p.claims_tax_free_threshold,
                "has_study_loan": p.has_study_loan,
                "tfn_declaration_received": p.tfn_declaration_received,
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
        name="employee_tax.html",
        context={
            "employee": worker_data,
            "profiles": profile_data,
            "masked_tfn": masked_tfn,
            "worker_mode": True,
        },
    )


@router.post("/ui/workers/{worker_id}/tax")
def save_worker_tax_details(
    request: Request,
    worker_id: int,
    csrf_token: str = Form(...),
    residency_status: str = Form(...),
    claims_tax_free_threshold: bool = Form(False),
    has_study_loan: bool = Form(False),
    tfn_declaration_received: bool = Form(False),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
):
    from app.employee_tfn_router import require_csrf

    require_tfn_admin(request)
    require_csrf(request, csrf_token)

    if residency_status not in {
        "resident", "foreign_resident", "working_holiday_maker"
    }:
        raise HTTPException(422, "Invalid residency status")

    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "End date cannot precede start date")

    with SessionLocal() as db:
        if db.get(Worker, worker_id) is None:
            raise HTTPException(404, "Worker not found")

        existing = db.scalars(
            select(EmployeeTaxProfile)
            .where(EmployeeTaxProfile.worker_id == worker_id)
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
                    "Tax profile dates overlap an existing profile",
                )

        db.add(
            EmployeeTaxProfile(
                worker_id=worker_id,
                employee_id=None,
                engagement_id=None,
                residency_status=residency_status,
                claims_tax_free_threshold=claims_tax_free_threshold,
                has_study_loan=has_study_loan,
                tfn_declaration_received=tfn_declaration_received,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
        db.commit()

    return RedirectResponse(
        f"/ui/workers/{worker_id}/tax",
        status_code=303,
    )


@router.post("/ui/workers/{worker_id}/tax/{profile_id}")
def update_worker_tax_details(
    request: Request,
    worker_id: int,
    profile_id: int,
    csrf_token: str = Form(...),
    residency_status: str = Form(...),
    claims_tax_free_threshold: bool = Form(False),
    has_study_loan: bool = Form(False),
    tfn_declaration_received: bool = Form(False),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
):
    from app.employee_tfn_router import require_csrf

    require_tfn_admin(request)
    require_csrf(request, csrf_token)

    if residency_status not in {
        "resident", "foreign_resident", "working_holiday_maker"
    }:
        raise HTTPException(422, "Invalid residency status")

    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "End date cannot precede start date")

    with SessionLocal() as db:
        profile = db.get(EmployeeTaxProfile, profile_id)
        if profile is None or profile.worker_id != worker_id:
            raise HTTPException(404, "Tax profile not found")

        other_profiles = db.scalars(
            select(EmployeeTaxProfile).where(
                EmployeeTaxProfile.worker_id == worker_id,
                EmployeeTaxProfile.id != profile_id,
            )
        ).all()

        for other in other_profiles:
            overlaps = (
                (effective_to is None or other.effective_from <= effective_to)
                and
                (other.effective_to is None or effective_from <= other.effective_to)
            )
            if overlaps:
                raise HTTPException(
                    409,
                    "Tax profile dates overlap an existing profile",
                )

        profile.residency_status = residency_status
        profile.claims_tax_free_threshold = claims_tax_free_threshold
        profile.has_study_loan = has_study_loan
        profile.tfn_declaration_received = tfn_declaration_received
        profile.effective_from = effective_from
        profile.effective_to = effective_to
        db.commit()

    return RedirectResponse(
        f"/ui/workers/{worker_id}/tax",
        status_code=303,
    )
