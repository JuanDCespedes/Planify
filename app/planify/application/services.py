import calendar
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from planify.domain.models import Category, Event, Notification, RoutineBlock, User
from planify.domain.rules import (
    DEFAULT_CATEGORIES,
    REMINDER_PREFERENCE_FIELDS,
    validate_category,
    validate_event,
    validate_routine_block,
)
from planify.infrastructure.repositories import CategoryRepository, EventRepository, NotificationRepository, RoutineRepository


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
        is_category_id = isinstance(category, int)
        errors = validate_event(
            title,
            event_date,
            start_time,
            category if is_category_id else 1,
            reminder,
        )
        category_repository = CategoryRepository(self.session)
        category_item = None
        is_new_category = False
        if is_category_id:
            category_item = category_repository.get(category, self.user_id)
            if category_item is None:
                errors.append("Selecciona una categoría de tu cuenta.")
        elif isinstance(category, str):
            category_name = category.strip()
            category_item = category_repository.by_name(category_name, self.user_id)
            if category_item is None and category_name.isdigit():
                possible_category = self.session.get(Category, int(category_name))
                if possible_category is not None:
                    if possible_category.user_id == self.user_id:
                        category_item = possible_category
                    else:
                        errors.append("Selecciona una categoría de tu cuenta.")
            if category_item is None:
                if not errors:
                    category_errors = validate_category(category_name, "other")
                    errors.extend(category_errors)
                if not errors:
                    category_item = Category(
                        user_id=self.user_id,
                        name=category_name,
                        color="other",
                    )
                    is_new_category = True
        else:
            errors.append("Escribe o selecciona una categoría.")

        reminder_preference = REMINDER_PREFERENCE_FIELDS.get(reminder)
        user = self.session.get(User, self.user_id)
        if (
            reminder_preference
            and not getattr(user, reminder_preference)
            and not (event.id and event.reminder == reminder)
        ):
            errors.append("Ese recordatorio está desactivado en tu configuración.")
        if errors:
            return errors
        if is_new_category:
            category_repository.add(category_item)
            try:
                self.session.flush()
            except IntegrityError:
                self.session.rollback()
                return ["Ya existe una categoría con ese nombre."]
        event.title = title.strip()
        event.event_date = event_date
        event.start_time = start_time
        event.category = {
            "work": "trabajo",
            "study": "estudio",
            "personal": "personal",
            "health": "salud",
        }.get(category_item.color, "otro")
        event.category_item = category_item
        event.reminder = reminder
        event.user_id = self.user_id
        self.events.add(event)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return ["No se pudo guardar la categoría. Comprueba si ya existe y vuelve a intentarlo."]
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


class CategoryService:
    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.user_id = user_id
        self.categories = CategoryRepository(session)

    def list_all(self):
        return self.categories.all(self.user_id)

    def create(self, name, color):
        errors = validate_category(name, color)
        normalized_name = name.strip() if name else ""
        if not errors and self.categories.by_name(normalized_name, self.user_id):
            errors.append("Ya existe una categoría con ese nombre.")
        if errors:
            return errors
        self.categories.add(Category(user_id=self.user_id, name=normalized_name, color=color))
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return ["Ya existe una categoría con ese nombre."]
        return []

    def update(self, category_id, name, color):
        category = self.categories.get(category_id, self.user_id)
        if category is None:
            return ["No encontramos esa categoría."]
        errors = validate_category(name, color)
        normalized_name = name.strip() if name else ""
        if not errors and self.categories.by_name(normalized_name, self.user_id, category.id):
            errors.append("Ya existe una categoría con ese nombre.")
        if errors:
            return errors
        category.name = normalized_name
        category.color = color
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return ["Ya existe una categoría con ese nombre."]
        return []

    def delete(self, category_id):
        category = self.categories.get(category_id, self.user_id)
        if category is None:
            return ["No encontramos esa categoría."]
        if len(self.categories.all(self.user_id)) <= 1:
            return ["Debes conservar al menos una categoría."]
        if self.categories.in_use(category.id, self.user_id):
            return ["Esta categoría tiene eventos. Cambia primero sus eventos a otra categoría."]
        self.categories.delete(category)
        self.session.commit()
        return []


def month_grid(year, month):
    return calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)


def seed_demo_data(session: Session, user_id: int):
    categories = {
        category.color: category
        for category in session.scalars(select(Category).where(Category.user_id == user_id)).all()
    }
    for name, color in DEFAULT_CATEGORIES:
        if color not in categories:
            category = Category(user_id=user_id, name=name, color=color)
            session.add(category)
            categories[color] = category
    session.flush()

    if session.scalar(select(Event.id).where(Event.user_id == user_id).limit(1)) is not None:
        session.commit()
        return

    today = date.today()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add_all(
        [
            Event(user_id=user_id, title="Planificar la semana", event_date=today, start_time=time(9, 0), category="trabajo", category_item=categories["work"], reminder="15m"),
            Event(user_id=user_id, title="Revisar avances del proyecto", event_date=today, start_time=time(11, 30), category="estudio", category_item=categories["study"], reminder="30m"),
            Event(user_id=user_id, title="Pausa para caminar", event_date=today, start_time=time(16, 0), category="salud", category_item=categories["health"], reminder="at_time"),
            Event(user_id=user_id, title="Entrega del proyecto", event_date=today + timedelta(days=2), start_time=time(10, 0), category="estudio", category_item=categories["study"], reminder="1d"),
            Event(user_id=user_id, title="Café con Alex", event_date=today + timedelta(days=4), start_time=time(17, 30), category="personal", category_item=categories["personal"], reminder="1h"),
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
