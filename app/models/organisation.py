from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Organisation(Base):
    __tablename__ = "organisations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    abn: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="AU")