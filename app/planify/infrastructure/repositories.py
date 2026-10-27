"""Consultas SQLAlchemy agrupadas por entidad y propiedad de cuenta."""

from datetime import date, datetime, time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from planify.domain.models import Category, Event, Notification, RoutineBlock, User


class UserRepository:
    """Operaciones de persistencia para cuentas de usuario."""

    def __init__(self, session: Session):
        """Asocia el repositorio a la sesión de base de datos actual."""
        self.session = session

    def by_email(self, email: str):
        """Busca la cuenta cuyo correo coincide exactamente con el argumento."""
        return self.session.scalar(select(User).where(User.email == email))

    def by_id(self, user_id: int):
        """Obtiene una cuenta por su clave primaria."""
        return self.session.get(User, user_id)

    def by_google_subject(self, google_subject: str):
        """Busca la cuenta vinculada al identificador estable de Google."""
        return self.session.scalar(select(User).where(User.google_subject == google_subject))

    def add(self, user: User):
        """Añade una cuenta a la sesión sin confirmar la transacción."""
        self.session.add(user)

    def delete(self, user: User):
        """Marca una cuenta para eliminación al confirmar la transacción."""
        self.session.delete(user)


class CategoryRepository:
    """Consultas de categorías filtradas por propietario."""

    def __init__(self, session: Session):
        """Asocia el repositorio a la sesión de base de datos actual."""
        self.session = session

    def all(self, user_id: int):
        """Lista las categorías de una cuenta en orden insensible a mayúsculas."""
        return self.session.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.name.collate("NOCASE"))
        ).all()

    def get(self, category_id: int, user_id: int):
        """Obtiene una categoría solo si pertenece al propietario indicado."""
        return self.session.scalar(
            select(Category).where(Category.id == category_id, Category.user_id == user_id)
        )

    def by_name(self, name: str, user_id: int, exclude_id: int | None = None):
        """Busca el nombre normalizado entre las categorías de una cuenta."""
        normalized_name = name.strip().casefold()
        return next(
            (
                category
                for category in self.all(user_id)
                if category.id != exclude_id and category.name.casefold() == normalized_name
            ),
            None,
        )

    def in_use(self, category_id: int, user_id: int):
        """Indica si algún evento propio hace referencia a la categoría."""
        return self.session.scalar(
            select(Event.id).where(
                Event.category_id == category_id,
                Event.user_id == user_id,
            ).limit(1)
        ) is not None

    def add(self, category: Category):
        """Añade una categoría a la sesión sin confirmar la transacción."""
        self.session.add(category)

    def delete(self, category: Category):
        """Marca una categoría para eliminación al confirmar la transacción."""
        self.session.delete(category)


class EventRepository:
    """Consultas de eventos limitadas al propietario de cada agenda."""

    def __init__(self, session: Session):
        """Asocia el repositorio a la sesión de base de datos actual."""
        self.session = session

    def get(self, event_id, user_id: int):
        """Obtiene un evento solo si pertenece al usuario indicado."""
        return self.session.scalar(
            select(Event).where(Event.id == event_id, Event.user_id == user_id)
        )

    def between(self, start_date: date, end_date: date, user_id: int):
        """Lista los eventos propios del intervalo inclusivo en orden cronológico."""
        return self.session.scalars(
            select(Event)
            .where(
                Event.user_id == user_id,
                Event.event_date >= start_date,
                Event.event_date <= end_date,
            )
            .order_by(Event.event_date, Event.start_time)
        ).all()

    def add(self, event):
        """Añade un evento a la sesión sin confirmar la transacción."""
        self.session.add(event)

    def delete(self, event):
        """Marca un evento para eliminación al confirmar la transacción."""
        self.session.delete(event)


class RoutineRepository:
    """Consultas y escrituras de bloques de rutina personales."""

    def __init__(self, session: Session):
        """Asocia el repositorio a la sesión de base de datos actual."""
        self.session = session

    def for_day(self, day_of_week: int, user_id: int):
        """Lista los bloques del día indicados que pertenecen al usuario."""
        return self.session.scalars(
            select(RoutineBlock)
            .where(
                RoutineBlock.user_id == user_id,
                RoutineBlock.day_of_week == day_of_week,
            )
            .order_by(RoutineBlock.start_time)
        ).all()

    def add(self, block):
        """Añade un bloque a la sesión sin confirmar la transacción."""
        self.session.add(block)


class NotificationRepository:
    """Consultas de notificaciones filtradas por cuenta."""

    def __init__(self, session: Session):
        """Asocia el repositorio a la sesión de base de datos actual."""
        self.session = session

    def all(self, user_id: int):
        """Lista avisos propios, primero los no leídos y luego por fecha."""
        return self.session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.is_read, Notification.created_at.desc())
        ).all()

    def get(self, notification_id, user_id: int):
        """Obtiene un aviso solo si pertenece al usuario indicado."""
        return self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )

    def mark_all_read(self, user_id: int):
        """Actualiza en bloque el estado de lectura de los avisos propios."""
        self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )

    def add(self, notification):
        """Añade una notificación a la sesión sin confirmar la transacción."""
        self.session.add(notification)

    def delete(self, notification):
        """Marca una notificación para eliminación al confirmar la transacción."""
        self.session.delete(notification)
