"""consolidate GL accounts and component mappings globally

Revision ID: c8b9c0d1e2f3
Revises: c7a8b9c0d1e2
"""

from alembic import op
import sqlalchemy as sa

revision = "c8b9c0d1e2f3"
down_revision = "c7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("gl_account_id", "debit_gl_account_id", "credit_gl_account_id"):
        op.execute(f"""
            UPDATE component_gl_mappings m
               SET {column} = canonical.id
              FROM gl_accounts old_account
              JOIN (
                    SELECT code, MIN(id) AS id
                      FROM gl_accounts
                     GROUP BY code
                   ) canonical ON canonical.code = old_account.code
             WHERE m.{column} = old_account.id
        """)
    op.execute("""
        UPDATE finance_posting_lines line
           SET gl_account_id = canonical.id
          FROM gl_accounts old_account
          JOIN (
                SELECT code, MIN(id) AS id
                  FROM gl_accounts
                 GROUP BY code
               ) canonical ON canonical.code = old_account.code
         WHERE line.gl_account_id = old_account.id
    """)
    op.execute("""
        DELETE FROM component_gl_mappings duplicate
         USING component_gl_mappings keeper
         WHERE duplicate.component_definition_id = keeper.component_definition_id
           AND duplicate.context = keeper.context
           AND duplicate.id > keeper.id
    """)
    op.execute("""
        DELETE FROM gl_accounts duplicate
         USING gl_accounts keeper
         WHERE duplicate.code = keeper.code
           AND duplicate.id > keeper.id
    """)

    op.drop_constraint("uq_component_gl_mapping_context", "component_gl_mappings", type_="unique")
    op.drop_index("ix_component_gl_mappings_organisation_id", table_name="component_gl_mappings")
    op.drop_constraint("component_gl_mappings_organisation_id_fkey", "component_gl_mappings", type_="foreignkey")
    op.drop_column("component_gl_mappings", "organisation_id")
    op.create_unique_constraint("uq_component_gl_mapping_context", "component_gl_mappings",
                                ["component_definition_id", "context"])

    op.drop_constraint("uq_gl_account_org_code", "gl_accounts", type_="unique")
    op.drop_constraint("uq_gl_account_org_role", "gl_accounts", type_="unique")
    op.drop_index("ix_gl_accounts_organisation_id", table_name="gl_accounts")
    op.drop_constraint("gl_accounts_organisation_id_fkey", "gl_accounts", type_="foreignkey")
    op.drop_column("gl_accounts", "organisation_id")
    op.create_unique_constraint("uq_gl_account_code", "gl_accounts", ["code"])
    op.create_unique_constraint("uq_gl_account_role", "gl_accounts", ["role"])


def downgrade() -> None:
    raise RuntimeError(
        "Global GL consolidation cannot be automatically reversed into organisation-specific mappings"
    )
