"""Punto de entrada para ejecutar Planify en desarrollo con Flask."""

from planify import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
