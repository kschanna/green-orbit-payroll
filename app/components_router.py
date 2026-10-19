from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.component_family import ComponentFamily
from app.models.component_definition import ComponentDefinition
from app.models.component_audit_log import ComponentAuditLog

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = lambda request: request.session.get(
    "csrf_token", ""
)


@router.get("/ui/components", response_class=HTMLResponse)
def components_page(request: Request):
    with SessionLocal() as db:
        families = db.scalars(
            select(ComponentFamily).order_by(ComponentFamily.name)
        ).all()

        definitions = db.scalars(
            select(ComponentDefinition).order_by(ComponentDefinition.name)
        ).all()

        family_names = {family.id: family.name for family in families}

        rows = [
            {
                "id": component.id,
                "code": component.code,
                "name": component.name,
                "family": family_names.get(component.family_id, "Unknown"),
                "calculation_type": component.calculation_type,
                "active": component.active,
            }
            for component in definitions
        ]

    return templates.TemplateResponse(
        request=request,
        name="components.html",
        context={"components": rows},
    )


@router.get("/ui/components/new", response_class=HTMLResponse)
def new_component_page(request: Request):
    with SessionLocal() as db:
        families = db.scalars(
            select(ComponentFamily).order_by(ComponentFamily.name)
        ).all()

        family_data = [
            {"id": family.id, "name": family.name}
            for family in families
        ]

    return templates.TemplateResponse(
        request=request,
        name="component_form.html",
        context={"component": None, "families": family_data},
    )


@router.get("/ui/components/{component_id}/edit", response_class=HTMLResponse)
def edit_component_page(request: Request, component_id: int):
    with SessionLocal() as db:
        component = db.get(ComponentDefinition, component_id)

        if component is None:
            raise HTTPException(404, "Component not found")

        families = db.scalars(
            select(ComponentFamily).order_by(ComponentFamily.name)
        ).all()

        data = {
            "id": component.id,
            "code": component.code,
            "name": component.name,
            "description": component.description or "",
            "family_id": component.family_id,
            "calculation_type": component.calculation_type,
            "active": component.active,
        }

        family_data = [
            {"id": family.id, "name": family.name}
            for family in families
        ]

    return templates.TemplateResponse(
        request=request,
        name="component_form.html",
        context={"component": data, "families": family_data},
    )


@router.post("/ui/components/save")
def save_component(
    request: Request,
    component_id: int | None = Form(None),
    family_id: int = Form(...),
    code: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    calculation_type: str = Form(...),
    active: bool = Form(False),
):
    code = code.strip().upper()
    name = name.strip()
    description = description.strip()

    if not code or len(code) > 50:
        raise HTTPException(422, "Invalid component code")

    if not name or len(name) > 150:
        raise HTTPException(422, "Invalid component name")

    if len(description) > 500:
        raise HTTPException(422, "Description is too long")

    allowed_types = {"fixed", "hourly", "percentage", "quantity"}

    if calculation_type not in allowed_types:
        raise HTTPException(422, "Invalid calculation type")

    with SessionLocal() as db:
        if db.get(ComponentFamily, family_id) is None:
            raise HTTPException(422, "Invalid component family")

        if component_id is None:
            component = ComponentDefinition(
                family_id=family_id,
                code=code,
                name=name,
                description=description,
                calculation_type=calculation_type,
                active=active,
            )
            db.add(component)
            action = "created"
        else:
            component = db.get(ComponentDefinition, component_id)

            if component is None:
                raise HTTPException(404, "Component not found")

            component.family_id = family_id
            component.code = code
            component.name = name
            component.description = description
            component.calculation_type = calculation_type
            component.active = active
            action = "updated"

        try:
            db.flush()

            db.add(ComponentAuditLog(
                component_definition_id=component.id,
                action=action,
                details=f"Component {code} {action}",
            ))

            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Component code already exists")

    return RedirectResponse("/ui/components", status_code=303)
