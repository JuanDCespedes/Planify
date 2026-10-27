from sqlalchemy import inspect, text


LEGACY_CATEGORIES = {
    "trabajo": "Trabajo",
    "estudio": "Estudio",
    "personal": "Personal",
    "salud": "Salud",
    "otro": "Otro",
}
DEFAULT_CATEGORIES = (
    ("Trabajo", "work"),
    ("Estudio", "study"),
    ("Personal", "personal"),
    ("Salud", "health"),
    ("Otro", "other"),
)


def migrate_sqlite_user_ownership(engine):
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table in ("events", "routine_blocks", "notifications"):
            if table in tables:
                columns = {column["name"] for column in inspector.get_columns(table)}
                if "user_id" not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table} "
                            "ADD COLUMN user_id INTEGER REFERENCES users(id)"
                        )
                    )

        if "users" in tables:
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            for name, definition in (
                ("google_subject", "VARCHAR(255)"),
                ("password_login_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                ("display_name", "VARCHAR(60) NOT NULL DEFAULT ''"),
                ("default_reminder", "VARCHAR(20) NOT NULL DEFAULT '15m'"),
                ("in_app_notifications", "BOOLEAN NOT NULL DEFAULT 1"),
                ("reminder_at_event_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                ("reminder_5_minutes_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                ("reminder_15_minutes_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                ("reminder_30_minutes_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                ("reminder_1_hour_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
                ("reminder_1_day_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                ("routine_notify_start", "BOOLEAN NOT NULL DEFAULT 1"),
                ("routine_notify_5_minutes", "BOOLEAN NOT NULL DEFAULT 0"),
                ("routine_notification_sounds", "BOOLEAN NOT NULL DEFAULT 1"),
                ("desktop_push_notifications", "BOOLEAN NOT NULL DEFAULT 1"),
                ("email_notifications", "BOOLEAN NOT NULL DEFAULT 0"),
                ("weekly_email_summaries", "BOOLEAN NOT NULL DEFAULT 0"),
                ("quiet_hours_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
                ("quiet_hours_start", "VARCHAR(5) NOT NULL DEFAULT '22:00'"),
                ("quiet_hours_end", "VARCHAR(5) NOT NULL DEFAULT '06:00'"),
                ("last_weekly_digest_key", "VARCHAR(8)"),
            ):
                if name not in user_columns:
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {definition}"))
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_subject ON users (google_subject)")
            )

        if "events" not in tables:
            if "notifications" in tables:
                columns = {column["name"] for column in inspector.get_columns("notifications")}
                if "dedupe_key" not in columns:
                    connection.execute(text("ALTER TABLE notifications ADD COLUMN dedupe_key VARCHAR(120)"))
                if "notification_type" not in columns:
                    connection.execute(
                        text("ALTER TABLE notifications ADD COLUMN notification_type VARCHAR(20) NOT NULL DEFAULT 'general'")
                    )
                if "email_sent_at" not in columns:
                    connection.execute(text("ALTER TABLE notifications ADD COLUMN email_sent_at DATETIME"))
                if "email_last_attempt_at" not in columns:
                    connection.execute(text("ALTER TABLE notifications ADD COLUMN email_last_attempt_at DATETIME"))
                if "email_attempt_count" not in columns:
                    connection.execute(
                        text("ALTER TABLE notifications ADD COLUMN email_attempt_count INTEGER NOT NULL DEFAULT 0")
                    )
                connection.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_dedupe_key ON notifications (dedupe_key)")
                )
            return

        event_columns = {column["name"] for column in inspector.get_columns("events")}
        if "category_id" not in event_columns:
            connection.execute(
                text("ALTER TABLE events ADD COLUMN category_id INTEGER REFERENCES categories(id)")
            )

        for name, color in DEFAULT_CATEGORIES:
            connection.execute(
                text(
                    "INSERT INTO categories (user_id, name, color) "
                    "SELECT users.id, :name, :color FROM users "
                    "WHERE NOT EXISTS (SELECT 1 FROM categories "
                    "WHERE categories.user_id = users.id AND categories.name = :name)"
                ),
                {"name": name, "color": color},
            )

        for legacy_name, display_name in LEGACY_CATEGORIES.items():
            connection.execute(
                text(
                    "UPDATE events SET category_id = ("
                    "SELECT categories.id FROM categories "
                    "WHERE categories.user_id = events.user_id AND categories.name = :display_name"
                    ") WHERE events.category = :legacy_name "
                    "AND events.category_id IS NULL AND events.user_id IS NOT NULL"
                ),
                {"display_name": display_name, "legacy_name": legacy_name},
            )

        if "notifications" in tables:
            notification_columns = {
                column["name"] for column in inspector.get_columns("notifications")
            }
            if "dedupe_key" not in notification_columns:
                connection.execute(
                    text("ALTER TABLE notifications ADD COLUMN dedupe_key VARCHAR(120)")
                )
            if "notification_type" not in notification_columns:
                connection.execute(
                    text("ALTER TABLE notifications ADD COLUMN notification_type VARCHAR(20) NOT NULL DEFAULT 'general'")
                )
            if "email_sent_at" not in notification_columns:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN email_sent_at DATETIME"))
            if "email_last_attempt_at" not in notification_columns:
                connection.execute(text("ALTER TABLE notifications ADD COLUMN email_last_attempt_at DATETIME"))
            if "email_attempt_count" not in notification_columns:
                connection.execute(
                    text("ALTER TABLE notifications ADD COLUMN email_attempt_count INTEGER NOT NULL DEFAULT 0")
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_dedupe_key ON notifications (dedupe_key)")
            )
