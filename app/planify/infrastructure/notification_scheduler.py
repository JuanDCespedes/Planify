from datetime import datetime, time, timedelta
import logging
import smtplib

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from planify.domain.models import Event, Notification, RoutineBlock, User
from planify.domain.rules import REMINDER_PREFERENCE_FIELDS
from planify.infrastructure.notification_delivery import (
    email_is_configured,
    push_is_configured,
    send_push_notification,
    send_weekly_digest,
)


REMINDER_OFFSETS = {
    "at_time": timedelta(),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
}
DELIVERY_GRACE = timedelta(minutes=2)
LOOKBACK = timedelta(days=1)


def _quiet_end_after(user, scheduled_at):
    if not user.quiet_hours_enabled:
        return None

    quiet_start = time.fromisoformat(user.quiet_hours_start)
    quiet_end = time.fromisoformat(user.quiet_hours_end)
    scheduled_time = scheduled_at.time()
    if quiet_start < quiet_end:
        if quiet_start <= scheduled_time < quiet_end:
            return datetime.combine(scheduled_at.date(), quiet_end)
        return None

    if scheduled_time >= quiet_start:
        return datetime.combine(scheduled_at.date() + timedelta(days=1), quiet_end)
    if scheduled_time < quiet_end:
        return datetime.combine(scheduled_at.date(), quiet_end)
    return None


def _delivery_time(user, scheduled_at, now):
    quiet_end = _quiet_end_after(user, scheduled_at)
    if quiet_end is None:
        return scheduled_at
    return quiet_end if quiet_end > now else now


def _notification_due(user, scheduled_at, now):
    delivery_at = _delivery_time(user, scheduled_at, now)
    return delivery_at <= now and now - delivery_at <= DELIVERY_GRACE


def _persist_notification(session, user, key, title, message, notification_type, config, logger):
    if not user.in_app_notifications and not (
        user.desktop_push_notifications and push_is_configured(config)
    ):
        return None

    existing = session.scalar(select(Notification.id).where(Notification.dedupe_key == key))
    if existing is not None:
        return None

    notification = Notification(
        user_id=user.id,
        title=title,
        message=message,
        dedupe_key=key,
        notification_type=notification_type,
    )
    session.add(notification)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return None

    send_push_notification(session, notification, user, config, logger)
    return notification


def _process_event_reminders(session, now, config, logger):
    start_date = (now - LOOKBACK).date()
    end_date = (now + timedelta(days=2)).date()
    events = session.scalars(
        select(Event).where(
            Event.user_id.is_not(None),
            Event.event_date >= start_date,
            Event.event_date <= end_date,
        )
    ).all()
    for event in events:
        reminder_delta = REMINDER_OFFSETS.get(event.reminder)
        if reminder_delta is None or event.user_id is None:
            continue
        user = session.get(User, event.user_id)
        if user is None:
            continue
        preference_name = REMINDER_PREFERENCE_FIELDS[event.reminder]
        if not getattr(user, preference_name):
            continue

        starts_at = datetime.combine(event.event_date, event.start_time)
        scheduled_at = starts_at - reminder_delta
        if scheduled_at > now or now - scheduled_at > LOOKBACK:
            continue
        if not _notification_due(user, scheduled_at, now):
            continue

        _persist_notification(
            session,
            user,
            f"event:{event.id}:{event.reminder}",
            "Recordatorio de evento",
            f"{event.title} empieza {REMINDER_LABELS[event.reminder]}.",
            "event",
            config,
            logger,
        )


REMINDER_LABELS = {
    "at_time": "ahora",
    "5m": "en 5 minutos",
    "15m": "en 15 minutos",
    "30m": "en 30 minutos",
    "1h": "en 1 hora",
    "1d": "mañana",
}


def _process_routine_reminders(session, now, config, logger):
    day_dates = (now.date() - timedelta(days=1), now.date())
    blocks = session.scalars(
        select(RoutineBlock).where(RoutineBlock.user_id.is_not(None))
    ).all()
    for block in blocks:
        for routine_day in day_dates:
            if routine_day.weekday() != block.day_of_week:
                continue
            user = session.get(User, block.user_id)
            if user is None:
                continue
            starts_at = datetime.combine(routine_day, block.start_time)
            for enabled, offset, suffix in (
                (user.routine_notify_5_minutes, timedelta(minutes=5), "5m"),
                (user.routine_notify_start, timedelta(), "start"),
            ):
                if not enabled:
                    continue
                scheduled_at = starts_at - offset
                if scheduled_at > now or now - scheduled_at > LOOKBACK:
                    continue
                if not _notification_due(user, scheduled_at, now):
                    continue
                when = "en 5 minutos" if suffix == "5m" else "ahora"
                _persist_notification(
                    session,
                    user,
                    f"routine:{block.id}:{routine_day.isoformat()}:{suffix}",
                    "Recordatorio de rutina",
                    f"{block.title} empieza {when}.",
                    "routine",
                    config,
                    logger,
                )


def _process_weekly_digests(session, now, config, logger):
    if now.weekday() != 0 or now.hour < 9 or not email_is_configured(config):
        return
    digest_key = now.strftime("%G-W%V")
    users = session.scalars(
        select(User).where(
            User.weekly_email_summaries.is_(True),
            or_(
                User.last_weekly_digest_key.is_(None),
                User.last_weekly_digest_key != digest_key,
            ),
        )
    ).all()
    for user in users:
        if user.quiet_hours_enabled:
            quiet_end = _quiet_end_after(user, datetime.combine(now.date(), now.time()))
            if quiet_end and quiet_end > now:
                continue
        events = session.scalars(
            select(Event)
            .where(
                Event.user_id == user.id,
                Event.event_date >= now.date(),
                Event.event_date <= now.date() + timedelta(days=7),
            )
            .order_by(Event.event_date, Event.start_time)
        ).all()
        try:
            if send_weekly_digest(user, events, config, logger):
                user.last_weekly_digest_key = digest_key
                session.commit()
        except (OSError, smtplib.SMTPException, ValueError) as error:
            logger.error("Weekly email failed for user %s: %s", user.id, error)


def process_due_notifications(session, now=None, config=None, logger=None):
    now = now or datetime.now().replace(second=0, microsecond=0)
    config = config or {}
    logger = logger or logging.getLogger("planify.notifications")
    _process_event_reminders(session, now, config, logger)
    _process_routine_reminders(session, now, config, logger)
    _process_weekly_digests(session, now, config, logger)


def start_notification_scheduler(app):
    scheduler = BackgroundScheduler(timezone=app.config.get("TIMEZONE", "UTC"))
    scheduler.add_job(
        _scheduled_job,
        trigger="interval",
        minutes=1,
        id="planify-notification-delivery",
        replace_existing=True,
        args=[app],
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.logger.info("Notification scheduler started.")
    return scheduler


def _scheduled_job(app):
    with app.app_context():
        session_factory = app.extensions["planify_session_factory"]
        session = session_factory()
        try:
            process_due_notifications(
                session,
                config=app.config,
                logger=app.logger,
            )
        finally:
            session.close()
