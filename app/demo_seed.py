"""Deterministic, transaction-safe synthetic data for demos and AI testing."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.assignment import Assignment
from app.models.assignment_component import AssignmentComponent
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily  # noqa: F401
from app.models.employee_payment_detail import EmployeePaymentDetail
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.engagement import Engagement
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.leave_plan import LeavePlan  # noqa: F401
from app.models.organisation import Organisation
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.pbt_schedule_rule import PBTScheduleRule
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.work_pattern import WorkPattern
from app.models.worker import Worker
from app.pbt.service import PBTScheduleService


FIRST_NAMES = (
    "Alex", "Amelia", "Ari", "Casey", "Charlotte", "Dev", "Eli", "Emily",
    "Harper", "Hayden", "Imogen", "Jamie", "Jordan", "Kai", "Luca",
    "Maya", "Noah", "Priya", "Riley", "Zoe",
)
LAST_NAMES = (
    "Anderson", "Brown", "Campbell", "Chen", "Davis", "Evans", "Garcia",
    "Harris", "Jones", "Kaur", "Lee", "Martin", "Nguyen", "Patel",
    "Robinson", "Singh", "Smith", "Taylor", "Walker", "Wilson",
)
ENGAGEMENT_TYPES = (
    "payg_employee", "payg_employee", "payg_employee", "payg_employee",
    "payg_contractor", "payg_contractor", "payg_contractor",
    "company_contractor", "company_contractor", "payg_employee",
)


@dataclass(frozen=True)
class DemoSeedConfig:
    workers: int = 200
    seed: int = 20261026
    customers: int = 8
    as_of: date = date.today()

    def validate(self) -> None:
        if not 1 <= self.workers <= 200:
            raise ValueError("workers must be between 1 and 200")
        if not 1 <= self.customers <= 20:
            raise ValueError("customers must be between 1 and 20")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")

    @property
    def batch(self) -> str:
        return f"ai-demo-{self.seed}"


def preview(config: DemoSeedConfig) -> dict[str, object]:
    config.validate()
    type_counts = {
        kind: sum(
            1 for index in range(config.workers)
            if ENGAGEMENT_TYPES[index % len(ENGAGEMENT_TYPES)] == kind
        )
        for kind in sorted(set(ENGAGEMENT_TYPES))
    }
    return {
        "batch": config.batch,
        "workers": config.workers,
        "customers": config.customers,
        "engagement_types": type_counts,
        "synthetic_email_domain": "example.invalid",
    }


def _monday_on_or_before(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _abn(seed: int, index: int) -> str:
    # Clearly synthetic identifier; uniqueness, not checksum validity, matters here.
    return f"9{seed % 1_000_000:06d}{index:04d}"


def seed_demo_data(config: DemoSeedConfig) -> dict[str, object]:
    """Create one complete synthetic batch, rolling back on any failure."""
    config.validate()
    plan = preview(config)
    batch_prefix = f"{config.batch}-"
    current_week = _monday_on_or_before(config.as_of)
    recent_week = current_week - timedelta(days=7)
    historical_week = current_week - timedelta(days=14)
    effective_from = current_week - timedelta(weeks=16)

    with SessionLocal.begin() as db:
        existing = db.scalar(select(func.count(Worker.id)).where(
            Worker.email.like(f"{batch_prefix}%@example.invalid")
        ))
        if existing:
            raise ValueError(
                f"Synthetic batch {config.batch!r} already exists; choose a new seed"
            )

        ordinary = db.scalar(select(ComponentDefinition).where(
            ComponentDefinition.code == "ORDINARY_HOURS"
        ))
        if ordinary is None or ordinary.calculation_type != "hourly":
            raise ValueError(
                "ORDINARY_HOURS hourly component must be seeded before demo data"
            )

        employer = Organisation(
            name=f"Green Orbit Demo Employer [{config.batch}]",
            abn=_abn(config.seed, 0),
            country="AU",
        )
        customers = [
            Organisation(
                name=f"Demo Client {index + 1:02d} [{config.batch}]",
                abn=_abn(config.seed, index + 1),
                country="AU",
            )
            for index in range(config.customers)
        ]
        db.add_all([employer, *customers])
        db.flush()

        schedules: list[PBTSchedule] = []
        for index, customer in enumerate(customers):
            schedule = PBTSchedule(
                customer_organisation_id=customer.id,
                name=f"Weekly demo schedule {index + 1:02d} [{config.batch}]",
                effective_from=effective_from,
                status="active",
                generation_months=12,
            )
            db.add(schedule)
            db.flush()
            db.add_all([
                PBTScheduleRule(
                    pbt_schedule_id=schedule.id,
                    schedule_type="timesheet",
                    frequency="weekly",
                    anchor_date=effective_from,
                    offset_days=1,
                    active=True,
                ),
                PBTScheduleRule(
                    pbt_schedule_id=schedule.id,
                    schedule_type="invoice",
                    frequency="fortnightly",
                    anchor_date=effective_from,
                    offset_days=2,
                    invoice_payment_terms_days=14,
                    active=True,
                ),
                PBTScheduleRule(
                    pbt_schedule_id=schedule.id,
                    schedule_type="payment",
                    frequency="fortnightly",
                    anchor_date=effective_from,
                    offset_days=5,
                    active=True,
                ),
            ])
            db.flush()
            PBTScheduleService.generate(db, schedule)
            schedules.append(schedule)
        db.flush()

        period_maps = []
        for schedule in schedules:
            periods = db.scalars(select(PBTSchedulePeriod).where(
                PBTSchedulePeriod.pbt_schedule_id == schedule.id,
                PBTSchedulePeriod.schedule_type == "timesheet",
            )).all()
            period_maps.append({period.period_start: period for period in periods})

        historical_run = PayRun(
            organisation_id=employer.id,
            period_start=historical_week,
            period_end=historical_week + timedelta(days=6),
            payment_date=historical_week + timedelta(days=9),
            status="completed",
        )
        ready_run = PayRun(
            organisation_id=employer.id,
            period_start=recent_week,
            period_end=recent_week + timedelta(days=6),
            payment_date=recent_week + timedelta(days=9),
            status="draft",
        )
        db.add_all([historical_run, ready_run])
        db.flush()

        counts = {
            "workers": 0, "engagements": 0, "assignments": 0,
            "timesheet_headers": 0, "timesheet_entries": 0,
            "invoices": 0, "payslips": 0, "pay_runs": 2,
        }

        for index in range(config.workers):
            number = index + 1
            first_name = FIRST_NAMES[index % len(FIRST_NAMES)]
            last_name = LAST_NAMES[(index * 7 + index // len(FIRST_NAMES)) % len(LAST_NAMES)]
            worker = Worker(
                first_name=first_name,
                last_name=f"{last_name} Demo {number:03d}",
                email=f"{batch_prefix}{number:03d}@example.invalid",
                phone=f"049900{number:04d}",
                active=True,
            )
            db.add(worker)
            db.flush()

            kind = ENGAGEMENT_TYPES[index % len(ENGAGEMENT_TYPES)]
            engagement = Engagement(
                worker_id=worker.id,
                organisation_id=employer.id,
                engagement_type=kind,
                status="active",
                start_date=effective_from,
            )
            db.add(engagement)
            db.flush()

            customer_index = index % len(customers)
            pay_rate = Decimal("30.00") + Decimal(index % 16) * Decimal("1.25")
            billing_rate = _money(pay_rate * Decimal("1.65"))
            assignment = Assignment(
                engagement_id=engagement.id,
                customer_id=customers[customer_index].id,
                host_organisation_id=customers[customer_index].id,
                pbt_schedule_id=schedules[customer_index].id,
                billing_rate=billing_rate,
                start_date=effective_from,
            )
            db.add(assignment)
            db.flush()
            db.add(AssignmentComponent(
                assignment_id=assignment.id,
                component_definition_id=ordinary.id,
                rate=pay_rate,
                pay_rate=pay_rate,
                bill_rate=billing_rate,
                applies_to="both",
                effective_from=effective_from,
            ))

            if kind == "payg_employee":
                db.add(WorkPattern(
                    engagement_id=engagement.id,
                    employment_type="full_time" if index % 3 else "part_time",
                    pay_basis="hourly",
                    hourly_rate=pay_rate,
                    ordinary_hours_per_week=(
                        Decimal("38.00") if index % 3 else Decimal("24.00")
                    ),
                    pay_frequency="weekly",
                    start_date=effective_from,
                ))

            if kind != "company_contractor":
                db.add_all([
                    EmployeeTaxProfile(
                        worker_id=worker.id,
                        engagement_id=engagement.id,
                        residency_status="resident",
                        claims_tax_free_threshold=index % 5 != 0,
                        has_study_loan=False,
                        tfn_declaration_received=True,
                        effective_from=effective_from,
                    ),
                    EmployeeSuperProfile(
                        worker_id=worker.id,
                        engagement_id=engagement.id,
                        fund_name="Synthetic Future Fund",
                        fund_usi="DEMO0000001",
                        member_number=f"DEMO-{config.seed}-{number:03d}",
                        additional_employer_rate=Decimal("0.0000"),
                        effective_from=effective_from,
                    ),
                    EmployeePaymentDetail(
                        worker_id=worker.id,
                        engagement_id=engagement.id,
                        payment_method="bank_transfer",
                        account_name=f"DEMO {first_name} {last_name}"[:32],
                        bsb="000000",
                        account_number=f"{number:09d}",
                        effective_from=effective_from,
                    ),
                ])

            header_entries: dict[date, list[Timesheet]] = {}
            for week_start, status in (
                (historical_week, "approved"),
                (recent_week, "draft" if index % 4 == 0 else "approved"),
            ):
                period = period_maps[customer_index].get(week_start)
                if period is None:
                    raise ValueError(f"Missing generated period for {week_start}")
                header = TimesheetHeader(
                    engagement_id=engagement.id,
                    assignment_id=assignment.id,
                    pbt_schedule_period_id=period.id,
                    period_type="scheduled",
                    period_start=week_start,
                    period_end=week_start + timedelta(days=6),
                    status=status,
                    source="pbt_schedule",
                )
                db.add(header)
                db.flush()
                daily_hours = Decimal("7.60") if kind == "payg_employee" else Decimal("8.00")
                entries = [
                    Timesheet(
                        engagement_id=engagement.id,
                        assignment_id=assignment.id,
                        component_definition_id=ordinary.id,
                        timesheet_header_id=header.id,
                        work_date=week_start + timedelta(days=day),
                        hours_worked=daily_hours if day < 5 else Decimal("0.00"),
                        status=status,
                    )
                    for day in range(7)
                ]
                db.add_all(entries)
                db.flush()
                header_entries[week_start] = entries
                counts["timesheet_headers"] += 1
                counts["timesheet_entries"] += len(entries)

            historical_hours = sum(
                (row.hours_worked for row in header_entries[historical_week]),
                Decimal("0"),
            )
            if kind == "payg_employee":
                historical_hours = Decimal("38.00") if index % 3 else Decimal("24.00")
            gross = _money(historical_hours * pay_rate)
            payg = _money(gross * Decimal("0.20"))
            if kind != "company_contractor":
                payslip = Payslip(
                    engagement_id=engagement.id,
                    pay_run_id=historical_run.id,
                    gross_pay=gross,
                    payg_withholding=payg,
                    net_pay=gross - payg,
                    superannuation=_money(gross * Decimal("0.12")),
                )
                db.add(payslip)
                db.flush()
                if kind == "payg_contractor":
                    db.add_all([
                        PayslipTimesheet(
                            payslip_id=payslip.id, timesheet_id=row.id
                        )
                        for row in header_entries[historical_week]
                    ])
                counts["payslips"] += 1

            if index % 5 == 1:
                invoice_rows = header_entries[historical_week]
                subtotal = _money(sum(
                    (row.hours_worked * billing_rate for row in invoice_rows),
                    Decimal("0"),
                ))
                gst = _money(subtotal * Decimal("0.10"))
                invoice = Invoice(
                    engagement_id=assignment.id,
                    invoice_number=f"DEMO-{config.seed}-{number:04d}",
                    issue_date=historical_week + timedelta(days=9),
                    due_date=historical_week + timedelta(days=23),
                    subtotal=subtotal,
                    gst=gst,
                    total=subtotal + gst,
                    status=("paid" if index % 10 == 1 else "sent"),
                )
                db.add(invoice)
                db.flush()
                db.add_all([
                    InvoiceTimesheet(invoice_id=invoice.id, timesheet_id=row.id)
                    for row in invoice_rows
                ])
                counts["invoices"] += 1

            counts["workers"] += 1
            counts["engagements"] += 1
            counts["assignments"] += 1

        plan["created"] = counts
        plan["ready_pay_run_id"] = ready_run.id
        plan["historical_pay_run_id"] = historical_run.id
        return plan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create deterministic synthetic Green Orbit demo data."
    )
    parser.add_argument("--workers", type=int, default=200)
    parser.add_argument("--customers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Write the previewed synthetic batch to the configured database.",
    )
    args = parser.parse_args()
    config = DemoSeedConfig(
        workers=args.workers, customers=args.customers, seed=args.seed
    )
    result = seed_demo_data(config) if args.confirm else preview(config)
    mode = "CREATED" if args.confirm else "DRY RUN"
    print(f"{mode}: {result}")
    if not args.confirm:
        print("Re-run with --confirm to write this batch.")


if __name__ == "__main__":
    main()
