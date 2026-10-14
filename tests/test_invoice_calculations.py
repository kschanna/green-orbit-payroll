from decimal import Decimal

from app.invoicing.calculations import calculate_invoice


def test_invoice_calculation():
    result = calculate_invoice(
        Decimal("7.00"),
        Decimal("150.00")
    )

    assert result["subtotal"] == Decimal("1050.00")
    assert result["gst"] == Decimal("105.00")
    assert result["total"] == Decimal("1155.00")


def test_invoice_rounding():
    result = calculate_invoice(
        Decimal("1.00"),
        Decimal("99.95")
    )

    assert result["subtotal"] == Decimal("99.95")
    assert result["gst"] == Decimal("10.00")
    assert result["total"] == Decimal("109.95")


def test_zero_hours():
    result = calculate_invoice(
        Decimal("0"),
        Decimal("150.00")
    )

    assert result["total"] == Decimal("0.00")