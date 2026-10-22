import os


class Config:
    SECRET_KEY = os.environ.get("PLANIFY_SECRET_KEY", "dev-only-change-me")
    DATABASE_URL = os.environ.get("PLANIFY_DATABASE_URL")
