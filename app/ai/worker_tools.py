"""Read-only AI tools scoped to the authenticated worker portal account."""

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.ai.provider import AITool
from app.database import SessionLocal
from app.leave.service import LeaveService
from app.models.assignment import Assignment
from app.models.component_definition import ComponentDefinition
from app.models.engagement import Engagement
from app.models.leave_plan import LeavePlan
from app.models.notification import Notification
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.worker_document import WorkerDocument


def _money(value: Decimal) -> str:
    return f"{Decimal(value):.2f}"


def _limit(args: dict[str, Any], maximum: int = 25) -> int:
    value = args.get("limit", 10)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return value


def _source(kind: str, record_id: int, label: str, url: str) -> dict[str, Any]:
    return {"type": kind, "id": record_id, "label": label, "url": url}


def worker_read_only_tools(worker_id: int, user_id: int) -> tuple[AITool, ...]:
    """Return tools whose scope is captured server-side and cannot be overridden."""

    engagement_ids = select(Engagement.id).where(Engagement.worker_id == worker_id)

    def get_my_timesheets(args: dict[str, Any]) -> dict[str, Any]:
        limit = _limit(args)
        with SessionLocal() as db:
            rows = db.execute(
                select(TimesheetHeader, func.coalesce(func.sum(Timesheet.hours_worked), 0))
                .outerjoin(Timesheet, Timesheet.timesheet_header_id == TimesheetHeader.id)
                .where(TimesheetHeader.engagement_id.in_(engagement_ids))
                .group_by(TimesheetHeader.id)
                .order_by(TimesheetHeader.period_end.desc())
                .limit(limit)
            ).all()
        items = [
            {
                "id": header.id,
                "period_start": header.period_start.isoformat(),
                "period_end": header.period_end.isoformat(),
                "status": header.status,
                "hours": _money(hours),
            }
            for header, hours in rows
        ]
        return {
            "items": items,
            "count": len(items),
            "_sources": [
                _source("timesheet", item["id"], f"Timesheet #{item['id']}", "/portal/timesheets")
                for item in items
            ],
        }

    def get_my_payslips(args: dict[str, Any]) -> dict[str, Any]:
        limit = _limit(args)
        with SessionLocal() as db:
            rows = db.execute(
                select(Payslip, PayRun, Organisation)
                .join(PayRun, PayRun.id == Payslip.pay_run_id)
                .join(Organisation, Organisation.id == PayRun.organisation_id)
                .where(Payslip.engagement_id.in_(engagement_ids))
                .order_by(PayRun.payment_date.desc())
                .limit(limit)
            ).all()
        items = [
            {
                "id": payslip.id,
                "payment_date": pay_run.payment_date.isoformat(),
                "period_start": pay_run.period_start.isoformat(),
                "period_end": pay_run.period_end.isoformat(),
                "organisation": organisation.name,
                "gross_pay": _money(payslip.gross_pay),
                "payg_withholding": _money(payslip.payg_withholding),
                "superannuation": _money(payslip.superannuation),
                "net_pay": _money(payslip.net_pay),
            }
            for payslip, pay_run, organisation in rows
        ]
        return {
            "items": items,
            "count": len(items),
            "_sources": [
                _source("payslip", item["id"], f"Payslip #{item['id']}", "/portal/payslips")
                for item in items
            ],
        }

    def get_my_leave_balances(args: dict[str, Any]) -> dict[str, Any]:
        if args:
            raise ValueError("This tool takes no arguments")
        with SessionLocal() as db:
            rows = db.execute(
                select(LeavePlan, ComponentDefinition)
                .join(ComponentDefinition, ComponentDefinition.id == LeavePlan.component_definition_id)
                .where(LeavePlan.worker_id == worker_id, LeavePlan.status == "active")
                .order_by(ComponentDefinition.name)
            ).all()
            items = [
                {
                    "plan_id": plan.id,
                    "name": definition.name,
                    "balance_hours": _money(LeaveService.balance(db, plan.id)),
                    "annual_entitlement_hours": _money(plan.annual_entitlement_hours),
                }
                for plan, definition in rows
            ]
        return {
            "items": items,
            "count": len(items),
            "_sources": [
                _source("leave_plan", item["plan_id"], item["name"], "/portal/leave")
                for item in items
            ],
        }

    def get_my_assignments(args: dict[str, Any]) -> dict[str, Any]:
        limit = _limit(args)
        with SessionLocal() as db:
            rows = db.execute(
                select(Assignment, Engagement, Organisation)
                .join(Engagement, Engagement.id == Assignment.engagement_id)
                .join(Organisation, Organisation.id == Assignment.customer_id)
                .where(Engagement.worker_id == worker_id)
                .order_by(Assignment.start_date.desc())
                .limit(limit)
            ).all()
        items = [
            {
                "assignment_id": assignment.id,
                "customer": organisation.name,
                "engagement_type": engagement.engagement_type,
                "engagement_status": engagement.status,
                "start_date": assignment.start_date.isoformat() if assignment.start_date else None,
                "end_date": assignment.end_date.isoformat() if assignment.end_date else None,
            }
            for assignment, engagement, organisation in rows
        ]
        return {
            "items": items,
            "count": len(items),
            "_sources": [
                _source("assignment", item["assignment_id"], f"Assignment #{item['assignment_id']}", "/portal/assignments")
                for item in items
            ],
        }

    def get_my_documents(args: dict[str, Any]) -> dict[str, Any]:
        limit = _limit(args)
        with SessionLocal() as db:
            rows = db.scalars(
                select(WorkerDocument)
                .where(WorkerDocument.worker_id == worker_id)
                .order_by(WorkerDocument.created_at.desc())
                .limit(limit)
            ).all()
        items = [
            {
                "id": row.id,
                "document_type": row.document_type,
                "filename": row.original_filename,
                "status": row.status,
                "issued_on": row.issued_on.isoformat() if row.issued_on else None,
                "expires_on": row.expires_on.isoformat() if row.expires_on else None,
            }
            for row in rows
        ]
        return {
            "items": items,
            "count": len(items),
            "_sources": [
                _source("document", item["id"], item["filename"], "/portal/documents")
                for item in items
            ],
        }

    def get_my_notifications(args: dict[str, Any]) -> dict[str, Any]:
        limit = _limit(args)
        unread_only = args.get("unread_only", False)
        if not isinstance(unread_only, bool):
            raise ValueError("unread_only must be true or false")
        with SessionLocal() as db:
            query = select(Notification).where(Notification.recipient_user_id == user_id)
            if unread_only:
                query = query.where(Notification.read_at.is_(None))
            rows = db.scalars(query.order_by(Notification.created_at.desc()).limit(limit)).all()
        items = [
            {
                "id": row.id,
                "title": row.title,
                "message": row.message,
                "is_read": row.read_at is not None,
                "created_at": row.created_at.isoformat(),
                "action_url": row.action_url,
            }
            for row in rows
        ]
        return {
            "items": items,
            "count": len(items),
            "_sources": [
                _source("notification", item["id"], item["title"], item["action_url"] or "/portal/notifications")
                for item in items
            ],
        }

    limited_schema = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}},
    }
    return (
        AITool("get_my_timesheets", "List only the signed-in worker's recent timesheets and hours.", limited_schema, get_my_timesheets),
        AITool("get_my_payslips", "List only the signed-in worker's recent payslips and verified pay figures.", limited_schema, get_my_payslips),
        AITool("get_my_leave_balances", "Get only the signed-in worker's current leave balances.", {"type": "object", "properties": {}}, get_my_leave_balances),
        AITool("get_my_assignments", "List only the signed-in worker's assignments.", limited_schema, get_my_assignments),
        AITool("get_my_documents", "List only the signed-in worker's document status and expiry dates.", limited_schema, get_my_documents),
        AITool(
            "get_my_notifications",
            "List only the signed-in worker's notifications.",
            {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}, "unread_only": {"type": "boolean"}}},
            get_my_notifications,
        ),
    )
