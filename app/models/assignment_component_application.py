from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class AssignmentComponentApplication(Base):
    __tablename__ = "assignment_component_applications"
    __table_args__ = (
        UniqueConstraint(
            "assignment_component_id",
            "source_assignment_component_id",
            name="uq_assignment_component_application",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_component_id: Mapped[int] = mapped_column(
        ForeignKey("assignment_components.id", ondelete="CASCADE"), nullable=False
    )
    source_assignment_component_id: Mapped[int] = mapped_column(
        ForeignKey("assignment_components.id", ondelete="CASCADE"), nullable=False
    )
    basis: Mapped[str] = mapped_column(String(20), nullable=False)
