from flask import Flask
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
    app.register_blueprint(main)
    init_database(app)
    register_security_handlers(app)
    return app


@login_manager.user_loader
def load_user(user_id):
    try:
        parsed_user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    from planify.infrastructure.database import get_session

    return get_session().get(User, parsed_user_id)
