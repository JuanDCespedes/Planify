"""Pruebas integradas del gateway contra los tres servicios REST."""

from urllib.parse import urlencode, urlsplit
from datetime import date, datetime, time, timedelta
import unittest
from unittest.mock import patch

from identity_service.app import create_app as create_identity_app
from notification_service.app import create_app as create_notification_app
from planify import create_app
from planning_service.app import create_app as create_planning_app
from notification_service.scheduler import process_due_notifications


TOKEN = "integration-test-service-token"


class GatewayConfig:
    """Configuración de prueba del gateway sin base de datos local."""

    TESTING = True
    SECRET_KEY = "gateway-integration-test-secret"
    MICROSERVICES_ENABLED = True
    SERVICE_TOKEN = TOKEN
    IDENTITY_SERVICE_URL = "http://identity.test"
    PLANNING_SERVICE_URL = "http://planning.test"
    NOTIFICATION_SERVICE_URL = "http://notifications.test"
    SERVICE_REQUEST_TIMEOUT = 1
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    ENABLE_NOTIFICATION_SCHEDULER = False
    TIMEZONE = "America/Bogota"


class FlaskResponseAdapter:
    """Adapta una respuesta Flask de prueba a la interfaz de requests.Response."""

    def __init__(self, response):
        """Conserva el estado HTTP y el JSON de la respuesta simulada."""
        self.status_code = response.status_code
        self.ok = response.status_code < 400
        self._json = response.get_json(silent=True) or {}

    def json(self):
        """Devuelve el cuerpo JSON del servicio simulado."""
        return self._json

    def raise_for_status(self):
        """Imita el error de requests para respuestas HTTP no exitosas."""
        if not self.ok:
            from requests import HTTPError

            raise HTTPError(str(self._json), response=self)


class MicroserviceIntegrationTest(unittest.TestCase):
    """Comprueba el flujo web completo sin iniciar servidores externos."""

    def setUp(self):
        """Construye cada servicio con una base aislada en memoria."""
        self.identity_app = create_identity_app(
            {"TESTING": True, "DATABASE_URL": "sqlite:///:memory:", "SERVICE_TOKEN": TOKEN}
        )
        self.planning_app = create_planning_app(
            {"TESTING": True, "DATABASE_URL": "sqlite:///:memory:", "SERVICE_TOKEN": TOKEN}
        )
        self.notifications_app = create_notification_app(
            {
                "TESTING": True,
                "DATABASE_URL": "sqlite:///:memory:",
                "SERVICE_TOKEN": TOKEN,
                "DELIVERY_SERVICE_TOKEN": TOKEN,
                "ENABLE_NOTIFICATION_SCHEDULER": False,
            }
        )
        self.service_apps = {
            "identity.test": self.identity_app.test_client(),
            "planning.test": self.planning_app.test_client(),
            "notifications.test": self.notifications_app.test_client(),
        }
        self.gateway_app = create_app(GatewayConfig)
        self.client = self.gateway_app.test_client()
        self.request_patch = patch(
            "planify.infrastructure.microservices.requests.request",
            side_effect=self.dispatch_request,
        )
        self.request_patch.start()

    def tearDown(self):
        """Detiene el transporte simulado y libera los tres motores de prueba."""
        self.request_patch.stop()
        for app, extension in (
            (self.identity_app, "identity_engine"),
            (self.planning_app, "planning_engine"),
            (self.notifications_app, "notification_engine"),
        ):
            app.extensions[extension].dispose()

    def dispatch_request(self, method, url, json=None, params=None, headers=None, timeout=None):
        """Enruta requests al cliente de prueba del servicio destino."""
        parts = urlsplit(url)
        path = parts.path
        if params:
            path = f"{path}?{urlencode(params)}"
        response = self.service_apps[parts.hostname].open(
            path,
            method=method,
            json=json,
            headers=headers,
        )
        return FlaskResponseAdapter(response)

    def test_registration_event_routine_and_notification_cross_service_flow(self):
        """Registra cuenta, crea agenda/rutina y consulta avisos remotos."""
        response = self.client.post(
            "/register",
            data={
                "email": "ana@example.test",
                "password": "long-password-123",
                "password_confirmation": "long-password-123",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Agenda del día".encode(), response.data)
        self.assertNotIn("planify_engine", self.gateway_app.extensions)

        service_headers = {"Authorization": f"Bearer {TOKEN}"}
        today = date.today()
        demo_events = self.service_apps["planning.test"].get(
            f"/api/v1/users/1/events?start={today.isoformat()}&end={(today + timedelta(days=7)).isoformat()}",
            headers=service_headers,
        ).json["events"]
        demo_routines = self.service_apps["planning.test"].get(
            f"/api/v1/users/1/routines?day={today.weekday()}",
            headers=service_headers,
        ).json["routines"]
        self.assertEqual(len(demo_events), 5)
        self.assertEqual(len(demo_routines), 4)
        self.service_apps["planning.test"].post(
            "/api/v1/users/1/bootstrap", headers=service_headers
        )
        self.assertEqual(
            len(self.service_apps["planning.test"].get(
                f"/api/v1/users/1/events?start={today.isoformat()}&end={(today + timedelta(days=7)).isoformat()}",
                headers=service_headers,
            ).json["events"]),
            5,
        )

        event_response = self.client.post(
            "/events/new",
            data={
                "title": "Entrega del proyecto",
                "event_date": date.today().isoformat(),
                "start_time": "10:00",
                "category": "Trabajo",
                "reminder": "at_time",
            },
            follow_redirects=True,
        )
        self.assertEqual(event_response.status_code, 200)
        self.assertIn("Entrega del proyecto".encode(), event_response.data)

        notification_session = self.notifications_app.extensions[
            "notification_session_factory"
        ]()
        scheduler_config = {
            "SERVICE_TOKEN": TOKEN,
            "IDENTITY_SERVICE_URL": "http://identity.test",
            "PLANNING_SERVICE_URL": "http://planning.test",
            "TIMEZONE": "America/Bogota",
        }
        with patch(
            "notification_service.scheduler.requests.get",
            side_effect=lambda url, params=None, headers=None, timeout=None: self.dispatch_request(
                "GET", url, params=params, headers=headers, timeout=timeout
            ),
        ):
            process_due_notifications(
                notification_session,
                now=datetime.combine(date.today(), time(10, 0)),
                config=scheduler_config,
            )
        notification_session.close()
        persisted = self.service_apps["notifications.test"].get(
            "/api/v1/users/1/notifications",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ).json["notifications"]
        self.assertEqual(persisted[0]["title"], "Recordatorio de evento")
        self.assertIn("Entrega del proyecto", persisted[0]["message"])

        routine_response = self.client.post(
            "/routine",
            data={"title": "Lectura", "start_time": "18:00", "duration_minutes": "30"},
            follow_redirects=True,
        )
        self.assertEqual(routine_response.status_code, 200)
        self.assertIn("Lectura".encode(), routine_response.data)

        created = self.service_apps["notifications.test"].post(
            "/api/v1/users/1/notifications",
            json={
                "title": "Recordatorio de evento",
                "message": "Tu evento empieza pronto.",
                "type": "event",
                "dedupe_key": "manual:test",
            },
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        self.assertEqual(created.status_code, 201)
        notifications_response = self.client.get("/notifications")
        self.assertEqual(notifications_response.status_code, 200)
        self.assertIn("Tu evento empieza pronto.".encode(), notifications_response.data)
