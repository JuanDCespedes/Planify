"""Pruebas de copia idempotente desde SQLite monolítico a los servicios."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

from identity_service.models import User, create_database as create_identity_database
from migrate_to_microservices import migrate
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


class MicroserviceMigrationTest(unittest.TestCase):
    """Comprueba la copia de entidades y preservación de la base original."""

    def setUp(self):
        """Crea una base monolítica pequeña y tres destinos temporales."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "legacy.db"
        connection = sqlite3.connect(self.source)
        connection.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT,
                created_at TEXT, default_reminder TEXT, in_app_notifications INTEGER
            );
            INSERT INTO users VALUES (7, 'ana@example.test', 'legacy-hash',
                '2026-01-01 00:00:00', '15m', 1);
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, color TEXT
            );
            INSERT INTO categories VALUES (3, 7, 'Trabajo', 'work');
            CREATE TABLE events (
                id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, event_date TEXT,
                start_time TEXT, category TEXT, category_id INTEGER, reminder TEXT,
                created_at TEXT
            );
            INSERT INTO events VALUES (9, 7, 'Evento legado', '2026-12-01',
                '10:00:00', 'trabajo', 3, '15m', '2026-01-01 00:00:00');
            CREATE TABLE routine_blocks (
                id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT,
                start_time TEXT, duration_minutes INTEGER, day_of_week INTEGER
            );
            INSERT INTO routine_blocks VALUES (2, 7, 'Rutina', '08:00:00', 30, 0);
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, message TEXT,
                created_at TEXT, is_read INTEGER
            );
            INSERT INTO notifications VALUES (4, 7, 'Aviso', 'Mensaje',
                '2026-01-01 00:00:00', 0);
            CREATE TABLE push_subscriptions (
                id INTEGER PRIMARY KEY, user_id INTEGER, endpoint TEXT,
                p256dh TEXT, auth TEXT, created_at TEXT
            );
            INSERT INTO push_subscriptions VALUES (5, 7, 'https://push.example',
                'public-key', 'auth-key', '2026-01-01 00:00:00');
            """
        )
        connection.commit()
        connection.close()
        self.identity_url = f"sqlite:///{self.root / 'identity.db'}"
        self.planning_url = f"sqlite:///{self.root / 'planning.db'}"
        self.notification_url = f"sqlite:///{self.root / 'notifications.db'}"

    def tearDown(self):
        """Elimina las bases temporales creadas por la prueba."""
        self.temporary_directory.cleanup()

    def test_migration_copies_all_domains_idempotently_and_keeps_source(self):
        """Copia cada tipo de registro, conserva IDs y tolera una segunda pasada."""
        counts = migrate(
            self.source,
            self.identity_url,
            self.planning_url,
            self.notification_url,
        )
        self.assertEqual(
            counts,
            {
                "users": 1,
                "categories": 1,
                "events": 1,
                "routines": 1,
                "notifications": 1,
                "push_subscriptions": 1,
            },
        )
        repeated = migrate(
            self.source,
            self.identity_url,
            self.planning_url,
            self.notification_url,
        )
        self.assertTrue(all(count == 0 for count in repeated.values()))

        identity_engine, identity_factory = create_identity_database(self.identity_url)
        planning_engine, planning_factory = create_planning_database(self.planning_url)
        notification_engine, notification_factory = create_notification_database(self.notification_url)
        try:
            with identity_factory() as session:
                self.assertEqual(session.get(User, 7).email, "ana@example.test")
            with planning_factory() as session:
                event = session.get(Event, 9)
                self.assertEqual(event.title, "Evento legado")
                self.assertEqual(session.get(Category, 3).name, "Trabajo")
                self.assertEqual(session.get(RoutineBlock, 2).title, "Rutina")
            with notification_factory() as session:
                self.assertEqual(session.get(Notification, 4).message, "Mensaje")
                self.assertEqual(
                    session.scalar(select(PushSubscription.endpoint)),
                    "https://push.example",
                )
        finally:
            identity_engine.dispose()
            planning_engine.dispose()
            notification_engine.dispose()

        source = sqlite3.connect(self.source)
        try:
            self.assertEqual(source.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            self.assertEqual(source.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
