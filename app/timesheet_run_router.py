from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.component_definition import ComponentDefinition
from app.models.engagement import Engagement
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.organisation import Organisation
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.worker import Worker


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["date_au"] = (
    lambda value: value.strftime("%d/%m/%Y") if value else "—"
)
templates.env.globals["csrf_token"] = (
    lambda request: request.session.get("csrf_token", "")
)


class TimesheetRunSelection(BaseModel):
    assignment_id: int
    pbt_schedule_period_id: int


class TimesheetRunCreate(BaseModel):
    selections: list[TimesheetRunSelection] = Field(min_length=1)


class ScheduledTimesheetEntry(BaseModel):
    work_date: date
    component_definition_id: int | None = None
    hours_worked: Decimal = Field(ge=0, le=24, max_digits=6, decimal_places=2)


class ScheduledTimesheetUpdate(BaseModel):
    entries: list[ScheduledTimesheetEntry]


def _expected_period(db, assignment_id: int, period_id: int):
    row = db.execute(
        select(Assignment, PBTSchedulePeriod)
        .join(
            PBTSchedulePeriod,
            PBTSchedulePeriod.pbt_schedule_id == Assignment.pbt_schedule_id,
        )
        .where(
            Assignment.id == assignment_id,
            PBTSchedulePeriod.id == period_id,
            PBTSchedulePeriod.schedule_type == "timesheet",
        )
    ).first()
    if row is None:
        raise HTTPException(
            422,
            "The selected period is not a timesheet period for this assignment",
        )
    return row


def _create_scheduled_timesheet(db, assignment, period):
    existing = db.scalar(
        select(TimesheetHeader).where(
            TimesheetHeader.assignment_id == assignment.id,
            TimesheetHeader.pbt_schedule_period_id == period.id,
        )
    )
    if existing is not None:
        return existing, False

    header = TimesheetHeader(
        engagement_id=assignment.engagement_id,
        assignment_id=assignment.id,
        pbt_schedule_period_id=period.id,
        employee_id=None,
        period_type="scheduled",
        period_start=period.period_start,
        period_end=period.period_end,
        status="draft",
        source="pbt_schedule",
    )
    db.add(header)
    db.flush()

    day_count = (period.period_end - period.period_start).days + 1
    db.add_all([
        Timesheet(
            engagement_id=assignment.engagement_id,
            employee_id=None,
            assignment_id=assignment.id,
            timesheet_header_id=header.id,
            work_date=period.period_start + timedelta(days=offset),
            hours_worked=Decimal("0.00"),
            status="draft",
        )
        for offset in range(day_count)
    ])
    return header, True


@router.get("/ui/timesheet-runs", response_class=HTMLResponse)
def timesheet_run_page(
    request: Request,
    customer_id: int | None = None,
    status: str | None = None,
):
    today = date.today()
    with SessionLocal() as db:
        statement = (
            select(
                Assignment,
                PBTSchedulePeriod,
                PBTSchedule,
                Engagement,
                Worker,
                Organisation,
            )
            .join(PBTSchedule, PBTSchedule.id == Assignment.pbt_schedule_id)
            .join(
                PBTSchedulePeriod,
                PBTSchedulePeriod.pbt_schedule_id == PBTSchedule.id,
            )
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Worker, Worker.id == Engagement.worker_id)
            .join(Organisation, Organisation.id == Assignment.customer_id)
            .where(
                PBTSchedulePeriod.schedule_type == "timesheet",
                PBTSchedule.status == "active",
            )
        )
        if customer_id is not None:
            statement = statement.where(Assignment.customer_id == customer_id)

        expected = db.execute(
            statement.order_by(
                PBTSchedulePeriod.event_date,
                Worker.last_name,
                Worker.first_name,
                Assignment.id,
            )
        ).all()
        header_map = {
            (header.assignment_id, header.pbt_schedule_period_id): header
            for header in db.scalars(
                select(TimesheetHeader).where(
                    TimesheetHeader.pbt_schedule_period_id.is_not(None)
                )
            ).all()
        }
        invoiced_header_ids = set(db.scalars(
            select(Timesheet.timesheet_header_id)
            .join(
                InvoiceTimesheet,
                InvoiceTimesheet.timesheet_id == Timesheet.id,
            )
            .where(Timesheet.timesheet_header_id.is_not(None))
            .distinct()
        ).all())

        rows = []
        counts = {
            "expected": len(expected), "missing": 0, "draft": 0,
            "overdue": 0, "completed": 0,
        }
        for assignment, period, schedule, engagement, worker, customer in expected:
            header = header_map.get((assignment.id, period.id))
            if header is not None:
                row_status = header.status
                if header.status == "draft":
                    counts["draft"] += 1
                elif header.status in {"submitted", "approved", "completed"}:
                    counts["completed"] += 1
            elif period.event_date < today:
                row_status = "overdue"
                counts["missing"] += 1
                counts["overdue"] += 1
            elif period.event_date == today:
                row_status = "due_today"
                counts["missing"] += 1
            else:
                row_status = "upcoming"
                counts["missing"] += 1

            if status and status != "all":
                if status == "missing" and header is not None:
                    continue
                if status != "missing" and row_status != status:
                    continue

            rows.append({
                "assignment_id": assignment.id,
                "period_id": period.id,
                "event_date": period.event_date,
                "period_start": period.period_start,
                "period_end": period.period_end,
                "worker_name": f"{worker.first_name} {worker.last_name}",
                "customer_name": customer.name,
                "schedule_name": schedule.name,
                "status": row_status,
                "header_id": header.id if header else None,
                "is_invoiced": (
                    header is not None and header.id in invoiced_header_ids
                ),
            })

        customers = db.scalars(
            select(Organisation)
            .join(Assignment, Assignment.customer_id == Organisation.id)
            .where(Assignment.pbt_schedule_id.is_not(None))
            .distinct()
            .order_by(Organisation.name)
        ).all()

    return templates.TemplateResponse(
        request=request,
        name="timesheet_run.html",
        context={
            "rows": rows,
            "counts": counts,
            "customers": customers,
            "selected_customer_id": customer_id,
            "selected_status": status or "all",
        },
    )


@router.post("/api/timesheet-runs", status_code=201)
def create_timesheet_run(data: TimesheetRunCreate):
    created = []
    skipped = []
    with SessionLocal() as db:
        try:
            for selection in data.selections:
                assignment, period = _expected_period(
                    db,
                    selection.assignment_id,
                    selection.pbt_schedule_period_id,
                )
                header, was_created = _create_scheduled_timesheet(
                    db, assignment, period
                )
                target = created if was_created else skipped
                target.append({
                    "assignment_id": assignment.id,
                    "period_id": period.id,
                    "timesheet_header_id": header.id,
                })
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                409,
                "One of these timesheets was created by another request; refresh and try again",
            )
    return {"created": created, "skipped": skipped}


@router.get(
    "/ui/timesheets/scheduled/{header_id}/preview",
    response_class=HTMLResponse,
)
def preview_scheduled_timesheet(request: Request, header_id: int):
    with SessionLocal() as db:
        header = db.get(TimesheetHeader, header_id)
        if header is None or header.source != "pbt_schedule":
            raise HTTPException(404, "Scheduled timesheet not found")
        engagement = db.get(Engagement, header.engagement_id)
        worker = db.get(Worker, engagement.worker_id)
        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header.id)
            .order_by(Timesheet.work_date, Timesheet.id)
        ).all()
        definitions = {
            definition.id: definition
            for definition in db.scalars(select(ComponentDefinition)).all()
        }
        ordinary = next(
            (item for item in definitions.values()
             if item.code == "ORDINARY_HOURS"),
            None,
        )
        component_totals = {}
        entry_data = []
        for entry in entries:
            definition = (
                definitions.get(entry.component_definition_id)
                if entry.component_definition_id is not None else ordinary
            )
            name = definition.name if definition else "Ordinary Hours"
            entry_data.append({
                "work_date": entry.work_date,
                "component": name,
                "hours_worked": entry.hours_worked,
            })
            component_totals[name] = (
                component_totals.get(name, Decimal("0.00"))
                + entry.hours_worked
            )
        context = {
            "timesheet_id": header.id,
            "worker_name": f"{worker.first_name} {worker.last_name}",
            "period_type": "scheduled",
            "period_start": header.period_start,
            "period_end": header.period_end,
            "status": header.status,
            "entries": entry_data,
            "component_totals": component_totals,
            "total_hours": sum(
                (entry.hours_worked for entry in entries), Decimal("0.00")
            ),
        }
    return templates.TemplateResponse(
        request=request, name="timesheet_preview.html", context=context
    )


@router.get(
    "/ui/timesheets/scheduled/{header_id}/edit",
    response_class=HTMLResponse,
)
def edit_scheduled_timesheet(request: Request, header_id: int):
    with SessionLocal() as db:
        header = db.get(TimesheetHeader, header_id)
        if header is None or header.source != "pbt_schedule":
            raise HTTPException(404, "Scheduled timesheet not found")
        assignment = db.get(Assignment, header.assignment_id)
        engagement = db.get(Engagement, header.engagement_id)
        worker = db.get(Worker, engagement.worker_id)
        customer = db.get(Organisation, assignment.customer_id)
        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header.id)
            .order_by(Timesheet.work_date, Timesheet.id)
        ).all()
        data = {
            "header": header,
            "assignment": assignment,
            "worker_name": f"{worker.first_name} {worker.last_name}",
            "customer_name": customer.name,
            "entries": entries,
        }
    return templates.TemplateResponse(
        request=request,
        name="timesheet_scheduled_edit.html",
        context=data,
    )


@router.patch("/api/timesheets/scheduled/{header_id}")
def update_scheduled_timesheet(header_id: int, data: ScheduledTimesheetUpdate):
    with SessionLocal() as db:
        header = db.get(TimesheetHeader, header_id)
        if header is None or header.source != "pbt_schedule":
            raise HTTPException(404, "Scheduled timesheet not found")
        if header.status != "draft":
            raise HTTPException(409, "Only draft timesheets can be edited")

        expected_dates = {
            header.period_start + timedelta(days=offset)
            for offset in range((header.period_end - header.period_start).days + 1)
        }
        submitted_dates = {entry.work_date for entry in data.entries}
        if submitted_dates != expected_dates:
            raise HTTPException(422, "Entries must cover the complete PBT period")
        for work_date in expected_dates:
            total = sum(
                entry.hours_worked
                for entry in data.entries
                if entry.work_date == work_date
            )
            if total > Decimal("24"):
                raise HTTPException(422, f"Total hours for {work_date} cannot exceed 24")

        # Import here to avoid coupling this router to the legacy route module.
        from app.main import validate_timesheet_component

        for entry in data.entries:
            validate_timesheet_component(
                db,
                header.assignment_id,
                entry.component_definition_id,
                entry.work_date,
            )

        old_entries = db.scalars(
            select(Timesheet).where(Timesheet.timesheet_header_id == header.id)
        ).all()
        for entry in old_entries:
            db.delete(entry)
        db.flush()
        db.add_all([
            Timesheet(
                engagement_id=header.engagement_id,
                employee_id=None,
                assignment_id=header.assignment_id,
                timesheet_header_id=header.id,
                component_definition_id=entry.component_definition_id,
                leave_plan_id=validate_timesheet_component(
                    db,
                    header.assignment_id,
                    entry.component_definition_id,
                    entry.work_date,
                ),
                work_date=entry.work_date,
                hours_worked=entry.hours_worked,
                status="draft",
            )
            for entry in data.entries
        ])
        db.commit()
    return {"message": "Scheduled timesheet updated", "timesheet_header_id": header_id}


@router.post("/api/timesheets/scheduled/{header_id}/approve")
def approve_scheduled_timesheet(header_id: int):
    from app.leave.service import LeaveService

    with SessionLocal() as db:
        header = db.get(TimesheetHeader, header_id)
        if header is None or header.source != "pbt_schedule":
            raise HTTPException(404, "Scheduled timesheet not found")
        if header.status != "draft":
            raise HTTPException(409, "Only draft timesheets can be approved")
        entries = db.scalars(
            select(Timesheet)
            .where(Timesheet.timesheet_header_id == header.id)
            .order_by(Timesheet.work_date, Timesheet.id)
        ).all()
        expected_dates = {
            header.period_start + timedelta(days=offset)
            for offset in range((header.period_end - header.period_start).days + 1)
        }
        if {entry.work_date for entry in entries} != expected_dates:
            raise HTTPException(409, "Timesheet must cover the complete PBT period")
        if any(entry.status != "draft" for entry in entries):
            raise HTTPException(409, "All timesheet entries must be draft")
        try:
            LeaveService.validate_timesheets(db, header.engagement_id, entries)
        except ValueError as error:
            raise HTTPException(422, str(error))

        header.status = "approved"
        for entry in entries:
            entry.status = "approved"
        db.commit()
        return {
            "timesheet_header_id": header.id,
            "status": "approved",
            "lines_approved": len(entries),
            "total_hours": sum(
                (entry.hours_worked for entry in entries), Decimal("0.00")
            ),
        }
