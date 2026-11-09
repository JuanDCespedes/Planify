"""Copia una base Planify monolítica a las bases propiedad de cada servicio."""

import argparse
import os
import sqlite3
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

from identity_service.models import User, create_database as create_identity_database
from notification_service.models import (
    Notification,
    PushSubscription,
    create_database as create_notification_database,
)
from planning_service.models import (
    Category,
    Event,
    RoutineBlock,
    create_database as create_planning_database,
)


DEFAULT_CATEGORIES = (
    ("Trabajo", "work"),
    ("Estudio", "study"),
    ("Personal", "personal"),
    ("Salud", "health"),
    ("Otro", "other"),
)
LEGACY_CATEGORY_COLORS = {
    "trabajo": "work",
    "work": "work",
    "estudio": "study",
    "study": "study",
    "personal": "personal",
    "salud": "health",
    "health": "health",
    "otro": "other",
    "other": "other",
}


def _value(row, name, default=None):
    """Lee una columna opcional de una fila SQLite heredada."""
    return row[name] if name in row.keys() else default


def _as_date(value):
    """Convierte un valor SQLite de fecha a date."""
    return value if isinstance(value, date) else date.fromisoformat(value)


def _as_time(value):
    """Convierte un valor SQLite de hora a time."""
    return value if isinstance(value, time) else time.fromisoformat(value)


def _as_datetime(value):
    """Convierte un valor SQLite opcional a datetime."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def migrate(source_path, identity_url, planning_url, notification_url):
    """Copia filas por ID sin modificar ni borrar la base de origen."""
    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"No se encontró la base de origen: {source_path}")
    identity_engine, identity_factory = create_identity_database(identity_url)
    planning_engine, planning_factory = create_planning_database(planning_url)
    notification_engine, notification_factory = create_notification_database(notification_url)
    connection = sqlite3.connect(source_path)
    connection.row_factory = sqlite3.Row
    copied = {"users": 0, "categories": 0, "events": 0, "routines": 0, "notifications": 0, "push_subscriptions": 0}
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        with identity_factory() as identity_session, planning_factory() as planning_session, notification_factory() as notification_session:
            if "users" in tables:
                for row in connection.execute("SELECT * FROM users"):
                    if identity_session.get(User, row["id"]) is not None:
                        continue
                    user = User(
                        id=row["id"],
                        email=row["email"],
                        password_hash=row["password_hash"],
                        password_login_enabled=bool(_value(row, "password_login_enabled", True)),
                        google_subject=_value(row, "google_subject"),
                        display_name=_value(row, "display_name", ""),
                        default_reminder=_value(row, "default_reminder", "15m"),
                        in_app_notifications=bool(_value(row, "in_app_notifications", True)),
                        reminder_at_event_enabled=bool(_value(row, "reminder_at_event_enabled", True)),
                        reminder_5_minutes_enabled=bool(_value(row, "reminder_5_minutes_enabled", False)),
                        reminder_15_minutes_enabled=bool(_value(row, "reminder_15_minutes_enabled", True)),
                        reminder_30_minutes_enabled=bool(_value(row, "reminder_30_minutes_enabled", True)),
                        reminder_1_hour_enabled=bool(_value(row, "reminder_1_hour_enabled", False)),
                        reminder_1_day_enabled=bool(_value(row, "reminder_1_day_enabled", True)),
                        routine_notify_start=bool(_value(row, "routine_notify_start", True)),
                        routine_notify_5_minutes=bool(_value(row, "routine_notify_5_minutes", False)),
                        routine_notification_sounds=bool(_value(row, "routine_notification_sounds", True)),
                        desktop_push_notifications=bool(_value(row, "desktop_push_notifications", True)),
                        email_notifications=bool(_value(row, "email_notifications", False)),
                        weekly_email_summaries=bool(_value(row, "weekly_email_summaries", False)),
                        quiet_hours_enabled=bool(_value(row, "quiet_hours_enabled", True)),
                        quiet_hours_start=_value(row, "quiet_hours_start", "22:00"),
                        quiet_hours_end=_value(row, "quiet_hours_end", "06:00"),
                        last_weekly_digest_key=_value(row, "last_weekly_digest_key"),
                        created_at=_as_datetime(_value(row, "created_at")) or datetime.utcnow(),
                    )
                    identity_session.add(user)
                    copied["users"] += 1
                identity_session.commit()

            if "categories" in tables:
                for row in connection.execute("SELECT * FROM categories"):
                    if planning_session.get(Category, row["id"]) is not None:
                        continue
                    user_id = _value(row, "user_id")
                    if user_id is None:
                        continue
                    planning_session.add(Category(
                        id=row["id"],
                        user_id=user_id,
                        name=row["name"],
                        color=_value(row, "color", "other"),
                    ))
                    copied["categories"] += 1
                planning_session.flush()

            category_cache = {}
            if "events" in tables:
                for row in connection.execute("SELECT * FROM events"):
                    if planning_session.get(Event, row["id"]) is not None:
                        continue
                    user_id = _value(row, "user_id")
                    if user_id is None:
                        continue
                    category_id = _value(row, "category_id")
                    category = planning_session.get(Category, category_id) if category_id else None
                    if category is None or category.user_id != user_id:
                        cache_key = (user_id, str(_value(row, "category", "otro")).casefold())
                        category = category_cache.get(cache_key)
                        if category is None:
                            color = LEGACY_CATEGORY_COLORS.get(cache_key[1], "other")
                            name = dict((item[1], item[0]) for item in DEFAULT_CATEGORIES)[color]
                            category = planning_session.scalar(
                                select(Category).where(Category.user_id == user_id, Category.color == color)
                            )
                            if category is None:
                                category = Category(user_id=user_id, name=name, color=color)
                                planning_session.add(category)
                                planning_session.flush()
                            category_cache[cache_key] = category
                    planning_session.add(Event(
                        id=row["id"],
                        user_id=user_id,
                        title=row["title"],
                        event_date=_as_date(row["event_date"]),
                        start_time=_as_time(row["start_time"]),
                        category_id=category.id,
                        reminder=_value(row, "reminder", "at_time"),
                        created_at=_as_datetime(_value(row, "created_at")) or datetime.utcnow(),
                    ))
                    copied["events"] += 1
                planning_session.commit()

            if "routine_blocks" in tables:
                for row in connection.execute("SELECT * FROM routine_blocks"):
                    if _value(row, "user_id") is None or planning_session.get(RoutineBlock, row["id"]) is not None:
                        continue
                    planning_session.add(RoutineBlock(
                        id=row["id"],
                        user_id=row["user_id"],
                        title=row["title"],
                        start_time=_as_time(row["start_time"]),
                        duration_minutes=row["duration_minutes"],
                        day_of_week=row["day_of_week"],
                    ))
                    copied["routines"] += 1
                planning_session.commit()

            if "notifications" in tables:
                for row in connection.execute("SELECT * FROM notifications"):
                    if _value(row, "user_id") is None or notification_session.get(Notification, row["id"]) is not None:
                        continue
                    notification_session.add(Notification(
                        id=row["id"],
                        user_id=row["user_id"],
                        title=row["title"],
                        message=row["message"],
                        dedupe_key=_value(row, "dedupe_key"),
                        notification_type=_value(row, "notification_type", "general"),
                        created_at=_as_datetime(_value(row, "created_at")) or datetime.utcnow(),
                        is_read=bool(_value(row, "is_read", False)),
                        email_sent_at=_as_datetime(_value(row, "email_sent_at")),
                        email_last_attempt_at=_as_datetime(_value(row, "email_last_attempt_at")),
                        email_attempt_count=_value(row, "email_attempt_count", 0),
                    ))
                    copied["notifications"] += 1
                notification_session.commit()

            if "push_subscriptions" in tables:
                for row in connection.execute("SELECT * FROM push_subscriptions"):
                    if _value(row, "user_id") is None or notification_session.get(PushSubscription, row["id"]) is not None:
                        continue
                    notification_session.add(PushSubscription(
                        id=row["id"],
                        user_id=row["user_id"],
                        endpoint=row["endpoint"],
                        p256dh=row["p256dh"],
                        auth=row["auth"],
                        created_at=_as_datetime(_value(row, "created_at")) or datetime.utcnow(),
                    ))
                    copied["push_subscriptions"] += 1
                notification_session.commit()
    finally:
        connection.close()
        identity_engine.dispose()
        planning_engine.dispose()
        notification_engine.dispose()
    return copied


def main():
    """Parse parámetros, ejecutar la copia y mostrar solo conteos."""
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="instance/planify.db")
    parser.add_argument("--identity-db", default=os.environ.get("IDENTITY_DATABASE_URL", "sqlite:///instance/identity.db"))
    parser.add_argument("--planning-db", default=os.environ.get("PLANNING_DATABASE_URL", "sqlite:///instance/planning.db"))
    parser.add_argument("--notification-db", default=os.environ.get("NOTIFICATION_DATABASE_URL", "sqlite:///instance/notifications.db"))
    args = parser.parse_args()
    counts = migrate(args.source, args.identity_db, args.planning_db, args.notification_db)
    print("Copia finalizada; la base original no se modificó.")
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()