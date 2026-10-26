import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from werkzeug.security import check_password_hash

from planify import create_app
from planify.domain.models import Category, Event, Notification, User
from planify.infrastructure.database import get_session


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret-key-for-planify"
    DATABASE_URL = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class GoogleTestConfig(TestConfig):
    GOOGLE_CLIENT_ID = "test-client-id"
    GOOGLE_CLIENT_SECRET = "test-client-secret"


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

        with self.app.app_context():
            work_category_id = get_session().scalar(
                select(Category.id).where(Category.color == "work")
            )
            personal_category_id = get_session().scalar(
                select(Category.id).where(Category.color == "personal")
            )
        response = self.client.post(
            "/events/new",
            data={
                "title": "Reunión de prueba",
                "event_date": "2030-04-10",
                "start_time": "14:30",
                "category": str(work_category_id),
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
                "category": str(personal_category_id),
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

    def test_personal_categories_are_private_and_cannot_be_deleted_while_in_use(self):
        self.register(self.client, "ana@example.com")
        created = self.client.post(
            "/settings/categories",
            data={"name": "Universidad", "color": "study"},
            follow_redirects=True,
        )
        self.assertEqual(created.status_code, 200)
        self.assertIn("Universidad".encode(), created.data)

        with self.app.app_context():
            category = get_session().scalar(
                select(Category).where(Category.name == "Universidad")
            )
            category_id = category.id
            ana_id = category.user_id
        updated = self.client.post(
            f"/settings/categories/{category_id}",
            data={"name": "Campus", "color": "personal"},
            follow_redirects=True,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertIn("Campus".encode(), updated.data)

        other_client = self.app.test_client()
        self.register(other_client, "luis@example.com", "otra-clave-segura-456")
        other_settings = other_client.get("/settings").data
        self.assertNotIn(b"Campus", other_settings)
        rejected = other_client.post(
            "/events/new",
            data={
                "title": "Evento ajeno",
                "event_date": "2030-04-10",
                "start_time": "14:30",
                "category": str(category_id),
                "reminder": "15m",
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("categoría de tu cuenta".encode(), rejected.data)

        with self.app.app_context():
            self.assertNotEqual(ana_id, get_session().scalar(
                select(Category.user_id).where(Category.color == "work", Category.user_id != ana_id)
            ))

        created_event = self.client.post(
            "/events/new",
            data={
                "title": "Examen",
                "event_date": "2030-04-10",
                "start_time": "14:30",
                "category": str(category_id),
                "reminder": "15m",
            },
            follow_redirects=True,
        )
        self.assertEqual(created_event.status_code, 200)
        blocked_delete = self.client.post(
            f"/settings/categories/{category_id}/delete",
            follow_redirects=True,
        )
        self.assertIn("tiene eventos".encode(), blocked_delete.data)
        with self.app.app_context():
            event = get_session().scalar(select(Event).where(Event.title == "Examen"))
            event_id = event.id
        self.client.post(f"/events/{event_id}/delete")
        self.client.post(f"/settings/categories/{category_id}/delete")
        with self.app.app_context():
            self.assertIsNone(get_session().get(Category, category_id))

    def test_settings_persist_profile_preferences_and_password(self):
        self.register(self.client)
        profile = self.client.post(
            "/settings/profile",
            data={
                "display_name": "Ana",
                "email": "ana.nueva@example.com",
                "current_password": "una-clave-segura-123",
            },
        )
        self.assertEqual(profile.status_code, 302)
        preferences = self.client.post(
            "/settings/preferences",
            data={"default_reminder": "1d"},
        )
        self.assertEqual(preferences.status_code, 302)
        password = self.client.post(
            "/settings/password",
            data={
                "current_password": "una-clave-segura-123",
                "new_password": "una-clave-nueva-789",
                "password_confirmation": "una-clave-nueva-789",
            },
        )
        self.assertEqual(password.status_code, 302)

        with self.app.app_context():
            user = get_session().scalar(select(User).where(User.email == "ana.nueva@example.com"))
            self.assertEqual(user.display_name, "Ana")
            self.assertEqual(user.default_reminder, "1d")
            self.assertFalse(user.in_app_notifications)
            self.assertTrue(user.check_password("una-clave-nueva-789"))

        self.client.post("/logout")
        login = self.client.post(
            "/login",
            data={"email": "ana.nueva@example.com", "password": "una-clave-nueva-789"},
        )
        self.assertEqual(login.status_code, 302)

    def test_account_deletion_requires_confirmation_and_removes_owned_data(self):
        self.register(self.client)
        with self.app.app_context():
            user_id = get_session().scalar(select(User.id).where(User.email == "ana@example.com"))
        rejected = self.client.post(
            "/settings/account/delete",
            data={
                "confirm_email": "ana@example.com",
                "confirmation": "BORRAR",
                "current_password": "una-clave-segura-123",
            },
        )
        self.assertEqual(rejected.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(get_session().get(User, user_id))

        removed = self.client.post(
            "/settings/account/delete",
            data={
                "confirm_email": "ana@example.com",
                "confirmation": "ELIMINAR",
                "current_password": "una-clave-segura-123",
            },
            follow_redirects=True,
        )
        self.assertEqual(removed.status_code, 200)
        self.assertIn("se eliminaron".encode(), removed.data)
        with self.app.app_context():
            self.assertIsNone(get_session().get(User, user_id))
            self.assertEqual(get_session().scalar(
                select(Event.id).where(Event.user_id == user_id)
            ), None)

    def test_google_login_is_exposed_but_requires_credentials(self):
        response = self.client.get("/login")
        self.assertIn("Continuar con Google".encode(), response.data)
        unavailable = self.client.get("/auth/google", follow_redirects=True)
        self.assertEqual(unavailable.status_code, 200)
        self.assertIn("Google aún no está configurado".encode(), unavailable.data)

    def test_google_oidc_creates_account_and_requires_verified_email(self):
        app = create_app(GoogleTestConfig)
        client = app.test_client()
        google = app.extensions["planify_oauth"].google
        with patch.object(
            google,
            "authorize_access_token",
            return_value={
                "userinfo": {
                    "sub": "google-subject-ana",
                    "email": "ana-google@example.com",
                    "email_verified": True,
                    "name": "Ana Google",
                }
            },
        ):
            response = client.get("/auth/google/callback", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Agenda del día".encode(), response.data)
        with app.app_context():
            user = get_session().scalar(
                select(User).where(User.email == "ana-google@example.com")
            )
            self.assertEqual(user.google_subject, "google-subject-ana")
            self.assertFalse(user.password_login_enabled)
            self.assertIsNotNone(get_session().scalar(
                select(Category.id).where(Category.user_id == user.id)
            ))
        app.extensions["planify_engine"].dispose()

        unverified_app = create_app(GoogleTestConfig)
        unverified_client = unverified_app.test_client()
        google = unverified_app.extensions["planify_oauth"].google
        with patch.object(
            google,
            "authorize_access_token",
            return_value={
                "userinfo": {
                    "sub": "unverified-subject",
                    "email": "bad@example.com",
                    "email_verified": False,
                }
            },
        ):
            response = unverified_client.get("/auth/google/callback", follow_redirects=True)
        self.assertIn("no confirmó tu correo".encode(), response.data)
        with unverified_app.app_context():
            self.assertIsNone(
                get_session().scalar(select(User).where(User.email == "bad@example.com"))
            )
        unverified_app.extensions["planify_engine"].dispose()

    def test_existing_email_requires_an_explicit_google_account_link(self):
        app = create_app(GoogleTestConfig)
        client = app.test_client()
        self.register(client, "ana@example.com")
        with app.app_context():
            user_id = get_session().scalar(select(User.id).where(User.email == "ana@example.com"))

        google = app.extensions["planify_oauth"].google
        profile = {
            "userinfo": {
                "sub": "google-subject-ana",
                "email": "ana@example.com",
                "email_verified": True,
                "name": "Ana",
            }
        }
        with patch.object(google, "authorize_access_token", return_value=profile):
            response = client.get("/auth/google/callback", follow_redirects=True)
        self.assertIn("conecta Google desde Ajustes".encode(), response.data)
        with app.app_context():
            self.assertIsNone(get_session().get(User, user_id).google_subject)

        with client.session_transaction() as session:
            session["google_link_user_id"] = user_id
        with patch.object(google, "authorize_access_token", return_value=profile):
            response = client.get("/auth/google/callback", follow_redirects=True)
        self.assertIn("cuenta de Google quedó conectada".encode(), response.data)
        with app.app_context():
            self.assertEqual(get_session().get(User, user_id).google_subject, "google-subject-ana")
        app.extensions["planify_engine"].dispose()

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

    def test_migration_connects_existing_users_events_to_private_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory, "owned-legacy.db")
            legacy_connection = sqlite3.connect(database_path)
            try:
                legacy_connection.executescript(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        email VARCHAR(254) NOT NULL UNIQUE,
                        password_hash VARCHAR(256) NOT NULL,
                        created_at DATETIME NOT NULL
                    );
                    INSERT INTO users (id, email, password_hash, created_at)
                    VALUES (7, 'ana@example.com', 'legacy-hash', '2029-12-31');
                    CREATE TABLE events (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id),
                        title VARCHAR(120) NOT NULL,
                        event_date DATE NOT NULL,
                        start_time TIME NOT NULL,
                        category VARCHAR(30) NOT NULL,
                        reminder VARCHAR(20) NOT NULL,
                        created_at DATETIME NOT NULL
                    );
                    INSERT INTO events
                        (id, user_id, title, event_date, start_time, category, reminder, created_at)
                    VALUES
                        (11, 7, 'Evento conservado', '2030-01-01', '09:00:00', 'personal', '15m', '2029-12-31');
                    """
                )
            finally:
                legacy_connection.close()

            class OwnedMigrationTestConfig(TestConfig):
                DATABASE_URL = f"sqlite:///{database_path.as_posix()}"

            app = create_app(OwnedMigrationTestConfig)
            with app.app_context():
                user = get_session().get(User, 7)
                event = get_session().get(Event, 11)
                self.assertEqual(user.default_reminder, "15m")
                self.assertTrue(user.password_login_enabled)
                self.assertEqual(event.user_id, 7)
                self.assertEqual(event.category_item.name, "Personal")
                self.assertEqual(event.category_item.user_id, user.id)
            app.extensions["planify_engine"].dispose()


if __name__ == "__main__":
    unittest.main()
