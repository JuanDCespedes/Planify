import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from werkzeug.security import check_password_hash

from planify import create_app
from planify.domain.models import Event, Notification, User
from planify.infrastructure.database import get_session


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret-key-for-planify"
    DATABASE_URL = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class PlanifyRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.extensions["planify_engine"].dispose()

    def register(self, client, email="ana@example.com", password="una-clave-segura-123"):
        return client.post(
            "/register",
            data={
                "email": email,
                "password": password,
                "password_confirmation": password,
            },
            follow_redirects=True,
        )

    def test_auth_pages_and_protected_routes(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].startswith("/login?next="))
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/register").status_code, 200)
        self.assertEqual(self.client.get("/forgot-password").status_code, 200)

    def test_register_login_and_logout_use_hashed_passwords(self):
        response = self.register(self.client, email="  ANA@EXAMPLE.COM ")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Tu cuenta está lista".encode(), response.data)

        with self.app.app_context():
            user = get_session().scalar(select(User).where(User.email == "ana@example.com"))
            self.assertIsNotNone(user)
            self.assertNotEqual(user.password_hash, "una-clave-segura-123")
            self.assertTrue(check_password_hash(user.password_hash, "una-clave-segura-123"))
            self.assertIsNotNone(get_session().scalar(select(Event.id).where(Event.user_id == user.id)))

        self.client.post("/logout", follow_redirects=True)
        login = self.client.post(
            "/login",
            data={"email": "ANA@example.com", "password": "una-clave-segura-123"},
            follow_redirects=True,
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("Agenda del día".encode(), login.data)

        self.client.post("/logout", follow_redirects=True)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_registration_rejects_weak_password_and_duplicate_email(self):
        weak_password = self.client.post(
            "/register",
            data={
                "email": "ana@example.com",
                "password": "corta",
                "password_confirmation": "corta",
            },
        )
        self.assertEqual(weak_password.status_code, 400)
        self.assertIn("12 caracteres".encode(), weak_password.data)

        self.register(self.client)
        self.client.post("/logout")
        duplicate = self.client.post(
            "/register",
            data={
                "email": "ANA@example.com",
                "password": "otra-clave-segura-456",
                "password_confirmation": "otra-clave-segura-456",
            },
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("ya está registrado".encode(), duplicate.data)

    def test_invalid_login_message_does_not_disclose_account_existence(self):
        self.register(self.client)
        self.client.post("/logout")

        messages = []
        for email in ("ana@example.com", "nobody@example.com"):
            response = self.client.post(
                "/login",
                data={"email": email, "password": "incorrect-password"},
            )
            self.assertEqual(response.status_code, 200)
            messages.append(response.data)
        self.assertIn("no son correctos".encode(), messages[0])
        self.assertIn("no son correctos".encode(), messages[1])

    def test_other_accounts_cannot_read_or_change_events(self):
        self.register(self.client, "ana@example.com")
        with self.app.app_context():
            event = get_session().scalar(select(Event).where(Event.title == "Planificar la semana"))
            event_id = event.id

        other_client = self.app.test_client()
        self.register(other_client, "luis@example.com", "otra-clave-segura-456")
        self.assertNotIn(f"/events/{event_id}/edit".encode(), other_client.get("/").data)
        response = other_client.get(f"/events/{event_id}/edit")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

        other_client.post(f"/events/{event_id}/delete")
        with self.app.app_context():
            event = get_session().get(Event, event_id)
            self.assertIsNotNone(event)

    def test_other_accounts_cannot_read_another_users_notifications(self):
        self.register(self.client, "ana@example.com")
        with self.app.app_context():
            ana = get_session().scalar(select(User).where(User.email == "ana@example.com"))
            notification = Notification(
                user_id=ana.id,
                title="Aviso privado de Ana",
                message="Información de su cuenta.",
            )
            get_session().add(notification)
            get_session().commit()
            notification_id = notification.id

        other_client = self.app.test_client()
        self.register(other_client, "luis@example.com", "otra-clave-segura-456")
        other_notifications = other_client.get("/notifications").data
        self.assertNotIn(b"Aviso privado de Ana", other_notifications)
        other_client.post(f"/notifications/{notification_id}/dismiss")

        with self.app.app_context():
            notification = get_session().get(Notification, notification_id)
            self.assertIsNotNone(notification)

    def test_create_edit_delete_event_and_account_features(self):
        self.register(self.client)
        self.assertIn("Agenda del día".encode(), self.client.get("/").data)
        self.assertEqual(self.client.get("/calendar").status_code, 200)
        self.assertEqual(self.client.get("/calendar?month=0001-01").status_code, 200)
        self.assertEqual(self.client.get("/calendar?month=9999-12").status_code, 200)
        self.assertEqual(self.client.get("/routine").status_code, 200)

        response = self.client.post(
            "/events/new",
            data={
                "title": "Reunión de prueba",
                "event_date": "2030-04-10",
                "start_time": "14:30",
                "category": "trabajo",
                "reminder": "15m",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Evento guardado".encode(), response.data)

        with self.app.app_context():
            event = get_session().scalar(select(Event).where(Event.title == "Reunión de prueba"))
            event_id = event.id

        edited = self.client.post(
            f"/events/{event_id}/edit",
            data={
                "title": "Reunión actualizada",
                "event_date": "2030-04-11",
                "start_time": "15:00",
                "category": "personal",
                "reminder": "1h",
            },
            follow_redirects=True,
        )
        self.assertEqual(edited.status_code, 200)
        deleted = self.client.post(f"/events/{event_id}/delete", follow_redirects=True)
        self.assertEqual(deleted.status_code, 200)

        response = self.client.post(
            "/routine",
            data={"title": "Lectura", "start_time": "20:00", "duration_minutes": "25"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Lectura".encode(), response.data)

        self.assertEqual(self.client.get("/notifications").status_code, 200)
        self.assertEqual(self.client.post("/notifications/read-all").status_code, 302)
        with self.app.app_context():
            notification = get_session().scalar(select(Notification))
            notification_id = notification.id
        self.assertEqual(self.client.post(f"/notifications/{notification_id}/read").status_code, 302)
        self.assertEqual(self.client.post(f"/notifications/{notification_id}/dismiss").status_code, 302)
        self.assertEqual(self.client.get("/settings").status_code, 200)

    def test_invalid_event_and_foreign_redirect_are_rejected(self):
        self.register(self.client)
        response = self.client.post(
            "/events/new",
            data={
                "title": "",
                "event_date": "",
                "start_time": "",
                "category": "nope",
                "reminder": "nope",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("título".encode(), response.data)

        self.client.post("/logout")
        response = self.client.post(
            "/login?next=https://example.com",
            data={"email": "ana@example.com", "password": "una-clave-segura-123", "next": "https://example.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_csrf_protects_state_changing_requests(self):
        class CsrfTestConfig(TestConfig):
            WTF_CSRF_ENABLED = True

        app = create_app(CsrfTestConfig)
        response = app.test_client().post("/login", data={"email": "ana@example.com", "password": "secret"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("formulario expiró".encode(), response.data)
        app.extensions["planify_engine"].dispose()

    def test_production_requires_a_long_secret_and_secure_cookies(self):
        class UnsafeProductionConfig(TestConfig):
            ENVIRONMENT = "production"
            SECRET_KEY = "too-short"

        with self.assertRaisesRegex(RuntimeError, "PLANIFY_SECRET_KEY"):
            create_app(UnsafeProductionConfig)

        class ProductionConfig(TestConfig):
            ENVIRONMENT = "production"
            SECRET_KEY = "a" * 48

        app = create_app(ProductionConfig)
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        app.extensions["planify_engine"].dispose()

    def test_login_attempts_are_rate_limited(self):
        class RateLimitTestConfig(TestConfig):
            RATELIMIT_ENABLED = True

        app = create_app(RateLimitTestConfig)
        client = app.test_client()
        response = None
        for _ in range(11):
            response = client.post(
                "/login",
                data={"email": "ana@example.com", "password": "clave-incorrecta"},
            )
        self.assertEqual(response.status_code, 429)
        app.extensions["planify_engine"].dispose()

    def test_existing_sqlite_data_is_migrated_without_claiming_old_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory, "legacy.db")
            legacy_connection = sqlite3.connect(database_path)
            try:
                legacy_connection.executescript(
                    """
                    CREATE TABLE events (
                        id INTEGER PRIMARY KEY,
                        title VARCHAR(120) NOT NULL,
                        event_date DATE NOT NULL,
                        start_time TIME NOT NULL,
                        category VARCHAR(30) NOT NULL,
                        reminder VARCHAR(20) NOT NULL,
                        created_at DATETIME NOT NULL
                    );
                    CREATE TABLE routine_blocks (
                        id INTEGER PRIMARY KEY,
                        title VARCHAR(100) NOT NULL,
                        start_time TIME NOT NULL,
                        duration_minutes INTEGER NOT NULL,
                        day_of_week INTEGER NOT NULL
                    );
                    CREATE TABLE notifications (
                        id INTEGER PRIMARY KEY,
                        title VARCHAR(120) NOT NULL,
                        message TEXT NOT NULL,
                        created_at DATETIME NOT NULL,
                        is_read BOOLEAN NOT NULL
                    );
                    INSERT INTO events
                        (id, title, event_date, start_time, category, reminder, created_at)
                    VALUES
                        (1, 'Dato anterior', '2030-01-01', '09:00:00', 'personal', 'at_time', '2029-12-31');
                    """
                )
            finally:
                legacy_connection.close()

            class MigrationTestConfig(TestConfig):
                DATABASE_URL = f"sqlite:///{database_path.as_posix()}"

            app = create_app(MigrationTestConfig)
            client = app.test_client()
            self.register(client, "migracion@example.com")
            with app.app_context():
                connection = get_session().connection()
                columns = {
                    column[1]
                    for column in connection.exec_driver_sql("PRAGMA table_info(events)")
                }
                legacy_event = get_session().get(Event, 1)
                self.assertIn("user_id", columns)
                self.assertIsNone(legacy_event.user_id)
                connection.close()
            self.assertNotIn(b"Dato anterior", client.get("/").data)
            app.extensions["planify_engine"].dispose()


if __name__ == "__main__":
    unittest.main()
