from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from app.models.assignment_component import AssignmentComponent
from app.models.component_definition import ComponentDefinition
from app.models.component_family import ComponentFamily
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.payroll.payg_withholding import PAYGWithholdingCalculator
from app.payroll.superannuation import SuperannuationCalculator


CENT = Decimal("0.01")


@dataclass(frozen=True)
class PaymentCalculation:
    payg: Decimal = Decimal("0.00")
    statutory_super: Decimal = Decimal("0.00")
    additional_super: Decimal = Decimal("0.00")
    deductions_total: Decimal = Decimal("0.00")
    net_before_gst: Decimal = Decimal("0.00")
    gst_paid: Decimal = Decimal("0.00")
    payment_total: Decimal = Decimal("0.00")
    component_lines: list[dict] = field(default_factory=list)

    @property
    def total_super(self):
        return self.statutory_super + self.additional_super


class BasePaymentPolicy:
    def calculate(
        self, *, session, assignment, engagement, entries, gross,
        payment_date, pay_frequency,
    ) -> PaymentCalculation:
        raise NotImplementedError


class PAYGPaymentPolicy(BasePaymentPolicy):
    def calculate(
        self, *, session, assignment, engagement, entries, gross,
        payment_date, pay_frequency,
    ) -> PaymentCalculation:
        tax_profiles = session.scalars(select(EmployeeTaxProfile).where(
            EmployeeTaxProfile.worker_id == engagement.worker_id,
            EmployeeTaxProfile.effective_from <= payment_date,
            EmployeeTaxProfile.effective_to.is_(None)
            | (EmployeeTaxProfile.effective_to >= payment_date),
        )).all()
        if len(tax_profiles) != 1:
            raise ValueError("Expected exactly one effective Tax Profile")
        tax = tax_profiles[0]
        if (
            tax.residency_status != "resident"
            or tax.has_study_loan
            or not tax.tfn_declaration_received
        ):
            raise ValueError("Tax Profile is incomplete or unsupported")

        payg = PAYGWithholdingCalculator().calculate(
            session=session,
            gross_pay=gross,
            pay_frequency=pay_frequency,
            claims_tax_free_threshold=tax.claims_tax_free_threshold,
            payment_date=payment_date,
        )

        super_profiles = session.scalars(select(EmployeeSuperProfile).where(
            EmployeeSuperProfile.worker_id == engagement.worker_id,
            EmployeeSuperProfile.effective_from <= payment_date,
            EmployeeSuperProfile.effective_to.is_(None)
            | (EmployeeSuperProfile.effective_to >= payment_date),
        )).all()
        if len(super_profiles) != 1:
            raise ValueError(
                "Expected exactly one effective Superannuation Profile"
            )
        additional_rate = (
            super_profiles[0].additional_employer_rate or Decimal("0")
        )
        if additional_rate < 0:
            raise ValueError("Invalid additional employer super rate")
        statutory_super = SuperannuationCalculator().calculate(
            ordinary_time_earnings=gross
        )
        additional_super = SuperannuationCalculator().calculate(
            ordinary_time_earnings=gross,
            rate=additional_rate / Decimal("100"),
        )
        net = gross - payg
        return PaymentCalculation(
            payg=payg,
            statutory_super=statutory_super,
            additional_super=additional_super,
            net_before_gst=net,
            payment_total=net,
        )


class PAYGEmployeePaymentPolicy(PAYGPaymentPolicy):
    pass


class PAYGContractorPaymentPolicy(PAYGPaymentPolicy):
    pass


class CompanyContractorPaymentPolicy(BasePaymentPolicy):
    GST_RATE = Decimal("0.10")

    def calculate(
        self, *, session, assignment, engagement, entries, gross,
        payment_date, pay_frequency,
    ) -> PaymentCalculation:
        period_start = min(entry.work_date for entry in entries)
        period_end = max(entry.work_date for entry in entries)
        rows = session.execute(
            select(AssignmentComponent, ComponentDefinition)
            .join(
                ComponentDefinition,
                ComponentDefinition.id
                == AssignmentComponent.component_definition_id,
            )
            .join(
                ComponentFamily,
                ComponentFamily.id == ComponentDefinition.family_id,
            )
            .where(
                AssignmentComponent.assignment_id == assignment.id,
                AssignmentComponent.applies_to.in_(("payroll", "both")),
                ComponentFamily.code == "DEDUCTION",
                AssignmentComponent.effective_from <= period_end,
                AssignmentComponent.effective_to.is_(None)
                | (AssignmentComponent.effective_to >= period_start),
            )
            .order_by(
                AssignmentComponent.processing_order,
                AssignmentComponent.id,
            )
        ).all()

        total_hours = sum(
            (Decimal(entry.hours_worked) for entry in entries), Decimal("0")
        )
        component_lines = []
        deductions_total = Decimal("0.00")
        for component, definition in rows:
            rate = component.pay_rate
            if rate is None or rate < 0:
                raise ValueError(f"Invalid pay rate for {definition.name}")
            if definition.calculation_type == "percentage":
                quantity = gross
                amount = gross * rate / Decimal("100")
                displayed_rate = rate / Decimal("100")
            elif definition.calculation_type in {"hourly", "quantity"}:
                quantity = total_hours
                amount = total_hours * rate
                displayed_rate = rate
            elif definition.calculation_type == "fixed":
                quantity = Decimal("1")
                amount = rate
                displayed_rate = rate
            else:
                raise ValueError(
                    f"Unsupported deduction calculation for {definition.name}"
                )
            amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
            deductions_total += amount
            component_lines.append({
                "component_definition_id": definition.id,
                "name": definition.name,
                "family_code": "DEDUCTION",
                "family_name": "Deductions",
                "calculation_type": definition.calculation_type,
                "quantity": quantity,
                "rate": displayed_rate,
                "amount": amount,
            })

        net_before_gst = gross - deductions_total
        if net_before_gst < 0:
            raise ValueError("Assignment deductions exceed earnings")
        gst_paid = (net_before_gst * self.GST_RATE).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        return PaymentCalculation(
            deductions_total=deductions_total,
            net_before_gst=net_before_gst,
            gst_paid=gst_paid,
            payment_total=net_before_gst + gst_paid,
            component_lines=component_lines,
        )


def payment_policy_for(engagement_type: str) -> BasePaymentPolicy:
    policies = {
        "payg_employee": PAYGEmployeePaymentPolicy,
        "employee": PAYGEmployeePaymentPolicy,
        "payg_contractor": PAYGContractorPaymentPolicy,
        "company_contractor": CompanyContractorPaymentPolicy,
    }
    policy = policies.get(engagement_type)
    if policy is None:
        raise ValueError("Unsupported engagement type for payment")
    return policy()


def supports_payment_policy(engagement_type: str) -> bool:
    try:
        payment_policy_for(engagement_type)
    except ValueError:
        return False
    return True
