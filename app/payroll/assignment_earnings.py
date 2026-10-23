from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily
from app.models.leave_plan import LeavePlan


class AssignmentEarningsCalculator:
    """Calculate ordinary earnings from assignment-linked timesheets."""

    def calculate(self, session, engagement, timesheets):
        earnings = defaultdict(
            lambda: {
                "quantity": Decimal("0"),
                "amount": Decimal("0"),
            }
        )

        for timesheet in timesheets:
            if timesheet.status != "approved":
                raise ValueError(
                    f"Timesheet {timesheet.id} is not approved"
                )

            if timesheet.engagement_id != engagement.id:
                raise ValueError(
                    f"Timesheet {timesheet.id} belongs to another engagement"
                )

            if timesheet.assignment_id is None:
                raise ValueError(
                    f"Timesheet {timesheet.id} has no assignment"
                )

            assignment = session.get(
                Assignment,
                timesheet.assignment_id
            )

            if assignment is None:
                raise ValueError(
                    f"Assignment {timesheet.assignment_id} not found"
                )

            if assignment.engagement_id != engagement.id:
                raise ValueError(
                    f"Assignment {assignment.id} belongs to another engagement"
                )

            definition = (
                session.get(
                    ComponentDefinition,
                    timesheet.component_definition_id,
                )
                if timesheet.component_definition_id is not None
                else session.scalar(
                    select(ComponentDefinition).where(
                        ComponentDefinition.code == "ORDINARY_HOURS"
                    )
                )
            )

            if definition is None:
                raise ValueError(
                    "Timesheet component definition not found"
                )

            family = session.get(ComponentFamily, definition.family_id)
            if family is None or family.code not in ("EARNINGS", "LEAVE"):
                raise ValueError("Unsupported Timesheet component family")
            if definition.calculation_type != "hourly":
                raise ValueError(
                    f"Payroll treatment for {definition.name} "
                    "is not supported"
                )

            if family.code == "LEAVE":
                if timesheet.leave_plan_id is None:
                    raise ValueError(
                        f"Timesheet {timesheet.id} has no Leave Plan"
                    )
                plan = session.get(LeavePlan, timesheet.leave_plan_id)
                if (
                    plan is None
                    or plan.engagement_id != engagement.id
                    or plan.component_definition_id != definition.id
                    or plan.status != "active"
                    or plan.effective_from > timesheet.work_date
                    or (
                        plan.effective_to is not None
                        and plan.effective_to < timesheet.work_date
                    )
                ):
                    raise ValueError("Invalid or ineffective Leave Plan")
                rate = plan.paid_leave_rate
                if rate is None or rate <= 0:
                    raise ValueError(
                        f"Invalid paid leave rate for {definition.name}"
                    )
                components = []
            else:
                components = session.scalars(
                select(AssignmentComponent).where(
                    AssignmentComponent.assignment_id == assignment.id,
                    AssignmentComponent.component_definition_id == definition.id,
                    AssignmentComponent.applies_to.in_(
                        ("payroll", "both")
                    ),
                    AssignmentComponent.effective_from <= timesheet.work_date,
                    (
                        AssignmentComponent.effective_to.is_(None)
                        | (
                            AssignmentComponent.effective_to
                            >= timesheet.work_date
                        )
                    )
                )
                ).all()

            if family.code != "LEAVE" and len(components) != 1:
                raise ValueError(
                    f"Expected exactly one {definition.name} pay rate "
                    f"for assignment {assignment.id} on "
                    f"{timesheet.work_date}; found {len(components)}"
                )

            if family.code != "LEAVE":
                component = components[0]
                rate = (
                    component.pay_rate
                    if component.pay_rate is not None
                    else component.rate
                )

            if rate is None or rate < 0:
                raise ValueError(
                    f"Invalid pay rate for assignment {assignment.id}"
                )

            quantity = Decimal(timesheet.hours_worked)
            amount = (quantity * rate).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            key = (
                assignment.id,
                definition.id,
                rate,
            )

            earnings[key]["quantity"] += quantity
            earnings[key]["amount"] += amount

        lines = []

        for (assignment_id, definition_id, rate), values in earnings.items():
            lines.append({
                "assignment_id": assignment_id,
                "component_definition_id": definition_id,
                "quantity": values["quantity"],
                "rate": rate,
                "amount": values["amount"],
            })

        gross_pay = sum(
            (line["amount"] for line in lines),
            Decimal("0.00")
        )

        return {
            "gross_pay": gross_pay,
            "lines": lines,
        }
