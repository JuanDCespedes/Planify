"""Carga la configuración de Planify desde variables de entorno y `.env`."""

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


class Config:
    """Valores predeterminados y ajustes de seguridad para Flask y sus servicios."""

    TIMEZONE = os.environ.get("PLANIFY_TIMEZONE", "America/Bogota")
    SECRET_KEY = os.environ.get("PLANIFY_SECRET_KEY", "dev-only-change-me")
    DATABASE_URL = os.environ.get("PLANIFY_DATABASE_URL")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")
    VAPID_PUBLIC_KEY = os.environ.get("PLANIFY_VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.environ.get("PLANIFY_VAPID_PRIVATE_KEY", "")
    VAPID_CLAIMS_EMAIL = os.environ.get("PLANIFY_VAPID_CLAIMS_EMAIL", "")
    SMTP_HOST = os.environ.get("PLANIFY_SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("PLANIFY_SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("PLANIFY_SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("PLANIFY_SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("PLANIFY_SMTP_FROM", "")
    SMTP_USE_SSL = os.environ.get("PLANIFY_SMTP_USE_SSL", "").casefold() == "true"
    SMTP_STARTTLS = os.environ.get("PLANIFY_SMTP_STARTTLS", "true").casefold() == "true"
    ENABLE_NOTIFICATION_SCHEDULER = os.environ.get(
        "PLANIFY_ENABLE_NOTIFICATION_SCHEDULER", "true"
    ).casefold() == "true"
    ENVIRONMENT = os.environ.get("PLANIFY_ENV", "development").casefold()
    DEBUG = os.environ.get("PLANIFY_DEBUG", "").casefold() == "true"
    MAX_CONTENT_LENGTH = 16 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ENVIRONMENT == "production"
    WTF_CSRF_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("PLANIFY_RATE_LIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = True
