from decimal import Decimal, ROUND_HALF_UP


def calculate_invoice(hours: Decimal, hourly_rate: Decimal) -> dict:
    subtotal = (hours * hourly_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    gst = (subtotal * Decimal("0.10")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    total = subtotal + gst

    return {
        "hours": hours,
        "hourly_rate": hourly_rate,
        "subtotal": subtotal,
        "gst": gst,
        "total": total,
    }