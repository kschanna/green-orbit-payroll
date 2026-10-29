from app.employee_tax_router import router as tax_router
from app.employee_tfn_router import router as tfn_router
from app.worker_forms_router import router as worker_forms_router


def test_worker_tax_get_registered():
    assert sum(
        route.path == "/ui/workers/{worker_id}/tax"
        and "GET" in route.methods
        for route in tax_router.routes
    ) == 1


def test_worker_tax_post_registered():
    assert sum(
        route.path == "/ui/workers/{worker_id}/tax"
        and "POST" in route.methods
        for route in tax_router.routes
    ) == 1


def test_worker_tfn_post_registered():
    assert sum(
        route.path == "/ui/workers/{worker_id}/tfn"
        and "POST" in route.methods
        for route in tfn_router.routes
    ) == 1


def test_worker_tfn_requires_admin_and_csrf():
    import inspect
    from app.employee_tfn_router import save_worker_tfn

    source = inspect.getsource(save_worker_tfn)

    assert "require_tfn_admin(request)" in source
    assert "require_csrf(request, csrf_token)" in source


def test_worker_tfn_encrypts_and_audits():
    import inspect
    from app.employee_tfn_router import save_worker_tfn

    source = inspect.getsource(save_worker_tfn)

    assert "encrypt_tfn(digits)" in source
    assert "EmployeeTFNAudit(" in source
    assert "worker_id=worker_id" in source


def test_worker_tax_requires_admin_and_csrf():
    import inspect
    from app.employee_tax_router import save_worker_tax_details

    source = inspect.getsource(save_worker_tax_details)

    assert "require_tfn_admin(request)" in source
    assert "require_csrf(request, csrf_token)" in source


def test_secure_worker_form_review_requires_tfn_admin():
    import inspect
    from app.worker_forms_router import (
        decide_worker_form,
        review_worker_form_page,
    )

    assert sum(
        route.path == "/ui/worker-forms/{submission_id}/review"
        for route in worker_forms_router.routes
    ) == 2
    assert "require_tfn_admin(request)" in inspect.getsource(
        review_worker_form_page
    )
    assert "require_tfn_admin(request)" in inspect.getsource(
        decide_worker_form
    )
