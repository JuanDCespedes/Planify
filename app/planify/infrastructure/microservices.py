"""Clientes HTTP internos para identidad, planificación y notificaciones."""

from datetime import date, datetime, time
from types import SimpleNamespace

import requests
from flask import current_app


class ServiceApiError(RuntimeError):
    """Error controlado al invocar un servicio interno de Planify."""

    def __init__(self, message, status_code=503):
        """Conserva mensaje y estado HTTP para traducir fallos a la interfaz."""
        super().__init__(message)
        self.status_code = status_code


class RemoteUser(SimpleNamespace):
    """Vista de usuario obtenida desde identidad, sin acceso a su ORM."""

    @property
    def is_authenticated(self):
        """Indica que la sesión local representa una identidad válida."""
        return True

    @property
    def is_active(self):
        """Permite a Flask-Login utilizar esta identidad remota."""
        return True

    @property
    def is_anonymous(self):
        """Indica que el usuario remoto no es anónimo."""
        return False

    def get_id(self):
        """Devuelve el identificador de identidad para la cookie Flask-Login."""
        return str(self.id)


def _namespace(payload):
    """Convierte un DTO recursivo en objetos con atributos para las plantillas."""
    if isinstance(payload, dict):
        values = {key: _namespace(value) for key, value in payload.items()}
        for field in ("event_date",):
            if isinstance(values.get(field), str):
                values[field] = date.fromisoformat(values[field])
        if isinstance(values.get("start_time"), str):
            values["start_time"] = time.fromisoformat(values["start_time"])
        if isinstance(values.get("created_at"), str):
            values["created_at"] = datetime.fromisoformat(values["created_at"])
        return SimpleNamespace(**values)
    if isinstance(payload, list):
        return [_namespace(item) for item in payload]
    return payload


class ServiceClients:
    """Agrupa clientes REST y convierte DTOs en vistas para el gateway."""

    def __init__(self, config=None):
        """Obtiene URLs y token de la configuración de Flask o de prueba."""
        self.config = config or current_app.config
        self.token = self.config.get("SERVICE_TOKEN", "")
        self.identity_url = self.config.get("IDENTITY_SERVICE_URL", "").rstrip("/")
        self.planning_url = self.config.get("PLANNING_SERVICE_URL", "").rstrip("/")
        self.notifications_url = self.config.get("NOTIFICATION_SERVICE_URL", "").rstrip("/")

    def _request(self, service_url, method, path, payload=None, params=None):
        """Realiza una llamada autenticada y normaliza fallos HTTP o de red."""
        if not service_url or not self.token:
            raise ServiceApiError("Los servicios internos no están configurados.")
        try:
            response = requests.request(
                method,
                f"{service_url}{path}",
                json=payload,
                params=params,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.config.get("SERVICE_REQUEST_TIMEOUT", 5),
            )
        except requests.RequestException as error:
            raise ServiceApiError("Un servicio interno no está disponible.") from error
        try:
            data = response.json()
        except ValueError:
            data = {}
        if not response.ok:
            message = data.get("errors", [data.get("error", "La solicitud al servicio falló.")])
            if isinstance(message, list):
                message = "; ".join(str(item) for item in message)
            raise ServiceApiError(str(message), response.status_code)
        return data

    def identity(self, method, path, payload=None):
        """Invoca un endpoint interno de identidad."""
        return self._request(self.identity_url, method, path, payload)

    def planning(self, method, path, payload=None, params=None):
        """Invoca un endpoint interno de planificación."""
        return self._request(self.planning_url, method, path, payload, params)

    def notifications(self, method, path, payload=None, params=None):
        """Invoca un endpoint interno de notificaciones."""
        return self._request(self.notifications_url, method, path, payload, params)

    def get_user(self, user_id):
        """Obtiene una cuenta remota para Flask-Login o devuelve None."""
        try:
            return RemoteUser(**self.identity("GET", f"/api/v1/users/{user_id}")["user"])
        except ServiceApiError as error:
            if error.status_code == 404:
                return None
            raise

    def authenticate(self, email, password):
        """Valida credenciales mediante el servicio de identidad."""
        try:
            return RemoteUser(**self.identity(
                "POST", "/api/v1/users/authenticate", {"email": email, "password": password}
            )["user"]), []
        except ServiceApiError as error:
            return None, [str(error)]

    def verify_password(self, user_id, password):
        """Comprueba una contraseña antes de mutar datos sensibles de identidad."""
        result = self.identity(
            "POST",
            f"/api/v1/users/{user_id}/verify-password",
            {"password": password},
        )
        return result.get("valid", False)

    def update_profile(self, user_id, payload):
        """Actualiza el perfil remoto y devuelve la identidad actualizada."""
        return RemoteUser(**self.identity(
            "PATCH", f"/api/v1/users/{user_id}/profile", payload
        )["user"])

    def update_password(self, user_id, payload):
        """Cambia la contraseña por medio del servicio propietario de credenciales."""
        return RemoteUser(**self.identity(
            "PATCH", f"/api/v1/users/{user_id}/password", payload
        )["user"])

    def update_preferences(self, user_id, payload):
        """Guarda preferencias de notificación en el servicio de identidad."""
        return RemoteUser(**self.identity(
            "PATCH", f"/api/v1/users/{user_id}/preferences", payload
        )["user"])

    def delete_account(self, user_id):
        """Elimina los datos de dominio y la identidad como una saga ordenada."""
        self.planning("DELETE", f"/api/v1/users/{user_id}/data")
        self.notifications("DELETE", f"/api/v1/users/{user_id}/data")
        self.identity("DELETE", f"/api/v1/users/{user_id}")

    def register(self, email, password, confirmation):
        """Registra una cuenta y aprovisiona sus categorías iniciales."""
        try:
            user = RemoteUser(**self.identity(
                "POST",
                "/api/v1/users/register",
                {"email": email, "password": password, "confirmation": confirmation},
            )["user"])
            self.planning("POST", f"/api/v1/users/{user.id}/bootstrap")
            return user, []
        except ServiceApiError as error:
            return None, [str(error)]

    def authenticate_google(self, email, subject, display_name):
        """Autentica un perfil Google ya verificado por el gateway OAuth."""
        try:
            user = self.identity(
                "POST",
                "/api/v1/users/google",
                {
                    "email": email,
                    "subject": subject,
                    "display_name": display_name,
                    "email_verified": True,
                },
            )["user"]
            remote_user = RemoteUser(**user)
            self.planning("POST", f"/api/v1/users/{remote_user.id}/bootstrap")
            return remote_user, []
        except ServiceApiError as error:
            return None, [str(error)]

    def events_between(self, user_id, start_date, end_date):
        """Lista eventos del usuario y convierte fechas para las plantillas."""
        data = self.planning(
            "GET",
            f"/api/v1/users/{user_id}/events",
            params={"start": start_date.isoformat(), "end": end_date.isoformat()},
        )
        return _namespace(data["events"])

    def event(self, user_id, event_id):
        """Obtiene un evento propio o devuelve None si no existe."""
        try:
            return _namespace(self.planning(
                "GET", f"/api/v1/users/{user_id}/events/{event_id}"
            )["event"])
        except ServiceApiError as error:
            if error.status_code == 404:
                return None
            raise

    def delete_event(self, user_id, event_id):
        """Elimina un evento dentro de la base propiedad de planificación."""
        self.planning("DELETE", f"/api/v1/users/{user_id}/events/{event_id}")

    def save_event(self, user_id, event_id, payload):
        """Crea o edita un evento remoto y devuelve el objeto o errores."""
        method = "PUT" if event_id else "POST"
        path = f"/api/v1/users/{user_id}/events"
        if event_id:
            path += f"/{event_id}"
        try:
            return _namespace(self.planning(method, path, payload)["event"]), []
        except ServiceApiError as error:
            return None, [str(error)]

    def categories(self, user_id):
        """Lista categorías remotas del usuario."""
        return _namespace(self.planning(
            "GET", f"/api/v1/users/{user_id}/categories"
        )["categories"])

    def create_category(self, user_id, payload):
        """Crea una categoría personal mediante el servicio de planificación."""
        return self.planning("POST", f"/api/v1/users/{user_id}/categories", payload)

    def update_category(self, user_id, category_id, payload):
        """Actualiza una categoría propia en el servicio de planificación."""
        return self.planning(
            "PATCH", f"/api/v1/users/{user_id}/categories/{category_id}", payload
        )

    def delete_category(self, user_id, category_id):
        """Elimina una categoría propia si no tiene eventos asociados."""
        return self.planning(
            "DELETE", f"/api/v1/users/{user_id}/categories/{category_id}"
        )

    def routines(self, user_id, day=None):
        """Lista bloques remotos de rutina, opcionalmente de un día."""
        params = {"day": day} if day is not None else None
        return _namespace(self.planning(
            "GET", f"/api/v1/users/{user_id}/routines", params=params
        )["routines"])

    def add_routine(self, user_id, payload):
        """Crea un bloque semanal en el servicio de planificación."""
        try:
            return _namespace(self.planning(
                "POST", f"/api/v1/users/{user_id}/routines", payload
            )["routine"]), []
        except ServiceApiError as error:
            return None, [str(error)]

    def notification_list(self, user_id):
        """Lista avisos persistidos por el servicio de notificaciones."""
        return _namespace(self.notifications(
            "GET", f"/api/v1/users/{user_id}/notifications"
        )["notifications"])

    def poll_notifications(self, user_id, after=None):
        """Consulta avisos incrementales para la sesión del navegador."""
        params = {"after": after} if after is not None else None
        return self.notifications(
            "GET", f"/api/v1/users/{user_id}/notifications/poll", params=params
        )

    def mark_notification_read(self, user_id, notification_id):
        """Marca un aviso propio como leído."""
        return self.notifications(
            "POST", f"/api/v1/users/{user_id}/notifications/{notification_id}/read"
        )

    def mark_all_notifications_read(self, user_id):
        """Marca como leídos todos los avisos propios."""
        return self.notifications(
            "POST", f"/api/v1/users/{user_id}/notifications/read-all"
        )

    def dismiss_notification(self, user_id, notification_id):
        """Elimina un aviso propio del centro de notificaciones."""
        return self.notifications(
            "DELETE", f"/api/v1/users/{user_id}/notifications/{notification_id}"
        )

    def push_public_key(self):
        """Obtiene la clave pública VAPID desde el servicio de notificaciones."""
        return self.notifications("GET", "/api/v1/push-key")

    def save_push_subscription(self, user_id, subscription):
        """Registra una suscripción de navegador en notificaciones."""
        return self.notifications(
            "POST",
            f"/api/v1/users/{user_id}/push-subscriptions",
            {"subscription": subscription},
        )

    def delete_push_subscription(self, user_id, endpoint):
        """Quita una suscripción de navegador propia."""
        return self.notifications(
            "DELETE",
            f"/api/v1/users/{user_id}/push-subscriptions",
            {"endpoint": endpoint},
        )