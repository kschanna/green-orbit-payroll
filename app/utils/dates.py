from datetime import date, datetime


def format_date_au(value):
    if value is None:
        return "—"

    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")

    try:
        return date.fromisoformat(str(value)).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(value)