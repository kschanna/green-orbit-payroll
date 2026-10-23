"""Seed canonical Green Orbit component catalogue.

Revision ID: c42e8a71d903
Revises: b71e6a20c9d4
"""

from alembic import op
import sqlalchemy as sa

revision = "c42e8a71d903"
down_revision = "b71e6a20c9d4"
branch_labels = None
depends_on = None

FAMILIES = [{'code': 'EARNINGS', 'description': None, 'name': 'Earnings'},
 {'code': 'ALLOWANCE', 'description': None, 'name': 'Allowance'},
 {'code': 'LEAVE', 'description': None, 'name': 'Leave'},
 {'code': 'TERMINATION', 'description': None, 'name': 'Termination'},
 {'code': 'REIMBURSEMENT', 'description': None, 'name': 'Reimbursement'},
 {'code': 'DEDUCTION', 'description': None, 'name': 'Deduction'},
 {'code': 'SUPERANNUATION', 'description': None, 'name': 'Superannuation'},
 {'code': 'ON_COST', 'description': None, 'name': 'On cost'},
 {'code': 'FEE', 'description': None, 'name': 'Fee'},
 {'code': 'RECHARGE', 'description': None, 'name': 'Recharge'},
 {'code': 'ADJUSTMENT', 'description': None, 'name': 'Adjustment'},
 {'code': 'TAX', 'description': None, 'name': 'Tax'}]

DEFINITIONS = [{'active': True,
  'calculation_type': 'hourly',
  'code': 'ORDINARY_HOURS',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Ordinary Hours'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'ORDINARY_SALARY',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Ordinary Salary'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'OVERTIME_150',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Overtime – 150%'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'OVERTIME_200',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Overtime – 200%'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'SATURDAY_PENALTY',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Saturday Penalty'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'SUNDAY_PENALTY',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Sunday Penalty'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'PUBLIC_HOLIDAY',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Public Holiday Pay'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'BONUS',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Bonus'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'COMMISSION',
  'description': None,
  'family_code': 'EARNINGS',
  'name': 'Commission'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'MEAL_ALLOWANCE',
  'description': None,
  'family_code': 'ALLOWANCE',
  'name': 'Meal Allowance'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'TRAVEL_ALLOWANCE',
  'description': None,
  'family_code': 'ALLOWANCE',
  'name': 'Travel Allowance'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'TOOL_ALLOWANCE',
  'description': None,
  'family_code': 'ALLOWANCE',
  'name': 'Tool Allowance'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'FIRST_AID_ALLOWANCE',
  'description': None,
  'family_code': 'ALLOWANCE',
  'name': 'First Aid Allowance'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'ON_CALL_ALLOWANCE',
  'description': None,
  'family_code': 'ALLOWANCE',
  'name': 'On-call Allowance'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'ANNUAL_LEAVE',
  'description': None,
  'family_code': 'LEAVE',
  'name': 'Annual Leave'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'PERSONAL_LEAVE',
  'description': None,
  'family_code': 'LEAVE',
  'name': "Personal/Carer's Leave"},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'LONG_SERVICE_LEAVE',
  'description': None,
  'family_code': 'LEAVE',
  'name': 'Long Service Leave'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'COMPASSIONATE_LEAVE',
  'description': None,
  'family_code': 'LEAVE',
  'name': 'Compassionate Leave'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'PARENTAL_LEAVE',
  'description': None,
  'family_code': 'LEAVE',
  'name': 'Paid Parental Leave'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'LEAVE_LOADING',
  'description': None,
  'family_code': 'LEAVE',
  'name': 'Annual Leave Loading'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'NOTICE_PAYMENT',
  'description': None,
  'family_code': 'TERMINATION',
  'name': 'Payment in Lieu of Notice'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'REDUNDANCY_PAYMENT',
  'description': None,
  'family_code': 'TERMINATION',
  'name': 'Redundancy Payment'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'UNUSED_ANNUAL_LEAVE',
  'description': None,
  'family_code': 'TERMINATION',
  'name': 'Unused Annual Leave'},
 {'active': True,
  'calculation_type': 'hourly',
  'code': 'UNUSED_LSL',
  'description': None,
  'family_code': 'TERMINATION',
  'name': 'Unused Long Service Leave'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'ETP_TAXABLE',
  'description': None,
  'family_code': 'TERMINATION',
  'name': 'Taxable Employment Termination Payment'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'EXPENSE_REIMBURSEMENT',
  'description': None,
  'family_code': 'REIMBURSEMENT',
  'name': 'Expense Reimbursement'},
 {'active': True,
  'calculation_type': 'quantity',
  'code': 'KILOMETRE_REIMBURSEMENT',
  'description': None,
  'family_code': 'REIMBURSEMENT',
  'name': 'Kilometre Reimbursement'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'ACCOMMODATION_REIMBURSEMENT',
  'description': None,
  'family_code': 'REIMBURSEMENT',
  'name': 'Accommodation Reimbursement'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'SALARY_SACRIFICE',
  'description': None,
  'family_code': 'DEDUCTION',
  'name': 'Salary Sacrifice'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'UNION_FEES',
  'description': None,
  'family_code': 'DEDUCTION',
  'name': 'Union Fees'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'CHILD_SUPPORT',
  'description': None,
  'family_code': 'DEDUCTION',
  'name': 'Child Support Deduction'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'OTHER_DEDUCTION',
  'description': None,
  'family_code': 'DEDUCTION',
  'name': 'Other Deduction'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'SUPER_GUARANTEE',
  'description': None,
  'family_code': 'SUPERANNUATION',
  'name': 'Superannuation Guarantee'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'SUPER_SALARY_SACRIFICE',
  'description': None,
  'family_code': 'SUPERANNUATION',
  'name': 'Salary Sacrifice Superannuation'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'SUPER_EMPLOYER_EXTRA',
  'description': None,
  'family_code': 'SUPERANNUATION',
  'name': 'Additional Employer Superannuation'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'PAYROLL_TAX',
  'description': None,
  'family_code': 'ON_COST',
  'name': 'Payroll Tax'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'WORKCOVER',
  'description': None,
  'family_code': 'ON_COST',
  'name': 'Workers Compensation'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'LEAVE_PROVISION',
  'description': None,
  'family_code': 'ON_COST',
  'name': 'Leave Provision'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'SERVICE_FEE',
  'description': None,
  'family_code': 'FEE',
  'name': 'Service Fee'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'PLACEMENT_FEE',
  'description': None,
  'family_code': 'FEE',
  'name': 'Placement Fee'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'ADMIN_FEE',
  'description': None,
  'family_code': 'FEE',
  'name': 'Administration Fee'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'EXPENSE_RECHARGE',
  'description': None,
  'family_code': 'RECHARGE',
  'name': 'Expense Recharge'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'TRAVEL_RECHARGE',
  'description': None,
  'family_code': 'RECHARGE',
  'name': 'Travel Recharge'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'EQUIPMENT_RECHARGE',
  'description': None,
  'family_code': 'RECHARGE',
  'name': 'Equipment Recharge'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'PAY_ADJUSTMENT',
  'description': None,
  'family_code': 'ADJUSTMENT',
  'name': 'Payroll Adjustment'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'INVOICE_ADJUSTMENT',
  'description': None,
  'family_code': 'ADJUSTMENT',
  'name': 'Invoice Adjustment'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'BACKPAY',
  'description': None,
  'family_code': 'ADJUSTMENT',
  'name': 'Backpay'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'PAYG_WITHHOLDING',
  'description': None,
  'family_code': 'TAX',
  'name': 'PAYG Withholding'},
 {'active': True,
  'calculation_type': 'percentage',
  'code': 'GST',
  'description': None,
  'family_code': 'TAX',
  'name': 'Goods and Services Tax'},
 {'active': True,
  'calculation_type': 'fixed',
  'code': 'ETP_WITHHOLDING',
  'description': None,
  'family_code': 'TAX',
  'name': 'ETP Tax Withholding'}]


def upgrade():

    connection = op.get_bind()

    for family in FAMILIES:

        existing = connection.execute(
            sa.text("""
                SELECT id, name, description
                FROM component_families
                WHERE code = :code
            """),
            {"code": family["code"]},
        ).mappings().first()

        if existing:

            if (
                existing["name"] != family["name"]
                or existing["description"] != family["description"]
            ):
                raise RuntimeError(
                    f"STOP: Conflicting component family {family['code']}"
                )

            continue

        connection.execute(
            sa.text("""
                INSERT INTO component_families (
                    code, name, description
                )
                VALUES (:code, :name, :description)
            """),
            family,
        )

    for definition in DEFINITIONS:

        family_id = connection.scalar(
            sa.text("""
                SELECT id
                FROM component_families
                WHERE code = :code
            """),
            {"code": definition["family_code"]},
        )

        if family_id is None:
            raise RuntimeError(
                f"STOP: Missing family {definition['family_code']}"
            )

        existing = connection.execute(
            sa.text("""
                SELECT
                    family_id,
                    name,
                    description,
                    calculation_type,
                    active
                FROM component_definitions
                WHERE code = :code
            """),
            {"code": definition["code"]},
        ).mappings().first()

        if existing:

            if (
                existing["family_id"] != family_id
                or existing["name"] != definition["name"]
                or existing["description"] != definition["description"]
                or existing["calculation_type"]
                    != definition["calculation_type"]
                or existing["active"] != definition["active"]
            ):
                raise RuntimeError(
                    f"STOP: Conflicting component definition "
                    f"{definition['code']}"
                )

            continue

        connection.execute(
            sa.text("""
                INSERT INTO component_definitions (
                    family_id,
                    code,
                    name,
                    description,
                    calculation_type,
                    active
                )
                VALUES (
                    :family_id,
                    :code,
                    :name,
                    :description,
                    :calculation_type,
                    :active
                )
            """),
            {
                **definition,
                "family_id": family_id,
            },
        )


def downgrade():
    raise RuntimeError(
        "Component catalogue seed migration cannot be "
        "automatically reversed because definitions may "
        "be referenced by historical transactions."
    )
