"""Scheduler que consulta identidad y planificación mediante sus APIs internas."""

from datetime import date, datetime, time, timedelta, timezone
import logging
import smtplib
from zoneinfo import ZoneInfo

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from notification_service.delivery import (
    email_is_configured,
    push_is_configured,
    send_email,
    send_push,
)
from notification_service.models import Notification, PushSubscription
from notification_service.services import NotificationService


REMINDER_OFFSETS = {
    "at_time": timedelta(),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}
REMINDER_FIELDS = {
    "at_time": "reminder_at_event_enabled",
    "5m": "reminder_5_minutes_enabled",
    "15m": "reminder_15_minutes_enabled",
    "30m": "reminder_30_minutes_enabled",
    "1h": "reminder_1_hour_enabled",
    "1d": "reminder_1_day_enabled",
}
REMINDER_LABELS = {
    "at_time": "ahora",
    "5m": "en 5 minutos",
    "15m": "en 15 minutos",
    "30m": "en 30 minutos",
    "1h": "en 1 hora",
    "1d": "mañana",
}
DELIVERY_GRACE = timedelta(minutes=2)
LOOKBACK = timedelta(days=1)
EMAIL_RETRY_AFTER = timedelta(minutes=15)
MAX_EMAIL_ATTEMPTS = 5


def _internal_get(base_url, path, token, params=None):
    """Solicita un DTO a identidad o planificación con el token interno."""
    response = requests.get(
        f"{base_url.rstrip('/')}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _quiet_end_after(user, scheduled_at):
    """Devuelve el fin del intervalo silencioso que contiene el aviso."""
    if not user.get("quiet_hours_enabled"):
        return None
    quiet_start = time.fromisoformat(user["quiet_hours_start"])
    quiet_end = time.fromisoformat(user["quiet_hours_end"])
    scheduled_time = scheduled_at.time()
    if quiet_start < quiet_end:
        return datetime.combine(scheduled_at.date(), quiet_end) if quiet_start <= scheduled_time < quiet_end else None
    if scheduled_time >= quiet_start:
        return datetime.combine(scheduled_at.date() + timedelta(days=1), quiet_end)
    if scheduled_time < quiet_end:
        return datetime.combine(scheduled_at.date(), quiet_end)
    return None


def _is_due(user, scheduled_at, now):
    """Comprueba vencimiento, horas silenciosas y ventana de tolerancia."""
    quiet_end = _quiet_end_after(user, scheduled_at)
    delivery_at = max(quiet_end, now) if quiet_end else scheduled_at
    return delivery_at <= now and now - delivery_at <= DELIVERY_GRACE


def _create_and_push(session, user, key, title, message, kind, config, logger):
    """Persiste un aviso idempotente y lo entrega a suscripciones push propias."""
    push_enabled = user.get("desktop_push_notifications") and push_is_configured(config)
    email_enabled = user.get("email_notifications") and email_is_configured(config)
    if not user.get("in_app_notifications") and not push_enabled and not email_enabled:
        return None
    item, created = NotificationService(session).create(
        user["id"], title, message, key, kind
    )
    if not created:
        return item
    if push_enabled:
        subscriptions = session.scalars(
            select(PushSubscription).where(PushSubscription.user_id == user["id"])
        ).all()
        result = send_push(
            [
                {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
                for sub in subscriptions
            ],
            title,
            message,
            "/notifications",
            key,
            config,
            logger,
        )
        expired = set(result["expired_endpoints"])
        for subscription in subscriptions:
            if subscription.endpoint in expired:
                session.delete(subscription)
        session.commit()
    return item


def _process_pending_emails(session, users, now, config, logger):
    """Reintenta correo de aviso hasta cinco veces con pausa de quince minutos."""
    if not email_is_configured(config):
        return
    by_id = {user["id"]: user for user in users}
    utc_now = now.replace(
        tzinfo=ZoneInfo(config.get("TIMEZONE", "America/Bogota"))
    ).astimezone(timezone.utc).replace(tzinfo=None)
    pending = session.scalars(
        select(Notification)
        .where(
            Notification.notification_type.in_(("event", "routine")),
            Notification.email_sent_at.is_(None),
            Notification.email_attempt_count < MAX_EMAIL_ATTEMPTS,
            Notification.created_at >= utc_now - LOOKBACK,
        )
        .order_by(Notification.created_at)
        .limit(100)
    ).all()
    for item in pending:
        user = by_id.get(item.user_id)
        if not user or not user.get("email_notifications"):
            continue
        if item.email_last_attempt_at and item.email_last_attempt_at > utc_now - EMAIL_RETRY_AFTER:
            continue
        item.email_attempt_count += 1
        item.email_last_attempt_at = utc_now
        session.commit()
        try:
            send_email(
                user["email"],
                f"Recordatorio de Planify: {item.title}",
                f"{item.title}\n\n{item.message}\n\nAbre Planify para ver los detalles de tu agenda.",
                config,
            )
            item.email_sent_at = utc_now
            session.commit()
        except (OSError, smtplib.SMTPException, ValueError) as error:
            session.rollback()
            logger.error("Notification email failed for user %s: %s", item.user_id, error)


def process_due_notifications(session, now=None, config=None, logger=None):
    """Consulta servicios de dominio y persiste recordatorios vencidos."""
    config = config or {}
    logger = logger or logging.getLogger("planify.notifications")
    timezone_name = config.get("TIMEZONE", "America/Bogota")
    zone = ZoneInfo(timezone_name)
    now = now or datetime.now(zone).replace(tzinfo=None, second=0, microsecond=0)
    token = config.get("SERVICE_TOKEN", "")
    users = _internal_get(
        config["IDENTITY_SERVICE_URL"], "/api/v1/users", token
    )["users"]
    start = (now - LOOKBACK).date()
    end = (now + timedelta(days=2)).date()
    events = _internal_get(
        config["PLANNING_SERVICE_URL"],
        "/api/v1/events/due",
        token,
        {"start": start.isoformat(), "end": end.isoformat()},
    )["events"]
    routines = _internal_get(
        config["PLANNING_SERVICE_URL"], "/api/v1/routines/due", token
    )["routines"]
    users_by_id = {user["id"]: user for user in users}

    for event in events:
        user = users_by_id.get(event["user_id"])
        reminder = event["reminder"]
        if not user or reminder not in REMINDER_OFFSETS or not user.get(REMINDER_FIELDS[reminder]):
            continue
        starts_at = datetime.combine(
            date.fromisoformat(event["event_date"]),
            time.fromisoformat(event["start_time"]),
        )
        scheduled_at = starts_at - REMINDER_OFFSETS[reminder]
        if scheduled_at > now or now - scheduled_at > LOOKBACK or not _is_due(user, scheduled_at, now):
            continue
        _create_and_push(
            session,
            user,
            f"event:{event['id']}:{reminder}",
            "Recordatorio de evento",
            f"{event['title']} empieza {REMINDER_LABELS[reminder]}.",
            "event",
            config,
            logger,
        )

    day_dates = (now.date() - timedelta(days=1), now.date())
    for block in routines:
        user = users_by_id.get(block["user_id"])
        if not user:
            continue
        for routine_day in day_dates:
            if routine_day.weekday() != block["day_of_week"]:
                continue
            starts_at = datetime.combine(routine_day, time.fromisoformat(block["start_time"]))
            for enabled, offset, suffix, when in (
                (user.get("routine_notify_5_minutes"), timedelta(minutes=5), "5m", "en 5 minutos"),
                (user.get("routine_notify_start"), timedelta(), "start", "ahora"),
            ):
                scheduled_at = starts_at - offset
                if not enabled or scheduled_at > now or now - scheduled_at > LOOKBACK or not _is_due(user, scheduled_at, now):
                    continue
                _create_and_push(
                    session,
                    user,
                    f"routine:{block['id']}:{routine_day.isoformat()}:{suffix}",
                    "Recordatorio de rutina",
                    f"{block['title']} empieza {when}.",
                    "routine",
                    config,
                    logger,
                )

    if now.weekday() == 0 and now.hour >= 9 and email_is_configured(config):
        week_key = now.strftime("%G-W%V")
        for user in users:
            if not user.get("weekly_email_summaries") or user.get("last_weekly_digest_key") == week_key:
                continue
            if user.get("quiet_hours_enabled"):
                quiet_end = _quiet_end_after(user, now)
                if quiet_end and quiet_end > now:
                    continue
            upcoming = [
                event for event in events
                if event["user_id"] == user["id"]
                and now.date() <= date.fromisoformat(event["event_date"]) <= now.date() + timedelta(days=7)
            ]
            body = "\n".join(
                ["Estos son tus próximos eventos:"]
                + [
                    f"- {date.fromisoformat(item['event_date']):%d/%m} · {item['start_time']} · {item['title']}"
                    for item in upcoming
                ]
            ) if upcoming else "No tienes eventos próximos esta semana. ¡Disfruta el espacio!"
            try:
                send_email(user["email"], "Tu semana en Planify", body, config)
                requests.patch(
                    f"{config['IDENTITY_SERVICE_URL'].rstrip('/')}/api/v1/users/{user['id']}/preferences",
                    json={"last_weekly_digest_key": week_key},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                ).raise_for_status()
            except (OSError, RequestException, smtplib.SMTPException, ValueError) as error:
                logger.error("Weekly email failed for user %s: %s", user["id"], error)

    _process_pending_emails(session, users, now, config, logger)


def start_notification_scheduler(app):
    """Inicia un único trabajo de entrega cada minuto para esta instancia."""
    scheduler = BackgroundScheduler(timezone=app.config.get("TIMEZONE", "America/Bogota"))

    def run_job():
        """Abre contexto y sesión propios para un ciclo de notificaciones."""
        with app.app_context():
            session = app.extensions["notification_session_factory"]()
            try:
                process_due_notifications(session, config=app.config, logger=app.logger)
            except (RequestException, KeyError, ValueError) as error:
                app.logger.error("Notification scheduler cycle failed: %s", error)
            finally:
                session.close()

    scheduler.add_job(run_job, "interval", minutes=1, id="notification-delivery", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    app.logger.info("Notification scheduler started.")
    return scheduler