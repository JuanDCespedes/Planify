"""Configura y expone la aplicación Flask para el servidor WSGI de PythonAnywhere."""

import os
import sys
from pathlib import Path


project_home = Path.home() / "Planify" / "app"
secret_file = Path.home() / ".planify_secret"

if not project_home.is_dir():
    raise RuntimeError(f"No se encontró el proyecto Planify en {project_home}.")
if not secret_file.is_file():
    raise RuntimeError("Genera una clave privada en ~/.planify_secret antes de cargar la aplicación.")

secret_key = secret_file.read_text(encoding="utf-8").strip()
if len(secret_key) < 32:
    raise RuntimeError("La clave privada debe tener al menos 32 caracteres.")

os.environ["PLANIFY_ENV"] = "production"
os.environ["PLANIFY_SECRET_KEY"] = secret_key
os.environ.setdefault("PLANIFY_RATE_LIMIT_STORAGE_URI", "memory://")
os.environ.setdefault(
    "PLANIFY_DATABASE_URL",
    f"sqlite:///{(project_home / 'instance' / 'planify.db').as_posix()}",
)

sys.path.insert(0, str(project_home))

from app import app as application
