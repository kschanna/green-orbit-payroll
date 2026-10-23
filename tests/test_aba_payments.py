from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.employee_payment_detail import EmployeePaymentDetail
from app.models.aba_profile import ABAProfile
from app.models.payment_batch import PaymentBatch
from app.models.payment_instruction import PaymentInstruction
from app.payments.service import PaymentBatchService


@pytest.fixture
def payment_data():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organisation = Organisation(name="Green Orbit", abn="11111111111")
        worker = Worker(first_name="Ada", last_name="Pay", email="ada@example.com")
        db.add_all([organisation, worker])
        db.flush()
        engagement = Engagement(
            worker_id=worker.id, organisation_id=organisation.id,
            engagement_type="payg_employee", status="active",
        )
        db.add(engagement)
        db.flush()
        pay_run = PayRun(
            organisation_id=organisation.id,
            period_start=date(2026, 10, 12), period_end=date(2026, 10, 18),
            payment_date=date(2026, 10, 19), status="approved",
        )
        db.add(pay_run)
        db.flush()
        payslip = Payslip(
            pay_run_id=pay_run.id, engagement_id=engagement.id,
            gross_pay=Decimal("1900"), payg_withholding=Decimal("300"),
            net_pay=Decimal("1600"), superannuation=Decimal("228"),
        )
        profile = ABAProfile(
            organisation_id=organisation.id, financial_institution="CBA",
            user_name="GREEN ORBIT", apca_user_id="123456",
            file_description="PAYROLL", source_bsb="063001",
            source_account_number="12345678",
            source_account_name="GREEN ORBIT", remitter_name="GREEN ORBIT",
            transaction_code="53", balancing_entry_required=True, active=True,
        )
        payment = EmployeePaymentDetail(
            worker_id=worker.id, engagement_id=None, employee_id=None,
            payment_method="bank_transfer", account_name="ADA PAY",
            bsb="062000", account_number="87654321",
            effective_from=date(2026, 1, 1), effective_to=None,
        )
        db.add_all([payslip, profile, payment])
        db.commit()
        ids = {"pay_run": pay_run.id, "payslip": payslip.id}
    yield engine, ids
    engine.dispose()


def test_prepare_payment_batch_snapshots_payslip_and_bank_details(payment_data):
    engine, ids = payment_data
    with Session(engine) as db:
        batch = PaymentBatchService.prepare_from_pay_run(db, ids["pay_run"])
        db.commit()
        line = db.scalar(select(PaymentInstruction).where(
            PaymentInstruction.payment_batch_id == batch.id
        ))
        assert batch.status == "draft"
        assert batch.total_amount == Decimal("1600.00")
        assert batch.line_count == 1
        assert line.payslip_id == ids["payslip"]
        assert line.source_type == "payroll"
        assert line.recipient_bsb == "062000"
        assert line.recipient_account_number == "87654321"


def test_aba_export_is_fixed_width_balanced_and_audited(payment_data):
    engine, ids = payment_data
    with Session(engine) as db:
        batch = PaymentBatchService.prepare_from_pay_run(db, ids["pay_run"])
        content = PaymentBatchService.render_aba(db, batch)
        db.commit()

        records = content.decode("ascii").splitlines()
        assert len(records) == 4  # header, credit, balancing debit, trailer
        assert all(len(record) == 120 for record in records)
        assert content.endswith(b"\r\n")
        assert records[1][18:20] == "53"
        assert records[1][20:30] == "0000160000"
        assert records[2][18:20] == "13"
        assert records[-1][20:30] == "0000000000"
        assert records[-1][30:40] == "0000160000"
        assert records[-1][40:50] == "0000160000"
        assert records[-1][74:80] == "000002"
        assert batch.status == "exported"
        assert batch.exported_at is not None
        assert len(batch.file_checksum) == 64


def test_unapproved_pay_run_cannot_prepare_payments(payment_data):
    engine, ids = payment_data
    with Session(engine) as db:
        db.get(PayRun, ids["pay_run"]).status = "draft"
        with pytest.raises(ValueError, match="Approve the pay run"):
            PaymentBatchService.prepare_from_pay_run(db, ids["pay_run"])


def test_manual_direct_entry_line_is_included_in_aba(payment_data):
    engine, ids = payment_data
    with Session(engine) as db:
        batch = PaymentBatchService.prepare_from_pay_run(db, ids["pay_run"])
        profile = db.get(ABAProfile, batch.aba_profile_id)
        db.add(PaymentInstruction(
            payment_batch_id=batch.id, payslip_id=None, worker_id=None,
            source_type="manual", amount=Decimal("50.25"),
            recipient_account_name="MANUAL RECIPIENT",
            recipient_bsb="033000", recipient_account_number="11223344",
            transaction_code="53", lodgement_reference="ADJUSTMENT",
            trace_bsb=profile.source_bsb,
            trace_account_number=profile.source_account_number,
            remitter_name=profile.remitter_name, status="pending",
            manual_entry_reason="Prototype adjustment",
        ))
        db.flush()
        PaymentBatchService.recalculate(db, batch)
        content = PaymentBatchService.render_aba(db, batch)

        records = content.decode("ascii").splitlines()
        assert len(records) == 5
        assert batch.line_count == 2
        assert batch.total_amount == Decimal("1650.25")
        assert records[2][20:30] == "0000005025"
