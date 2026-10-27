from datetime import date, datetime, time, timezone

from flask_login import UserMixin
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    pass


class User(UserMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_google_subject", "google_subject", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    password_login_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    google_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    event_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    category: Mapped[str] = mapped_column(String(30))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    category_item: Mapped["Category | None"] = relationship(lazy="selectin")
    reminder: Mapped[str] = mapped_column(String(20), default="at_time")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_categories_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    color: Mapped[str] = mapped_column(String(20), default="other")


class RoutineBlock(Base):
    __tablename__ = "routine_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(100))
    start_time: Mapped[time] = mapped_column(Time)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    day_of_week: Mapped[int] = mapped_column(Integer)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    notification_type: Mapped[str] = mapped_column(String(20), default="general")
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (Index("uq_push_subscriptions_endpoint", "endpoint", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )
