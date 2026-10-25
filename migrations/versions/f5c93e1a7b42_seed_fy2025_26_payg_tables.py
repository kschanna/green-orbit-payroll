"""Seed FY2025-26 resident PAYG withholding tables.

Revision ID: f5c93e1a7b42
Revises: e4b82d0f6a31

The regular Schedule 1 tables effective 1 July 2024 continued unchanged for
payments made in FY2025-26. Rows are generated from the ATO NAT 1004 Scale 1
and Scale 2 coefficients, using the ATO rounding and frequency conversions.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from alembic import op
import sqlalchemy as sa


revision = "f5c93e1a7b42"
down_revision = "e4b82d0f6a31"
branch_labels = None
depends_on = None


EFFECTIVE_FROM = date(2025, 7, 1)
EFFECTIVE_TO = date(2026, 6, 30)

SCALE_1 = (
    (Decimal("150"), Decimal("0.1600"), Decimal("0.1600")),
    (Decimal("371"), Decimal("0.2117"), Decimal("7.7550")),
    (Decimal("515"), Decimal("0.1890"), Decimal("-0.6702")),
    (Decimal("932"), Decimal("0.3227"), Decimal("68.2367")),
    (Decimal("2246"), Decimal("0.3200"), Decimal("65.7202")),
    (Decimal("3303"), Decimal("0.3900"), Decimal("222.9510")),
    (None, Decimal("0.4700"), Decimal("487.2587")),
)

SCALE_2 = (
    (Decimal("361"), Decimal("0"), Decimal("0")),
    (Decimal("500"), Decimal("0.1600"), Decimal("57.8462")),
    (Decimal("625"), Decimal("0.2600"), Decimal("107.8462")),
    (Decimal("721"), Decimal("0.1800"), Decimal("57.8462")),
    (Decimal("865"), Decimal("0.1890"), Decimal("64.3365")),
    (Decimal("1282"), Decimal("0.3227"), Decimal("180.0385")),
    (Decimal("2596"), Decimal("0.3200"), Decimal("176.5769")),
    (Decimal("3653"), Decimal("0.3900"), Decimal("358.3077")),
    (None, Decimal("0.4700"), Decimal("650.6154")),
)


def _round_dollar(value):
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _weekly_withholding(weekly_dollars, claims_threshold):
    x = Decimal(weekly_dollars) + Decimal("0.99")
    coefficients = SCALE_2 if claims_threshold else SCALE_1
    for upper, coefficient, constant in coefficients:
        if upper is None or x < upper:
            return max(
                Decimal("0"),
                _round_dollar((coefficient * x) - constant),
            )
    raise AssertionError("PAYG coefficient range not found")


def _rows():
    configurations = (
        ("weekly", 3400),
        ("fortnightly", 3400),
        ("monthly", 2880),
    )
    for frequency, maximum_weekly_equivalent in configurations:
        for claims_threshold in (False, True):
            for weekly_dollars in range(1, maximum_weekly_equivalent + 1):
                weekly_amount = _weekly_withholding(
                    weekly_dollars, claims_threshold
                )
                if frequency == "weekly":
                    gross_pay = Decimal(weekly_dollars)
                    withholding = weekly_amount
                elif frequency == "fortnightly":
                    gross_pay = Decimal(weekly_dollars * 2)
                    withholding = weekly_amount * 2
                else:
                    gross_pay = (
                        Decimal(weekly_dollars) * Decimal("13")
                        / Decimal("3")
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    withholding = _round_dollar(
                        weekly_amount * Decimal("13") / Decimal("3")
                    )
                yield {
                    "pay_frequency": frequency,
                    "claims_tax_free_threshold": claims_threshold,
                    "gross_pay": gross_pay,
                    "withholding_amount": withholding,
                    "effective_from": EFFECTIVE_FROM,
                    "effective_to": EFFECTIVE_TO,
                }


def upgrade():
    table = sa.table(
        "payg_tax_tables",
        sa.column("pay_frequency", sa.String()),
        sa.column("claims_tax_free_threshold", sa.Boolean()),
        sa.column("gross_pay", sa.Numeric(12, 2)),
        sa.column("withholding_amount", sa.Numeric(12, 2)),
        sa.column("effective_from", sa.Date()),
        sa.column("effective_to", sa.Date()),
    )
    batch = []
    for row in _rows():
        batch.append(row)
        if len(batch) == 1000:
            op.bulk_insert(table, batch)
            batch = []
    if batch:
        op.bulk_insert(table, batch)


def downgrade():
    op.execute(
        sa.text(
            "DELETE FROM payg_tax_tables "
            "WHERE effective_from = :effective_from "
            "AND effective_to = :effective_to"
        ).bindparams(
            effective_from=EFFECTIVE_FROM,
            effective_to=EFFECTIVE_TO,
        )
    )
