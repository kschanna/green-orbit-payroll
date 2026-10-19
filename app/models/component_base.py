from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.organisation import Base


class ComponentBase(Base):
    __tablename__ = "component_bases"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
