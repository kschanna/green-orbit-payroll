from app.workers_router import router


def test_worker_delete_route_registered():
    routes = [
        route for route in router.routes
        if route.path == "/api/workers/{worker_id}"
    ]

    assert any("DELETE" in route.methods for route in routes)
