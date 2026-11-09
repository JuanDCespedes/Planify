"""Pruebas del contrato HTTP y de la entrega del microservicio de notificaciones."""

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from notification_service.app import create_app
from notification_service.delivery import valid_push_subscription
from planify.infrastructure.notification_delivery import send_notification_email


class DeliveryServiceApiTest(unittest.TestCase):
    """Verifica autenticación, validación y despacho de la API de entrega."""

    def setUp(self):
        """Crea un cliente Flask con SMTP, VAPID y token de prueba."""
        self.app = create_app(
            {
                "TESTING": True,
                "DELIVERY_SERVICE_TOKEN": "test-internal-token",
                "SMTP_HOST": "smtp.example.test",
                "SMTP_FROM": "planify@example.test",
                "VAPID_PRIVATE_KEY": "private-test-key",
                "VAPID_PUBLIC_KEY": "public-test-key",
                "VAPID_CLAIMS_EMAIL": "mailto:planify@example.test",
            }
        )
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test-internal-token"}

    def tearDown(self):
        """Libera el motor SQLite en memoria de la API probada."""
        self.app.extensions["notification_engine"].dispose()

    def test_health_is_public_and_minimal(self):
        """Expone solo el estado de vida y no requiere token interno."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})

    def test_email_requires_valid_bearer_token(self):
        """Rechaza llamadas de correo sin autenticación interna válida."""
        response = self.client.post("/api/v1/email", json={})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/v1/email",
                json={},
                headers={"Authorization": "Bearer wrong-token"},
            ).status_code,
            401,
        )

    def test_email_validates_and_dispatches_payload(self):
        """Envía un DTO válido al adaptador SMTP y devuelve confirmación."""
        payload = {
            "to": "ana@example.test",
            "subject": "Recordatorio",
            "body": "Tu evento empieza pronto.",
        }
        with patch("notification_service.app.send_email") as send_email:
            response = self.client.post("/api/v1/email", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"sent": True})
        send_email.assert_called_once_with(
            payload["to"], payload["subject"], payload["body"], self.app.config
        )

    def test_email_rejects_header_injection_and_invalid_addresses(self):
        """Rechaza direcciones inválidas y saltos de línea en el asunto."""
        invalid_payloads = (
            {"to": "not-an-email", "subject": "Hola", "body": "Texto"},
            {"to": "ana@example.test", "subject": "Hola\nBcc: otro@example.test", "body": "Texto"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/v1/email", json=payload, headers=self.headers
                )
                self.assertEqual(response.status_code, 400)

    def test_push_authenticates_and_dispatches_subscription_data(self):
        """Entrega una solicitud push autenticada al adaptador del microservicio."""
        payload = {
            "title": "Planify",
            "body": "Tienes un recordatorio.",
            "url": "/notifications",
            "tag": "notification-1",
            "subscriptions": [],
        }
        with patch(
            "notification_service.app.send_push",
            return_value={"sent": 0, "failed": 0, "expired_endpoints": []},
        ) as send_push:
            response = self.client.post("/api/v1/push", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["sent"], 0)
        send_push.assert_called_once()

    def test_push_rejects_external_navigation_targets(self):
        """Impide que una notificación ordene al navegador abrir otro dominio."""
        response = self.client.post(
            "/api/v1/push",
            json={"title": "Aviso", "body": "Texto", "url": "//example.test", "subscriptions": []},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)

    def test_push_subscription_rejects_untrusted_hosts(self):
        """Rechaza endpoints que podrían convertir el servicio en un proxy SSRF."""
        public_key = base64.urlsafe_b64encode(b"\x04" + b"a" * 64).decode().rstrip("=")
        auth_key = base64.urlsafe_b64encode(b"b" * 16).decode().rstrip("=")
        subscription = {
            "endpoint": "https://example.test/push",
            "keys": {"p256dh": public_key, "auth": auth_key},
        }
        self.assertFalse(valid_push_subscription(subscription))

    def test_planify_delegates_email_as_json_to_delivery_service(self):
        """Envía al microservicio un mensaje sin pasarle modelos ORM."""
        response = Mock()
        response.raise_for_status.return_value = None
        notification = SimpleNamespace(title="Evento", message="Empieza pronto.")
        user = SimpleNamespace(email="ana@example.test")
        config = {
            "DELIVERY_SERVICE_URL": "http://delivery:8100",
            "DELIVERY_SERVICE_TOKEN": "test-internal-token",
        }
        with patch(
            "planify.infrastructure.notification_delivery.requests.post",
            return_value=response,
        ) as post:
            self.assertTrue(send_notification_email(notification, user, config))
        self.assertEqual(post.call_args.args[0], "http://delivery:8100/api/v1/email")
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-internal-token",
        )
        self.assertEqual(post.call_args.kwargs["json"]["to"], user.email)
