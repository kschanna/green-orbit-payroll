from datetime import date

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.employee_tfn_router import require_csrf
from app.models.organisation import Organisation
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.pbt_schedule_rule import PBTScheduleRule
from app.pbt.service import FREQUENCIES, PBTScheduleService


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["date_au"] = (
    lambda value: value.strftime("%d/%m/%Y") if value else "—"
)
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)


def _validate_rule(
    schedule_type: str,
    frequency: str,
    anchor_date: date | None,
    offset_days: int,
    payment_terms_days: int | None = None,
):
    if frequency not in FREQUENCIES:
        raise HTTPException(422, f"Invalid {schedule_type} frequency")
    if frequency in {"weekly", "fortnightly"} and anchor_date is None:
        raise HTTPException(
            422,
            f"{schedule_type.title()} schedule requires an anchor date",
        )
    if not -365 <= offset_days <= 365:
        raise HTTPException(422, "Offsets must be between -365 and 365 days")
    if payment_terms_days is not None and not 0 <= payment_terms_days <= 365:
        raise HTTPException(
            422,
            "Invoice payment terms must be between 0 and 365 days",
        )


@router.get("/ui/pbt-schedules", response_class=HTMLResponse)
def pbt_schedules_page(request: Request):
    with SessionLocal() as db:
        schedules = db.scalars(
            select(PBTSchedule)
            .options(selectinload(PBTSchedule.customer))
            .order_by(PBTSchedule.id.desc())
        ).all()
        rows = [{
            "id": schedule.id,
            "name": schedule.name,
            "customer_name": schedule.customer.name,
            "effective_from": schedule.effective_from,
            "effective_to": schedule.effective_to,
            "status": schedule.status,
            "generated_through": schedule.generated_through,
        } for schedule in schedules]

    return templates.TemplateResponse(
        request=request,
        name="pbt_schedules.html",
        context={"schedules": rows},
    )


@router.get("/ui/pbt-schedules/new", response_class=HTMLResponse)
def new_pbt_schedule_page(request: Request):
    with SessionLocal() as db:
        organisations = db.scalars(
            select(Organisation).order_by(Organisation.name)
        ).all()
        customers = [
            {"id": organisation.id, "name": organisation.name}
            for organisation in organisations
        ]

    return templates.TemplateResponse(
        request=request,
        name="pbt_schedule_form.html",
        context={
            "customers": customers,
            "today": date.today().isoformat(),
        },
    )


@router.post("/ui/pbt-schedules")
def create_pbt_schedule(
    request: Request,
    customer_organisation_id: int = Form(...),
    name: str = Form(...),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
    status: str = Form("draft"),
    timesheet_frequency: str = Form(...),
    timesheet_anchor_date: date | None = Form(None),
    timesheet_offset_days: int = Form(...),
    invoice_frequency: str = Form(...),
    invoice_anchor_date: date | None = Form(None),
    invoice_offset_days: int = Form(...),
    invoice_payment_terms_days: int = Form(...),
    payment_frequency: str = Form(...),
    payment_anchor_date: date | None = Form(None),
    payment_offset_days: int = Form(...),
    csrf_token: str = Form(...),
):
    require_csrf(request, csrf_token)

    if not name.strip():
        raise HTTPException(422, "PBT schedule name is required")
    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "End date cannot precede start date")
    if status not in {"draft", "active"}:
        raise HTTPException(422, "Invalid PBT schedule status")

    _validate_rule(
        "timesheet", timesheet_frequency,
        timesheet_anchor_date, timesheet_offset_days,
    )
    _validate_rule(
        "invoice", invoice_frequency,
        invoice_anchor_date, invoice_offset_days,
        invoice_payment_terms_days,
    )
    _validate_rule(
        "payment", payment_frequency,
        payment_anchor_date, payment_offset_days,
    )

    with SessionLocal() as db:
        if db.get(Organisation, customer_organisation_id) is None:
            raise HTTPException(404, "Customer organisation not found")

        if status == "active":
            _ensure_no_active_overlap(
                db,
                customer_organisation_id,
                effective_from,
                effective_to,
            )

        schedule = PBTSchedule(
            customer_organisation_id=customer_organisation_id,
            name=name.strip(),
            effective_from=effective_from,
            effective_to=effective_to,
            status=status,
            generation_months=12,
        )
        db.add(schedule)
        db.flush()

        schedule.rules.extend([
            PBTScheduleRule(
                schedule_type="timesheet",
                frequency=timesheet_frequency,
                anchor_date=timesheet_anchor_date,
                offset_days=timesheet_offset_days,
                active=True,
            ),
            PBTScheduleRule(
                schedule_type="invoice",
                frequency=invoice_frequency,
                anchor_date=invoice_anchor_date,
                offset_days=invoice_offset_days,
                invoice_payment_terms_days=invoice_payment_terms_days,
                active=True,
            ),
            PBTScheduleRule(
                schedule_type="payment",
                frequency=payment_frequency,
                anchor_date=payment_anchor_date,
                offset_days=payment_offset_days,
                active=True,
            ),
        ])
        db.flush()
        PBTScheduleService.generate(db, schedule)
        db.commit()
        schedule_id = schedule.id

    return RedirectResponse(
        f"/ui/pbt-schedules/{schedule_id}",
        status_code=303,
    )


def _ensure_no_active_overlap(
    db,
    customer_organisation_id: int,
    effective_from: date,
    effective_to: date | None,
    exclude_schedule_id: int | None = None,
):
    statement = select(PBTSchedule).where(
        PBTSchedule.customer_organisation_id == customer_organisation_id,
        PBTSchedule.status == "active",
    )
    if exclude_schedule_id is not None:
        statement = statement.where(PBTSchedule.id != exclude_schedule_id)

    for current in db.scalars(statement).all():
        overlaps = (
            (effective_to is None or current.effective_from <= effective_to)
            and
            (current.effective_to is None
             or effective_from <= current.effective_to)
        )
        if overlaps:
            raise HTTPException(
                409,
                "PBT schedule dates overlap an active customer schedule",
            )


@router.post("/ui/pbt-schedules/{schedule_id}/status")
def update_pbt_schedule_status(
    request: Request,
    schedule_id: int,
    status: str = Form(...),
    csrf_token: str = Form(...),
):
    require_csrf(request, csrf_token)
    if status not in {"active", "inactive"}:
        raise HTTPException(422, "Invalid PBT schedule status")

    with SessionLocal() as db:
        schedule = db.get(PBTSchedule, schedule_id)
        if schedule is None:
            raise HTTPException(404, "PBT schedule not found")
        if status == "active":
            _ensure_no_active_overlap(
                db,
                schedule.customer_organisation_id,
                schedule.effective_from,
                schedule.effective_to,
                exclude_schedule_id=schedule.id,
            )
        schedule.status = status
        db.commit()

    return RedirectResponse(
        f"/ui/pbt-schedules/{schedule_id}",
        status_code=303,
    )


@router.get("/ui/pbt-schedules/{schedule_id}", response_class=HTMLResponse)
def pbt_schedule_detail_page(request: Request, schedule_id: int):
    with SessionLocal() as db:
        schedule = db.scalar(
            select(PBTSchedule)
            .options(
                selectinload(PBTSchedule.customer),
                selectinload(PBTSchedule.rules),
            )
            .where(PBTSchedule.id == schedule_id)
        )
        if schedule is None:
            raise HTTPException(404, "PBT schedule not found")

        periods = db.scalars(
            select(PBTSchedulePeriod)
            .where(PBTSchedulePeriod.pbt_schedule_id == schedule_id)
            .order_by(
                PBTSchedulePeriod.schedule_type,
                PBTSchedulePeriod.period_start,
            )
        ).all()
        period_groups = {"timesheet": [], "invoice": [], "payment": []}
        for period in periods:
            period_groups[period.schedule_type].append(period)
        rules = {
            rule.schedule_type: rule for rule in schedule.rules
        }

        context = {
            "schedule": schedule,
            "rules": rules,
            "period_groups": period_groups,
            "period_count": len(periods),
        }

    return templates.TemplateResponse(
        request=request,
        name="pbt_schedule_detail.html",
        context=context,
    )
