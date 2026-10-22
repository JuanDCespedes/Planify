import calendar
from datetime import date, time, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from planify.application.services import EventService, NotificationService, RoutineService, month_grid
from planify.domain.models import Event
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


@main.route("/")
def dashboard():
    today = date.today()
    service = EventService(get_session())
    todays_events = service.list_between(today, today)
    upcoming = service.list_between(today + timedelta(days=1), today + timedelta(days=7))
    unread_count = sum(not notification.is_read for notification in NotificationService(get_session()).list_all())
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
    events = EventService(get_session()).list_between(month_start, month_end)
    events_by_day = {}
    for event in events:
        events_by_day.setdefault(event.event_date.day, []).append(event)

    previous = (month_start.replace(day=1) - timedelta(days=1))
    next_month = (month_end + timedelta(days=1)).replace(day=1)
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
        month_key=f"{year}-{month:02}",
    )


@main.route("/events/new", methods=["GET", "POST"])
@main.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
def event_form(event_id=None):
    session = get_session()
    service = EventService(session)
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
    service = EventService(get_session())
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
    service = RoutineService(get_session())
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
    items = NotificationService(get_session()).list_all()
    return render_template(
        "notifications.html",
        notifications=items,
        unread_count=sum(not item.is_read for item in items),
    )


@main.route("/notifications/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    service = NotificationService(get_session())
    notification = service.get(notification_id)
    if notification is None:
        flash("No encontramos esa notificación.", "error")
    else:
        service.mark_read(notification)
    return redirect(url_for("main.notifications"))


@main.route("/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    NotificationService(get_session()).mark_all_read()
    flash("Todas las notificaciones están marcadas como leídas.", "success")
    return redirect(url_for("main.notifications"))


@main.route("/notifications/<int:notification_id>/dismiss", methods=["POST"])
def dismiss_notification(notification_id):
    service = NotificationService(get_session())
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
