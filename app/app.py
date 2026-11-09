"""Punto de entrada Flask para ejecutar Planify en desarrollo local."""

from planify import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
