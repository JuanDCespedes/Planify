from flask import Flask

from planify.config import Config
from planify.infrastructure.database import init_database
from planify.presentation.routes import main


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    app.register_blueprint(main)
    init_database(app)
    return app
