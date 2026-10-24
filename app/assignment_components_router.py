from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

templates.env.filters["date_au"] = (
    lambda value: value.strftime("%d/%m/%Y") if value else ""
)

templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)


def require_session(request: Request):
    if not request.session.get("user_id"):
        raise HTTPException(401, "Authentication required")


@router.get(
    "/ui/assignments/{assignment_id}/components",
    response_class=HTMLResponse,
)
def assignment_components_page(request: Request, assignment_id: int):
    require_session(request)

    with SessionLocal() as db:
        assignment = db.get(Assignment, assignment_id)

        if assignment is None:
            raise HTTPException(404, "Assignment not found")

        definitions = db.scalars(
            select(ComponentDefinition)
            .where(ComponentDefinition.active.is_(True))
            .order_by(ComponentDefinition.name)
        ).all()

        families = db.scalars(
            select(ComponentFamily).order_by(ComponentFamily.name)
        ).all()

        family_lookup = {
            family.id: family.name for family in families
        }

        rows = db.scalars(
            select(AssignmentComponent)
            .where(AssignmentComponent.assignment_id == assignment_id)
            .order_by(AssignmentComponent.effective_from.desc())
        ).all()

        definition_lookup = {
            definition.id: definition
            for definition in db.scalars(
                select(ComponentDefinition)
            ).all()
        }

        assignment_data = {
            "id": assignment.id,
            "engagement_id": assignment.engagement_id,
            "worker_id": assignment.engagement.worker_id,
            "employee": (
                f"{assignment.engagement.worker.first_name} "
                f"{assignment.engagement.worker.last_name}"
            ),
            "customer": assignment.customer.name,
        }

        component_options = [
            {
                "id": definition.id,
                "name": definition.name,
                "family": family_lookup.get(
                    definition.family_id, "Other"
                ),
            }
            for definition in definitions
        ]

        component_options.sort(
            key=lambda item: (
                item["family"].lower(),
                item["name"].lower(),
            )
        )

        component_groups = {}

        for component in component_options:
            component_groups.setdefault(
                component["family"], []
            ).append(component)

        history = []

        for row in rows:
            definition = definition_lookup.get(
                row.component_definition_id
            )

            history.append({
                "id": row.id,
                "component_definition_id": row.component_definition_id,
                "name": definition.name if definition else "Unknown",
                "code": definition.code if definition else "",
                "calculation_type": (
                    definition.calculation_type if definition else ""
                ),
                "pay_rate": row.pay_rate,
                "bill_rate": row.bill_rate,
                "applies_to": row.applies_to,
                "effective_from": row.effective_from,
                "effective_to": row.effective_to,
            })

    return templates.TemplateResponse(
        request=request,
        name="assignment_components.html",
        context={
            "assignment": assignment_data,
            "definitions": component_options,
            "component_groups": component_groups,
            "history": history,
        },
    )


@router.post("/ui/assignments/{assignment_id}/components")
def save_assignment_component(
    request: Request,
    assignment_id: int,
    component_definition_id: int = Form(...),
    applies_to: str = Form(...),
    pay_rate: Decimal | None = Form(None),
    bill_rate: Decimal | None = Form(None),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
    return_to_preview: bool = Form(False),
    csrf_token: str = Form(...),
):
    require_session(request)

    expected_token = request.session.get("csrf_token")

    if not expected_token or csrf_token != expected_token:
        raise HTTPException(403, "Invalid CSRF token")

    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "Invalid effective date range")

    if applies_to not in ("payroll", "invoice", "both"):
        raise HTTPException(422, "Invalid component applicability")

    for value in (pay_rate, bill_rate):
        if value is not None and (value < 0 or value > 99999999):
            raise HTTPException(422, "Invalid component rate")

    if applies_to in ("payroll", "both") and pay_rate is None:
        raise HTTPException(422, "Pay rate is required")

    if applies_to in ("invoice", "both") and bill_rate is None:
        raise HTTPException(422, "Bill rate is required")

    if applies_to == "payroll" and bill_rate is not None:
        raise HTTPException(422, "Bill rate must be empty")

    if applies_to == "invoice" and pay_rate is not None:
        raise HTTPException(422, "Pay rate must be empty")

    with SessionLocal() as db:
        assignment = db.get(Assignment, assignment_id)

        if assignment is None:
            raise HTTPException(404, "Assignment not found")

        preview_url = (
            f"/ui/workers/{assignment.engagement.worker_id}"
            f"/engagements/{assignment.engagement_id}"
            f"/assignments/{assignment.id}/preview"
        )

        definition = db.get(
            ComponentDefinition,
            component_definition_id,
        )

        if definition is None or not definition.active:
            raise HTTPException(422, "Invalid or inactive component")

        existing = db.scalars(
            select(AssignmentComponent).where(
                AssignmentComponent.assignment_id == assignment_id,
                AssignmentComponent.component_definition_id
                == component_definition_id,
            )
        ).all()

        for profile in existing:
            overlaps = (
                (
                    effective_to is None
                    or profile.effective_from <= effective_to
                )
                and
                (
                    profile.effective_to is None
                    or effective_from <= profile.effective_to
                )
            )

            if overlaps:
                raise HTTPException(
                    409,
                    "This component already has a configuration "
                    "for the selected dates",
                )

        db.add(
            AssignmentComponent(
                assignment_id=assignment_id,
                component_definition_id=component_definition_id,
                rate=pay_rate,
                pay_rate=pay_rate,
                bill_rate=bill_rate,
                applies_to=applies_to,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )

        db.commit()

    return RedirectResponse(
        preview_url if return_to_preview
        else f"/ui/assignments/{assignment_id}/components",
        status_code=303,
    )


@router.post(
    "/ui/assignments/{assignment_id}/components/{component_id}"
)
def update_assignment_component(
    request: Request,
    assignment_id: int,
    component_id: int,
    component_definition_id: int = Form(...),
    applies_to: str = Form(...),
    pay_rate: Decimal | None = Form(None),
    bill_rate: Decimal | None = Form(None),
    effective_from: date = Form(...),
    effective_to: date | None = Form(None),
    return_to_preview: bool = Form(False),
    csrf_token: str = Form(...),
):
    require_session(request)

    expected_token = request.session.get("csrf_token")

    if not expected_token or csrf_token != expected_token:
        raise HTTPException(403, "Invalid CSRF token")

    if effective_to is not None and effective_to < effective_from:
        raise HTTPException(422, "Invalid effective date range")

    if applies_to not in ("payroll", "invoice", "both"):
        raise HTTPException(422, "Invalid component applicability")

    for value in (pay_rate, bill_rate):
        if value is not None and (value < 0 or value > 99999999):
            raise HTTPException(422, "Invalid component rate")

    if applies_to in ("payroll", "both") and pay_rate is None:
        raise HTTPException(422, "Pay rate is required")

    if applies_to in ("invoice", "both") and bill_rate is None:
        raise HTTPException(422, "Bill rate is required")

    if applies_to == "payroll" and bill_rate is not None:
        raise HTTPException(422, "Bill rate must be empty")

    if applies_to == "invoice" and pay_rate is not None:
        raise HTTPException(422, "Pay rate must be empty")

    with SessionLocal() as db:
        assignment = db.get(Assignment, assignment_id)

        if assignment is None:
            raise HTTPException(404, "Assignment not found")

        preview_url = (
            f"/ui/workers/{assignment.engagement.worker_id}"
            f"/engagements/{assignment.engagement_id}"
            f"/assignments/{assignment.id}/preview"
        )

        component = db.get(AssignmentComponent, component_id)

        if component is None or component.assignment_id != assignment_id:
            raise HTTPException(404, "Assignment component not found")

        definition = db.get(
            ComponentDefinition,
            component_definition_id,
        )

        if definition is None or not definition.active:
            raise HTTPException(422, "Invalid or inactive component")

        existing = db.scalars(
            select(AssignmentComponent).where(
                AssignmentComponent.assignment_id == assignment_id,
                AssignmentComponent.component_definition_id
                == component_definition_id,
                AssignmentComponent.id != component_id,
            )
        ).all()

        for profile in existing:
            overlaps = (
                (
                    effective_to is None
                    or profile.effective_from <= effective_to
                )
                and
                (
                    profile.effective_to is None
                    or effective_from <= profile.effective_to
                )
            )

            if overlaps:
                raise HTTPException(
                    409,
                    "This component already has a configuration "
                    "for the selected dates",
                )

        component.component_definition_id = component_definition_id
        component.rate = pay_rate
        component.pay_rate = pay_rate
        component.bill_rate = bill_rate
        component.applies_to = applies_to
        component.effective_from = effective_from
        component.effective_to = effective_to

        db.commit()

    return RedirectResponse(
        preview_url if return_to_preview
        else f"/ui/assignments/{assignment_id}/components",
        status_code=303,
    )
