import unittest

from planify import create_app


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-key"
    DATABASE_URL = "sqlite:///:memory:"


class PlanifyRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def test_dashboard_and_calendar_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/calendar").status_code, 200)
        self.assertEqual(self.client.get("/routine").status_code, 200)

    def test_create_edit_and_delete_event(self):
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
            from sqlalchemy import select

            from planify.domain.models import Event
            from planify.infrastructure.database import get_session

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

    def test_routine_and_notification_actions(self):
        response = self.client.post(
            "/routine",
            data={"title": "Lectura", "start_time": "20:00", "duration_minutes": "25"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Lectura".encode(), response.data)

        notifications = self.client.get("/notifications")
        self.assertEqual(notifications.status_code, 200)
        self.assertEqual(self.client.post("/notifications/read-all").status_code, 302)
        self.assertEqual(self.client.post("/notifications/1/dismiss").status_code, 302)

    def test_invalid_event_is_reported(self):
        response = self.client.post(
            "/events/new",
            data={"title": "", "event_date": "", "start_time": "", "category": "nope", "reminder": "nope"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("título".encode(), response.data)


if __name__ == "__main__":
    unittest.main()
