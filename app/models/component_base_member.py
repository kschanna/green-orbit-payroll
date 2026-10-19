from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class ComponentBaseMember(Base):
    __tablename__ = "component_base_members"
    __table_args__ = (
        UniqueConstraint(
            "base_id", "component_definition_id",
            name="uq_component_base_member"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(
        ForeignKey("component_bases.id"), nullable=False
    )
    component_definition_id: Mapped[int] = mapped_column(
        ForeignKey("component_definitions.id"), nullable=False
    )
