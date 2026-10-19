
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from sqlalchemy import select
from app.models.engagement import Engagement
from app.database import SessionLocal
from app.worker_service import WorkerError, WorkerService


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


def worker_data(worker):
    return {
        "id": worker.id,
        "first_name": worker.first_name,
        "last_name": worker.last_name,
        "email": worker.email,
        "phone": worker.phone,
        "active": worker.active,
    }


@router.get("/ui/workers", response_class=HTMLResponse)
def workers_page(request: Request, search: str = ""):
    with SessionLocal() as db:
        workers = [
            worker_data(w)
            for w in WorkerService.list(db, search)
        ]

    return templates.TemplateResponse(
        request=request,
        name="workers.html",
        context={
            "workers": workers,
            "search": search,
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
