"""Entidades ORM propiedad exclusiva del servicio de notificaciones."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    """Base declarativa para avisos y suscripciones push."""


class Notification(Base):
    """Aviso con estado de lectura, deduplicación y seguimiento de correo."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    notification_type: Mapped[str] = mapped_column(String(20), default="general")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_attempt_count: Mapped[int] = mapped_column(Integer, default=0)


class PushSubscription(Base):
    """Suscripción Web Push perteneciente a un usuario externo."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )


def create_database(database_url):
    """Crea las tablas de notificaciones y devuelve motor y sesiones."""
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)