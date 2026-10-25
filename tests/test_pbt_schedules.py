from datetime import date
from types import SimpleNamespace

from app.pbt.service import (
    add_months,
    first_complete_period_start,
    next_period_start,
    period_end,
)


def rule(frequency, anchor_date=None):
    return SimpleNamespace(
        frequency=frequency,
        anchor_date=anchor_date,
    )


def test_monthly_schedule_starts_with_next_complete_month():
    result = first_complete_period_start(
        rule("monthly"),
        date(2026, 7, 10),
    )
    assert result == date(2026, 8, 1)
    assert period_end(result, "monthly") == date(2026, 8, 31)


def test_monthly_schedule_includes_month_when_starting_on_first():
    result = first_complete_period_start(
        rule("monthly"),
        date(2026, 7, 1),
    )
    assert result == date(2026, 7, 1)


def test_semi_monthly_uses_complete_half_months():
    assert first_complete_period_start(
        rule("semi_monthly"), date(2026, 7, 8)
    ) == date(2026, 7, 16)
    assert period_end(
        date(2026, 7, 16), "semi_monthly"
    ) == date(2026, 7, 31)
    assert next_period_start(
        date(2026, 7, 16), "semi_monthly"
    ) == date(2026, 8, 1)


def test_semi_monthly_handles_leap_year_month_end():
    assert period_end(
        date(2028, 2, 16), "semi_monthly"
    ) == date(2028, 2, 29)


def test_fortnightly_anchor_advances_to_complete_period():
    result = first_complete_period_start(
        rule("fortnightly", date(2026, 7, 6)),
        date(2026, 7, 10),
    )
    assert result == date(2026, 7, 20)
    assert period_end(result, "fortnightly") == date(2026, 8, 2)


def test_add_months_handles_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
