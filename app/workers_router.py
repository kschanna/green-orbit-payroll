
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from sqlalchemy import select
from app.models.engagement import Engagement
from app.database import SessionLocal
from app.worker_service import WorkerError, WorkerService
from app.pagination import build_pagination


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)


class WorkerInput(BaseModel):
    first_name: str = Field(max_length=100)
    last_name: str = Field(max_length=100)
    email: str = Field(max_length=200)
    phone: str | None = Field(default=None, max_length=30)


ENGAGEMENT_TYPE_LABELS = {
    "payg_employee": "PAYG Employee",
    "payg_contractor": "PAYG Contractor",
    "company_contractor": "Company Contractor",
}
ENGAGEMENT_TYPE_BADGE_CLASSES = {
    "payg_employee": "badge-engagement-employee",
    "payg_contractor": "badge-engagement-payg-contractor",
    "company_contractor": "badge-engagement-company-contractor",
}
ENGAGEMENT_TYPE_ORDER = tuple(ENGAGEMENT_TYPE_LABELS)


def engagement_type_data(engagements):
    statuses_by_type = defaultdict(set)
    for engagement in engagements:
        statuses_by_type[engagement.engagement_type].add(engagement.status)

    types = []
    for engagement_type in sorted(
        statuses_by_type,
        key=lambda value: (
            ENGAGEMENT_TYPE_ORDER.index(value)
            if value in ENGAGEMENT_TYPE_ORDER else len(ENGAGEMENT_TYPE_ORDER),
            value,
        ),
    ):
        statuses = statuses_by_type[engagement_type]
        status = (
            "active" if "active" in statuses
            else "draft" if "draft" in statuses
            else "ended"
        )
        types.append({
            "type": engagement_type,
            "label": ENGAGEMENT_TYPE_LABELS.get(
                engagement_type, engagement_type.replace("_", " ").title()
            ),
            "badge_class": ENGAGEMENT_TYPE_BADGE_CLASSES.get(
                engagement_type, "bg-secondary"
            ),
            "status": status,
        })
    return types


def worker_data(worker, engagement_types=None):
    data = {
        "id": worker.id,
        "first_name": worker.first_name,
        "last_name": worker.last_name,
        "email": worker.email,
        "phone": worker.phone,
        "active": worker.active,
    }
    if engagement_types is not None:
        data["engagement_types"] = engagement_types
    return data


@router.get("/ui/workers", response_class=HTMLResponse)
def workers_page(
    request: Request, search: str = "", active_status: str = "all",
    tax_free: str = "all", engagement_type: str = "all",
    page: int = 1, page_size: int = 25,
):
    with SessionLocal() as db:
        pagination = build_pagination(
            total=WorkerService.count(
                db, search, active_status, tax_free, engagement_type
            ),
            page=page, page_size=page_size, path="/ui/workers",
            params={
                "search": search,
                "active_status": active_status,
                "tax_free": tax_free,
                "engagement_type": engagement_type,
            },
        )
        worker_rows = WorkerService.list(
            db, search, pagination.offset, pagination.page_size,
            active_status, tax_free, engagement_type,
        )
        engagements_by_worker = defaultdict(list)
        worker_ids = [worker.id for worker in worker_rows]
        if worker_ids:
            for engagement in db.scalars(
                select(Engagement)
                .where(Engagement.worker_id.in_(worker_ids))
                .order_by(Engagement.worker_id, Engagement.id)
            ).all():
                engagements_by_worker[engagement.worker_id].append(engagement)
        workers = [
            worker_data(
                worker,
                engagement_type_data(engagements_by_worker[worker.id]),
            )
            for worker in worker_rows
        ]

    return templates.TemplateResponse(
        request=request,
        name="workers.html",
        context={
            "workers": workers,
            "search": search,
            "active_status": active_status,
            "tax_free": tax_free,
            "engagement_type": engagement_type,
            "pagination": pagination,
        },
    )


@router.get("/ui/workers/new", response_class=HTMLResponse)
def new_worker_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="worker_form.html",
        context={"worker": None},
    )


@router.get("/ui/workers/{worker_id}/edit", response_class=HTMLResponse)
def edit_worker_page(request: Request, worker_id: int):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        data = worker_data(worker)

    return templates.TemplateResponse(
        request=request,
        name="worker_form.html",
        context={"worker": data},
    )


@router.get("/ui/workers/{worker_id}", response_class=HTMLResponse)
def worker_detail_page(request: Request, worker_id: int):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        data = worker_data(worker)

        engagements = db.scalars(
            select(Engagement)
            .where(Engagement.worker_id == worker_id)
            .order_by(Engagement.id)
        ).all()

        engagement_data = [
            {
                "id": engagement.id,
                "organisation": engagement.organisation.name,
                "type": engagement.engagement_type,
                "status": engagement.status,
                "start_date": engagement.start_date,
                "end_date": engagement.end_date,
            }
            for engagement in engagements
        ]

    return templates.TemplateResponse(
        request=request,
        name="worker_detail.html",
        context={
            "worker": data,
            "engagements": engagement_data,
        },
    )


@router.get("/api/workers")
def list_workers(search: str = ""):
    with SessionLocal() as db:
        return [
            worker_data(w)
            for w in WorkerService.list(db, search)
        ]


@router.post("/api/workers", status_code=201)
def create_worker(data: WorkerInput):
    with SessionLocal() as db:
        try:
            worker = WorkerService.create(
                db, **data.model_dump()
            )
        except WorkerError as exc:
            raise HTTPException(409, str(exc)) from exc

        return worker_data(worker)


@router.get("/api/workers/{worker_id}")
def get_worker(worker_id: int):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        return worker_data(worker)


@router.patch("/api/workers/{worker_id}")
def update_worker(worker_id: int, data: WorkerInput):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        try:
            worker = WorkerService.update(
                db, worker, **data.model_dump()
            )
        except WorkerError as exc:
            raise HTTPException(409, str(exc)) from exc

        return worker_data(worker)


@router.delete("/api/workers/{worker_id}")
def delete_worker(worker_id: int):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        try:
            WorkerService.delete(db, worker)
        except WorkerError as exc:
            raise HTTPException(409, str(exc)) from exc

        return {"deleted": True, "id": worker_id}


@router.post("/api/workers/{worker_id}/deactivate")
def deactivate_worker(worker_id: int):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        return worker_data(
            WorkerService.set_active(db, worker, False)
        )


@router.post("/api/workers/{worker_id}/reactivate")
def reactivate_worker(worker_id: int):
    with SessionLocal() as db:
        worker = WorkerService.get(db, worker_id)

        if worker is None:
            raise HTTPException(404, "Worker not found")

        return worker_data(
            WorkerService.set_active(db, worker, True)
        )
