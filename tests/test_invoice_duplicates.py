from datetime import date

import pytest

from app.invoicing.engine import generate_invoice


def test_duplicate_invoice_prevention():

    with pytest.raises(
        ValueError,
        match="No approved, uninvoiced timesheets found"
    ):
        generate_invoice(
            engagement_id=1,
            start_date=date(2026, 10, 14),
            end_date=date(2026, 10, 15),
        )