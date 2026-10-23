import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from app.models.aba_profile import ABAProfile
from app.models.employee_payment_detail import EmployeePaymentDetail
from app.models.engagement import Engagement
from app.models.pay_run import PayRun
from app.models.payment_batch import PaymentBatch
from app.models.payment_instruction import PaymentInstruction
from app.models.payslip import Payslip
from app.models.worker import Worker


class PaymentBatchService:
    ACTIVE_STATUSES = {"draft", "validated", "exported", "submitted", "confirmed"}

    @staticmethod
    def prepare_from_pay_run(session, pay_run_id: int) -> PaymentBatch:
        pay_run = session.get(PayRun, pay_run_id)
        if pay_run is None:
            raise ValueError("Pay run not found")
        if pay_run.status not in {"approved", "completed"}:
            raise ValueError("Approve the pay run before preparing payments")

        existing = session.scalar(
            select(PaymentBatch).where(PaymentBatch.pay_run_id == pay_run.id)
        )
        if existing is not None:
            return existing

        profile = session.scalar(select(ABAProfile).where(
            ABAProfile.organisation_id == pay_run.organisation_id,
            ABAProfile.active.is_(True),
        ))
        if profile is None:
            raise ValueError("Configure the organisation ABA profile first")

        rows = session.execute(
            select(Payslip, Engagement, Worker)
            .join(Engagement, Engagement.id == Payslip.engagement_id)
            .join(Worker, Worker.id == Engagement.worker_id)
            .where(Payslip.pay_run_id == pay_run.id)
            .order_by(Worker.last_name, Worker.first_name)
        ).all()
        if not rows:
            raise ValueError("Pay run has no payslips")

        batch = PaymentBatch(
            organisation_id=pay_run.organisation_id,
            pay_run_id=pay_run.id,
            aba_profile_id=profile.id,
            processing_date=pay_run.payment_date,
            description=profile.file_description,
            status="draft",
        )
        session.add(batch)
        session.flush()

        for payslip, engagement, worker in rows:
            if payslip.net_pay <= 0:
                raise ValueError(f"Payslip #{payslip.id} has no positive net pay")
            duplicate = session.scalar(
                select(PaymentInstruction.id)
                .join(
                    PaymentBatch,
                    PaymentBatch.id == PaymentInstruction.payment_batch_id,
                )
                .where(
                    PaymentInstruction.payslip_id == payslip.id,
                    PaymentBatch.status.in_(PaymentBatchService.ACTIVE_STATUSES),
                )
                .limit(1)
            )
            if duplicate is not None:
                raise ValueError(f"Payslip #{payslip.id} is already in a payment batch")

            payment_profiles = session.scalars(
                select(EmployeePaymentDetail).where(
                    EmployeePaymentDetail.worker_id == worker.id,
                    EmployeePaymentDetail.effective_from <= pay_run.payment_date,
                    (
                        EmployeePaymentDetail.effective_to.is_(None)
                        | (EmployeePaymentDetail.effective_to >= pay_run.payment_date)
                    ),
                )
            ).all()
            if len(payment_profiles) != 1:
                raise ValueError(
                    f"Expected exactly one effective payment profile for "
                    f"{worker.first_name} {worker.last_name}"
                )
            payment = payment_profiles[0]
            if payment.payment_method != "bank_transfer":
                raise ValueError(
                    f"{worker.first_name} {worker.last_name} is not configured "
                    "for bank transfer"
                )

            session.add(PaymentInstruction(
                payment_batch_id=batch.id,
                payslip_id=payslip.id,
                worker_id=worker.id,
                source_type="payroll",
                amount=payslip.net_pay,
                recipient_account_name=payment.account_name or "",
                recipient_bsb=payment.bsb or "",
                recipient_account_number=payment.account_number or "",
                transaction_code=profile.transaction_code,
                lodgement_reference=f"PAYSLIP {payslip.id}"[:18],
                trace_bsb=profile.source_bsb,
                trace_account_number=profile.source_account_number,
                remitter_name=profile.remitter_name,
                status="pending",
            ))

        session.flush()
        PaymentBatchService.recalculate(session, batch)
        return batch

    @staticmethod
    def recalculate(session, batch: PaymentBatch) -> None:
        lines = session.scalars(select(PaymentInstruction).where(
            PaymentInstruction.payment_batch_id == batch.id
        )).all()
        batch.line_count = len(lines)
        batch.total_amount = sum((line.amount for line in lines), Decimal("0"))

    @staticmethod
    def validate(session, batch: PaymentBatch):
        profile = session.get(ABAProfile, batch.aba_profile_id)
        if profile is None or not profile.active:
            raise ValueError("ABA profile is missing or inactive")
        lines = session.scalars(select(PaymentInstruction).where(
            PaymentInstruction.payment_batch_id == batch.id
        ).order_by(PaymentInstruction.id)).all()
        if not lines:
            raise ValueError("Payment batch has no lines")
        PaymentBatchService._validate_profile(profile)
        for line in lines:
            PaymentBatchService._validate_line(line)
            if line.source_type == "payroll":
                payslip = session.get(Payslip, line.payslip_id)
                if payslip is None or line.amount != payslip.net_pay:
                    raise ValueError(
                        f"Payment line #{line.id} no longer matches payslip net pay"
                    )
        PaymentBatchService.recalculate(session, batch)
        if batch.total_amount * 100 > Decimal("9999999999"):
            raise ValueError("Payment batch exceeds ABA total limits")
        return profile, lines

    @staticmethod
    def render_aba(session, batch: PaymentBatch) -> bytes:
        profile, lines = PaymentBatchService.validate(session, batch)
        records = [PaymentBatchService._header(profile, batch)]
        credit_cents = 0
        for line in lines:
            records.append(PaymentBatchService._detail(line))
            credit_cents += PaymentBatchService._cents(line.amount)
        debit_cents = 0
        if profile.balancing_entry_required:
            records.append(PaymentBatchService._contra(profile, credit_cents))
            debit_cents = credit_cents
        records.append(PaymentBatchService._trailer(
            credit_cents, debit_cents, len(records) - 1
        ))
        content = ("\r\n".join(records) + "\r\n").encode("ascii")
        batch.status = "exported"
        batch.exported_at = datetime.now(UTC).replace(tzinfo=None)
        batch.file_checksum = hashlib.sha256(content).hexdigest()
        return content

    @staticmethod
    def _validate_profile(profile):
        if not re.fullmatch(r"[A-Za-z0-9]{3}", profile.financial_institution):
            raise ValueError("Financial institution code must be 3 characters")
        if not re.fullmatch(r"\d{6}", profile.apca_user_id):
            raise ValueError("APCA user ID must contain 6 digits")
        PaymentBatchService._bank_fields(
            profile.source_bsb, profile.source_account_number,
            profile.source_account_name,
        )

    @staticmethod
    def _validate_line(line):
        if line.amount <= 0 or line.amount != line.amount.quantize(Decimal("0.01")):
            raise ValueError(f"Payment line #{line.id} has an invalid amount")
        PaymentBatchService._bank_fields(
            line.recipient_bsb, line.recipient_account_number,
            line.recipient_account_name,
        )
        if not re.fullmatch(r"\d{2}", line.transaction_code):
            raise ValueError(f"Payment line #{line.id} has an invalid transaction code")
        if not line.lodgement_reference.strip():
            raise ValueError(f"Payment line #{line.id} requires a reference")

    @staticmethod
    def _bank_fields(bsb, account_number, account_name):
        if not re.fullmatch(r"\d{6}", bsb or ""):
            raise ValueError("BSB must contain 6 digits")
        if not re.fullmatch(r"\d{4,9}", account_number or ""):
            raise ValueError("ABA account number must contain 4–9 digits")
        if not (account_name or "").strip():
            raise ValueError("Account name is required")

    @staticmethod
    def _text(value, length):
        value = unicodedata.normalize("NFKD", value or "").encode(
            "ascii", "ignore"
        ).decode("ascii")
        value = re.sub(r"[^ A-Za-z0-9!#$%&'\-./:;=?@_*()+,~]", " ", value)
        return value[:length].ljust(length)

    @staticmethod
    def _bsb(value):
        return f"{value[:3]}-{value[3:]}"

    @staticmethod
    def _cents(amount):
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _header(profile, batch):
        record = (
            "0" + " " * 17 + "01"
            + profile.financial_institution.upper().ljust(3)
            + " " * 7
            + PaymentBatchService._text(profile.user_name, 26)
            + profile.apca_user_id.zfill(6)
            + PaymentBatchService._text(batch.description, 12)
            + batch.processing_date.strftime("%d%m%y")
            + " " * 40
        )
        assert len(record) == 120
        return record

    @staticmethod
    def _detail(line):
        record = (
            "1" + PaymentBatchService._bsb(line.recipient_bsb)
            + line.recipient_account_number.rjust(9) + " "
            + line.transaction_code
            + f"{PaymentBatchService._cents(line.amount):010d}"
            + PaymentBatchService._text(line.recipient_account_name, 32)
            + PaymentBatchService._text(line.lodgement_reference, 18)
            + PaymentBatchService._bsb(line.trace_bsb)
            + line.trace_account_number.rjust(9)
            + PaymentBatchService._text(line.remitter_name, 16)
            + "00000000"
        )
        assert len(record) == 120
        return record

    @staticmethod
    def _contra(profile, cents):
        record = (
            "1" + PaymentBatchService._bsb(profile.source_bsb)
            + profile.source_account_number.rjust(9) + " " + "13"
            + f"{cents:010d}"
            + PaymentBatchService._text(profile.source_account_name, 32)
            + PaymentBatchService._text("BALANCING ENTRY", 18)
            + PaymentBatchService._bsb(profile.source_bsb)
            + profile.source_account_number.rjust(9)
            + PaymentBatchService._text(profile.remitter_name, 16)
            + "00000000"
        )
        assert len(record) == 120
        return record

    @staticmethod
    def _trailer(credit_cents, debit_cents, count):
        net = abs(credit_cents - debit_cents)
        record = (
            "7" + "999-999" + " " * 12
            + f"{net:010d}" + f"{credit_cents:010d}" + f"{debit_cents:010d}"
            + " " * 24 + f"{count:06d}" + " " * 40
        )
        assert len(record) == 120
        return record
