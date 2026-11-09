"""API interna para las cuentas, credenciales y preferencias de Planify."""

import hmac
import os
import re
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, current_app, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from identity_service.models import User, create_database


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
REMINDER_FIELDS = {
    "at_time": "reminder_at_event_enabled",
    "5m": "reminder_5_minutes_enabled",
    "15m": "reminder_15_minutes_enabled",
    "30m": "reminder_30_minutes_enabled",
    "1h": "reminder_1_hour_enabled",
    "1d": "reminder_1_day_enabled",
}
PREFERENCE_FIELDS = set(REMINDER_FIELDS.values()) | {
    "routine_notify_start",
    "routine_notify_5_minutes",
    "routine_notification_sounds",
    "desktop_push_notifications",
    "email_notifications",
    "weekly_email_summaries",
    "in_app_notifications",
    "quiet_hours_enabled",
    "quiet_hours_start",
    "quiet_hours_end",
    "default_reminder",
    "last_weekly_digest_key",
}
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))


def _serialize_user(user):
    """Convierte una cuenta ORM en un DTO sin credenciales ni secretos."""
    return {
        column.name: getattr(user, column.name)
        for column in User.__table__.columns
        if column.name not in {"password_hash", "created_at"}
    }


def create_app(test_config=None):
    """Construye el API de identidad con base de datos propia."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    app = Flask(__name__)
    instance_dir = Path(__file__).resolve().parents[1] / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        DATABASE_URL=os.environ.get(
            "IDENTITY_DATABASE_URL",
            f"sqlite:///{(instance_dir / 'identity.db').as_posix()}",
        ),
        SERVICE_TOKEN=os.environ.get(
            "PLANIFY_SERVICE_TOKEN", os.environ.get("PLANIFY_DELIVERY_SERVICE_TOKEN", "")
        ),
    )
    if test_config:
        app.config.update(test_config)
    engine, session_factory = create_database(app.config["DATABASE_URL"])
    app.extensions["identity_engine"] = engine
    app.extensions["identity_session_factory"] = session_factory

    @app.before_request
    def authenticate_internal_request():
        """Protege las rutas internas con un token Bearer compartido."""
        if request.path == "/health":
            return None
        token = current_app.config.get("SERVICE_TOKEN", "")
        supplied = request.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(supplied, f"Bearer {token}"):
            return jsonify({"error": "Autenticación interna no válida."}), 401
        g.identity_session = session_factory()
        return None

    @app.teardown_request
    def close_session(_error=None):
        """Cierra la sesión SQLAlchemy de la solicitud."""
        session = g.pop("identity_session", None)
        if session is not None:
            session.close()

    @app.get("/health")
    def health():
        """Expone una comprobación de vida sin datos de identidad."""
        return jsonify({"status": "ok"})

    @app.post("/api/v1/users/register")
    def register():
        """Valida y crea una cuenta nueva con contraseña hasheada."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Se requiere un objeto JSON."}), 400
        email = payload.get("email", "")
        password = payload.get("password", "")
        confirmation = payload.get("confirmation", "")
        normalized_email = email.strip().casefold() if isinstance(email, str) else ""
        if not EMAIL_PATTERN.fullmatch(normalized_email) or len(normalized_email) > 254:
            return jsonify({"error": "Escribe un correo electrónico válido."}), 400
        if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            return jsonify({"error": "La contraseña debe tener entre 12 y 128 caracteres."}), 400
        if password != confirmation:
            return jsonify({"error": "Las contraseñas no coinciden."}), 400
        session = g.identity_session
        user = User(email=normalized_email)
        user.set_password(password)
        session.add(user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return jsonify({"error": "Ese correo ya está registrado."}), 409
        return jsonify({"user": _serialize_user(user)}), 201

    @app.post("/api/v1/users/authenticate")
    def authenticate():
        """Valida credenciales locales y usa respuesta uniforme ante fallos."""
        payload = request.get_json(silent=True) or {}
        email = payload.get("email", "")
        password = payload.get("password", "")
        normalized_email = email.strip().casefold() if isinstance(email, str) else ""
        user = g.identity_session.scalar(select(User).where(User.email == normalized_email))
        encoded_password = password if isinstance(password, str) and len(password) <= MAX_PASSWORD_LENGTH else ""
        password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
        valid = check_password_hash(password_hash, encoded_password)
        if not user or not user.password_login_enabled or not valid:
            return jsonify({"error": "El correo o la contraseña no son correctos."}), 401
        return jsonify({"user": _serialize_user(user)})

    @app.post("/api/v1/users/google")
    def authenticate_google():
        """Busca, vincula o crea una cuenta con un correo Google verificado."""
        payload = request.get_json(silent=True) or {}
        email = payload.get("email")
        subject = payload.get("subject")
        display_name = payload.get("display_name", "")
        if (
            payload.get("email_verified") is not True
            or not isinstance(email, str)
            or not isinstance(subject, str)
            or not EMAIL_PATTERN.fullmatch(email.strip().casefold())
        ):
            return jsonify({"error": "Se requiere un perfil Google con correo verificado."}), 400
        session = g.identity_session
        normalized_email = email.strip().casefold()
        user = session.scalar(select(User).where(User.google_subject == subject))
        if user is None:
            user = session.scalar(select(User).where(User.email == normalized_email))
            if user is None:
                user = User(
                    email=normalized_email,
                    google_subject=subject,
                    display_name=display_name[:60] if isinstance(display_name, str) else "",
                    password_login_enabled=False,
                )
                user.set_password(secrets.token_urlsafe(32))
                session.add(user)
            else:
                user.google_subject = subject
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            user = session.scalar(select(User).where(User.google_subject == subject))
            if user is None:
                return jsonify({"error": "La cuenta de Google ya está vinculada."}), 409
        return jsonify({"user": _serialize_user(user)})

    @app.get("/api/v1/users")
    def list_users():
        """Devuelve datos mínimos necesarios para programar avisos por cuenta."""
        users = g.identity_session.scalars(select(User)).all()
        return jsonify({"users": [_serialize_user(user) for user in users]})

    @app.get("/api/v1/users/<int:user_id>")
    def get_user(user_id):
        """Devuelve los atributos de una cuenta sin contraseñas."""
        user = g.identity_session.get(User, user_id)
        if user is None:
            return jsonify({"error": "No encontramos la cuenta."}), 404
        return jsonify({"user": _serialize_user(user)})

    @app.post("/api/v1/users/<int:user_id>/verify-password")
    def verify_password(user_id):
        """Comprueba una contraseña actual para una operación sensible."""
        user = g.identity_session.get(User, user_id)
        password = (request.get_json(silent=True) or {}).get("password", "")
        valid = bool(user and isinstance(password, str) and user.check_password(password))
        return jsonify({"valid": valid})

    @app.patch("/api/v1/users/<int:user_id>/profile")
    def update_profile(user_id):
        """Actualiza nombre y correo, comprobando unicidad del correo."""
        session = g.identity_session
        user = session.get(User, user_id)
        payload = request.get_json(silent=True) or {}
        if user is None:
            return jsonify({"error": "No encontramos la cuenta."}), 404
        display_name = payload.get("display_name", user.display_name)
        email = payload.get("email", user.email)
        if not isinstance(display_name, str) or len(display_name) > 60:
            return jsonify({"error": "El nombre no puede superar 60 caracteres."}), 400
        normalized_email = email.strip().casefold() if isinstance(email, str) else ""
        if not EMAIL_PATTERN.fullmatch(normalized_email) or len(normalized_email) > 254:
            return jsonify({"error": "Escribe un correo electrónico válido."}), 400
        existing = session.scalar(select(User).where(User.email == normalized_email, User.id != user_id))
        if existing:
            return jsonify({"error": "Ese correo ya pertenece a otra cuenta."}), 409
        user.display_name = display_name.strip()
        user.email = normalized_email
        session.commit()
        return jsonify({"user": _serialize_user(user)})

    @app.patch("/api/v1/users/<int:user_id>/password")
    def update_password(user_id):
        """Cambia o habilita el acceso local después de validar la contraseña."""
        user = g.identity_session.get(User, user_id)
        payload = request.get_json(silent=True) or {}
        current_password = payload.get("current_password", "")
        password = payload.get("password", "")
        confirmation = payload.get("confirmation", "")
        if user is None:
            return jsonify({"error": "No encontramos la cuenta."}), 404
        if user.password_login_enabled and not user.check_password(current_password):
            return jsonify({"error": "La contraseña actual no es correcta."}), 400
        if not isinstance(password, str) or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            return jsonify({"error": "La contraseña debe tener entre 12 y 128 caracteres."}), 400
        if password != confirmation:
            return jsonify({"error": "Las contraseñas nuevas no coinciden."}), 400
        user.set_password(password)
        user.password_login_enabled = True
        g.identity_session.commit()
        return jsonify({"user": _serialize_user(user)})

    @app.patch("/api/v1/users/<int:user_id>/preferences")
    def update_preferences(user_id):
        """Valida y persiste las preferencias admitidas para la cuenta."""
        user = g.identity_session.get(User, user_id)
        payload = request.get_json(silent=True) or {}
        if user is None:
            return jsonify({"error": "No encontramos la cuenta."}), 404
        unknown = set(payload) - PREFERENCE_FIELDS
        if unknown:
            return jsonify({"error": "La solicitud incluye preferencias desconocidas."}), 400
        for field, value in payload.items():
            if field in {"quiet_hours_start", "quiet_hours_end"}:
                if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
                    return jsonify({"error": "Las horas silenciosas no son válidas."}), 400
                hour, minute = (int(part) for part in value.split(":"))
                if hour > 23 or minute > 59:
                    return jsonify({"error": "Las horas silenciosas no son válidas."}), 400
            elif field == "default_reminder":
                if value not in REMINDER_FIELDS:
                    return jsonify({"error": "El recordatorio predeterminado no es válido."}), 400
            elif field == "last_weekly_digest_key":
                if value is not None and (not isinstance(value, str) or len(value) > 8):
                    return jsonify({"error": "La clave del resumen semanal no es válida."}), 400
            elif not isinstance(value, bool):
                return jsonify({"error": "Las preferencias booleanas deben ser verdaderas o falsas."}), 400
            setattr(user, field, value)
        if not any(getattr(user, field) for field in REMINDER_FIELDS.values()):
            return jsonify({"error": "Mantén activo al menos un tipo de recordatorio."}), 400
        if user.default_reminder not in REMINDER_FIELDS or not getattr(
            user, REMINDER_FIELDS[user.default_reminder]
        ):
            user.default_reminder = next(
                key for key, field in REMINDER_FIELDS.items() if getattr(user, field)
            )
        if user.quiet_hours_enabled and user.quiet_hours_start == user.quiet_hours_end:
            return jsonify({"error": "Las horas silenciosas deben ser diferentes."}), 400
        g.identity_session.commit()
        return jsonify({"user": _serialize_user(user)})

    @app.delete("/api/v1/users/<int:user_id>")
    def delete_user(user_id):
        """Elimina la cuenta después de que el gateway borre datos de dominio."""
        user = g.identity_session.get(User, user_id)
        if user is None:
            return jsonify({"deleted": True})
        g.identity_session.delete(user)
        g.identity_session.commit()
        return jsonify({"deleted": True})

    return app