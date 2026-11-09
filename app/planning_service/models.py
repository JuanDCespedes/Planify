"""Entidades ORM propiedad exclusiva del servicio de planificación."""

from datetime import date, datetime, time, timezone

from sqlalchemy import Date, DateTime, Integer, String, Time, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    """Base declarativa para las tablas de planificación."""


class Category(Base):
    """Categoría cuyo identificador de propietario es externo a este servicio."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_categories_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(40))
    color: Mapped[str] = mapped_column(String(20), default="other")


class Event(Base):
    """Evento asociado a una cuenta externa y a una categoría personal."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(120))
    event_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    category_id: Mapped[int] = mapped_column(Integer, index=True)
    reminder: Mapped[str] = mapped_column(String(20), default="at_time")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


class RoutineBlock(Base):
    """Bloque semanal identificado por día, hora y duración."""

    __tablename__ = "routine_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(100))
    start_time: Mapped[time] = mapped_column(Time)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    day_of_week: Mapped[int] = mapped_column(Integer)


def create_database(database_url):
    """Crea las tablas de planificación y devuelve motor y sesiones."""
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)