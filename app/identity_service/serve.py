"""Inicia el microservicio de identidad con Waitress."""

import os

from waitress import serve

from identity_service.app import create_app


app = create_app()


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=int(os.environ.get("IDENTITY_PORT", "8101")))