"""seed shared chart of accounts and component GL mappings

Revision ID: c9c0d1e2f3a4
Revises: c8b9c0d1e2f3
"""

from alembic import op

revision = "c9c0d1e2f3a4"
down_revision = "c8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO gl_accounts (code, name, account_type, role, active)
        VALUES
          ('1000', 'Operating Bank Account', 'asset', 'bank', true),
          ('1100', 'Accounts Receivable', 'asset', 'accounts_receivable', true),
          ('1200', 'GST Receivable', 'asset', 'gst_receivable', true),
          ('2100', 'Payroll Clearing', 'liability', 'payroll_clearing', true),
          ('2110', 'PAYG Withholding Payable', 'liability', 'payg_payable', true),
          ('2120', 'Superannuation Payable', 'liability', 'super_payable', true),
          ('2130', 'Payroll Deductions Payable', 'liability', 'deductions_payable', true),
          ('2200', 'GST Payable', 'liability', 'gst_payable', true),
          ('4000', 'Service Revenue', 'revenue', 'service_revenue', true),
          ('4010', 'On-cost Revenue', 'revenue', 'oncost_revenue', true),
          ('4020', 'Reimbursement Revenue', 'revenue', 'reimbursement_revenue', true),
          ('4990', 'Other Revenue', 'revenue', 'other_revenue', true),
          ('5000', 'Wages and Salaries', 'expense', 'wages_expense', true),
          ('5010', 'Contractor Costs', 'expense', 'contractor_expense', true),
          ('5020', 'Superannuation Expense', 'expense', 'super_expense', true),
          ('5030', 'Payroll On-cost Expense', 'expense', 'oncost_expense', true),
          ('5090', 'Other Payroll Expense', 'expense', 'other_payroll_expense', true)
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO component_gl_mappings
          (component_definition_id, context, credit_gl_account_id)
        SELECT definition.id, 'invoice_revenue', account.id
          FROM component_definitions definition
          JOIN component_families family ON family.id = definition.family_id
          JOIN gl_accounts account ON account.role = CASE
            WHEN family.code IN ('REIMBURSEMENT', 'RECHARGE')
              THEN 'reimbursement_revenue'
            WHEN family.code IN ('ON_COST', 'SUPERANNUATION', 'TAX')
              THEN 'oncost_revenue'
            ELSE 'service_revenue'
          END
        ON CONFLICT (component_definition_id, context) DO NOTHING
    """)
    op.execute("""
        INSERT INTO component_gl_mappings
          (component_definition_id, context, debit_gl_account_id, credit_gl_account_id)
        SELECT definition.id, 'payroll', debit_account.id, credit_account.id
          FROM component_definitions definition
          JOIN component_families family ON family.id = definition.family_id
          JOIN gl_accounts debit_account ON debit_account.role = CASE
            WHEN definition.code IN ('PAYG_WITHHOLDING', 'ETP_WITHHOLDING')
              THEN 'payroll_clearing'
            WHEN definition.code = 'GST_PAID' THEN 'gst_receivable'
            WHEN family.code = 'SUPERANNUATION' AND definition.code LIKE '%SACRIFICE%'
              THEN 'payroll_clearing'
            WHEN family.code = 'SUPERANNUATION' THEN 'super_expense'
            WHEN family.code = 'DEDUCTION' THEN 'payroll_clearing'
            WHEN family.code = 'ON_COST' THEN 'oncost_expense'
            ELSE 'wages_expense'
          END
          JOIN gl_accounts credit_account ON credit_account.role = CASE
            WHEN definition.code IN ('PAYG_WITHHOLDING', 'ETP_WITHHOLDING')
              THEN 'payg_payable'
            WHEN definition.code = 'GST_PAID' THEN 'payroll_clearing'
            WHEN family.code = 'SUPERANNUATION' THEN 'super_payable'
            WHEN family.code IN ('DEDUCTION', 'ON_COST') THEN 'deductions_payable'
            ELSE 'payroll_clearing'
          END
        ON CONFLICT (component_definition_id, context) DO NOTHING
    """)


def downgrade() -> None:
    # Seed rows may be referenced by immutable postings or changed by users.
    # Schema rollback deliberately preserves accounting configuration.
    pass
