from app.engagement_resolver import resolve_engagement_id, resolve_worker_id
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.models.employee_super_profile import EmployeeSuperProfile

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)






# Worker-native Superannuation administration.
from app.models.worker import Worker
from app.employee_tfn_router import require_csrf


@router.get("/ui/workers/{worker_id}/super", response_class=HTMLResponse)
def worker_super_details_page(request: Request, worker_id: int):
    if not request.session.get("user_id"):
        raise HTTPException(401, "Authentication required")

    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        profiles = db.scalars(
            select(EmployeeSuperProfile)
            .where(EmployeeSuperProfile.worker_id == worker_id)
            .order_by(EmployeeSuperProfile.effective_from.desc())
        ).all()

        profile_data = [
            {
                "id": p.id,
                "fund_name": p.fund_name,
                "fund_usi": p.fund_usi,
                "member_number": p.member_number,
                "additional_employer_rate": (
                    str(p.additional_employer_rate)
                    if p.additional_employer_rate is not None else None
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
        name="employee_super.html",
        context={
            "employee": worker_data,
            "profiles": profile_data,
            "worker_mode": True,
        },
    )


@router.post("/ui/workers/{worker_id}/super")
def save_worker_super_details(
    request: Request,
    worker_id: int,
    csrf_token: str = Form(...),
    fund_name: str = Form(...),
    fund_usi: str = Form(...),
    member_number: str = Form(...),
    additional_employer_rate: Decimal | None = Form(None),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
):
    if not request.session.get("user_id"):
        raise HTTPException(401, "Authentication required")

    require_csrf(request, csrf_token)

    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "End date cannot precede start date")

    if additional_employer_rate is not None and not (
        Decimal("0") <= additional_employer_rate <= Decimal("100")
    ):
        raise HTTPException(
            422,
            "Additional employer rate must be between 0 and 100",
        )

    with SessionLocal() as db:
        if db.get(Worker, worker_id) is None:
            raise HTTPException(404, "Worker not found")

        existing = db.scalars(
            select(EmployeeSuperProfile)
            .where(EmployeeSuperProfile.worker_id == worker_id)
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
                    "Superannuation profile dates overlap",
                )

        db.add(
            EmployeeSuperProfile(
                worker_id=worker_id,
                employee_id=None,
                engagement_id=None,
                fund_name=fund_name.strip(),
                fund_usi=fund_usi.strip(),
                member_number=member_number.strip(),
                additional_employer_rate=additional_employer_rate,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
        db.commit()

    return RedirectResponse(
        f"/ui/workers/{worker_id}/super",
        status_code=303,
    )


@router.post("/ui/workers/{worker_id}/super/{profile_id}")
def update_worker_super_details(
    request: Request,
    worker_id: int,
    profile_id: int,
    csrf_token: str = Form(...),
    fund_name: str = Form(...),
    fund_usi: str = Form(...),
    member_number: str = Form(...),
    additional_employer_rate: Decimal | None = Form(None),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
):
    if not request.session.get("user_id"):
        raise HTTPException(401, "Authentication required")

    require_csrf(request, csrf_token)

    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "End date cannot precede start date")

    if additional_employer_rate is not None and not (
        Decimal("0") <= additional_employer_rate <= Decimal("100")
    ):
        raise HTTPException(
            422,
            "Additional employer rate must be between 0 and 100",
        )

    with SessionLocal() as db:
        profile = db.get(EmployeeSuperProfile, profile_id)
        if profile is None or profile.worker_id != worker_id:
            raise HTTPException(404, "Superannuation profile not found")

        other_profiles = db.scalars(
            select(EmployeeSuperProfile).where(
                EmployeeSuperProfile.worker_id == worker_id,
                EmployeeSuperProfile.id != profile_id,
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
                    "Superannuation profile dates overlap",
                )

        profile.fund_name = fund_name.strip()
        profile.fund_usi = fund_usi.strip()
        profile.member_number = member_number.strip()
        profile.additional_employer_rate = additional_employer_rate
        profile.effective_from = effective_from
        profile.effective_to = effective_to
        db.commit()

    return RedirectResponse(
        f"/ui/workers/{worker_id}/super",
        status_code=303,
    )
