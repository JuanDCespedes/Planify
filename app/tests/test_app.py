import base64
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from werkzeug.security import check_password_hash

from planify import create_app
from planify.domain.models import Category, Event, Notification, PushSubscription, RoutineBlock, User
from planify.infrastructure.database import get_session
from planify.infrastructure.notification_scheduler import process_due_notifications


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret-key-for-planify"
    DATABASE_URL = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class GoogleTestConfig(TestConfig):
    GOOGLE_CLIENT_ID = "test-client-id"
    GOOGLE_CLIENT_SECRET = "test-client-secret"


class PushTestConfig(TestConfig):
    VAPID_PUBLIC_KEY = "public-test-key"
    VAPID_PRIVATE_KEY = "private-test-key"
    VAPID_CLAIMS_EMAIL = "mailto:test@example.com"


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
        polled_notifications = other_client.get("/api/notifications?after=0").json
        self.assertNotIn(
            "Aviso privado de Ana",
            " ".join(item["message"] for item in polled_notifications["notifications"]),
        )
        other_client.post(f"/notifications/{notification_id}/dismiss")

        with self.app.app_context():
            notification = get_session().get(Notification, notification_id)
            self.assertIsNotNone(notification)

    def test_notification_timestamps_are_shown_in_bogota_time(self):
        self.register(self.client)
        with self.app.app_context():
            user = get_session().scalar(select(User).where(User.email == "ana@example.com"))
            get_session().add(
                Notification(
                    user_id=user.id,
                    title="Aviso de prueba",
                    message="Prueba de hora local.",
                    created_at=datetime(2026, 10, 27, 2, 31),
                )
            )
            get_session().commit()

        response = self.client.get("/notifications")
        self.assertIn("26/10 · 21:31".encode(), response.data)

    def test_event_notifications_are_scheduled_once_after_quiet_hours(self):
        self.register(self.client)
        with self.app.app_context():
            db_session = get_session()
            user = db_session.scalar(select(User).where(User.email == "ana@example.com"))
            user.quiet_hours_enabled = True
            event = Event(
                user_id=user.id,
                title="Evento nocturno",
                event_date=date(2026, 5, 11),
                start_time=time(23, 0),
                category="personal",
                reminder="at_time",
            )
            db_session.add(event)
            db_session.commit()

            process_due_notifications(
                db_session,
                now=datetime(2026, 5, 11, 23, 0),
                config={},
            )
            self.assertIsNone(
                db_session.scalar(
                    select(Notification.id).where(
                        Notification.dedupe_key == f"event:{event.id}:at_time"
                    )
                )
            )

            process_due_notifications(
                db_session,
                now=datetime(2026, 5, 12, 6, 0),
                config={},
            )
            process_due_notifications(
                db_session,
                now=datetime(2026, 5, 12, 6, 1),
                config={},
            )
            matching = db_session.scalars(
                select(Notification).where(
                    Notification.dedupe_key == f"event:{event.id}:at_time"
                )
            ).all()
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0].user_id, user.id)

    def test_routine_reminder_uses_user_preferences(self):
        self.register(self.client)
        with self.app.app_context():
            db_session = get_session()
            user = db_session.scalar(select(User).where(User.email == "ana@example.com"))
            user.quiet_hours_enabled = False
            user.routine_notify_start = False
            user.routine_notify_5_minutes = True
            block = RoutineBlock(
                user_id=user.id,
                title="Estudiar",
                start_time=time(9, 30),
                duration_minutes=60,
                day_of_week=0,
            )
            db_session.add(block)
            db_session.commit()

            process_due_notifications(
                db_session,
                now=datetime(2026, 5, 11, 9, 25),
                config={},
            )

            notification = db_session.scalar(
                select(Notification).where(
                    Notification.dedupe_key
                    == f"routine:{block.id}:2026-05-11:5m"
                )
            )
            self.assertIsNotNone(notification)
            self.assertEqual(notification.message, "Estudiar empieza en 5 minutos.")

    def test_weekly_digest_runs_after_nine_and_is_deduplicated(self):
        self.register(self.client)
        with self.app.app_context():
            db_session = get_session()
            user = db_session.scalar(select(User).where(User.email == "ana@example.com"))
            user.weekly_email_summaries = True
            user.quiet_hours_enabled = False
            db_session.commit()
            mail_config = {"SMTP_HOST": "smtp.example.com", "SMTP_FROM": "planify@example.com"}

            with patch(
                "planify.infrastructure.notification_scheduler.send_weekly_digest",
                return_value=True,
            ) as send_digest:
                process_due_notifications(
                    db_session,
                    now=datetime(2026, 5, 11, 8, 59),
                    config=mail_config,
                )
                self.assertEqual(send_digest.call_count, 0)
                process_due_notifications(
                    db_session,
                    now=datetime(2026, 5, 11, 9, 0),
                    config=mail_config,
                )
                process_due_notifications(
                    db_session,
                    now=datetime(2026, 5, 11, 9, 1),
                    config=mail_config,
                )
                self.assertEqual(send_digest.call_count, 1)
            self.assertEqual(user.last_weekly_digest_key, "2026-W20")

    def test_weekly_digest_stays_disabled_without_smtp_configuration(self):
        self.register(self.client)
        with self.app.app_context():
            db_session = get_session()
            user = db_session.scalar(select(User).where(User.email == "ana@example.com"))
            user.weekly_email_summaries = True
            user.quiet_hours_enabled = False
            db_session.commit()
            with patch(
                "planify.infrastructure.notification_scheduler.send_weekly_digest"
            ) as send_digest:
                process_due_notifications(
                    db_session,
                    now=datetime(2026, 10, 26, 9, 0),
                    config={"TIMEZONE": "America/Bogota"},
                )
                send_digest.assert_not_called()
            self.assertIsNone(user.last_weekly_digest_key)

    def test_event_and_routine_email_reminders_are_sent_once(self):
        self.register(self.client)
        with self.app.app_context():
            db_session = get_session()
            user = db_session.scalar(select(User).where(User.email == "ana@example.com"))
            user.email_notifications = True
            user.quiet_hours_enabled = False
            block = RoutineBlock(
                user_id=user.id,
                title="Práctica de guitarra",
                start_time=time(9, 30),
                duration_minutes=30,
                day_of_week=0,
            )
            db_session.add(block)
            db_session.commit()
            mail_config = {
                "TIMEZONE": "America/Bogota",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_FROM": "planify@example.com",
            }

            with patch(
                "planify.infrastructure.notification_scheduler.send_notification_email",
                return_value=True,
            ) as send_email:
                process_due_notifications(
                    db_session,
                    now=datetime(2026, 5, 11, 9, 30),
                    config=mail_config,
                )
                process_due_notifications(
                    db_session,
                    now=datetime(2026, 5, 11, 9, 31),
                    config=mail_config,
                )
                self.assertEqual(send_email.call_count, 1)

            notification = db_session.scalar(
                select(Notification).where(
                    Notification.dedupe_key == f"routine:{block.id}:2026-05-11:start"
                )
            )
            self.assertIsNotNone(notification.email_sent_at)
            self.assertEqual(notification.email_attempt_count, 1)

    def test_push_subscription_is_owned_and_browser_service_worker_is_available(self):
        app = create_app(PushTestConfig)
        try:
            client = app.test_client()
            self.register(client, "ana@example.com")
            public_key = client.get("/api/notifications/push-key")
            self.assertEqual(public_key.status_code, 200)
            self.assertEqual(public_key.json["public_key"], "public-test-key")

            subscription = {
                "endpoint": "https://fcm.googleapis.com/fcm/send/test-endpoint",
                "keys": {
                    "p256dh": base64.urlsafe_b64encode(b"\x04" + b"a" * 64).decode().rstrip("="),
                    "auth": base64.urlsafe_b64encode(b"b" * 16).decode().rstrip("="),
                },
            }
            response = client.post(
                "/api/notifications/push-subscription",
                json={"subscription": subscription},
            )
            self.assertEqual(response.status_code, 200)
            invalid_endpoint = {
                **subscription,
                "endpoint": "https://127.0.0.1/private-resource",
            }
            rejected = client.post(
                "/api/notifications/push-subscription",
                json={"subscription": invalid_endpoint},
            )
            self.assertEqual(rejected.status_code, 400)

            other_client = app.test_client()
            self.register(other_client, "luis@example.com", "otra-clave-segura-456")
            conflict = other_client.post(
                "/api/notifications/push-subscription",
                json={"subscription": subscription},
            )
            self.assertEqual(conflict.status_code, 409)
            with app.app_context():
                saved = get_session().scalar(select(PushSubscription))
                self.assertEqual(saved.user_id, 1)
            worker = client.get("/service-worker.js")
            self.assertEqual(worker.status_code, 200)
            self.assertEqual(worker.headers["Service-Worker-Allowed"], "/")
            worker.close()
        finally:
            app.extensions["planify_engine"].dispose()

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
                "category": "Trabajo",
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
                "category": "Personal",
                "reminder": "30m",
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

    def test_event_form_creates_and_reuses_typed_personal_categories(self):
        self.register(self.client)
        for title, category in (
            ("Preparar examen", "Universidad"),
            ("Leer apuntes", " universidad "),
        ):
            response = self.client.post(
                "/events/new",
                data={
                    "title": title,
                    "event_date": "2030-04-10",
                    "start_time": "14:30",
                    "category": category,
                    "reminder": "15m",
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            db_session = get_session()
            user = db_session.scalar(select(User).where(User.email == "ana@example.com"))
            custom_categories = db_session.scalars(
                select(Category).where(
                    Category.user_id == user.id,
                    Category.name == "Universidad",
                )
            ).all()
            self.assertEqual(len(custom_categories), 1)
            self.assertEqual(custom_categories[0].color, "other")
            assigned_events = db_session.scalars(
                select(Event).where(
                    Event.user_id == user.id,
                    Event.title.in_(("Preparar examen", "Leer apuntes")),
                )
            ).all()
            self.assertEqual(len(assigned_events), 2)
            self.assertTrue(
                all(event.category_id == custom_categories[0].id for event in assigned_events)
            )

        form = self.client.get("/events/new")
        self.assertIn(b'<option value="Universidad">', form.data)

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
        settings_page = self.client.get("/settings")
        self.assertIn("Correo por cada recordatorio".encode(), settings_page.data)
        self.assertIn("hasta configurar SMTP".encode(), settings_page.data)
        self.assertIn("El acceso con Google es independiente".encode(), settings_page.data)
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
            data={
                "default_reminder": "1d",
                "reminder_at_event_enabled": "on",
                "reminder_5_minutes_enabled": "on",
                "reminder_15_minutes_enabled": "on",
                "reminder_30_minutes_enabled": "on",
                "reminder_1_hour_enabled": "on",
                "reminder_1_day_enabled": "on",
                "routine_notify_start": "on",
                "desktop_push_notifications": "on",
                "email_notifications": "on",
                "quiet_hours_enabled": "on",
                "quiet_hours_start": "23:00",
                "quiet_hours_end": "07:00",
            },
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
            self.assertTrue(user.reminder_5_minutes_enabled)
            self.assertTrue(user.routine_notify_start)
            self.assertTrue(user.email_notifications)
            self.assertTrue(user.desktop_push_notifications)
            self.assertTrue(user.quiet_hours_enabled)
            self.assertEqual(user.quiet_hours_start, "23:00")
            self.assertEqual(user.quiet_hours_end, "07:00")
            self.assertTrue(user.check_password("una-clave-nueva-789"))

        self.client.post("/logout")
        login = self.client.post(
            "/login",
            data={"email": "ana.nueva@example.com", "password": "una-clave-nueva-789"},
        )
        self.assertEqual(login.status_code, 302)

    def test_notification_settings_require_a_reminder_and_valid_quiet_hours(self):
        self.register(self.client)
        no_reminders = self.client.post(
            "/settings/preferences",
            data={"default_reminder": "15m", "quiet_hours_start": "22:00", "quiet_hours_end": "06:00"},
            follow_redirects=True,
        )
        self.assertIn("Mantén activo al menos un tipo de recordatorio".encode(), no_reminders.data)
        with self.app.app_context():
            user = get_session().scalar(select(User).where(User.email == "ana@example.com"))
            self.assertTrue(user.reminder_15_minutes_enabled)

        equal_quiet_hours = self.client.post(
            "/settings/preferences",
            data={
                "default_reminder": "15m",
                "reminder_15_minutes_enabled": "on",
                "quiet_hours_enabled": "on",
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "22:00",
            },
            follow_redirects=True,
        )
        self.assertIn("deben ser diferentes".encode(), equal_quiet_hours.data)
        with self.app.app_context():
            user = get_session().scalar(select(User).where(User.email == "ana@example.com"))
            self.assertTrue(user.quiet_hours_enabled)
            self.assertEqual(user.quiet_hours_start, "22:00")

    def test_event_reminder_preferences_are_applied_when_creating_events(self):
        self.register(self.client)
        with self.app.app_context():
            category_id = get_session().scalar(select(Category.id).where(Category.color == "work"))
        self.client.post(
            "/settings/preferences",
            data={
                "default_reminder": "15m",
                "reminder_15_minutes_enabled": "on",
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "06:00",
            },
        )
        unavailable_reminder = self.client.post(
            "/events/new",
            data={
                "title": "Reunión",
                "event_date": "2030-04-10",
                "start_time": "14:30",
                "category": str(category_id),
                "reminder": "1d",
            },
        )
        self.assertEqual(unavailable_reminder.status_code, 400)
        self.assertIn("desactivado en tu configuración".encode(), unavailable_reminder.data)

    def test_default_reminder_setting_accepts_only_enabled_options(self):
        self.register(self.client)
        saved = self.client.post(
            "/settings/default-reminder",
            data={"default_reminder": "1d"},
            follow_redirects=True,
        )
        self.assertIn("recordatorio predeterminado se actualizó".encode(), saved.data)
        rejected = self.client.post(
            "/settings/default-reminder",
            data={"default_reminder": "5m"},
            follow_redirects=True,
        )
        self.assertIn("que esté activo".encode(), rejected.data)
        with self.app.app_context():
            user = get_session().scalar(select(User).where(User.email == "ana@example.com"))
            self.assertEqual(user.default_reminder, "1d")

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

    def test_google_sign_in_links_verified_email_to_existing_account(self):
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
        self.assertEqual(response.status_code, 200)
        self.assertIn("Agenda del día".encode(), response.data)
        with app.app_context():
            user = get_session().get(User, user_id)
            self.assertEqual(user.google_subject, "google-subject-ana")
            self.assertTrue(user.password_login_enabled)
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
                self.assertTrue(user.reminder_at_event_enabled)
                self.assertFalse(user.reminder_5_minutes_enabled)
                self.assertFalse(user.reminder_1_hour_enabled)
                self.assertTrue(user.routine_notification_sounds)
                self.assertTrue(user.quiet_hours_enabled)
                self.assertEqual(user.quiet_hours_start, "22:00")
                self.assertFalse(user.email_notifications)
            app.extensions["planify_engine"].dispose()


if __name__ == "__main__":
    unittest.main()
