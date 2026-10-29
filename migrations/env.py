from app.models.employee_tfn import EmployeeTFN
from app.models.employee_tfn_audit import EmployeeTFNAudit
from app.models.employee_tax_profile import EmployeeTaxProfile
from app.models.employee_super_profile import EmployeeSuperProfile
from app.models.employee_payment_detail import EmployeePaymentDetail
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import URL

from alembic import context

from app.database import DATABASE_URL
from app.models.organisation import Base, Organisation
from app.models.worker import Worker
from app.models.engagement import Engagement
from app.models.work_pattern import WorkPattern
from app.models.payg_tax_table import PAYGTaxTable
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.user import User
from app.models.timesheet import Timesheet
from app.models.timesheet_header import TimesheetHeader
from app.models.payslip_timesheet import PayslipTimesheet
from app.models.assignment import Assignment
from app.models.invoice import Invoice
from app.models.invoice_timesheet import InvoiceTimesheet
from app.models.component_family import ComponentFamily
from app.models.component_definition import ComponentDefinition
from app.models.component_base import ComponentBase
from app.models.component_base_member import ComponentBaseMember
from app.models.assignment_component import AssignmentComponent
from app.models.invoice_component import InvoiceComponent
from app.models.payroll_component import PayrollComponent
from app.models.component_audit_log import ComponentAuditLog
from app.models.leave_plan import LeavePlan
from app.models.leave_transaction import LeaveTransaction
from app.models.aba_profile import ABAProfile
from app.models.payment_batch import PaymentBatch
from app.models.payment_instruction import PaymentInstruction
from app.models.pbt_schedule import PBTSchedule
from app.models.pbt_schedule_rule import PBTScheduleRule
from app.models.pbt_schedule_period import PBTSchedulePeriod
from app.models.worker_document import WorkerDocument
from app.models.document_extraction import DocumentExtraction
from app.models.document_review import DocumentReview
from app.models.notification import Notification
from app.models.assignment_component_application import AssignmentComponentApplication
from app.models.invoice_component_allocation import InvoiceComponentAllocation
from app.models.worker_form_submission import WorkerFormSubmission

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
database_url = (
    DATABASE_URL.render_as_string(hide_password=False)
    if isinstance(DATABASE_URL, URL)
    else DATABASE_URL
)
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None
target_metadata = Base.metadata


# Historical Employee -> Worker/Engagement mapping.
# Preserve this table during schema autogeneration.
def include_object(object_, name, type_, reflected, compare_to):
    if (
        type_ == "table"
        and name in (
            "employee_engagement_migration",
            "employees",
        )
        and reflected
    ):
        return False

    return True


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
