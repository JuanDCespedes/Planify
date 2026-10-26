from flask_wtf.csrf import CSRFError


def register_security_handlers(app):
    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error):
        return "El formulario expiró o no es válido. Recarga la página e inténtalo de nuevo.", 400
