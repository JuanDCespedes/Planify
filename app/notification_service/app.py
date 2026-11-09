"""API HTTP autenticada para enviar correo y Web Push sin acceso a la agenda."""

import hmac
import os
import re
import smtplib
from pathlib import Path

from flask import Flask, current_app, g, jsonify, request
from dotenv import load_dotenv
from sqlalchemy import select

from notification_service.delivery import (
    email_is_configured,
    push_is_configured,
    send_email,
    send_push,
    valid_push_subscription,
)
from notification_service.models import Notification, PushSubscription, create_database
from notification_service.services import NotificationService


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def create_app(test_config=None):
    """Construye la API de entrega usando configuración de entorno o de prueba."""
    app = Flask(__name__)
    app.config.from_mapping(
        DELIVERY_SERVICE_TOKEN=os.environ.get(
            "PLANIFY_SERVICE_TOKEN", os.environ.get("PLANIFY_DELIVERY_SERVICE_TOKEN", "")
        ),
        DATABASE_URL=os.environ.get(
            "NOTIFICATION_DATABASE_URL",
            f"sqlite:///{(Path(__file__).resolve().parents[1] / 'instance' / 'notifications.db').as_posix()}",
        ),
        SERVICE_TOKEN=os.environ.get(
            "PLANIFY_SERVICE_TOKEN", os.environ.get("PLANIFY_DELIVERY_SERVICE_TOKEN", "")
        ),
        IDENTITY_SERVICE_URL=os.environ.get("IDENTITY_SERVICE_URL", "http://127.0.0.1:8101"),
        PLANNING_SERVICE_URL=os.environ.get("PLANNING_SERVICE_URL", "http://127.0.0.1:8102"),
        TIMEZONE=os.environ.get("PLANIFY_TIMEZONE", "America/Bogota"),
        ENABLE_NOTIFICATION_SCHEDULER=os.environ.get(
            "PLANIFY_ENABLE_NOTIFICATION_SCHEDULER", "true"
        ).casefold() == "true",
        SMTP_HOST=os.environ.get("PLANIFY_SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("PLANIFY_SMTP_PORT", "587")),
        SMTP_USERNAME=os.environ.get("PLANIFY_SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("PLANIFY_SMTP_PASSWORD", ""),
        SMTP_FROM=os.environ.get("PLANIFY_SMTP_FROM", ""),
        SMTP_USE_SSL=os.environ.get("PLANIFY_SMTP_USE_SSL", "").casefold() == "true",
        SMTP_STARTTLS=os.environ.get("PLANIFY_SMTP_STARTTLS", "true").casefold() == "true",
        VAPID_PRIVATE_KEY=os.environ.get("PLANIFY_VAPID_PRIVATE_KEY", ""),
        VAPID_PUBLIC_KEY=os.environ.get("PLANIFY_VAPID_PUBLIC_KEY", ""),
        VAPID_CLAIMS_EMAIL=os.environ.get("PLANIFY_VAPID_CLAIMS_EMAIL", ""),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
        if test_config.get("TESTING") and "DATABASE_URL" not in test_config:
            app.config["DATABASE_URL"] = "sqlite:///:memory:"
    Path(app.config["DATABASE_URL"].removeprefix("sqlite:///" )).parent.mkdir(
        parents=True,
        exist_ok=True,
    ) if app.config["DATABASE_URL"].startswith("sqlite:///") and ":memory:" not in app.config["DATABASE_URL"] else None
    engine, session_factory = create_database(app.config["DATABASE_URL"])
    app.extensions["notification_engine"] = engine
    app.extensions["notification_session_factory"] = session_factory

    def authorized():
        """Compara de forma constante el token Bearer interno configurado."""
        token = app.config.get("DELIVERY_SERVICE_TOKEN", "")
        supplied = request.headers.get("Authorization", "")
        return bool(token) and hmac.compare_digest(supplied, f"Bearer {token}")

    def authorization_error():
        """Devuelve un error sin revelar si falta o no coincide el token."""
        return jsonify({"error": "Autenticación interna no válida."}), 401

    @app.before_request
    def open_notification_session():
        """Autentica solicitudes internas y abre la sesión de avisos."""
        if request.path == "/health":
            return None
        if not authorized():
            return authorization_error()
        g.notification_session = session_factory()
        return None

    @app.teardown_request
    def close_notification_session(_error=None):
        """Cierra la sesión de base de datos de la solicitud actual."""
        session = g.pop("notification_session", None)
        if session is not None:
            session.close()

    @app.get("/health")
    def health():
        """Expone una comprobación de vida sin información sensible."""
        return jsonify({"status": "ok"})

    @app.get("/api/v1/users/<int:user_id>/notifications")
    def list_notifications(user_id):
        """Lista los avisos propios en orden de lectura y fecha."""
        items = NotificationService(g.notification_session).list_all(user_id)
        return jsonify({"notifications": [_notification_dto(item) for item in items]})

    @app.get("/api/v1/users/<int:user_id>/notifications/poll")
    def poll_notifications(user_id):
        """Devuelve avisos nuevos desde el id indicado para el navegador."""
        session = g.notification_session
        latest_id = session.scalar(
            select(Notification.id)
            .where(Notification.user_id == user_id)
            .order_by(Notification.id.desc())
            .limit(1)
        ) or 0
        after = request.args.get("after", "0")
        try:
            after_id = max(0, int(after))
        except ValueError:
            return jsonify({"error": "El identificador no es válido."}), 400
        items = session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.id > after_id)
            .order_by(Notification.id)
            .limit(10)
        ).all()
        return jsonify({
            "latest_id": latest_id,
            "notifications": [_notification_dto(item) for item in items],
        })

    @app.post("/api/v1/users/<int:user_id>/notifications")
    def create_notification(user_id):
        """Persiste un aviso con clave idempotente para un usuario externo."""
        payload = request.get_json(silent=True) or {}
        title, message = payload.get("title"), payload.get("message")
        notification_type = payload.get("type", "general")
        dedupe_key = payload.get("dedupe_key")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 120
            or not isinstance(message, str)
            or not message.strip()
            or len(message) > 2000
            or notification_type not in {"event", "routine", "general"}
            or (dedupe_key is not None and (not isinstance(dedupe_key, str) or len(dedupe_key) > 160))
        ):
            return jsonify({"error": "Los datos de la notificación no son válidos."}), 400
        item, created = NotificationService(g.notification_session).create(
            user_id,
            title.strip(),
            message,
            dedupe_key,
            notification_type,
        )
        return jsonify({"notification": _notification_dto(item), "created": created}), 201 if created else 200

    @app.post("/api/v1/users/<int:user_id>/notifications/<int:notification_id>/read")
    def mark_notification_read(user_id, notification_id):
        """Marca como leído un aviso propio."""
        found = NotificationService(g.notification_session).mark_read(notification_id, user_id)
        return jsonify({"updated": found}), 200 if found else 404

    @app.post("/api/v1/users/<int:user_id>/notifications/read-all")
    def mark_all_notifications_read(user_id):
        """Marca como leídos todos los avisos del usuario indicado."""
        NotificationService(g.notification_session).mark_all_read(user_id)
        return jsonify({"updated": True})

    @app.delete("/api/v1/users/<int:user_id>/notifications/<int:notification_id>")
    def dismiss_notification(user_id, notification_id):
        """Elimina un aviso solo si pertenece al usuario indicado."""
        found = NotificationService(g.notification_session).dismiss(notification_id, user_id)
        return jsonify({"deleted": found}), 200 if found else 404

    @app.post("/api/v1/users/<int:user_id>/push-subscriptions")
    def save_push_subscription(user_id):
        """Valida y guarda una suscripción push dentro de una cuenta."""
        payload = request.get_json(silent=True) or {}
        subscription = payload.get("subscription")
        if not valid_push_subscription(subscription):
            return jsonify({"error": "La suscripción push no es válida."}), 400
        saved = NotificationService(g.notification_session).save_subscription(
            user_id,
            subscription["endpoint"],
            subscription["keys"]["p256dh"],
            subscription["keys"]["auth"],
        )
        return jsonify({"saved": saved}), 201 if saved else 409

    @app.delete("/api/v1/users/<int:user_id>/push-subscriptions")
    def delete_push_subscription(user_id):
        """Elimina una suscripción push propia por endpoint."""
        endpoint = (request.get_json(silent=True) or {}).get("endpoint")
        if not isinstance(endpoint, str):
            return jsonify({"error": "Indica el endpoint que se quitará."}), 400
        NotificationService(g.notification_session).remove_subscription(user_id, endpoint)
        return jsonify({"deleted": True})

    @app.delete("/api/v1/users/<int:user_id>/data")
    def delete_user_data(user_id):
        """Borra avisos y suscripciones de la cuenta en este servicio."""
        NotificationService(g.notification_session).delete_user_data(user_id)
        return jsonify({"deleted": True})

    @app.get("/api/v1/push-key")
    def get_push_key():
        """Devuelve la clave pública VAPID si el canal push está activo."""
        if not push_is_configured(current_app.config):
            return jsonify({"configured": False}), 503
        return jsonify({"configured": True, "public_key": current_app.config["VAPID_PUBLIC_KEY"]})

    @app.get("/api/v1/capabilities")
    def capabilities():
        """Informa qué transportes de entrega están configurados."""
        return jsonify({
            "email_configured": email_is_configured(current_app.config),
            "push_configured": push_is_configured(current_app.config),
        })

    @app.post("/api/v1/email")
    def deliver_email():
        """Valida un mensaje transaccional y lo entrega mediante SMTP."""
        if not email_is_configured(current_app.config):
            return jsonify({"error": "El correo no está configurado."}), 503

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Se requiere un objeto JSON."}), 400
        recipient = payload.get("to")
        subject = payload.get("subject")
        body = payload.get("body")
        if (
            not isinstance(recipient, str)
            or not EMAIL_PATTERN.fullmatch(recipient)
            or not isinstance(subject, str)
            or not subject.strip()
            or len(subject) > 200
            or "\r" in subject
            or "\n" in subject
            or not isinstance(body, str)
            or not body.strip()
            or len(body) > 20000
        ):
            return jsonify({"error": "Los datos del correo no son válidos."}), 400

        try:
            send_email(recipient, subject.strip(), body, current_app.config)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            current_app.logger.error("Delivery service email failed: %s", error)
            return jsonify({"error": "No se pudo entregar el correo."}), 502
        return jsonify({"sent": True})

    @app.post("/api/v1/push")
    def deliver_push():
        """Entrega una notificación a las suscripciones incluidas en la solicitud."""
        if not push_is_configured(current_app.config):
            return jsonify({"error": "Web Push no está configurado."}), 503

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Se requiere un objeto JSON."}), 400
        title = payload.get("title")
        body = payload.get("body")
        tag = payload.get("tag", "planify-notification")
        target_url = payload.get("url", "/notifications")
        subscriptions = payload.get("subscriptions")
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 120
            or not isinstance(body, str)
            or len(body) > 2000
            or not isinstance(tag, str)
            or len(tag) > 120
            or not isinstance(target_url, str)
            or not target_url.startswith("/")
            or target_url.startswith("//")
            or not isinstance(subscriptions, list)
            or len(subscriptions) > 100
        ):
            return jsonify({"error": "Los datos de la notificación no son válidos."}), 400

        result = send_push(
            subscriptions,
            title.strip(),
            body,
            target_url,
            tag,
            current_app.config,
            current_app.logger,
        )
        return jsonify(result)

    if app.config.get("ENABLE_NOTIFICATION_SCHEDULER") and not app.config.get("TESTING"):
        from notification_service.scheduler import start_notification_scheduler

        app.extensions["notification_scheduler"] = start_notification_scheduler(app)

    return app


def _notification_dto(item):
    """Convierte un aviso ORM en un contrato JSON sin estado interno de envío."""
    return {
        "id": item.id,
        "user_id": item.user_id,
        "title": item.title,
        "message": item.message,
        "type": item.notification_type,
        "created_at": item.created_at.isoformat(),
        "is_read": item.is_read,
    }