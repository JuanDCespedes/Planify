import os


class Config:
    SECRET_KEY = os.environ.get("PLANIFY_SECRET_KEY", "dev-only-change-me")
    DATABASE_URL = os.environ.get("PLANIFY_DATABASE_URL")
    ENVIRONMENT = os.environ.get("PLANIFY_ENV", "development").casefold()
    DEBUG = os.environ.get("PLANIFY_DEBUG", "").casefold() == "true"
    MAX_CONTENT_LENGTH = 16 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = ENVIRONMENT == "production"
    WTF_CSRF_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get("PLANIFY_RATE_LIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = True
