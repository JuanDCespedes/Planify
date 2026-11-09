"""Encabezados HTTP de seguridad y respuesta uniforme para errores CSRF."""

from flask_wtf.csrf import CSRFError


def register_security_handlers(app):
    """Registra encabezados de seguridad y el manejador de errores CSRF."""
    @app.after_request
    def add_security_headers(response):
        """Añade encabezados defensivos a las respuestas HTTP."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error):
        """Solicita recargar el formulario cuando falla la validación CSRF."""
        return "El formulario expiró o no es válido. Recarga la página e inténtalo de nuevo.", 400
