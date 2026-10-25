from pathlib import Path


MAIN_FILE = Path("app/main.py")
LIST_TEMPLATE = Path("app/templates/timesheet_list.html")
PREVIEW_TEMPLATE = Path("app/templates/timesheet_preview.html")


def test_weekly_preview_route_exists():
    source = MAIN_FILE.read_text()

    assert '/ui/timesheets/weekly/{header_id}/preview' in source
    assert 'def preview_weekly_timesheet(' in source


def test_daily_preview_route_exists():
    source = MAIN_FILE.read_text()

    assert '/ui/timesheets/daily/{timesheet_id}/preview' in source
    assert 'def preview_daily_timesheet(' in source


def test_preview_template_exists():
    assert PREVIEW_TEMPLATE.exists()

    source = PREVIEW_TEMPLATE.read_text()

    assert "Timesheet Preview" in source
    assert "worker_name" in source
    assert "total_hours" in source
    assert "entries" in source


def test_preview_links_in_timesheet_listing():
    source = LIST_TEMPLATE.read_text()

    assert (
        '/ui/timesheets/{{ timesheet.period_type }}/'
        '{{ timesheet.id }}/preview'
    ) in source
    assert '/ui/timesheets/daily/{{ timesheet.id }}/preview' in source


def test_preview_is_read_only():
    source = PREVIEW_TEMPLATE.read_text()

    assert "<form" not in source
    assert 'type="submit"' not in source
