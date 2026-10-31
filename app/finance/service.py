import hashlib
import json
from decimal import Decimal

from sqlalchemy import select

from app.models.assignment import Assignment
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily
from app.models.engagement import Engagement
from app.models.finance import (
    ComponentGLMapping, FinancePosting, FinancePostingLine, GLAccount,
)
from app.models.invoice import Invoice
from app.models.invoice_component import InvoiceComponent
from app.models.payment_batch import PaymentBatch
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.payroll_component import PayrollComponent


MONEY = Decimal("0.01")
STANDARD_ACCOUNTS = (
    ("1000", "Operating Bank Account", "asset", "bank"),
    ("1100", "Accounts Receivable", "asset", "accounts_receivable"),
    ("1200", "GST Receivable", "asset", "gst_receivable"),
    ("2100", "Payroll Clearing", "liability", "payroll_clearing"),
    ("2110", "PAYG Withholding Payable", "liability", "payg_payable"),
    ("2120", "Superannuation Payable", "liability", "super_payable"),
    ("2130", "Payroll Deductions Payable", "liability", "deductions_payable"),
    ("2200", "GST Payable", "liability", "gst_payable"),
    ("4000", "Service Revenue", "revenue", "service_revenue"),
    ("4010", "On-cost Revenue", "revenue", "oncost_revenue"),
    ("4020", "Reimbursement Revenue", "revenue", "reimbursement_revenue"),
    ("4990", "Other Revenue", "revenue", "other_revenue"),
    ("5000", "Wages and Salaries", "expense", "wages_expense"),
    ("5010", "Contractor Costs", "expense", "contractor_expense"),
    ("5020", "Superannuation Expense", "expense", "super_expense"),
    ("5030", "Payroll On-cost Expense", "expense", "oncost_expense"),
    ("5090", "Other Payroll Expense", "expense", "other_payroll_expense"),
)


class FinancePostingService:
    @staticmethod
    def ensure_chart(db) -> dict[str, GLAccount]:
        accounts = {
            account.role: account for account in db.scalars(
                select(GLAccount)
            ).all() if account.role
        }
        for code, name, account_type, role in STANDARD_ACCOUNTS:
            if role not in accounts:
                account = GLAccount(
                    code=code, name=name, account_type=account_type, role=role,
                )
                db.add(account)
                db.flush()
                accounts[role] = account
        return accounts

    @staticmethod
    def _component_account(db, component, accounts):
        if component.component_definition_id:
            mapping = db.scalar(select(ComponentGLMapping).where(
                ComponentGLMapping.component_definition_id == component.component_definition_id,
                ComponentGLMapping.context == "invoice_revenue",
            ))
            if mapping:
                account_id = mapping.credit_gl_account_id or mapping.gl_account_id
                if account_id:
                    return db.get(GLAccount, account_id)

        family = (component.family_code or "").upper()
        if "REIMBURSE" in family or "EXPENSE" in family:
            role = "reimbursement_revenue"
        elif any(word in family for word in ("ONCOST", "ON_COST", "SUPER", "TAX")):
            role = "oncost_revenue"
        else:
            role = "service_revenue"
        account = accounts[role]
        if component.component_definition_id:
            db.add(ComponentGLMapping(
                component_definition_id=component.component_definition_id,
                context="invoice_revenue", credit_gl_account_id=account.id,
            ))
            db.flush()
        return account

    @staticmethod
    def ensure_component_mappings(db):
        accounts = FinancePostingService.ensure_chart(db)
        definitions = db.execute(select(ComponentDefinition, ComponentFamily).join(
            ComponentFamily, ComponentFamily.id == ComponentDefinition.family_id
        )).all()
        existing = {(m.component_definition_id, m.context): m for m in db.scalars(
            select(ComponentGLMapping)
        ).all()}
        for definition, family in definitions:
            invoice_key = (definition.id, "invoice_revenue")
            if invoice_key not in existing:
                family_code = family.code.upper()
                if family_code in {"REIMBURSEMENT", "RECHARGE"}:
                    invoice_account = accounts["reimbursement_revenue"]
                elif family_code in {"ON_COST", "SUPERANNUATION", "TAX"}:
                    invoice_account = accounts["oncost_revenue"]
                else:
                    invoice_account = accounts["service_revenue"]
                invoice_mapping = ComponentGLMapping(
                    component_definition_id=definition.id,
                    context="invoice_revenue",
                    credit_gl_account_id=invoice_account.id,
                )
                db.add(invoice_mapping)
                existing[invoice_key] = invoice_mapping
            key = (definition.id, "payroll")
            if key in existing:
                continue
            code, family_code = definition.code.upper(), family.code.upper()
            if code in {"PAYG_WITHHOLDING", "ETP_WITHHOLDING"}:
                debit, credit = accounts["payroll_clearing"], accounts["payg_payable"]
            elif code == "GST_PAID":
                debit, credit = accounts["gst_receivable"], accounts["payroll_clearing"]
            elif family_code == "SUPERANNUATION":
                if "SACRIFICE" in code:
                    debit, credit = accounts["payroll_clearing"], accounts["super_payable"]
                else:
                    debit, credit = accounts["super_expense"], accounts["super_payable"]
            elif family_code == "DEDUCTION":
                debit, credit = accounts["payroll_clearing"], accounts["deductions_payable"]
            elif family_code == "ON_COST":
                debit, credit = accounts["oncost_expense"], accounts["deductions_payable"]
            else:
                debit, credit = accounts["wages_expense"], accounts["payroll_clearing"]
            mapping = ComponentGLMapping(
                component_definition_id=definition.id,
                context="payroll", debit_gl_account_id=debit.id,
                credit_gl_account_id=credit.id,
            )
            db.add(mapping)
            existing[key] = mapping
        db.flush()
        return accounts

    @staticmethod
    def _save(db, *, organisation_id, source_type, source_id,
              source_reference, posting_date, description, source_total,
              raw_lines, created_by_user_id=None):
        existing = db.scalar(select(FinancePosting).where(
            FinancePosting.source_type == source_type,
            FinancePosting.source_id == source_id,
        ))
        if existing:
            return existing

        lines = []
        for raw in raw_lines:
            amount = Decimal(raw["amount"]).quantize(MONEY)
            if amount == 0:
                continue
            if amount < 0:
                raise ValueError("Finance posting lines cannot contain negative amounts")
            lines.append({**raw, "amount": amount})
        debits = sum((line["amount"] for line in lines if line["side"] == "debit"), Decimal("0"))
        credits = sum((line["amount"] for line in lines if line["side"] == "credit"), Decimal("0"))
        source_total = Decimal(source_total).quantize(MONEY)
        if debits != credits:
            raise ValueError(f"Posting is out of balance by {abs(debits - credits):.2f}")
        reconciled = debits == source_total
        if not reconciled:
            raise ValueError(
                f"Posting total {debits:.2f} does not reconcile to source total {source_total:.2f}"
            )

        canonical = [{
            "line": index, "account": line["account"].code,
            "side": line["side"], "amount": f'{line["amount"]:.2f}',
            "component": line.get("component_code"),
            "source_line_id": line.get("source_line_id"),
        } for index, line in enumerate(lines, 1)]
        checksum = hashlib.sha256(json.dumps(
            canonical, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        posting = FinancePosting(
            organisation_id=organisation_id, source_type=source_type,
            source_id=source_id, source_reference=source_reference,
            posting_date=posting_date, description=description, status="posted",
            total_debits=debits, total_credits=credits, source_total=source_total,
            balanced=True, reconciled=True, checksum=checksum,
            created_by_user_id=created_by_user_id,
        )
        db.add(posting)
        db.flush()
        for index, line in enumerate(lines, 1):
            account = line["account"]
            db.add(FinancePostingLine(
                posting_id=posting.id, line_number=index,
                gl_account_id=account.id, account_code=account.code,
                account_name=account.name, account_type=account.account_type,
                description=line["description"],
                debit=line["amount"] if line["side"] == "debit" else Decimal("0"),
                credit=line["amount"] if line["side"] == "credit" else Decimal("0"),
                component_definition_id=line.get("component_definition_id"),
                component_code=line.get("component_code"),
                source_line_type=line.get("source_line_type"),
                source_line_id=line.get("source_line_id"),
            ))
        db.flush()
        return posting

    @classmethod
    def post_invoice(cls, db, invoice_id: int, created_by_user_id=None):
        invoice = db.get(Invoice, invoice_id)
        if not invoice:
            raise LookupError("Invoice not found")
        if invoice.status not in {"issued", "paid"}:
            raise ValueError("Only issued or paid invoices can be posted to finance")
        assignment = db.get(Assignment, invoice.engagement_id)
        engagement = db.get(Engagement, assignment.engagement_id)
        organisation_id = engagement.organisation_id
        accounts = cls.ensure_chart(db)
        components = db.scalars(select(InvoiceComponent).where(
            InvoiceComponent.invoice_id == invoice.id
        ).order_by(InvoiceComponent.id)).all()
        lines = [{
            "account": accounts["accounts_receivable"], "side": "debit",
            "amount": invoice.total, "description": f"Invoice {invoice.invoice_number}",
            "source_line_type": "invoice",
        }]
        component_total = Decimal("0")
        for component in components:
            account = cls._component_account(db, component, accounts)
            amount = Decimal(component.amount).quantize(MONEY)
            component_total += amount
            lines.append({
                "account": account, "side": "credit", "amount": amount,
                "description": f"{invoice.invoice_number} — {component.component_name or component.component_code or 'service'}",
                "component_definition_id": component.component_definition_id,
                "component_code": component.component_code,
                "source_line_type": "invoice_component",
                "source_line_id": component.id,
            })
        subtotal = Decimal(invoice.subtotal).quantize(MONEY)
        difference = subtotal - component_total
        if difference < 0:
            raise ValueError(
                f"Invoice components exceed invoice subtotal by {abs(difference):.2f}"
            )
        if difference:
            lines.append({
                "account": accounts["other_revenue"], "side": "credit",
                "amount": difference, "description": f"{invoice.invoice_number} — invoice adjustment",
                "source_line_type": "invoice_adjustment",
            })
        if invoice.gst:
            lines.append({
                "account": accounts["gst_payable"], "side": "credit",
                "amount": invoice.gst, "description": f"GST on {invoice.invoice_number}",
                "source_line_type": "invoice_gst",
            })
        return cls._save(
            db, organisation_id=organisation_id, source_type="invoice",
            source_id=invoice.id, source_reference=invoice.invoice_number,
            posting_date=invoice.issue_date,
            description=f"Customer invoice {invoice.invoice_number}",
            source_total=invoice.total, raw_lines=lines,
            created_by_user_id=created_by_user_id,
        )

    @classmethod
    def post_payment_batch(cls, db, batch_id: int, created_by_user_id=None):
        batch = db.get(PaymentBatch, batch_id)
        if not batch:
            raise LookupError("Payment batch not found")
        if batch.status != "exported":
            raise ValueError("The payment batch must be exported before it can be posted")
        accounts = cls.ensure_chart(db)
        reference = f"PAY-{batch.id}"
        lines = [
            {"account": accounts["payroll_clearing"], "side": "debit",
             "amount": batch.total_amount, "description": f"Clear {reference}",
             "source_line_type": "payment_batch"},
            {"account": accounts["bank"], "side": "credit",
             "amount": batch.total_amount, "description": f"Bank payment {reference}",
             "source_line_type": "payment_batch"},
        ]
        return cls._save(
            db, organisation_id=batch.organisation_id, source_type="payment_batch",
            source_id=batch.id, source_reference=reference,
            posting_date=batch.processing_date,
            description=f"Payment batch {batch.id} — {batch.description}",
            source_total=batch.total_amount, raw_lines=lines,
            created_by_user_id=created_by_user_id,
        )

    @classmethod
    def post_pay_run(cls, db, pay_run_id: int, created_by_user_id=None):
        pay_run = db.get(PayRun, pay_run_id)
        if not pay_run:
            raise LookupError("Pay run not found")
        if pay_run.status != "completed":
            raise ValueError("The pay run must be completed before it can be posted")
        cls.ensure_component_mappings(db)
        rows = db.execute(
            select(PayrollComponent, ComponentDefinition, ComponentGLMapping)
            .join(Payslip, Payslip.id == PayrollComponent.payslip_id)
            .join(ComponentDefinition, ComponentDefinition.id == PayrollComponent.component_definition_id)
            .join(ComponentGLMapping,
                  (ComponentGLMapping.component_definition_id == ComponentDefinition.id)
                  & (ComponentGLMapping.context == "payroll"))
            .where(Payslip.pay_run_id == pay_run.id)
            .order_by(PayrollComponent.id)
        ).all()
        if not rows:
            raise ValueError("The pay run has no component transactions to post")
        lines, source_total = [], Decimal("0")
        for component, definition, mapping in rows:
            debit_account = db.get(GLAccount, mapping.debit_gl_account_id)
            credit_account = db.get(GLAccount, mapping.credit_gl_account_id)
            if not debit_account or not credit_account:
                raise ValueError(f"Component {definition.code} does not have complete payroll GL mapping")
            amount = Decimal(component.amount)
            source_total += abs(amount)
            if amount < 0:
                debit_account, credit_account, amount = credit_account, debit_account, abs(amount)
            common = {
                "amount": amount, "description": f"Pay run {pay_run.id} — {definition.name}",
                "component_definition_id": definition.id, "component_code": definition.code,
                "source_line_type": "payroll_component", "source_line_id": component.id,
            }
            lines.append({**common, "account": debit_account, "side": "debit"})
            lines.append({**common, "account": credit_account, "side": "credit"})
        return cls._save(
            db, organisation_id=pay_run.organisation_id, source_type="pay_run",
            source_id=pay_run.id, source_reference=f"PR-{pay_run.id}",
            posting_date=pay_run.payment_date,
            description=f"Payroll component journal for pay run {pay_run.id}",
            source_total=source_total, raw_lines=lines,
            created_by_user_id=created_by_user_id,
        )
