
"""Canonical Worker and Engagement migration.

Revision ID: b71e6a20c9d4
Revises: ea606b53c1aa

Preserves historical Employee mappings and financial records.
"""

from alembic import op
import sqlalchemy as sa

revision = "b71e6a20c9d4"
down_revision = "ea606b53c1aa"
branch_labels = None
depends_on = None


def upgrade():

    connection = op.get_bind()
    inspector = sa.inspect(connection)

    tables = set(inspector.get_table_names())

    has_legacy = "employees" in tables
    has_workers = "workers" in tables
    has_engagements = "engagements" in tables

    # --------------------------------------------------
    # ALREADY-CONVERTED DATABASE
    # --------------------------------------------------

    if has_workers and has_engagements and not has_legacy:

        required = {
            "workers",
            "engagements",
            "employee_engagement_migration",
        }

        if not required.issubset(tables):
            raise RuntimeError(
                "STOP: Incomplete canonical migration state"
            )

        invalid = connection.scalar(sa.text("""
            SELECT COUNT(*)
            FROM employee_engagement_migration m
            LEFT JOIN workers w ON w.id = m.worker_id
            LEFT JOIN engagements e ON e.id = m.engagement_id
            WHERE w.id IS NULL
               OR e.id IS NULL
               OR e.worker_id <> m.worker_id
        """))

        if invalid:
            raise RuntimeError(
                "STOP: Historical Employee mappings are invalid"
            )

        return

    # --------------------------------------------------
    # LEGACY DATABASE
    # --------------------------------------------------

    if not has_legacy or has_workers or has_engagements:
        raise RuntimeError(
            "STOP: Unexpected database migration state"
        )

    op.create_table(
        "workers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(30)),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    op.create_table(
        "engagements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.id"),
            nullable=False,
        ),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id"),
            nullable=False,
        ),
        sa.Column(
            "engagement_type",
            sa.String(30),
            nullable=False,
            server_default="employee",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL "
            "OR end_date >= start_date",
            name="engagement_date_order",
        ),
        sa.CheckConstraint(
            "engagement_type IN "
            "('employee', 'payg_employee', "
            "'payg_contractor', 'company_contractor')",
            name="engagements_engagement_type_check",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'ended')",
            name="engagements_status_check",
        ),
    )

    op.create_table(
        "employee_engagement_migration",
        sa.Column(
            "legacy_employee_id",
            sa.Integer(),
            primary_key=True,
        ),
        sa.Column(
            "worker_id",
            sa.Integer(),
            sa.ForeignKey("workers.id"),
            nullable=False,
        ),
        sa.Column(
            "engagement_id",
            sa.Integer(),
            sa.ForeignKey("engagements.id"),
            nullable=False,
        ),
    )

    # --------------------------------------------------
    # COPY LEGACY EMPLOYEES
    # --------------------------------------------------

    connection.execute(sa.text("""
        INSERT INTO workers (
            id, first_name, last_name, email, active
        )
        SELECT
            id, first_name, last_name, email, TRUE
        FROM employees
        ORDER BY id
    """))

    connection.execute(sa.text("""
        INSERT INTO engagements (
            id,
            worker_id,
            organisation_id,
            engagement_type,
            status
        )
        SELECT
            id,
            id,
            organisation_id,
            'employee',
            'active'
        FROM employees
        ORDER BY id
    """))

    connection.execute(sa.text("""
        INSERT INTO employee_engagement_migration (
            legacy_employee_id,
            worker_id,
            engagement_id
        )
        SELECT id, id, id
        FROM employees
    """))

    # Reset sequences to account for explicitly copied IDs.
    for table in ("workers", "engagements"):
        connection.execute(sa.text("""
            SELECT setval(
                pg_get_serial_sequence(:table_name, 'id'),
                COALESCE(
                    (SELECT MAX(id) FROM """ + table + """),
                    1
                ),
                EXISTS (SELECT 1 FROM """ + table + """)
            )
        """), {"table_name": table})

    # --------------------------------------------------
    # ADD CANONICAL RELATIONSHIPS
    # --------------------------------------------------

    engagement_tables = (
        "assignments",
        "work_patterns",
        "timesheets",
        "timesheet_headers",
        "payslips",
        "employee_tax_profiles",
        "employee_super_profiles",
        "employee_payment_details",
        "employee_tfns",
        "employee_tfn_audit",
    )

    for table in engagement_tables:

        op.add_column(
            table,
            sa.Column(
                "engagement_id",
                sa.Integer(),
                nullable=True,
            ),
        )

        connection.execute(sa.text(f"""
            UPDATE {table} t
            SET engagement_id = m.engagement_id
            FROM employee_engagement_migration m
            WHERE t.employee_id = m.legacy_employee_id
        """))

        missing = connection.scalar(sa.text(f"""
            SELECT COUNT(*)
            FROM {table}
            WHERE engagement_id IS NULL
        """))

        if missing:
            raise RuntimeError(
                f"STOP: Unmapped historical records in {table}"
            )

        op.create_foreign_key(
            f"{table}_engagement_id_fkey",
            table,
            "engagements",
            ["engagement_id"],
            ["id"],
        )

        op.create_index(
            f"ix_{table}_engagement_id",
            table,
            ["engagement_id"],
        )

    # --------------------------------------------------
    # ADD WORKER RELATIONSHIPS TO PAYROLL PROFILES
    # --------------------------------------------------

    worker_tables = (
        "employee_tax_profiles",
        "employee_super_profiles",
        "employee_payment_details",
        "employee_tfns",
        "employee_tfn_audit",
    )

    for table in worker_tables:

        op.add_column(
            table,
            sa.Column(
                "worker_id",
                sa.Integer(),
                nullable=True,
            ),
        )

        connection.execute(sa.text(f"""
            UPDATE {table} t
            SET worker_id = m.worker_id
            FROM employee_engagement_migration m
            WHERE t.employee_id = m.legacy_employee_id
        """))

        missing = connection.scalar(sa.text(f"""
            SELECT COUNT(*)
            FROM {table}
            WHERE worker_id IS NULL
        """))

        if missing:
            raise RuntimeError(
                f"STOP: Unmapped Worker profiles in {table}"
            )

        op.create_foreign_key(
            f"{table}_worker_id_fkey",
            table,
            "workers",
            ["worker_id"],
            ["id"],
        )

        op.alter_column(
            table,
            "worker_id",
            nullable=False,
        )

    # --------------------------------------------------
    # CANONICAL REQUIRED ENGAGEMENT LINKS
    # --------------------------------------------------

    for table in ("assignments", "work_patterns", "payslips"):
        op.alter_column(
            table,
            "engagement_id",
            nullable=False,
        )

    # --------------------------------------------------
    # PAYSLIP UNIQUENESS
    # --------------------------------------------------

    op.drop_constraint(
        "uq_payslip_pay_run_employee",
        "payslips",
        type_="unique",
    )

    op.create_unique_constraint(
        "uq_payslip_pay_run_engagement",
        "payslips",
        ["pay_run_id", "engagement_id"],
    )


    # --------------------------------------------------
    # RETIRE LEGACY FOREIGN KEY DEPENDENCIES
    # --------------------------------------------------

    legacy_tables = (
        "assignments",
        "work_patterns",
        "timesheets",
        "timesheet_headers",
        "payslips",
        "employee_tax_profiles",
        "employee_super_profiles",
        "employee_payment_details",
        "employee_tfns",
        "employee_tfn_audit",
    )

    inspector = sa.inspect(connection)

    for table in legacy_tables:

        foreign_keys = inspector.get_foreign_keys(table)

        for fk in foreign_keys:

            if (
                fk["referred_table"] == "employees"
                and fk["constrained_columns"] == ["employee_id"]
            ):
                op.drop_constraint(
                    fk["name"],
                    table,
                    type_="foreignkey",
                )

        # TFN employee_id is still the primary key.
        # Change its nullability after PK conversion.
        if table != "employee_tfns":
            op.alter_column(
                table,
                "employee_id",
                existing_type=sa.Integer(),
                nullable=True,
            )

    # --------------------------------------------------
    # TFN PRIMARY KEY CONVERSION
    # --------------------------------------------------

    inspector = sa.inspect(connection)

    primary_key = inspector.get_pk_constraint(
        "employee_tfns"
    )

    if primary_key["constrained_columns"] != ["employee_id"]:
        raise RuntimeError(
            "STOP: Unexpected legacy TFN primary key"
        )

    op.drop_constraint(
        primary_key["name"],
        "employee_tfns",
        type_="primary",
    )

    op.create_primary_key(
        "employee_tfns_pkey",
        "employee_tfns",
        ["worker_id"],
    )

    op.alter_column(
        "employee_tfns",
        "employee_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # --------------------------------------------------
    # PRESERVE HISTORICAL EMPLOYEE TABLE
    # --------------------------------------------------

    # The employees table and legacy employee_id values
    # remain available for historical reconciliation.

    # --------------------------------------------------
    # PRESERVE LEGACY EMPLOYEE COLUMNS
    # --------------------------------------------------

    # The legacy Employee table and employee_id columns
    # are deliberately retained during this migration.

    # --------------------------------------------------
    # FINAL RECONCILIATION
    # --------------------------------------------------

    legacy_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM employees")
    )

    mapping_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM employee_engagement_migration"
        )
    )

    if legacy_count != mapping_count:
        raise RuntimeError(
            "STOP: Historical Employee mapping count mismatch"
        )


def downgrade():
    raise RuntimeError(
        "Canonical Worker/Engagement migration cannot be "
        "automatically reversed without risking historical data"
    )
