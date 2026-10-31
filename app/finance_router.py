import json
from io import BytesIO

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.database import SessionLocal
from app.employee_tfn_router import require_csrf
from app.finance.service import FinancePostingService
from app.models.assignment import Assignment
from app.models.engagement import Engagement
from app.models.finance import ComponentGLMapping, FinancePosting, FinancePostingLine, GLAccount
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily
from app.models.invoice import Invoice
from app.models.organisation import Organisation
from app.models.payment_batch import PaymentBatch
from app.models.pay_run import PayRun
from app.pagination import build_pagination

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_token"] = lambda request: request.session.get("csrf_token", "")


@router.get("/ui/finance/postings", response_class=HTMLResponse)
def finance_postings_page(request: Request, page: int = 1, page_size: int = 25):
    with SessionLocal() as db:
        posted_invoice_ids = select(FinancePosting.source_id).where(
            FinancePosting.source_type == "invoice"
        )
        posted_batch_ids = select(FinancePosting.source_id).where(
            FinancePosting.source_type == "payment_batch"
        )
        invoice_rows = db.execute(
            select(Invoice, Organisation)
            .join(Assignment, Assignment.id == Invoice.engagement_id)
            .join(Engagement, Engagement.id == Assignment.engagement_id)
            .join(Organisation, Organisation.id == Engagement.organisation_id)
            .where(Invoice.status.in_(("issued", "paid")), Invoice.id.not_in(posted_invoice_ids))
            .order_by(Invoice.issue_date.desc(), Invoice.id.desc()).limit(50)
        ).all()
        batch_rows = db.execute(
            select(PaymentBatch, Organisation)
            .join(Organisation, Organisation.id == PaymentBatch.organisation_id)
            .where(PaymentBatch.status == "exported", PaymentBatch.id.not_in(posted_batch_ids))
            .order_by(PaymentBatch.processing_date.desc(), PaymentBatch.id.desc()).limit(50)
        ).all()
        posted_pay_run_ids = select(FinancePosting.source_id).where(
            FinancePosting.source_type == "pay_run"
        )
        pay_run_rows = db.execute(
            select(PayRun, Organisation)
            .join(Organisation, Organisation.id == PayRun.organisation_id)
            .where(PayRun.status == "completed", PayRun.id.not_in(posted_pay_run_ids))
            .order_by(PayRun.payment_date.desc(), PayRun.id.desc()).limit(50)
        ).all()
        total = int(db.scalar(select(func.count(FinancePosting.id))) or 0)
        pagination = build_pagination(total=total, page=page, page_size=page_size,
                                      path="/ui/finance/postings")
        rows = db.execute(
            select(FinancePosting, Organisation)
            .join(Organisation, Organisation.id == FinancePosting.organisation_id)
            .order_by(FinancePosting.id.desc())
            .offset(pagination.offset).limit(pagination.page_size)
        ).all()
        postings = [{"posting": posting, "organisation": organisation}
                    for posting, organisation in rows]
        invoices = [{"invoice": invoice, "organisation": organisation}
                    for invoice, organisation in invoice_rows]
        batches = [{"batch": batch, "organisation": organisation}
                   for batch, organisation in batch_rows]
        pay_runs = [{"pay_run": pay_run, "organisation": organisation}
                    for pay_run, organisation in pay_run_rows]
    return templates.TemplateResponse(request=request, name="finance_postings.html", context={
        "postings": postings, "invoices": invoices, "batches": batches,
        "pay_runs": pay_runs, "pagination": pagination,
    })


@router.post("/ui/finance/postings/invoices/{invoice_id}")
def post_invoice(request: Request, invoice_id: int, csrf_token: str = Form(...)):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        try:
            posting = FinancePostingService.post_invoice(
                db, invoice_id, request.session.get("user_id")
            )
            db.commit()
            posting_id = posting.id
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    return RedirectResponse(f"/ui/finance/postings/{posting_id}", status_code=303)


@router.post("/ui/finance/postings/payment-batches/{batch_id}")
def post_payment_batch(request: Request, batch_id: int, csrf_token: str = Form(...)):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        try:
            posting = FinancePostingService.post_payment_batch(
                db, batch_id, request.session.get("user_id")
            )
            db.commit()
            posting_id = posting.id
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    return RedirectResponse(f"/ui/finance/postings/{posting_id}", status_code=303)


@router.post("/ui/finance/postings/pay-runs/{pay_run_id}")
def post_pay_run(request: Request, pay_run_id: int, csrf_token: str = Form(...)):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        try:
            posting = FinancePostingService.post_pay_run(
                db, pay_run_id, request.session.get("user_id")
            )
            db.commit()
            posting_id = posting.id
        except LookupError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    return RedirectResponse(f"/ui/finance/postings/{posting_id}", status_code=303)


def _posting_data(db, posting_id: int):
    posting = db.get(FinancePosting, posting_id)
    if not posting:
        raise HTTPException(404, "Finance posting not found")
    organisation = db.get(Organisation, posting.organisation_id)
    lines = db.scalars(select(FinancePostingLine).where(
        FinancePostingLine.posting_id == posting.id
    ).order_by(FinancePostingLine.line_number)).all()
    return posting, organisation, lines


@router.get("/ui/finance/postings/{posting_id}", response_class=HTMLResponse)
def finance_posting_detail(request: Request, posting_id: int):
    with SessionLocal() as db:
        posting, organisation, lines = _posting_data(db, posting_id)
    return templates.TemplateResponse(request=request, name="finance_posting_detail.html",
                                      context={"posting": posting, "organisation": organisation,
                                               "lines": lines})


@router.get("/ui/finance/postings/{posting_id}/json")
def download_finance_posting(posting_id: int):
    with SessionLocal() as db:
        posting, organisation, lines = _posting_data(db, posting_id)
        payload = {
            "posting_id": posting.id, "organisation": organisation.name,
            "organisation_abn": organisation.abn,
            "source": {"type": posting.source_type, "id": posting.source_id,
                       "reference": posting.source_reference},
            "posting_date": posting.posting_date.isoformat(),
            "description": posting.description, "currency": "AUD",
            "lines": [{"line_number": line.line_number,
                       "account_code": line.account_code,
                       "account_name": line.account_name,
                       "description": line.description,
                       "debit": f"{line.debit:.2f}", "credit": f"{line.credit:.2f}",
                       "component_code": line.component_code}
                      for line in lines],
            "totals": {"debits": f"{posting.total_debits:.2f}",
                       "credits": f"{posting.total_credits:.2f}",
                       "source": f"{posting.source_total:.2f}"},
            "balanced": posting.balanced, "reconciled": posting.reconciled,
            "checksum": posting.checksum,
        }
        content = json.dumps(payload, indent=2).encode()
    return StreamingResponse(BytesIO(content), media_type="application/json",
                             headers={"Content-Disposition":
                                      f'attachment; filename="finance-posting-{posting_id}.json"'})


@router.get("/ui/finance/chart-of-accounts", response_class=HTMLResponse)
def chart_of_accounts_page(request: Request):
    with SessionLocal() as db:
        FinancePostingService.ensure_chart(db)
        db.commit()
        account_models = db.scalars(select(GLAccount).order_by(GLAccount.code)).all()
        rows = [{"id": account.id, "code": account.code, "name": account.name,
                 "account_type": account.account_type, "role": account.role,
                 "active": account.active} for account in account_models]
    return templates.TemplateResponse(request=request, name="chart_of_accounts.html",
                                      context={"rows": rows})


@router.get("/ui/finance/component-mappings", response_class=HTMLResponse)
def component_mappings_page(request: Request):
    with SessionLocal() as db:
        FinancePostingService.ensure_component_mappings(db)
        db.commit()
        account_models = db.scalars(select(GLAccount).where(
            GLAccount.active.is_(True)
        ).order_by(GLAccount.code)).all()
        mappings = {(m.component_definition_id, m.context): m for m in db.scalars(
            select(ComponentGLMapping)
        ).all()}
        definitions = db.execute(select(ComponentDefinition, ComponentFamily).join(
            ComponentFamily, ComponentFamily.id == ComponentDefinition.family_id
        ).order_by(ComponentFamily.name, ComponentDefinition.name)).all()
        accounts = [{"id": account.id, "code": account.code, "name": account.name}
                    for account in account_models]
        rows = []
        for component, family in definitions:
            payroll = mappings.get((component.id, "payroll"))
            invoice = mappings.get((component.id, "invoice_revenue"))
            rows.append({
                "component": {"id": component.id, "code": component.code,
                              "name": component.name},
                "family": {"name": family.name},
                "payroll": None if not payroll else {
                    "debit_gl_account_id": payroll.debit_gl_account_id,
                    "credit_gl_account_id": payroll.credit_gl_account_id,
                },
                "invoice": None if not invoice else {
                    "credit_gl_account_id": invoice.credit_gl_account_id,
                    "gl_account_id": invoice.gl_account_id,
                },
            })
    return templates.TemplateResponse(request=request, name="component_gl_mappings.html", context={
        "accounts": accounts, "rows": rows,
    })


@router.post("/ui/finance/component-mappings/{component_id}")
def save_component_mapping(
    request: Request, component_id: int,
    payroll_debit_id: int = Form(...), payroll_credit_id: int = Form(...),
    invoice_credit_id: int = Form(...), csrf_token: str = Form(...),
):
    require_csrf(request, csrf_token)
    with SessionLocal() as db:
        if not db.get(ComponentDefinition, component_id):
            raise HTTPException(404, "Component not found")
        valid_ids = set(db.scalars(select(GLAccount.id).where(GLAccount.active.is_(True))).all())
        if not {payroll_debit_id, payroll_credit_id, invoice_credit_id}.issubset(valid_ids):
            raise HTTPException(422, "All selected GL accounts must be active")
        payroll = db.scalar(select(ComponentGLMapping).where(
            ComponentGLMapping.component_definition_id == component_id,
            ComponentGLMapping.context == "payroll"))
        if not payroll:
            payroll = ComponentGLMapping(component_definition_id=component_id, context="payroll")
            db.add(payroll)
        payroll.debit_gl_account_id = payroll_debit_id
        payroll.credit_gl_account_id = payroll_credit_id
        invoice = db.scalar(select(ComponentGLMapping).where(
            ComponentGLMapping.component_definition_id == component_id,
            ComponentGLMapping.context == "invoice_revenue"))
        if not invoice:
            invoice = ComponentGLMapping(component_definition_id=component_id,
                context="invoice_revenue")
            db.add(invoice)
        invoice.credit_gl_account_id = invoice_credit_id
        db.commit()
    return RedirectResponse("/ui/finance/component-mappings", status_code=303)
