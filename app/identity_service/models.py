"""Entidades ORM propiedad exclusiva del servicio de identidad."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    """Base declarativa para las tablas de identidad."""


class User(Base):
    """Cuenta, credenciales y preferencias personales de recordatorios."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    password_login_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    google_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    display_name: Mapped[str] = mapped_column(String(60), default="")
    default_reminder: Mapped[str] = mapped_column(String(20), default="15m")
    in_app_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_at_event_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_5_minutes_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_15_minutes_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_30_minutes_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_1_hour_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1_day_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    routine_notify_start: Mapped[bool] = mapped_column(Boolean, default=True)
    routine_notify_5_minutes: Mapped[bool] = mapped_column(Boolean, default=False)
    routine_notification_sounds: Mapped[bool] = mapped_column(Boolean, default=True)
    desktop_push_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_email_summaries: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="22:00")
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="06:00")
    last_weekly_digest_key: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    def set_password(self, password: str) -> None:
        """Guarda una contraseña usando el hash de Werkzeug."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Comprueba la contraseña sin revelar el hash almacenado."""
        return check_password_hash(self.password_hash, password)


def create_database(database_url):
    """Crea las tablas de identidad y devuelve motor y fábrica de sesiones."""
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
