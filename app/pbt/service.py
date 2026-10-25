from calendar import monthrange
from datetime import date, timedelta

from sqlalchemy import select

from app.models.pbt_schedule_period import PBTSchedulePeriod


FREQUENCIES = {"weekly", "fortnightly", "monthly", "semi_monthly"}
SCHEDULE_TYPES = {"timesheet", "invoice", "payment"}


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def first_complete_period_start(rule, effective_from: date) -> date:
    if rule.frequency in {"weekly", "fortnightly"}:
        if rule.anchor_date is None:
            raise ValueError("Weekly and fortnightly rules require an anchor date")
        period_days = 7 if rule.frequency == "weekly" else 14
        if rule.anchor_date >= effective_from:
            return rule.anchor_date
        elapsed = (effective_from - rule.anchor_date).days
        periods = (elapsed + period_days - 1) // period_days
        return rule.anchor_date + timedelta(days=periods * period_days)

    if rule.frequency == "monthly":
        if effective_from.day == 1:
            return effective_from
        next_month = add_months(effective_from.replace(day=1), 1)
        return next_month

    if rule.frequency == "semi_monthly":
        if effective_from.day == 1:
            return effective_from
        if effective_from.day <= 16:
            return effective_from.replace(day=16)
        return add_months(effective_from.replace(day=1), 1)

    raise ValueError("Unsupported PBT frequency")


def period_end(period_start: date, frequency: str) -> date:
    if frequency == "weekly":
        return period_start + timedelta(days=6)
    if frequency == "fortnightly":
        return period_start + timedelta(days=13)
    if frequency == "monthly":
        return period_start.replace(
            day=monthrange(period_start.year, period_start.month)[1]
        )
    if frequency == "semi_monthly":
        if period_start.day == 1:
            return period_start.replace(day=15)
        return period_start.replace(
            day=monthrange(period_start.year, period_start.month)[1]
        )
    raise ValueError("Unsupported PBT frequency")


def next_period_start(period_start: date, frequency: str) -> date:
    if frequency == "weekly":
        return period_start + timedelta(days=7)
    if frequency == "fortnightly":
        return period_start + timedelta(days=14)
    if frequency == "monthly":
        return add_months(period_start, 1).replace(day=1)
    if frequency == "semi_monthly":
        if period_start.day == 1:
            return period_start.replace(day=16)
        return add_months(period_start.replace(day=1), 1)
    raise ValueError("Unsupported PBT frequency")


class PBTScheduleService:
    @staticmethod
    def generate(db, schedule) -> int:
        horizon = add_months(
            schedule.effective_from,
            schedule.generation_months,
        )
        generated = 0
        last_period_end = schedule.generated_through

        for rule in schedule.rules:
            if not rule.active:
                continue
            start = first_complete_period_start(
                rule,
                schedule.effective_from,
            )

            while start < horizon:
                end = period_end(start, rule.frequency)
                if schedule.effective_to and end > schedule.effective_to:
                    break

                existing = db.scalar(
                    select(PBTSchedulePeriod.id).where(
                        PBTSchedulePeriod.rule_id == rule.id,
                        PBTSchedulePeriod.period_start == start,
                        PBTSchedulePeriod.period_end == end,
                    )
                )
                if existing is None:
                    event_date = end + timedelta(days=rule.offset_days)
                    terms = (
                        rule.invoice_payment_terms_days
                        if rule.schedule_type == "invoice" else None
                    )
                    db.add(PBTSchedulePeriod(
                        pbt_schedule_id=schedule.id,
                        rule_id=rule.id,
                        schedule_type=rule.schedule_type,
                        period_start=start,
                        period_end=end,
                        event_date=event_date,
                        payment_terms_days=terms,
                        customer_payment_due_date=(
                            event_date + timedelta(days=terms)
                            if terms is not None else None
                        ),
                        status="planned",
                    ))
                    generated += 1

                if last_period_end is None or end > last_period_end:
                    last_period_end = end
                start = next_period_start(start, rule.frequency)

        schedule.generated_through = last_period_end
        return generated
