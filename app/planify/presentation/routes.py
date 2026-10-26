import calendar
from datetime import date, time, timedelta
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from planify.application.auth_service import AuthenticationService
from planify.application.services import EventService, NotificationService, RoutineService, month_grid
from planify.domain.models import Event
from planify.extensions import limiter
from planify.domain.rules import CATEGORIES, REMINDERS
from planify.infrastructure.database import get_session


main = Blueprint("main", __name__)
MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


@main.app_context_processor
def template_helpers():
    return {"category_labels": CATEGORIES}


@main.before_request
def require_signed_in_user():
    public_endpoints = {"main.login", "main.register", "main.forgot_password"}
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
            login_user(user)
            return redirect(safe_redirect_target(next_url) or url_for("main.dashboard"))
        errors.append("El correo o la contraseña no son correctos.")

    return render_template("auth/login.html", email=email, errors=errors, next_url=next_url)


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
            login_user(user)
            flash("Tu cuenta está lista. ¡Empecemos a planificar!", "success")
            return redirect(url_for("main.dashboard"))

    return render_template("auth/register.html", email=email, errors=errors), (400 if errors else 200)


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
    unread_count = sum(
        not notification.is_read
        for notification in NotificationService(get_session(), current_user.id).list_all()
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

    values = {
        "title": event.title or "",
        "event_date": event.event_date.isoformat() if event.event_date else date.today().isoformat(),
        "start_time": event.start_time.strftime("%H:%M") if event.start_time else "",
        "category": event.category or "personal",
        "reminder": event.reminder or "at_time",
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
        categories=CATEGORIES,
        reminders=REMINDERS,
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
    return render_template("settings.html")
