import base64
import binascii
import calendar
import secrets
import time as clock
from datetime import date, time, timedelta
from urllib.parse import urlsplit

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
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from planify.application.auth_service import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    AuthenticationService,
    normalize_email,
    validate_email,
)
from planify.application.services import (
    CategoryService,
    EventService,
    NotificationService,
    RoutineService,
    month_grid,
)
from planify.domain.models import Category, Event, Notification, PushSubscription, RoutineBlock
from planify.extensions import limiter
from planify.domain.rules import CATEGORY_COLORS, REMINDER_PREFERENCE_FIELDS, REMINDERS
from planify.infrastructure.database import get_session
from planify.infrastructure.notification_delivery import push_is_configured
from planify.infrastructure.repositories import UserRepository


main = Blueprint("main", __name__)
MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


@main.app_context_processor
def template_helpers():
    return {"category_labels": {}}


@main.before_request
def require_signed_in_user():
    public_endpoints = {
        "main.login",
        "main.register",
        "main.forgot_password",
        "main.google_login",
        "main.google_callback",
    }
    if (
        request.endpoint
        and request.endpoint.startswith("main.")
        and request.endpoint not in public_endpoints
        and not current_user.is_authenticated
    ):
        flash("Inicia sesión para acceder a tu planificador.", "info")
        next_url = request.full_path.rstrip("?")
        return redirect(url_for("main.login", next=next_url))
    return None


def safe_redirect_target(target):
    if not target:
        return None
    parsed = urlsplit(target)
    if target.startswith("/") and not target.startswith("//") and not parsed.scheme and not parsed.netloc:
        return target
    return None


def valid_push_endpoint(endpoint):
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    trusted_host = (
        host in {
            "fcm.googleapis.com",
            "web.push.apple.com",
            "push.services.mozilla.com",
            "updates.push.services.mozilla.com",
        }
        or host == "notify.windows.com"
        or host.endswith(".push.services.mozilla.com")
        or host.endswith(".notify.windows.com")
    )
    return (
        parsed.scheme == "https"
        and port in (None, 443)
        and not parsed.username
        and not parsed.password
        and trusted_host
    )


def valid_push_keys(p256dh, auth):
    try:
        decoded_p256dh = base64.b64decode(
            p256dh + "=" * ((4 - len(p256dh) % 4) % 4),
            altchars=b"-_",
            validate=True,
        )
        decoded_auth = base64.b64decode(
            auth + "=" * ((4 - len(auth) % 4) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        return False
    return len(decoded_p256dh) == 65 and decoded_p256dh[0] == 4 and len(decoded_auth) == 16


@main.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    next_url = request.values.get("next", "")
    email = request.form.get("email", "")
    errors = []
    if request.method == "POST":
        password = request.form.get("password", "")
        user = AuthenticationService(get_session()).authenticate(email, password)
        if user:
            login_user(user, fresh=True)
            return redirect(safe_redirect_target(next_url) or url_for("main.dashboard"))
        errors.append("El correo o la contraseña no son correctos.")

    return render_template(
        "auth/login.html",
        email=email,
        errors=errors,
        next_url=next_url,
        google_configured=bool(
            current_app.config.get("GOOGLE_CLIENT_ID")
            and current_app.config.get("GOOGLE_CLIENT_SECRET")
        ),
        push_configured=push_is_configured(current_app.config),
        smtp_configured=bool(
            current_app.config.get("SMTP_HOST") and current_app.config.get("SMTP_FROM")
        ),
    )


@main.route("/auth/google")
@limiter.limit("10 per minute")
def google_login():
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get("GOOGLE_CLIENT_SECRET"):
        flash(
            "Google aún no está configurado. Sigue la guía de configuración del README para activarlo.",
            "info",
        )
        return redirect(url_for("main.settings" if current_user.is_authenticated else "main.login"))

    oauth = current_app.extensions["planify_oauth"].google
    if current_user.is_authenticated:
        session["google_link_user_id"] = current_user.id
    else:
        session.pop("google_link_user_id", None)
    nonce = secrets.token_urlsafe(32)
    redirect_uri = current_app.config.get("GOOGLE_REDIRECT_URI") or url_for(
        "main.google_callback", _external=True
    )
    return oauth.authorize_redirect(redirect_uri, nonce=nonce)


@main.route("/auth/google/callback")
@limiter.limit("10 per minute")
def google_callback():
    oauth = current_app.extensions["planify_oauth"]
    if not current_app.config.get("GOOGLE_CLIENT_ID") or not current_app.config.get("GOOGLE_CLIENT_SECRET"):
        flash("Google aún no está configurado.", "error")
        return redirect(url_for("main.login"))

    try:
        token = oauth.google.authorize_access_token()
    except (OAuthError, JoseError, RequestException) as error:
        current_app.logger.warning("Google sign-in failed: %s", error)
        flash("No pudimos validar el acceso con Google. Inténtalo de nuevo.", "error")
        return redirect(url_for("main.login"))

    profile = token.get("userinfo")
    if (
        not profile
        or profile.get("email_verified") is not True
        or not isinstance(profile.get("email"), str)
        or not isinstance(profile.get("sub"), str)
        or not profile.get("email")
        or not profile.get("sub")
    ):
        current_app.logger.warning("Google sign-in returned incomplete or unverified profile claims.")
        flash("Google no confirmó tu correo. No se inició sesión.", "error")
        return redirect(url_for("main.login"))

    users = UserRepository(get_session())
    google_link_user_id = session.pop("google_link_user_id", None)
    if google_link_user_id is not None:
        user = users.by_id(google_link_user_id)
        if (
            not current_user.is_authenticated
            or current_user.id != google_link_user_id
            or user is None
            or normalize_email(profile["email"]) != user.email
        ):
            flash("Para conectar Google, confirma con Google el mismo correo de tu cuenta.", "error")
            return redirect(url_for("main.settings" if current_user.is_authenticated else "main.login"))
        linked_user = users.by_google_subject(profile["sub"])
        if linked_user and linked_user.id != user.id:
            flash("Esta cuenta de Google ya está conectada a otro usuario.", "error")
            return redirect(url_for("main.settings"))
        user.google_subject = profile["sub"]
        get_session().commit()
        session["google_authenticated_at"] = int(clock.time())
        flash("Tu cuenta de Google quedó conectada.", "success")
        return redirect(url_for("main.settings"))

    user, errors = AuthenticationService(get_session()).authenticate_google(
        profile["email"],
        profile["sub"],
        profile.get("name", "") if isinstance(profile.get("name", ""), str) else "",
    )
    if errors:
        flash(errors[0], "error")
        return redirect(url_for("main.login"))
    login_user(user, fresh=True)
    session["google_authenticated_at"] = int(clock.time())
    flash("Has iniciado sesión con Google.", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    email = request.form.get("email", "")
    errors = []
    if request.method == "POST":
        user, errors = AuthenticationService(get_session()).register(
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
        google_configured=bool(
            current_app.config.get("GOOGLE_CLIENT_ID")
            and current_app.config.get("GOOGLE_CLIENT_SECRET")
        ),
    ), (400 if errors else 200)


@main.route("/forgot-password")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("auth/forgot_password.html")


@main.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("Has cerrado sesión correctamente.", "success")
    return redirect(url_for("main.login"))


@main.route("/")
def dashboard():
    today = date.today()
    service = EventService(get_session(), current_user.id)
    todays_events = service.list_between(today, today)
    upcoming = service.list_between(today + timedelta(days=1), today + timedelta(days=7))
    unread_count = (
        sum(
            not notification.is_read
            for notification in NotificationService(get_session(), current_user.id).list_all()
        )
        if current_user.in_app_notifications
        else 0
    )
    return render_template(
        "dashboard.html",
        today=today,
        todays_events=todays_events,
        upcoming=upcoming,
        unread_count=unread_count,
    )


@main.route("/calendar")
def calendar_view():
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
    events = EventService(get_session(), current_user.id).list_between(month_start, month_end)
    events_by_day = {}
    for event in events:
        events_by_day.setdefault(event.event_date.day, []).append(event)

    previous = month_start if (year, month) == (1, 1) else month_start - timedelta(days=1)
    next_month = month_start if (year, month) == (9999, 12) else (month_end + timedelta(days=1))
    return render_template(
        "calendar.html",
        year=year,
        month=month,
        categories=CategoryService(get_session(), current_user.id).list_all(),
        month_name=MONTHS[month - 1].capitalize(),
        weekdays=WEEKDAYS,
        weeks=month_grid(year, month),
        events_by_day=events_by_day,
        today=today,
        previous_month=f"{previous.year}-{previous.month:02}",
        next_month=f"{next_month.year}-{next_month.month:02}",
    )


@main.route("/events/new", methods=["GET", "POST"])
@main.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
def event_form(event_id=None):
    session = get_session()
    service = EventService(session, current_user.id)
    event = service.get(event_id) if event_id is not None else Event()
    if event is None:
        flash("No encontramos ese evento.", "error")
        return redirect(url_for("main.dashboard"))

    categories = CategoryService(session, current_user.id).list_all()
    default_category = next(
        (category.name for category in categories if category.color == "work"),
        categories[0].name if categories else "",
    )
    values = {
        "title": event.title or "",
        "event_date": event.event_date.isoformat() if event.event_date else date.today().isoformat(),
        "start_time": event.start_time.strftime("%H:%M") if event.start_time else "",
        "category": (
            event.category_item.name
            if event.category_item
            else default_category
        ),
        "reminder": event.reminder or current_user.default_reminder,
    }
    errors = []
    if request.method == "POST":
        values = {
            "title": request.form.get("title", ""),
            "event_date": request.form.get("event_date", ""),
            "start_time": request.form.get("start_time", ""),
            "category": request.form.get("category", ""),
            "reminder": request.form.get("reminder", ""),
        }
        try:
            parsed_date = date.fromisoformat(values["event_date"])
        except ValueError:
            parsed_date = None
        try:
            parsed_time = time.fromisoformat(values["start_time"])
        except ValueError:
            parsed_time = None
        errors = service.save(
            event,
            values["title"],
            parsed_date,
            parsed_time,
            values["category"],
            values["reminder"],
        )
        if not errors:
            flash("Evento guardado. ¡Tu día va tomando forma!", "success")
            return redirect(url_for("main.dashboard"))

    return render_template(
        "event_form.html",
        event=event if event.id else None,
        values=values,
        errors=errors,
        categories=categories,
        reminders=(
            {
                key: label
                for key, label in REMINDERS.items()
                if getattr(current_user, REMINDER_PREFERENCE_FIELDS[key])
                or (event.id and event.reminder == key)
            }
        ),
    ), (400 if errors else 200)


@main.route("/events/<int:event_id>/delete", methods=["POST"])
def delete_event(event_id):
    service = EventService(get_session(), current_user.id)
    event = service.get(event_id)
    if event is None:
        flash("No encontramos ese evento.", "error")
    else:
        service.delete(event)
        flash("Evento eliminado.", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/routine", methods=["GET", "POST"])
def routine():
    today = date.today()
    service = RoutineService(get_session(), current_user.id)
    errors = []
    form_values = {"title": "", "start_time": "", "duration_minutes": "30"}
    if request.method == "POST":
        form_values = {
            "title": request.form.get("title", ""),
            "start_time": request.form.get("start_time", ""),
            "duration_minutes": request.form.get("duration_minutes", ""),
        }
        try:
            block_time = time.fromisoformat(form_values["start_time"])
        except ValueError:
            block_time = None
        try:
            duration = int(form_values["duration_minutes"])
        except ValueError:
            duration = None
        errors = service.add(form_values["title"], block_time, duration, today.weekday())
        if not errors:
            flash("Bloque añadido a tu rutina.", "success")
            return redirect(url_for("main.routine"))

    return render_template(
        "routine.html",
        today=today,
        blocks=service.list_for_day(today.weekday()),
        errors=errors,
        form_values=form_values,
    ), (400 if errors else 200)


@main.route("/notifications")
def notifications():
    items = NotificationService(get_session(), current_user.id).list_all()
    return render_template(
        "notifications.html",
        notifications=items,
        unread_count=sum(not item.is_read for item in items),
    )


@main.route("/api/notifications")
def poll_notifications():
    db_session = get_session()
    user = UserRepository(db_session).by_id(current_user.id)
    latest_id = db_session.scalar(
        select(Notification.id)
        .where(Notification.user_id == user.id)
        .order_by(Notification.id.desc())
        .limit(1)
    ) or 0
    if not user.in_app_notifications:
        return jsonify({"notifications": [], "latest_id": latest_id})

    after_value = request.args.get("after")
    if after_value is None:
        return jsonify({"notifications": [], "latest_id": latest_id})
    try:
        after_id = max(0, int(after_value))
    except ValueError:
        return jsonify({"error": "El identificador de notificación no es válido."}), 400

    notifications = db_session.scalars(
        select(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.id > after_id,
        )
        .order_by(Notification.id)
        .limit(10)
    ).all()
    return jsonify(
        {
            "notifications": [
                {
                    "id": item.id,
                    "title": item.title,
                    "message": item.message,
                    "type": item.notification_type,
                    "sound_enabled": (
                        item.notification_type == "routine"
                        and user.routine_notification_sounds
                    ),
                }
                for item in notifications
            ],
            "latest_id": latest_id,
        }
    )


@main.route("/api/notifications/push-key")
def push_public_key():
    if not push_is_configured(current_app.config):
        return jsonify({"configured": False}), 503
    return jsonify(
        {
            "configured": True,
            "public_key": current_app.config["VAPID_PUBLIC_KEY"],
        }
    )


@main.route("/api/notifications/push-subscription", methods=["POST"])
def save_push_subscription():
    db_session = get_session()
    user = UserRepository(db_session).by_id(current_user.id)
    if not user.desktop_push_notifications:
        return jsonify({"error": "Activa primero las notificaciones push en Ajustes."}), 409
    if not push_is_configured(current_app.config):
        return jsonify({"error": "Las notificaciones push no están configuradas en este servidor."}), 503

    payload = request.get_json(silent=True)
    subscription = payload.get("subscription") if isinstance(payload, dict) else None
    if not isinstance(subscription, dict):
        return jsonify({"error": "La suscripción del navegador no es válida."}), 400
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")
    if (
        not isinstance(endpoint, str)
        or len(endpoint) > 4096
        or not valid_push_endpoint(endpoint)
        or not isinstance(keys, dict)
        or not isinstance(keys.get("p256dh"), str)
        or not isinstance(keys.get("auth"), str)
        or len(keys["p256dh"]) > 255
        or len(keys["auth"]) > 255
        or not valid_push_keys(keys["p256dh"], keys["auth"])
    ):
        return jsonify({"error": "La suscripción del navegador contiene datos no válidos."}), 400

    existing = db_session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    if existing and existing.user_id != user.id:
        return jsonify({"error": "Este navegador ya está vinculado a otra cuenta."}), 409
    if existing is None:
        existing = PushSubscription(user_id=user.id, endpoint=endpoint)
        db_session.add(existing)
    existing.p256dh = keys["p256dh"]
    existing.auth = keys["auth"]
    db_session.commit()
    return jsonify({"saved": True})


@main.route("/api/notifications/push-subscription", methods=["DELETE"])
def delete_push_subscription():
    payload = request.get_json(silent=True)
    endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
    if not isinstance(endpoint, str):
        return jsonify({"error": "Indica la suscripción que quieres quitar."}), 400
    db_session = get_session()
    subscription = db_session.scalar(
        select(PushSubscription).where(
            PushSubscription.user_id == current_user.id,
            PushSubscription.endpoint == endpoint,
        )
    )
    if subscription is not None:
        db_session.delete(subscription)
        db_session.commit()
    return jsonify({"removed": True})


@main.route("/service-worker.js")
def service_worker():
    response = make_response(
        send_from_directory(current_app.static_folder, "service-worker.js")
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@main.route("/notifications/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    service = NotificationService(get_session(), current_user.id)
    notification = service.get(notification_id)
    if notification is None:
        flash("No encontramos esa notificación.", "error")
    else:
        service.mark_read(notification)
    return redirect(url_for("main.notifications"))


@main.route("/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    NotificationService(get_session(), current_user.id).mark_all_read()
    flash("Todas las notificaciones están marcadas como leídas.", "success")
    return redirect(url_for("main.notifications"))


@main.route("/notifications/<int:notification_id>/dismiss", methods=["POST"])
def dismiss_notification(notification_id):
    service = NotificationService(get_session(), current_user.id)
    notification = service.get(notification_id)
    if notification is None:
        flash("No encontramos esa notificación.", "error")
    else:
        service.dismiss(notification)
        flash("Notificación descartada.", "success")
    return redirect(url_for("main.notifications"))


@main.route("/settings")
def settings():
    return render_template(
        "settings.html",
        categories=CategoryService(get_session(), current_user.id).list_all(),
        category_colors=CATEGORY_COLORS,
        reminders=REMINDERS,
        enabled_reminders={
            key: label
            for key, label in REMINDERS.items()
            if getattr(current_user, REMINDER_PREFERENCE_FIELDS[key])
        },
        reminder_preference_fields=REMINDER_PREFERENCE_FIELDS,
        google_configured=bool(
            current_app.config.get("GOOGLE_CLIENT_ID")
            and current_app.config.get("GOOGLE_CLIENT_SECRET")
        ),
    )


@main.route("/settings/profile", methods=["POST"])
def update_profile():
    db_session = get_session()
    user = UserRepository(db_session).by_id(current_user.id)
    display_name = request.form.get("display_name", "").strip()
    if len(display_name) > 60:
        flash("El nombre no puede superar los 60 caracteres.", "error")
        return redirect(url_for("main.settings"))

    user.display_name = display_name
    new_email = normalize_email(request.form.get("email", ""))
    errors = validate_email(new_email)
    if not errors and new_email != user.email:
        existing_user = UserRepository(db_session).by_email(new_email)
        if existing_user and existing_user.id != user.id:
            errors.append("Ese correo ya pertenece a otra cuenta.")
        elif user.password_login_enabled and not user.check_password(request.form.get("current_password", "")):
            errors.append("Confirma tu contraseña actual para cambiar el correo.")
        elif not user.password_login_enabled:
            errors.append("Configura una contraseña antes de cambiar el correo.")
    if errors:
        db_session.rollback()
        flash(errors[0], "error")
        return redirect(url_for("main.settings"))

    user.email = new_email
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        flash("Ese correo ya pertenece a otra cuenta.", "error")
        return redirect(url_for("main.settings"))
    flash("Tu perfil se actualizó correctamente.", "success")
    return redirect(url_for("main.settings"))


@main.route("/settings/password", methods=["POST"])
def update_password():
    db_session = get_session()
    user = UserRepository(db_session).by_id(current_user.id)
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirmation = request.form.get("password_confirmation", "")
    errors = []
    if (
        not user.password_login_enabled
        and clock.time() - session.get("google_authenticated_at", 0) > 600
    ):
        errors.append("Vuelve a iniciar sesión con Google y repite la acción en menos de 10 minutos.")
    if user.password_login_enabled and not user.check_password(current_password):
        errors.append("La contraseña actual no es correcta.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        errors.append(f"La nueva contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
    elif len(new_password) > MAX_PASSWORD_LENGTH:
        errors.append(f"La nueva contraseña no puede superar los {MAX_PASSWORD_LENGTH} caracteres.")
    if new_password != confirmation:
        errors.append("Las contraseñas nuevas no coinciden.")
    if errors:
        flash(errors[0], "error")
        return redirect(url_for("main.settings"))

    user.password_hash = generate_password_hash(new_password)
    user.password_login_enabled = True
    db_session.commit()
    flash("Tu contraseña se actualizó correctamente.", "success")
    return redirect(url_for("main.settings"))


@main.route("/settings/preferences", methods=["POST"])
def update_preferences():
    db_session = get_session()
    user = UserRepository(db_session).by_id(current_user.id)
    reminder = request.form.get("default_reminder", "")
    if reminder not in REMINDERS or not getattr(
        user, REMINDER_PREFERENCE_FIELDS.get(reminder, "")
    ):
        flash("Selecciona un recordatorio predeterminado válido.", "error")
        return redirect(url_for("main.settings"))

    for field_name in REMINDER_PREFERENCE_FIELDS.values():
        setattr(user, field_name, request.form.get(field_name) == "on")
    enabled_reminders = [
        key for key, field_name in REMINDER_PREFERENCE_FIELDS.items()
        if getattr(user, field_name)
    ]
    if not enabled_reminders:
        db_session.rollback()
        flash("Mantén activo al menos un tipo de recordatorio.", "error")
        return redirect(url_for("main.settings"))
    if reminder not in enabled_reminders:
        user.default_reminder = enabled_reminders[0]
    else:
        user.default_reminder = reminder

    for field_name in (
        "routine_notify_start",
        "routine_notify_5_minutes",
        "routine_notification_sounds",
        "desktop_push_notifications",
        "weekly_email_summaries",
        "in_app_notifications",
    ):
        setattr(user, field_name, request.form.get(field_name) == "on")

    quiet_start = request.form.get("quiet_hours_start", "")
    quiet_end = request.form.get("quiet_hours_end", "")
    try:
        parsed_quiet_start = time.fromisoformat(quiet_start)
        parsed_quiet_end = time.fromisoformat(quiet_end)
    except ValueError:
        db_session.rollback()
        flash("Selecciona horas válidas para No molestar.", "error")
        return redirect(url_for("main.settings"))

    user.quiet_hours_enabled = request.form.get("quiet_hours_enabled") == "on"
    if user.quiet_hours_enabled and parsed_quiet_start == parsed_quiet_end:
        db_session.rollback()
        flash("La hora de inicio y la hora de fin de No molestar deben ser diferentes.", "error")
        return redirect(url_for("main.settings"))
    user.quiet_hours_start = parsed_quiet_start.strftime("%H:%M")
    user.quiet_hours_end = parsed_quiet_end.strftime("%H:%M")
    db_session.commit()
    flash("La configuración de notificaciones se guardó.", "success")
    return redirect(url_for("main.settings"))


@main.route("/settings/default-reminder", methods=["POST"])
def update_default_reminder():
    reminder = request.form.get("default_reminder", "")
    if (
        reminder not in REMINDERS
        or not getattr(current_user, REMINDER_PREFERENCE_FIELDS.get(reminder, ""))
    ):
        flash("Selecciona un recordatorio predeterminado que esté activo.", "error")
        return redirect(url_for("main.settings"))
    user = UserRepository(get_session()).by_id(current_user.id)
    user.default_reminder = reminder
    get_session().commit()
    flash("Tu recordatorio predeterminado se actualizó.", "success")
    return redirect(url_for("main.settings"))


@main.route("/settings/categories", methods=["POST"])
def create_category():
    errors = CategoryService(get_session(), current_user.id).create(
        request.form.get("name", ""),
        request.form.get("color", ""),
    )
    if errors:
        for error in errors:
            flash(error, "error")
    else:
        flash("Categoría creada.", "success")
    return redirect(url_for("main.settings"))


@main.route("/settings/categories/<int:category_id>", methods=["POST"])
def update_category(category_id):
    errors = CategoryService(get_session(), current_user.id).update(
        category_id,
        request.form.get("name", ""),
        request.form.get("color", ""),
    )
    if errors:
        for error in errors:
            flash(error, "error")
    else:
        flash("Categoría actualizada.", "success")
    return redirect(url_for("main.settings"))


@main.route("/settings/categories/<int:category_id>/delete", methods=["POST"])
def delete_category(category_id):
    errors = CategoryService(get_session(), current_user.id).delete(category_id)
    if errors:
        for error in errors:
            flash(error, "error")
    else:
        flash("Categoría eliminada.", "success")
    return redirect(url_for("main.settings"))


@main.route("/settings/account/delete", methods=["POST"])
def delete_account():
    db_session = get_session()
    user = UserRepository(db_session).by_id(current_user.id)
    if normalize_email(request.form.get("confirm_email", "")) != user.email:
        flash("Escribe el correo de tu cuenta para confirmar la eliminación.", "error")
        return redirect(url_for("main.settings"))
    if request.form.get("confirmation", "").strip() != "ELIMINAR":
        flash("Escribe ELIMINAR para confirmar la acción.", "error")
        return redirect(url_for("main.settings"))
    if user.password_login_enabled:
        if not user.check_password(request.form.get("current_password", "")):
            flash("La contraseña actual no es correcta.", "error")
            return redirect(url_for("main.settings"))
    elif clock.time() - session.get("google_authenticated_at", 0) > 600:
        flash("Vuelve a iniciar sesión con Google y repite la eliminación en menos de 10 minutos.", "error")
        return redirect(url_for("main.settings"))

    user_id = user.id
    db_session.execute(delete(Event).where(Event.user_id == user_id))
    db_session.execute(delete(RoutineBlock).where(RoutineBlock.user_id == user_id))
    db_session.execute(delete(Notification).where(Notification.user_id == user_id))
    db_session.execute(delete(PushSubscription).where(PushSubscription.user_id == user_id))
    db_session.execute(delete(Category).where(Category.user_id == user_id))
    db_session.delete(user)
    db_session.commit()
    logout_user()
    session.clear()
    flash("Tu cuenta y sus datos se eliminaron.", "success")
    return redirect(url_for("main.login"))
