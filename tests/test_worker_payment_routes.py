from app.employee_payment_router import router


def test_worker_payment_get_route_registered():
    matches = [
        route for route in router.routes
        if route.path == "/ui/workers/{worker_id}/payment"
        and "GET" in route.methods
    ]
    assert len(matches) == 1


def test_worker_payment_post_route_registered():
    matches = [
        route for route in router.routes
        if route.path == "/ui/workers/{worker_id}/payment"
        and "POST" in route.methods
    ]
    assert len(matches) == 1


def test_worker_payment_handler_independent_of_employee():
    import inspect
    from app.employee_payment_router import save_worker_payment_details

    source = inspect.getsource(save_worker_payment_details)

    assert "resolve_worker_id" not in source
    assert "resolve_engagement_id" not in source
    assert "db.get(Employee," not in source
