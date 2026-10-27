"""Encabezados de seguridad HTTP y respuestas para errores CSRF."""

from flask_wtf.csrf import CSRFError


def register_security_handlers(app):
    """Registra encabezados comunes y el manejador de errores CSRF en Flask."""
    @app.after_request
    def add_security_headers(response):
        """Añade encabezados defensivos sin sobrescribir valores existentes."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error):
        """Devuelve un mensaje localizado y HTTP 400 cuando falla la validación CSRF."""
        return "El formulario expiró o no es válido. Recarga la página e inténtalo de nuevo.", 400
