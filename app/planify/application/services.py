import calendar
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from planify.domain.models import Event, Notification, RoutineBlock, User
from planify.domain.rules import validate_event, validate_routine_block
from planify.infrastructure.repositories import EventRepository, NotificationRepository, RoutineRepository


class EventService:
    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.events = EventRepository(session)
        self.user_id = user_id

    def get(self, event_id):
        return self.events.get(event_id, self.user_id)

    def list_between(self, start_date, end_date):
        return self.events.between(start_date, end_date, self.user_id)

    def save(self, event, title, event_date, start_time, category, reminder):
        errors = validate_event(title, event_date, start_time, category, reminder)
        if errors:
            return errors
        event.title = title.strip()
        event.event_date = event_date
        event.start_time = start_time
        event.category = category
        event.reminder = reminder
        event.user_id = self.user_id
        self.events.add(event)
        self.session.commit()
        return []

    def delete(self, event):
        self.events.delete(event)
        self.session.commit()


class RoutineService:
    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.blocks = RoutineRepository(session)
        self.user_id = user_id

    def list_for_day(self, day_of_week):
        return self.blocks.for_day(day_of_week, self.user_id)

    def add(self, title, start_time, duration_minutes, day_of_week):
        errors = validate_routine_block(title, start_time, duration_minutes)
        if errors:
            return errors
        self.blocks.add(
            RoutineBlock(
                title=title.strip(),
                user_id=self.user_id,
                start_time=start_time,
                duration_minutes=duration_minutes,
                day_of_week=day_of_week,
            )
        )
        self.session.commit()
        return []


class NotificationService:
    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.notifications = NotificationRepository(session)
        self.user_id = user_id

    def list_all(self):
        return self.notifications.all(self.user_id)

    def get(self, notification_id):
        return self.notifications.get(notification_id, self.user_id)

    def mark_read(self, notification):
        notification.is_read = True
        self.session.commit()

    def mark_all_read(self):
        self.notifications.mark_all_read(self.user_id)
        self.session.commit()

    def dismiss(self, notification):
        self.notifications.delete(notification)
        self.session.commit()


def month_grid(year, month):
    return calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)


def seed_demo_data(session: Session, user_id: int):
    if session.scalar(select(Event.id).where(Event.user_id == user_id).limit(1)) is not None:
        return

    today = date.today()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add_all(
        [
            Event(user_id=user_id, title="Planificar la semana", event_date=today, start_time=time(9, 0), category="trabajo", reminder="15m"),
            Event(user_id=user_id, title="Revisar avances del proyecto", event_date=today, start_time=time(11, 30), category="estudio", reminder="30m"),
            Event(user_id=user_id, title="Pausa para caminar", event_date=today, start_time=time(16, 0), category="salud", reminder="at_time"),
            Event(user_id=user_id, title="Entrega del proyecto", event_date=today + timedelta(days=2), start_time=time(10, 0), category="estudio", reminder="1d"),
            Event(user_id=user_id, title="Café con Alex", event_date=today + timedelta(days=4), start_time=time(17, 30), category="personal", reminder="1h"),
        ]
    )

    for title, start, duration in [
        ("Rutina de mañana", time(7, 0), 45),
        ("Bloque de concentración", time(9, 0), 90),
        ("Pausa y estiramientos", time(11, 0), 15),
        ("Cierre del día", time(17, 0), 30),
    ]:
        session.add(RoutineBlock(user_id=user_id, title=title, start_time=start, duration_minutes=duration, day_of_week=today.weekday()))

    session.add_all(
        [
            Notification(
                title="Tu día está listo para empezar",
                user_id=user_id,
                message="Tienes 3 eventos en tu agenda de hoy. ¡Organiza tus prioridades y avanza a tu ritmo!",
                created_at=now - timedelta(minutes=12),
            ),
            Notification(
                title="Se acerca una entrega",
                user_id=user_id,
                message="El proyecto de estudio vence dentro de 2 días. Reserva un espacio para revisarlo.",
                created_at=now - timedelta(hours=3),
            ),
            Notification(
                title="Consejo de bienestar",
                user_id=user_id,
                message="Una pausa breve también forma parte de un día productivo.",
                created_at=now - timedelta(days=1),
                is_read=True,
            ),
        ]
    )
    session.commit()
