"""Fábrica de la aplicación Flask y configuración de extensiones de Planify."""

import os

from flask import Flask
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from planify.config import Config
from planify.domain.models import User
from planify.extensions import limiter
from planify.infrastructure.database import init_database
from planify.infrastructure.security import register_security_handlers
from planify.presentation.routes import main


login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_object=Config):
    """Crea y configura una instancia de Planify.

    Registra extensiones y rutas, inicializa la base de datos y habilita el
    planificador de notificaciones cuando corresponde a la configuración.
    """
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    if app.config.get("ENVIRONMENT") == "production":
        secret_key = app.config.get("SECRET_KEY")
        if not secret_key or secret_key == "dev-only-change-me" or len(secret_key) < 32:
            raise RuntimeError("Configura PLANIFY_SECRET_KEY con una clave aleatoria de al menos 32 caracteres.")
        app.config["SESSION_COOKIE_SECURE"] = True
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.login"
    login_manager.login_message = "Inicia sesión para acceder a tu planificador."
    login_manager.login_message_category = "info"
    limiter.init_app(app)
    oauth = OAuth(app)
    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    app.extensions["planify_oauth"] = oauth
    app.register_blueprint(main)
    init_database(app)
    is_debug_reloader_parent = app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true"
    if (
        app.config.get("ENABLE_NOTIFICATION_SCHEDULER")
        and not app.config.get("TESTING")
        and not is_debug_reloader_parent
    ):
        from planify.infrastructure.notification_scheduler import start_notification_scheduler

        app.extensions["planify_notification_scheduler"] = start_notification_scheduler(app)
    register_security_handlers(app)
    return app


@login_manager.user_loader
def load_user(user_id):
    """Recupera de la base de datos al usuario asociado a una sesión Flask-Login."""
    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    from planify.infrastructure.database import get_session

    return get_session().get(User, parsed_user_id)
