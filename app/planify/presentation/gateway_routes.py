"""Rutas HTML que presentan datos obtenidos exclusivamente de microservicios."""

import calendar
import secrets
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_user, logout_user
from joserfc.errors import JoseError
from requests.exceptions import RequestException

from planify.domain.rules import CATEGORY_COLORS, REMINDER_PREFERENCE_FIELDS, REMINDERS
from planify.extensions import limiter
from planify.infrastructure.microservices import RemoteUser, ServiceApiError, ServiceClients


main = Blueprint("main", __name__)
MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


@main.app_context_processor
def template_helpers():
    """Expone formato horario local y etiquetas compartidas a las plantillas."""
    def local_datetime(value):
        """Interpreta valores sin zona como UTC y convierte a la zona configurada."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo(current_app.config.get("TIMEZONE", "America/Bogota")))

    def format_local_datetime(value, format_string="%d/%m · %H:%M"):
        """Formatea una fecha después de convertirla a la zona de la aplicación."""
        return local_datetime(value).strftime(format_string)

    return {
        "category_labels": {},
        "format_local_datetime": format_local_datetime,
        "local_datetime": local_datetime,
    }


@main.before_request
def require_signed_in_user():
    """Restringe las vistas de negocio a sesiones emitidas por identidad."""
    public = {
        "main.login",
        "main.register",
        "main.forgot_password",
        "main.google_login",
        "main.google_callback",
    }
    if request.endpoint and request.endpoint.startswith("main.") and request.endpoint not in public and not current_user.is_authenticated:
        flash("Inicia sesión para acceder a tu planificador.", "info")
        return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
    return None


@main.app_errorhandler(ServiceApiError)
def handle_service_error(error):
    """Devuelve un error controlado si identidad, planificación o avisos caen."""
    current_app.logger.error("Microservice request failed: %s", error)
    if request.path.startswith("/api/"):
        return jsonify({"error": "Planify no está disponible temporalmente."}), 503
    return render_template("service_unavailable.html"), 503


def _safe_redirect_target(target):
    """Permite únicamente destinos relativos dentro del mismo sitio."""
    if not target:
        return None
    parsed = urlsplit(target)
    return target if target.startswith("/") and not target.startswith("//") and not parsed.scheme and not parsed.netloc else None


def _render_service_error(error):
    """Traduce una indisponibilidad interna a una respuesta comprensible."""
    current_app.logger.error("Gateway service call failed: %s", error)
    return render_template("auth/base_auth.html"), 503


@main.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    """Autentica contra identidad y crea una sesión de presentación."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    email = request.form.get("email", "")
    errors = []
    if request.method == "POST":
        user, errors = ServiceClients().authenticate(email, request.form.get("password", ""))
        if user:
            login_user(user, fresh=True)
            return redirect(_safe_redirect_target(request.values.get("next", "")) or url_for("main.dashboard"))
    return render_template(
        "auth/login.html",
        email=email,
        errors=errors,
        next_url=request.values.get("next", ""),
        google_configured=bool(current_app.config.get("GOOGLE_CLIENT_ID") and current_app.config.get("GOOGLE_CLIENT_SECRET")),
    )


@main.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def register():
    """Crea una cuenta remota y aprovisiona sus categorías iniciales."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    email = request.form.get("email", "")
    errors = []
    if request.method == "POST":
        user, errors = ServiceClients().register(
            email,
            request.form.get("password", ""),
            request.form.get("password_confirmation", ""),
        )
        if user:
            login_user(user, fresh=True)
            flash("Tu cuenta está lista. ¡Empecemos a planificar!", "success")
            return redirect(url_for("main.dashboard"))
    return render_template(
        "auth/register.html",
        email=email,
        errors=errors,
        google_configured=bool(current_app.config.get("GOOGLE_CLIENT_ID") and current_app.config.get("GOOGLE_CLIENT_SECRET")),
    ), (400 if errors else 200)


@main.route("/forgot-password")
def forgot_password():
    """Muestra la pantalla informativa de recuperación aún no habilitada."""
    return render_template("auth/forgot_password.html")


@main.route("/logout", methods=["POST"])
def logout():
    """Cierra la sesión local del gateway."""
    logout_user()
    flash("Has cerrado sesión correctamente.", "success")
    return redirect(url_for("main.login"))


@main.route("/auth/google")
@limiter.limit("10 per minute")
def google_login():
    """Inicia OAuth de Google desde el gateway si está configurado."""
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get("GOOGLE_CLIENT_SECRET"):
        flash("Google aún no está configurado.", "info")
        return redirect(url_for("main.settings" if current_user.is_authenticated else "main.login"))
    oauth = current_app.extensions["planify_oauth"].google
    if current_user.is_authenticated:
        session["google_link_user_id"] = current_user.id
    nonce = secrets.token_urlsafe(32)
    session["google_nonce"] = nonce
    redirect_uri = current_app.config.get("GOOGLE_REDIRECT_URI") or url_for("main.google_callback", _external=True)
    return oauth.authorize_redirect(redirect_uri, nonce=nonce)


@main.route("/auth/google/callback")
@limiter.limit("10 per minute")
def google_callback():
    """Valida la respuesta OpenID y delega identidad al servicio propietario."""
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get("GOOGLE_CLIENT_SECRET"):
        flash("Google aún no está configurado.", "error")
        return redirect(url_for("main.login"))
    try:
        token = current_app.extensions["planify_oauth"].google.authorize_access_token()
    except (OAuthError, JoseError, RequestException) as error:
        current_app.logger.warning("Google sign-in failed: %s", error)
        flash("No pudimos validar el acceso con Google. Inténtalo de nuevo.", "error")
        return redirect(url_for("main.login"))
    profile = token.get("userinfo")
    if not profile or profile.get("email_verified") is not True or not isinstance(profile.get("email"), str) or not isinstance(profile.get("sub"), str):
        flash("Google no confirmó tu correo. No se inició sesión.", "error")
        return redirect(url_for("main.login"))
    if session.get("google_link_user_id") and profile["email"].strip().casefold() != current_user.email:
        session.pop("google_link_user_id", None)
        flash("Para conectar Google, confirma el mismo correo de tu cuenta.", "error")
        return redirect(url_for("main.settings"))
    user, errors = ServiceClients().authenticate_google(
        profile["email"],
        profile["sub"],
        profile.get("name", "") if isinstance(profile.get("name", ""), str) else "",
    )
    session.pop("google_link_user_id", None)
    if errors:
        flash(errors[0], "error")
        return redirect(url_for("main.login"))
    login_user(user, fresh=True)
    session["google_authenticated_at"] = int(clock.time())
    flash("Has iniciado sesión con Google.", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/")
def dashboard():
    """Compone el panel usando APIs de planificación y notificaciones."""
    today = date.today()
    clients = ServiceClients()
    todays_events = clients.events_between(current_user.id, today, today)
    upcoming = clients.events_between(current_user.id, today + timedelta(days=1), today + timedelta(days=7))
    unread_count = 0
    if current_user.in_app_notifications:
        unread_count = sum(not item.is_read for item in clients.notification_list(current_user.id))
    return render_template(
        "dashboard.html",
        today=today,
        todays_events=todays_events,
        upcoming=upcoming,
        unread_count=unread_count,
    )


@main.route("/calendar")
def calendar_view():
    """Muestra el calendario mensual con eventos devueltos por planificación."""
    today = date.today()
    try:
        year, month = (int(part) for part in request.args.get("month", f"{today.year}-{today.month:02}").split("-"))
        if not 1 <= month <= 12 or not 1 <= year <= 9999:
            raise ValueError
    except ValueError:
        flash("El mes solicitado no es válido.", "error")
        return redirect(url_for("main.calendar_view"))
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    clients = ServiceClients()
    events = clients.events_between(current_user.id, month_start, month_end)
    events_by_day = {}
    for event in events:
        events_by_day.setdefault(event.event_date.day, []).append(event)
    previous = month_start if (year, month) == (1, 1) else month_start - timedelta(days=1)
    next_month = month_start if (year, month) == (9999, 12) else month_end + timedelta(days=1)
    return render_template(
        "calendar.html",
        year=year,
        month=month,
        categories=clients.categories(current_user.id),
        month_name=MONTHS[month - 1].capitalize(),
        weekdays=WEEKDAYS,
        weeks=calendar.Calendar(firstweekday=0).monthdayscalendar(year, month),
        events_by_day=events_by_day,
        today=today,
        previous_month=f"{previous.year}-{previous.month:02}",
        next_month=f"{next_month.year}-{next_month.month:02}",
    )


@main.route("/events/new", methods=["GET", "POST"])
@main.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
def event_form(event_id=None):
    """Crea o edita un evento mediante el API de planificación."""
    clients = ServiceClients()
    event = clients.event(current_user.id, event_id) if event_id is not None else None
    if event_id is not None and event is None:
        flash("No encontramos ese evento.", "error")
        return redirect(url_for("main.dashboard"))
    categories = clients.categories(current_user.id)
    default_category = next((item.name for item in categories if item.color == "work"), categories[0].name if categories else "")
    values = {
        "title": event.title if event else "",
        "event_date": event.event_date.isoformat() if event else date.today().isoformat(),
        "start_time": event.start_time.strftime("%H:%M") if event else "",
        "category": event.category_item.name if event and event.category_item else default_category,
        "reminder": event.reminder if event else current_user.default_reminder,
    }
    errors = []
    if request.method == "POST":
        values = {key: request.form.get(key, "") for key in ("title", "event_date", "start_time", "category", "reminder")}
        saved, errors = clients.save_event(current_user.id, event_id, values)
        if saved:
            flash("Evento guardado. ¡Tu día va tomando forma!", "success")
            return redirect(url_for("main.dashboard"))
    return render_template(
        "event_form.html",
        event=event,
        values=values,
        errors=errors,
        categories=categories,
        reminders={
            key: label for key, label in REMINDERS.items()
            if getattr(current_user, REMINDER_PREFERENCE_FIELDS[key]) or (event and event.reminder == key)
        },
    ), (400 if errors else 200)


@main.route("/events/<int:event_id>/delete", methods=["POST"])
def delete_event(event_id):
    """Elimina un evento por medio del servicio propietario de planificación."""
    clients = ServiceClients()
    if clients.event(current_user.id, event_id) is None:
        flash("No encontramos ese evento.", "error")
    else:
        clients.delete_event(current_user.id, event_id)
        flash("Evento eliminado.", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/routine", methods=["GET", "POST"])
def routine():
    """Muestra y crea bloques de rutina mediante planificación."""
    today = date.today()
    clients = ServiceClients()
    errors = []
    form_values = {"title": "", "start_time": "", "duration_minutes": "30"}
    if request.method == "POST":
        form_values = {key: request.form.get(key, "") for key in ("title", "start_time", "duration_minutes")}
        _, errors = clients.add_routine(
            current_user.id,
            {**form_values, "day_of_week": today.weekday()},
        )
        if not errors:
            flash("Bloque añadido a tu rutina.", "success")
            return redirect(url_for("main.routine"))
    return render_template(
        "routine.html",
        today=today,
        blocks=clients.routines(current_user.id, today.weekday()),
        errors=errors,
        form_values=form_values,
    ), (400 if errors else 200)


@main.route("/notifications")
def notifications():
    """Muestra avisos propios guardados por el microservicio de notificaciones."""
    items = ServiceClients().notification_list(current_user.id)
    return render_template(
        "notifications.html",
        notifications=items,
        unread_count=sum(not item.is_read for item in items),
    )


@main.route("/api/notifications")
def poll_notifications():
    """Adapta la consulta de navegador al API incremental de notificaciones."""
    clients = ServiceClients()
    if not current_user.in_app_notifications:
        return jsonify({"notifications": [], "latest_id": 0})
    after = request.args.get("after")
    result = clients.poll_notifications(current_user.id, after)
    if after is None:
        result["notifications"] = []
    return jsonify(result)


@main.route("/api/notifications/push-key")
def push_public_key():
    """Devuelve la clave VAPID pública desde el servicio de notificaciones."""
    try:
        return jsonify(ServiceClients().push_public_key())
    except ServiceApiError as error:
        return jsonify({"configured": False, "error": str(error)}), error.status_code


@main.route("/api/notifications/push-subscription", methods=["POST"])
def save_push_subscription():
    """Registra en notificaciones la suscripción del navegador actual."""
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(ServiceClients().save_push_subscription(current_user.id, payload.get("subscription")))
    except ServiceApiError as error:
        return jsonify({"error": str(error)}), error.status_code


@main.route("/api/notifications/push-subscription", methods=["DELETE"])
def delete_push_subscription():
    """Elimina una suscripción push propia mediante el API de notificaciones."""
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(ServiceClients().delete_push_subscription(current_user.id, payload.get("endpoint")))
    except ServiceApiError as error:
        return jsonify({"error": str(error)}), error.status_code


@main.route("/service-worker.js")
def service_worker():
    """Sirve el service worker desde la raíz para habilitar Web Push."""
    response = make_response(send_from_directory(current_app.static_folder, "service-worker.js"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@main.route("/notifications/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    """Marca como leído un aviso propio."""
    try:
        ServiceClients().mark_notification_read(current_user.id, notification_id)
    except ServiceApiError:
        flash("No encontramos esa notificación.", "error")
    return redirect(url_for("main.notifications"))


@main.route("/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    """Marca como leídos todos los avisos propios."""
    ServiceClients().mark_all_notifications_read(current_user.id)
    flash("Todas las notificaciones están marcadas como leídas.", "success")
    return redirect(url_for("main.notifications"))


@main.route("/notifications/<int:notification_id>/dismiss", methods=["POST"])
def dismiss_notification(notification_id):
    """Descarta un aviso propio y confirma el resultado al usuario."""
    try:
        ServiceClients().dismiss_notification(current_user.id, notification_id)
        flash("Notificación descartada.", "success")
    except ServiceApiError:
        flash("No encontramos esa notificación.", "error")
    return redirect(url_for("main.notifications"))


@main.route("/settings")
def settings():
    """Muestra preferencias de identidad y categorías de planificación."""
    clients = ServiceClients()
    try:
        push_configured = clients.push_public_key().get("configured", False)
    except ServiceApiError:
        push_configured = False
    return render_template(
        "settings.html",
        categories=clients.categories(current_user.id),
        category_colors=CATEGORY_COLORS,
        reminders=REMINDERS,
        enabled_reminders={key: label for key, label in REMINDERS.items() if getattr(current_user, REMINDER_PREFERENCE_FIELDS[key])},
        reminder_preference_fields=REMINDER_PREFERENCE_FIELDS,
        google_configured=bool(current_app.config.get("GOOGLE_CLIENT_ID") and current_app.config.get("GOOGLE_CLIENT_SECRET")),
        push_configured=push_configured,
        smtp_configured=current_app.config.get("DELIVERY_EMAIL_ENABLED", False),
    )


@main.route("/settings/profile", methods=["POST"])
def update_profile():
    """Actualiza el perfil remoto, exigiendo contraseña al cambiar el correo."""
    clients = ServiceClients()
    email = request.form.get("email", "").strip().casefold()
    payload = {"email": email, "display_name": request.form.get("display_name", "").strip()}
    if email != current_user.email:
        if not current_user.password_login_enabled:
            flash("Configura una contraseña antes de cambiar el correo.", "error")
            return redirect(url_for("main.settings"))
        if not clients.verify_password(current_user.id, request.form.get("current_password", "")):
            flash("Confirma tu contraseña actual para cambiar el correo.", "error")
            return redirect(url_for("main.settings"))
    try:
        clients.update_profile(current_user.id, payload)
        flash("Tu perfil se actualizó correctamente.", "success")
    except ServiceApiError as error:
        flash(str(error), "error")
    return redirect(url_for("main.settings"))


@main.route("/settings/password", methods=["POST"])
def update_password():
    """Cambia o habilita la contraseña remota con comprobación reciente."""
    current_password = request.form.get("current_password", "")
    if not current_user.password_login_enabled and clock.time() - session.get("google_authenticated_at", 0) > 600:
        flash("Vuelve a iniciar sesión con Google y repite la acción en menos de 10 minutos.", "error")
        return redirect(url_for("main.settings"))
    try:
        ServiceClients().update_password(
            current_user.id,
            {
                "current_password": current_password,
                "password": request.form.get("new_password", ""),
                "confirmation": request.form.get("password_confirmation", ""),
            },
        )
        flash("Tu contraseña se actualizó correctamente.", "success")
    except ServiceApiError as error:
        flash(str(error), "error")
    return redirect(url_for("main.settings"))


@main.route("/settings/preferences", methods=["POST"])
def update_preferences():
    """Valida y delega todas las preferencias de aviso al servicio de identidad."""
    payload = {}
    for field in REMINDER_PREFERENCE_FIELDS.values():
        payload[field] = request.form.get(field) == "on"
    enabled = [key for key, field in REMINDER_PREFERENCE_FIELDS.items() if payload[field]]
    if not enabled:
        flash("Mantén activo al menos un tipo de recordatorio.", "error")
        return redirect(url_for("main.settings"))
    selected = request.form.get("default_reminder", current_user.default_reminder)
    payload["default_reminder"] = selected if selected in enabled else enabled[0]
    for field in (
        "routine_notify_start", "routine_notify_5_minutes", "routine_notification_sounds",
        "desktop_push_notifications", "email_notifications", "weekly_email_summaries",
        "in_app_notifications", "quiet_hours_enabled",
    ):
        payload[field] = request.form.get(field) == "on"
    payload["quiet_hours_start"] = request.form.get("quiet_hours_start", "")
    payload["quiet_hours_end"] = request.form.get("quiet_hours_end", "")
    try:
        ServiceClients().update_preferences(current_user.id, payload)
        flash("La configuración de notificaciones se guardó.", "success")
    except ServiceApiError as error:
        flash(str(error), "error")
    return redirect(url_for("main.settings"))


@main.route("/settings/default-reminder", methods=["POST"])
def update_default_reminder():
    """Actualiza la anticipación predeterminada en identidad."""
    try:
        ServiceClients().update_preferences(
            current_user.id,
            {"default_reminder": request.form.get("default_reminder", "")},
        )
        flash("Tu recordatorio predeterminado se actualizó.", "success")
    except ServiceApiError as error:
        flash(str(error), "error")
    return redirect(url_for("main.settings"))


@main.route("/settings/categories", methods=["POST"])
def create_category():
    """Crea una categoría en el servicio de planificación."""
    clients = ServiceClients()
    try:
        clients.create_category(current_user.id, {"name": request.form.get("name", ""), "color": request.form.get("color", "")})
        flash("Categoría creada.", "success")
    except ServiceApiError as error:
        flash(str(error), "error")
    return redirect(url_for("main.settings"))


@main.route("/settings/categories/<int:category_id>", methods=["POST"])
def update_category(category_id):
    """Actualiza una categoría en el servicio de planificación."""
    clients = ServiceClients()
    try:
        clients.update_category(current_user.id, category_id, {"name": request.form.get("name", ""), "color": request.form.get("color", "")})
        flash("Categoría actualizada.", "success")
    except ServiceApiError as error:
        flash(str(error), "error")
    return redirect(url_for("main.settings"))


@main.route("/settings/categories/<int:category_id>/delete", methods=["POST"])
def delete_category(category_id):
    """Elimina una categoría en el servicio de planificación."""
    try:
        ServiceClients().delete_category(current_user.id, category_id)
        flash("Categoría eliminada.", "success")
    except ServiceApiError as error:
        flash(str(error), "error")
    return redirect(url_for("main.settings"))


@main.route("/settings/account/delete", methods=["POST"])
def delete_account():
    """Orquesta la eliminación de datos distribuidos antes de borrar identidad."""
    clients = ServiceClients()
    if request.form.get("confirm_email", "").strip().casefold() != current_user.email:
        flash("Escribe el correo de tu cuenta para confirmar la eliminación.", "error")
        return redirect(url_for("main.settings"))
    if request.form.get("confirmation", "").strip() != "ELIMINAR":
        flash("Escribe ELIMINAR para confirmar la acción.", "error")
        return redirect(url_for("main.settings"))
    if current_user.password_login_enabled:
        if not clients.verify_password(current_user.id, request.form.get("current_password", "")):
            flash("La contraseña actual no es correcta.", "error")
            return redirect(url_for("main.settings"))
    elif clock.time() - session.get("google_authenticated_at", 0) > 600:
        flash("Vuelve a iniciar sesión con Google y repite la eliminación en menos de 10 minutos.", "error")
        return redirect(url_for("main.settings"))
    try:
        clients.delete_account(current_user.id)
    except ServiceApiError as error:
        current_app.logger.error("Account deletion saga failed: %s", error)
        flash("No fue posible completar la eliminación en todos los servicios. Contacta soporte.", "error")
        return redirect(url_for("main.settings"))
    logout_user()
    session.clear()
    flash("Tu cuenta y sus datos se eliminaron.", "success")
    return redirect(url_for("main.login"))