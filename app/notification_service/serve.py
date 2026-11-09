"""Inicia el microservicio de entrega con Waitress."""

import os

from waitress import serve

from notification_service.app import create_app


app = create_app()


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=int(os.environ.get("DELIVERY_PORT", "8100")))