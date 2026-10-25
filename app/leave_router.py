from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.employee_tfn_router import require_csrf
from app.leave.service import LeaveService
from app.models.component_definition import ComponentDefinition
from app.models.engagement import Engagement
from app.models.leave_plan import LeavePlan
from app.models.leave_transaction import LeaveTransaction
from app.models.worker import Worker
from app.utils.dates import format_date_au

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)
templates.env.filters["date_au"] = format_date_au


@router.get("/ui/workers/{worker_id}/leave", response_class=HTMLResponse)
def worker_leave_page(request: Request, worker_id: int):
    if not request.session.get("user_id"):
        raise HTTPException(401, "Authentication required")
    with SessionLocal() as db:
        worker = db.get(Worker, worker_id)
        if worker is None:
            raise HTTPException(404, "Worker not found")
        engagements = db.scalars(
            select(Engagement).where(
                Engagement.worker_id == worker_id,
                Engagement.engagement_type.in_((
                    "payg_employee", "payg_contractor"
                )),
            ).order_by(Engagement.start_date.desc())
        ).all()
        definitions = db.scalars(
            select(ComponentDefinition).where(
                ComponentDefinition.code.in_(("ANNUAL_LEAVE", "PERSONAL_LEAVE")),
                ComponentDefinition.active.is_(True),
            ).order_by(ComponentDefinition.name)
        ).all()
        plans = db.scalars(
            select(LeavePlan).where(LeavePlan.worker_id == worker_id)
            .order_by(LeavePlan.effective_from.desc())
        ).all()
        definition_names = {d.id: d.name for d in definitions}
        rows = [{
            "id": p.id,
            "engagement_id": p.engagement_id,
            "leave_type": definition_names.get(p.component_definition_id, "Unknown"),
            "annual_entitlement_hours": p.annual_entitlement_hours,
            "standard_hours_per_year": p.standard_hours_per_year,
            "accrual_rate_per_hour": p.accrual_rate_per_hour,
            "opening_balance_hours": p.opening_balance_hours,
            "balance": LeaveService.balance(db, p.id),
            "effective_from": p.effective_from,
            "effective_to": p.effective_to,
            "allow_negative_balance": p.allow_negative_balance,
            "plan_basis": p.plan_basis,
            "paid_leave_rate": p.paid_leave_rate,
            "edit_data": {
                "id": p.id,
                "engagement_id": p.engagement_id,
                "component_definition_id": p.component_definition_id,
                "annual_entitlement_hours": str(p.annual_entitlement_hours),
                "standard_hours_per_year": str(p.standard_hours_per_year),
                "opening_balance_hours": str(p.opening_balance_hours),
                "paid_leave_rate": (
                    str(p.paid_leave_rate)
                    if p.paid_leave_rate is not None else ""
                ),
                "effective_from": p.effective_from.isoformat(),
                "effective_to": (
                    p.effective_to.isoformat() if p.effective_to else ""
                ),
                "allow_negative_balance": p.allow_negative_balance,
                "accrues_during_paid_leave": p.accrues_during_paid_leave,
            },
        } for p in plans]
        transactions = db.execute(
            select(LeaveTransaction, LeavePlan, ComponentDefinition)
            .join(LeavePlan, LeavePlan.id == LeaveTransaction.leave_plan_id)
            .join(ComponentDefinition, ComponentDefinition.id == LeavePlan.component_definition_id)
            .where(LeavePlan.worker_id == worker_id)
            .order_by(LeaveTransaction.transaction_date.desc(), LeaveTransaction.id.desc())
            .limit(100)
        ).all()
        engagement_rows = [{
            "id": engagement.id,
            "organisation_name": engagement.organisation.name,
            "engagement_type": engagement.engagement_type,
        } for engagement in engagements]
        definition_rows = [{
            "id": definition.id,
            "name": definition.name,
        } for definition in definitions]
        context = {
            "worker": {"id": worker.id, "name": f"{worker.first_name} {worker.last_name}"},
            "engagements": engagement_rows,
            "definitions": definition_rows,
            "plans": rows,
            "transactions": [{
                "date": t.transaction_date, "leave_type": d.name,
                "type": t.transaction_type, "hours": t.hours,
                "description": t.description,
            } for t, p, d in transactions],
            "today": date.today().isoformat(),
        }
    return templates.TemplateResponse(request=request, name="worker_leave.html", context=context)


@router.post("/ui/workers/{worker_id}/leave")
def save_worker_leave_plan(
    request: Request, worker_id: int,
    engagement_id: int = Form(...),
    component_definition_id: int = Form(...),
    annual_entitlement_hours: Decimal = Form(...),
    standard_hours_per_year: Decimal = Form(...),
    opening_balance_hours: Decimal = Form(Decimal("0")),
    paid_leave_rate: Decimal | None = Form(None),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
    allow_negative_balance: bool = Form(False),
    accrues_during_paid_leave: bool = Form(False),
    csrf_token: str = Form(...),
):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        validated = _validate_leave_plan(
            db=db, worker_id=worker_id, engagement_id=engagement_id,
            component_definition_id=component_definition_id,
            annual_entitlement_hours=annual_entitlement_hours,
            standard_hours_per_year=standard_hours_per_year,
            paid_leave_rate=paid_leave_rate, effective_from=effective_from,
            effective_to=effective_to,
        )
        db.add(LeavePlan(
            worker_id=worker_id, engagement_id=engagement_id,
            component_definition_id=component_definition_id,
            annual_entitlement_hours=annual_entitlement_hours,
            standard_hours_per_year=standard_hours_per_year,
            accrual_rate_per_hour=(annual_entitlement_hours / standard_hours_per_year),
            plan_basis=validated["plan_basis"],
            paid_leave_rate=validated["paid_leave_rate"],
            opening_balance_hours=opening_balance_hours,
            allow_negative_balance=allow_negative_balance,
            accrues_during_paid_leave=accrues_during_paid_leave,
            effective_from=effective_from, effective_to=effective_to,
        ))
        db.commit()
    return RedirectResponse(f"/ui/workers/{worker_id}/leave", status_code=303)


@router.post("/ui/workers/{worker_id}/leave/{plan_id}")
def update_worker_leave_plan(
    request: Request, worker_id: int, plan_id: int,
    engagement_id: int = Form(...),
    component_definition_id: int = Form(...),
    annual_entitlement_hours: Decimal = Form(...),
    standard_hours_per_year: Decimal = Form(...),
    opening_balance_hours: Decimal = Form(Decimal("0")),
    paid_leave_rate: Decimal | None = Form(None),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
    allow_negative_balance: bool = Form(False),
    accrues_during_paid_leave: bool = Form(False),
    csrf_token: str = Form(...),
):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        plan = db.get(LeavePlan, plan_id)
        if plan is None or plan.worker_id != worker_id:
            raise HTTPException(404, "Leave plan not found")
        validated = _validate_leave_plan(
            db=db, worker_id=worker_id, engagement_id=engagement_id,
            component_definition_id=component_definition_id,
            annual_entitlement_hours=annual_entitlement_hours,
            standard_hours_per_year=standard_hours_per_year,
            paid_leave_rate=paid_leave_rate, effective_from=effective_from,
            effective_to=effective_to, exclude_plan_id=plan_id,
        )
        plan.engagement_id = engagement_id
        plan.component_definition_id = component_definition_id
        plan.annual_entitlement_hours = annual_entitlement_hours
        plan.standard_hours_per_year = standard_hours_per_year
        plan.accrual_rate_per_hour = annual_entitlement_hours / standard_hours_per_year
        plan.plan_basis = validated["plan_basis"]
        plan.paid_leave_rate = validated["paid_leave_rate"]
        plan.opening_balance_hours = opening_balance_hours
        plan.allow_negative_balance = allow_negative_balance
        plan.accrues_during_paid_leave = accrues_during_paid_leave
        plan.effective_from = effective_from
        plan.effective_to = effective_to
        db.commit()
    return RedirectResponse(f"/ui/workers/{worker_id}/leave", status_code=303)


def _validate_leave_plan(
    *, db, worker_id: int, engagement_id: int, component_definition_id: int,
    annual_entitlement_hours: Decimal, standard_hours_per_year: Decimal,
    paid_leave_rate: Decimal | None, effective_from: date,
    effective_to: date | None, exclude_plan_id: int | None = None,
):
    if annual_entitlement_hours <= 0 or standard_hours_per_year <= 0:
        raise HTTPException(422, "Entitlement and annual hours must be positive")
    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "End date cannot precede start date")

    engagement = db.get(Engagement, engagement_id)
    if engagement is None or engagement.worker_id != worker_id:
        raise HTTPException(422, "Invalid worker engagement")
    if engagement.engagement_type not in {"payg_employee", "payg_contractor"}:
        raise HTTPException(422, "Leave plans require a PAYG engagement")
    if engagement.engagement_type == "payg_contractor":
        if paid_leave_rate is None or paid_leave_rate <= 0:
            raise HTTPException(
                422, "A positive paid leave rate is required for contractors"
            )
        plan_basis = "contractual"
    else:
        plan_basis = "statutory"
        paid_leave_rate = None
    definition = db.get(ComponentDefinition, component_definition_id)
    if definition is None or definition.code not in {"ANNUAL_LEAVE", "PERSONAL_LEAVE"}:
        raise HTTPException(422, "Unsupported leave type")
    existing = db.scalars(select(LeavePlan).where(
        LeavePlan.engagement_id == engagement_id,
        LeavePlan.component_definition_id == component_definition_id,
    )).all()
    for plan in existing:
        if plan.id == exclude_plan_id:
            continue
        if ((effective_to is None or plan.effective_from <= effective_to)
                and (plan.effective_to is None or effective_from <= plan.effective_to)):
            raise HTTPException(409, "Leave plan dates overlap")
    return {"plan_basis": plan_basis, "paid_leave_rate": paid_leave_rate}
