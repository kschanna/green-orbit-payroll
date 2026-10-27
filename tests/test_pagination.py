from app.pagination import build_pagination


def test_pagination_clamps_page_and_builds_filter_preserving_links():
    pagination = build_pagination(
        total=200,
        page=99,
        page_size=25,
        path="/ui/workers",
        params={"search": "Demo Worker", "status": "all"},
    )

    assert pagination.page == 8
    assert pagination.offset == 175
    assert pagination.start == 176
    assert pagination.end == 200
    assert pagination.next_url is None
    assert "search=Demo+Worker" in pagination.previous_url
    assert "status=" not in pagination.previous_url


def test_pagination_rejects_unbounded_page_size():
    pagination = build_pagination(
        total=1000, page=-4, page_size=5000, path="/ui/timesheets"
    )

    assert pagination.page == 1
    assert pagination.page_size == 25
    assert pagination.end == 25


def test_empty_pagination_has_stable_first_page():
    pagination = build_pagination(
        total=0, page=4, page_size=50, path="/ui/invoices"
    )

    assert pagination.page == 1
    assert pagination.total_pages == 1
    assert pagination.start == 0
    assert pagination.end == 0
