from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.ai.provider import AITool
from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.engagement import Engagement
from app.models.invoice import Invoice
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.timesheet import Timesheet  # noqa: F401
from app.models.timesheet_header import TimesheetHeader
from app.models.worker import Worker
from app.ai.payroll_readiness import (
    find_timesheet_issues,
    find_worker_data_issues,
    readiness_summary,
)


MAX_TOOL_RESULTS = 50


def _with_sources(
    execute, source_type: str, id_field: str, url_prefix: str, *, append_id: bool = True
):
    """Attach safe application links without exposing them to business queries."""
    def wrapped(args: dict[str, Any]) -> dict[str, Any]:
        result = execute(args)
        candidates = result.get("items", [])
        if not candidates and isinstance(result.get("item"), dict):
            candidates = [result["item"]]
        if not candidates and isinstance(result.get(source_type), dict):
            candidates = [result[source_type]]
        sources = []
        for item in candidates:
            record_id = item.get(id_field) if isinstance(item, dict) else None
            if record_id is None:
                continue
            sources.append({
                "type": source_type,
                "id": record_id,
                "label": f"{source_type.replace('_', ' ').title()} #{record_id}",
                "url": f"{url_prefix}{record_id}" if append_id else url_prefix,
            })
        if sources:
            result["_sources"] = sources
        return result
    return wrapped


def _iso(value):
    return value.isoformat() if value is not None else None


def _money(value) -> str:
    return f"{Decimal(value or 0):.2f}"


def _parse_date(value: Any, name: str) -> date | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def _limit(args: dict[str, Any]) -> int:
    value = args.get("limit", 20)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    return max(1, min(value, MAX_TOOL_RESULTS))


def _worker_name_filter(term: str):
    return func.concat(Worker.first_name, " ", Worker.last_name).ilike(
        f"%{term.strip()}%"
    )


def _date_range(args: dict[str, Any]) -> tuple[date, date]:
    end = _parse_date(args.get("date_to"), "date_to") or date.today()
    start = _parse_date(args.get("date_from"), "date_from") or (end - timedelta(days=90))
    if start > end:
        raise ValueError("date_from cannot be after date_to")
    if (end - start).days > 366:
        raise ValueError("Date range cannot exceed 366 days")
    return start, end


def get_payroll_readiness(args: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic pre-payroll checks; the model only explains the result."""
    as_of = _parse_date(args.get("as_of"), "as_of") or date.today()
    start = _parse_date(args.get("date_from"), "date_from") or (as_of - timedelta(days=14))
    end = _parse_date(args.get("date_to"), "date_to") or as_of
    if start > end:
        raise ValueError("date_from cannot be after date_to")
    if (end - start).days > 93:
        raise ValueError("Readiness date range cannot exceed 93 days")
    with SessionLocal() as db:
        issues = find_timesheet_issues(db, start=start, end=end, as_of=as_of)
        issues.extend(find_worker_data_issues(db, as_of=as_of))
    result = readiness_summary(issues)
    result.update({
        "as_of": as_of.isoformat(),
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "_sources": [
            {
                "type": "worker",
                "id": issue["worker_id"],
                "label": issue.get("worker", f"Worker #{issue['worker_id']}"),
                "url": f"/ui/workers/{issue['worker_id']}",
            }
            for issue in issues if issue.get("worker_id") is not None
        ],
    })
    return result


def _monthly_series(rows, date_index: int, value_indexes: tuple[int, ...]):
    values: dict[str, list[Decimal]] = {}
    for row in rows:
        label = row[date_index].strftime("%Y-%m")
        bucket = values.setdefault(label, [Decimal("0") for _ in value_indexes])
        for position, row_index in enumerate(value_indexes):
            bucket[position] += Decimal(row[row_index] or 0)
    return values


def get_outstanding_timesheets(args: dict[str, Any]) -> dict[str, Any]:
    start = _parse_date(args.get("date_from"), "date_from")
    end = _parse_date(args.get("date_to"), "date_to") or date.today()
    if start and start > end:
        raise ValueError("date_from cannot be after date_to")
    limit = _limit(args)

    with SessionLocal() as db:
        statement = (
            select(
                Assignment,
                PBTSchedulePeriod,
                Worker,
                Organisation,
                TimesheetHeader,
            )
            .join(PBTSchedule, PBTSchedule.id == Assignment.pbt_schedule_id)
            .join(
                PBTSchedulePeriod,
                PBTSchedulePeriod.pbt_schedule_id == PBTSchedule.id,
            )
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Worker, Worker.id == Engagement.worker_id)
            .join(Organisation, Organisation.id == Assignment.customer_id)
            .outerjoin(
                TimesheetHeader,
                and_(
                    TimesheetHeader.assignment_id == Assignment.id,
                    TimesheetHeader.pbt_schedule_period_id == PBTSchedulePeriod.id,
                ),
            )
            .where(
                PBTSchedule.status == "active",
                PBTSchedulePeriod.schedule_type == "timesheet",
                PBTSchedulePeriod.event_date <= end,
                or_(
                    TimesheetHeader.id.is_(None),
                    TimesheetHeader.status == "draft",
                ),
            )
        )
        if start:
            statement = statement.where(PBTSchedulePeriod.event_date >= start)
        worker_name = args.get("worker_name")
        if worker_name:
            if not isinstance(worker_name, str):
                raise ValueError("worker_name must be text")
            statement = statement.where(_worker_name_filter(worker_name))

        rows = db.execute(
            statement.order_by(
                PBTSchedulePeriod.event_date,
                Worker.last_name,
                Worker.first_name,
            ).limit(limit + 1)
        ).all()

    items = []
    for assignment, period, worker, customer, header in rows[:limit]:
        if header is not None:
            status = header.status
        elif period.event_date < date.today():
            status = "overdue"
        elif period.event_date == date.today():
            status = "due_today"
        else:
            status = "missing"
        items.append({
            "timesheet_header_id": header.id if header else None,
            "assignment_id": assignment.id,
            "period_id": period.id,
            "worker": f"{worker.first_name} {worker.last_name}",
            "customer": customer.name,
            "period_start": _iso(period.period_start),
            "period_end": _iso(period.period_end),
            "due_date": _iso(period.event_date),
            "status": status,
        })
    return {"items": items, "count": len(items), "truncated": len(rows) > limit}


def get_timesheet_status(args: dict[str, Any]) -> dict[str, Any]:
    header_id = args.get("timesheet_header_id")
    worker_name = args.get("worker_name")
    if header_id is None and not worker_name:
        raise ValueError("timesheet_header_id or worker_name is required")
    if header_id is not None and (isinstance(header_id, bool) or not isinstance(header_id, int)):
        raise ValueError("timesheet_header_id must be an integer")
    limit = _limit(args)

    with SessionLocal() as db:
        statement = (
            select(TimesheetHeader, Assignment, Engagement, Worker, Organisation)
            .join(Assignment, Assignment.id == TimesheetHeader.assignment_id)
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Worker, Worker.id == Engagement.worker_id)
            .join(Organisation, Organisation.id == Assignment.customer_id)
        )
        if header_id is not None:
            statement = statement.where(TimesheetHeader.id == header_id)
        if worker_name:
            if not isinstance(worker_name, str):
                raise ValueError("worker_name must be text")
            statement = statement.where(_worker_name_filter(worker_name))
        rows = db.execute(
            statement.order_by(TimesheetHeader.period_start.desc()).limit(limit + 1)
        ).all()

    items = [{
        "timesheet_header_id": header.id,
        "assignment_id": assignment.id,
        "engagement_id": engagement.id,
        "worker": f"{worker.first_name} {worker.last_name}",
        "customer": customer.name,
        "period_type": header.period_type,
        "period_start": _iso(header.period_start),
        "period_end": _iso(header.period_end),
        "status": header.status,
    } for header, assignment, engagement, worker, customer in rows[:limit]]
    return {"items": items, "count": len(items), "truncated": len(rows) > limit}


def get_engagement_details(args: dict[str, Any]) -> dict[str, Any]:
    engagement_id = args.get("engagement_id")
    worker_name = args.get("worker_name")
    if engagement_id is None and not worker_name:
        raise ValueError("engagement_id or worker_name is required")
    if engagement_id is not None and (
        isinstance(engagement_id, bool) or not isinstance(engagement_id, int)
    ):
        raise ValueError("engagement_id must be an integer")
    limit = _limit(args)

    with SessionLocal() as db:
        statement = (
            select(Engagement, Worker, Organisation)
            .join(Worker, Worker.id == Engagement.worker_id)
            .join(Organisation, Organisation.id == Engagement.organisation_id)
        )
        if engagement_id is not None:
            statement = statement.where(Engagement.id == engagement_id)
        if worker_name:
            if not isinstance(worker_name, str):
                raise ValueError("worker_name must be text")
            statement = statement.where(_worker_name_filter(worker_name))
        rows = db.execute(
            statement.order_by(Worker.last_name, Worker.first_name).limit(limit + 1)
        ).all()

        items = []
        for engagement, worker, organisation in rows[:limit]:
            assignments = db.execute(
                select(Assignment, Organisation)
                .join(Organisation, Organisation.id == Assignment.customer_id)
                .where(Assignment.engagement_id == engagement.id)
                .order_by(Assignment.id)
            ).all()
            items.append({
                "engagement_id": engagement.id,
                "worker": f"{worker.first_name} {worker.last_name}",
                "organisation": organisation.name,
                "engagement_type": engagement.engagement_type,
                "status": engagement.status,
                "start_date": _iso(engagement.start_date),
                "end_date": _iso(engagement.end_date),
                "assignments": [{
                    "assignment_id": assignment.id,
                    "customer": customer.name,
                    "start_date": _iso(assignment.start_date),
                    "end_date": _iso(assignment.end_date),
                } for assignment, customer in assignments],
            })
    return {"items": items, "count": len(items), "truncated": len(rows) > limit}


def get_assignment_details(args: dict[str, Any]) -> dict[str, Any]:
    assignment_id = args.get("assignment_id")
    if isinstance(assignment_id, bool) or not isinstance(assignment_id, int):
        raise ValueError("assignment_id is required and must be an integer")

    employer = aliased(Organisation)
    customer = aliased(Organisation)
    host = aliased(Organisation)
    with SessionLocal() as db:
        row = db.execute(
            select(
                Assignment,
                Engagement,
                Worker,
                employer,
                customer,
                host,
            )
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Worker, Worker.id == Engagement.worker_id)
            .join(employer, employer.id == Engagement.organisation_id)
            .join(customer, customer.id == Assignment.customer_id)
            .outerjoin(host, host.id == Assignment.host_organisation_id)
            .where(Assignment.id == assignment_id)
        ).first()

    if row is None:
        return {"item": None, "found": False}

    assignment, engagement, worker, employer_org, customer_org, host_org = row
    return {
        "found": True,
        "item": {
            "assignment_id": assignment.id,
            "engagement_id": engagement.id,
            "worker": f"{worker.first_name} {worker.last_name}",
            "employer": employer_org.name,
            "customer": customer_org.name,
            "host_organisation": host_org.name if host_org else None,
            "engagement_type": engagement.engagement_type,
            "engagement_status": engagement.status,
            "engagement_start_date": _iso(engagement.start_date),
            "engagement_end_date": _iso(engagement.end_date),
            "assignment_start_date": _iso(assignment.start_date),
            "assignment_end_date": _iso(assignment.end_date),
            "billing_rate": _money(assignment.billing_rate),
            "pbt_schedule_id": assignment.pbt_schedule_id,
        },
    }


def get_worker_business_summary(args: dict[str, Any]) -> dict[str, Any]:
    worker_id = args.get("worker_id")
    worker_name = args.get("worker_name")
    if worker_id is None and not worker_name:
        raise ValueError("worker_id or worker_name is required")
    if worker_id is not None and (
        isinstance(worker_id, bool) or not isinstance(worker_id, int)
    ):
        raise ValueError("worker_id must be an integer")
    start, end = _date_range(args)

    with SessionLocal() as db:
        worker_statement = select(Worker)
        if worker_id is not None:
            worker_statement = worker_statement.where(Worker.id == worker_id)
        else:
            worker_statement = worker_statement.where(_worker_name_filter(worker_name))
        workers = db.scalars(worker_statement.order_by(Worker.id).limit(6)).all()
        if not workers:
            return {"found": False, "candidates": []}
        if len(workers) != 1:
            return {
                "found": False,
                "ambiguous": True,
                "candidates": [
                    {"worker_id": worker.id, "worker": f"{worker.first_name} {worker.last_name}"}
                    for worker in workers
                ],
            }
        worker = workers[0]

        engagement_ids = select(Engagement.id).where(Engagement.worker_id == worker.id)
        assignment_ids = select(Assignment.id).where(
            Assignment.engagement_id.in_(engagement_ids)
        )

        timesheet_rows = db.execute(
            select(
                Timesheet.status,
                func.count(Timesheet.id),
                func.coalesce(func.sum(Timesheet.hours_worked), 0),
            )
            .where(
                Timesheet.engagement_id.in_(engagement_ids),
                Timesheet.work_date.between(start, end),
            )
            .group_by(Timesheet.status)
        ).all()
        payroll_rows = db.execute(
            select(
                PayRun.payment_date,
                Payslip.gross_pay,
                Payslip.payg_withholding,
                Payslip.superannuation,
                Payslip.net_pay,
            )
            .join(PayRun, PayRun.id == Payslip.pay_run_id)
            .where(
                Payslip.engagement_id.in_(engagement_ids),
                PayRun.payment_date.between(start, end),
            )
        ).all()
        invoice_rows = db.execute(
            select(
                Invoice.issue_date,
                Invoice.subtotal,
                Invoice.gst,
                Invoice.total,
                Invoice.status,
            ).where(
                Invoice.engagement_id.in_(assignment_ids),
                Invoice.issue_date.between(start, end),
            )
        ).all()

    timesheets = {
        status: {"entries": count, "hours": _money(hours)}
        for status, count, hours in timesheet_rows
    }
    payroll = {
        "payslip_count": len(payroll_rows),
        "gross_pay": _money(sum((row[1] for row in payroll_rows), Decimal("0"))),
        "payg_withholding": _money(sum((row[2] for row in payroll_rows), Decimal("0"))),
        "superannuation": _money(sum((row[3] for row in payroll_rows), Decimal("0"))),
        "net_pay": _money(sum((row[4] for row in payroll_rows), Decimal("0"))),
    }
    invoicing = {
        "invoice_count": len(invoice_rows),
        "subtotal": _money(sum((row[1] for row in invoice_rows), Decimal("0"))),
        "gst": _money(sum((row[2] for row in invoice_rows), Decimal("0"))),
        "total": _money(sum((row[3] for row in invoice_rows), Decimal("0"))),
        "status_counts": {
            status: sum(1 for row in invoice_rows if row[4] == status)
            for status in sorted({row[4] for row in invoice_rows})
        },
    }
    payroll_months = _monthly_series(payroll_rows, 0, (1, 4))
    invoice_months = _monthly_series(invoice_rows, 0, (3,))
    month_labels = sorted(set(payroll_months) | set(invoice_months))

    charts = [{
        "type": "bar",
        "title": f"{worker.first_name} {worker.last_name} — financial totals",
        "labels": ["Gross pay", "Net pay", "Super", "Invoiced incl. GST"],
        "datasets": [{
            "label": "AUD",
            "values": [
                float(payroll["gross_pay"]),
                float(payroll["net_pay"]),
                float(payroll["superannuation"]),
                float(invoicing["total"]),
            ],
        }],
        "value_format": "currency",
    }]
    if month_labels:
        charts.append({
            "type": "line",
            "title": f"{worker.first_name} {worker.last_name} — monthly activity",
            "labels": month_labels,
            "datasets": [
                {
                    "label": "Gross pay",
                    "values": [float(payroll_months.get(month, [0, 0])[0]) for month in month_labels],
                },
                {
                    "label": "Invoiced incl. GST",
                    "values": [float(invoice_months.get(month, [0])[0]) for month in month_labels],
                },
            ],
            "value_format": "currency",
        })
    return {
        "found": True,
        "worker": {"worker_id": worker.id, "name": f"{worker.first_name} {worker.last_name}"},
        "date_from": _iso(start),
        "date_to": _iso(end),
        "timesheets": timesheets,
        "payroll": payroll,
        "invoicing": invoicing,
        "_charts": charts,
    }


def get_assignment_business_summary(args: dict[str, Any]) -> dict[str, Any]:
    assignment_id = args.get("assignment_id")
    if isinstance(assignment_id, bool) or not isinstance(assignment_id, int):
        raise ValueError("assignment_id is required and must be an integer")
    start, end = _date_range(args)

    with SessionLocal() as db:
        row = db.execute(
            select(Assignment, Engagement, Worker, Organisation)
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Worker, Worker.id == Engagement.worker_id)
            .join(Organisation, Organisation.id == Assignment.customer_id)
            .where(Assignment.id == assignment_id)
        ).first()
        if row is None:
            return {"found": False, "assignment_id": assignment_id}
        assignment, engagement, worker, customer = row

        timesheet_rows = db.execute(
            select(
                Timesheet.status,
                func.count(Timesheet.id),
                func.coalesce(func.sum(Timesheet.hours_worked), 0),
            )
            .where(
                Timesheet.assignment_id == assignment.id,
                Timesheet.work_date.between(start, end),
            )
            .group_by(Timesheet.status)
        ).all()
        invoice_rows = db.execute(
            select(
                Invoice.issue_date,
                Invoice.subtotal,
                Invoice.gst,
                Invoice.total,
                Invoice.status,
            ).where(
                Invoice.engagement_id == assignment.id,
                Invoice.issue_date.between(start, end),
            )
        ).all()
        linked_payslip_ids = (
            select(PayslipTimesheet.payslip_id)
            .join(Timesheet, Timesheet.id == PayslipTimesheet.timesheet_id)
            .where(Timesheet.assignment_id == assignment.id)
            .distinct()
        )
        payroll_rows = db.execute(
            select(
                PayRun.payment_date,
                Payslip.gross_pay,
                Payslip.payg_withholding,
                Payslip.superannuation,
                Payslip.net_pay,
            )
            .join(PayRun, PayRun.id == Payslip.pay_run_id)
            .where(
                Payslip.id.in_(linked_payslip_ids),
                PayRun.payment_date.between(start, end),
            )
        ).all()

    timesheets = {
        status: {"entries": count, "hours": _money(hours)}
        for status, count, hours in timesheet_rows
    }
    payroll = {
        "linked_payslip_count": len(payroll_rows),
        "gross_pay": _money(sum((row[1] for row in payroll_rows), Decimal("0"))),
        "payg_withholding": _money(sum((row[2] for row in payroll_rows), Decimal("0"))),
        "superannuation": _money(sum((row[3] for row in payroll_rows), Decimal("0"))),
        "net_pay": _money(sum((row[4] for row in payroll_rows), Decimal("0"))),
        "caveat": "A linked payslip may include work from more than one assignment.",
    }
    invoicing = {
        "invoice_count": len(invoice_rows),
        "subtotal": _money(sum((row[1] for row in invoice_rows), Decimal("0"))),
        "gst": _money(sum((row[2] for row in invoice_rows), Decimal("0"))),
        "total": _money(sum((row[3] for row in invoice_rows), Decimal("0"))),
        "status_counts": {
            status: sum(1 for row in invoice_rows if row[4] == status)
            for status in sorted({row[4] for row in invoice_rows})
        },
    }
    status_labels = sorted(timesheets)
    charts = [{
        "type": "bar",
        "title": f"Assignment #{assignment.id} — timesheet hours by status",
        "labels": status_labels,
        "datasets": [{
            "label": "Hours",
            "values": [float(timesheets[status]["hours"]) for status in status_labels],
        }],
        "value_format": "number",
    }, {
        "type": "bar",
        "title": f"Assignment #{assignment.id} — financial totals",
        "labels": ["Linked gross pay", "Linked net pay", "Super", "Invoiced incl. GST"],
        "datasets": [{
            "label": "AUD",
            "values": [
                float(payroll["gross_pay"]),
                float(payroll["net_pay"]),
                float(payroll["superannuation"]),
                float(invoicing["total"]),
            ],
        }],
        "value_format": "currency",
    }]
    return {
        "found": True,
        "assignment": {
            "assignment_id": assignment.id,
            "engagement_id": engagement.id,
            "worker": f"{worker.first_name} {worker.last_name}",
            "customer": customer.name,
        },
        "date_from": _iso(start),
        "date_to": _iso(end),
        "timesheets": timesheets,
        "payroll": payroll,
        "invoicing": invoicing,
        "_charts": charts,
    }


def get_payroll_summary(args: dict[str, Any]) -> dict[str, Any]:
    end = _parse_date(args.get("date_to"), "date_to") or date.today()
    start = _parse_date(args.get("date_from"), "date_from") or (end - timedelta(days=90))
    if start > end:
        raise ValueError("date_from cannot be after date_to")
    if (end - start).days > 366:
        raise ValueError("Payroll summary range cannot exceed 366 days")
    limit = _limit(args)

    with SessionLocal() as db:
        rows = db.execute(
            select(
                PayRun,
                Organisation,
                func.count(Payslip.id),
                func.coalesce(func.sum(Payslip.gross_pay), 0),
                func.coalesce(func.sum(Payslip.payg_withholding), 0),
                func.coalesce(func.sum(Payslip.superannuation), 0),
                func.coalesce(func.sum(Payslip.net_pay), 0),
            )
            .join(Organisation, Organisation.id == PayRun.organisation_id)
            .outerjoin(Payslip, Payslip.pay_run_id == PayRun.id)
            .where(PayRun.payment_date.between(start, end))
            .group_by(PayRun.id, Organisation.id)
            .order_by(PayRun.payment_date.desc(), PayRun.id.desc())
            .limit(limit + 1)
        ).all()

    items = [{
        "pay_run_id": run.id,
        "organisation": organisation.name,
        "period_start": _iso(run.period_start),
        "period_end": _iso(run.period_end),
        "payment_date": _iso(run.payment_date),
        "status": run.status,
        "payslip_count": payslip_count,
        "gross_pay": _money(gross),
        "payg_withholding": _money(payg),
        "superannuation": _money(superannuation),
        "net_pay": _money(net),
    } for run, organisation, payslip_count, gross, payg, superannuation, net in rows[:limit]]

    totals = {
        "gross_pay": _money(sum(Decimal(item["gross_pay"]) for item in items)),
        "payg_withholding": _money(sum(Decimal(item["payg_withholding"]) for item in items)),
        "superannuation": _money(sum(Decimal(item["superannuation"]) for item in items)),
        "net_pay": _money(sum(Decimal(item["net_pay"]) for item in items)),
    }
    return {
        "date_from": _iso(start),
        "date_to": _iso(end),
        "items": items,
        "totals": totals,
        "count": len(items),
        "truncated": len(rows) > limit,
    }


def read_only_tools() -> tuple[AITool, ...]:
    common_limit = {
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    }
    return (
        AITool(
            name="get_payroll_readiness",
            description=(
                "Run a payroll readiness audit for missing, incomplete, duplicate, "
                "or unapproved timesheets and workers missing tax, super, bank, "
                "engagement, pay-rate, or required document data."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "as_of": {"type": "string", "format": "date"},
                    "date_from": {"type": "string", "format": "date"},
                    "date_to": {"type": "string", "format": "date"},
                },
            },
            execute=get_payroll_readiness,
        ),
        AITool(
            name="get_outstanding_timesheets",
            description="List missing, overdue, due-today, or draft scheduled timesheets.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "format": "date"},
                    "date_to": {"type": "string", "format": "date"},
                    "worker_name": {"type": "string"},
                    **common_limit,
                },
            },
            execute=_with_sources(get_outstanding_timesheets, "timesheet", "timesheet_header_id", "/ui/timesheets/weekly/", append_id=True),
        ),
        AITool(
            name="get_timesheet_status",
            description="Get scheduled timesheet statuses by header ID or worker name.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "timesheet_header_id": {"type": "integer"},
                    "worker_name": {"type": "string"},
                    **common_limit,
                },
            },
            execute=_with_sources(get_timesheet_status, "timesheet", "timesheet_header_id", "/ui/timesheets/weekly/", append_id=True),
        ),
        AITool(
            name="get_engagement_details",
            description="Get engagement and assignment details by engagement ID or worker name.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "engagement_id": {"type": "integer"},
                    "worker_name": {"type": "string"},
                    **common_limit,
                },
            },
            execute=_with_sources(get_engagement_details, "engagement", "engagement_id", "/ui/engagements", append_id=False),
        ),
        AITool(
            name="get_assignment_details",
            description="Get one assignment and its engagement details by assignment ID.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "assignment_id": {"type": "integer"},
                },
                "required": ["assignment_id"],
            },
            execute=_with_sources(get_assignment_details, "assignment", "assignment_id", "/ui/engagements", append_id=False),
        ),
        AITool(
            name="get_worker_business_summary",
            description=(
                "Get read-only timesheet, payroll, and invoicing totals and "
                "chart data for one worker over a date range."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "worker_id": {"type": "integer"},
                    "worker_name": {"type": "string"},
                    "date_from": {"type": "string", "format": "date"},
                    "date_to": {"type": "string", "format": "date"},
                },
            },
            execute=_with_sources(get_worker_business_summary, "worker", "worker_id", "/ui/workers/"),
        ),
        AITool(
            name="get_assignment_business_summary",
            description=(
                "Get read-only timesheet, linked payroll, and invoicing totals "
                "and chart data for one assignment over a date range."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "assignment_id": {"type": "integer"},
                    "date_from": {"type": "string", "format": "date"},
                    "date_to": {"type": "string", "format": "date"},
                },
                "required": ["assignment_id"],
            },
            execute=_with_sources(get_assignment_business_summary, "assignment", "assignment_id", "/ui/engagements", append_id=False),
        ),
        AITool(
            name="get_payroll_summary",
            description="Summarize pay runs and payslip totals for a payment-date range.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "format": "date"},
                    "date_to": {"type": "string", "format": "date"},
                    **common_limit,
                },
            },
            execute=_with_sources(get_payroll_summary, "pay_run", "pay_run_id", "/ui/pay-runs/"),
        ),
    )
