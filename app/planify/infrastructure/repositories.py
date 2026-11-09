"""Consultas de persistencia que encapsulan el acceso a entidades Planify."""

from datetime import date, datetime, time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from planify.domain.models import Category, Event, Notification, RoutineBlock, User


class UserRepository:
    """Busca y persiste cuentas de usuario."""

    def __init__(self, session: Session):
        """Asocia el repositorio a una sesión SQLAlchemy."""
        self.session = session

    def by_email(self, email: str):
        """Busca una cuenta por su correo normalizado."""
        return self.session.scalar(select(User).where(User.email == email))

    def by_id(self, user_id: int):
        """Busca una cuenta por identificador primario."""
        return self.session.get(User, user_id)

    def by_google_subject(self, google_subject: str):
        """Busca una cuenta por el identificador estable de Google."""
        return self.session.scalar(select(User).where(User.google_subject == google_subject))

    def add(self, user: User):
        """Añade una cuenta a la sesión sin confirmar la transacción."""
        self.session.add(user)

    def delete(self, user: User):
        """Marca una cuenta para eliminar dentro de la sesión actual."""
        self.session.delete(user)


class CategoryRepository:
    """Consulta categorías siempre dentro del ámbito de una cuenta."""

    def __init__(self, session: Session):
        """Asocia el repositorio a una sesión SQLAlchemy."""
        self.session = session

    def all(self, user_id: int):
        """Lista categorías del usuario por nombre, sin distinguir mayúsculas."""
        return self.session.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.name.collate("NOCASE"))
        ).all()

    def get(self, category_id: int, user_id: int):
        """Busca una categoría por id y propietario."""
        return self.session.scalar(
            select(Category).where(Category.id == category_id, Category.user_id == user_id)
        )

    def by_name(self, name: str, user_id: int, exclude_id: int | None = None):
        """Busca por nombre normalizado y permite excluir una categoría al editar."""
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
        """Indica si algún evento del usuario utiliza la categoría."""
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
        """Marca una categoría para eliminar dentro de la sesión actual."""
        self.session.delete(category)

class EventRepository:
    """Consulta y persiste eventos con filtro obligatorio por propietario."""

    def __init__(self, session: Session):
        """Asocia el repositorio a una sesión SQLAlchemy."""
        self.session = session

    def get(self, event_id, user_id: int):
        """Busca un evento únicamente si pertenece al usuario indicado."""
        return self.session.scalar(
            select(Event).where(Event.id == event_id, Event.user_id == user_id)
        )

    def between(self, start_date: date, end_date: date, user_id: int):
        """Lista eventos propios en un intervalo inclusivo y ordenado."""
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
        """Marca un evento para eliminar dentro de la sesión actual."""
        self.session.delete(event)


class RoutineRepository:
    """Consulta y persiste bloques semanales de rutina."""

    def __init__(self, session: Session):
        """Asocia el repositorio a una sesión SQLAlchemy."""
        self.session = session

    def for_day(self, day_of_week: int, user_id: int):
        """Lista bloques propios de un día de semana en orden horario."""
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
    """Consulta y persiste notificaciones filtradas por propietario."""

    def __init__(self, session: Session):
        """Asocia el repositorio a una sesión SQLAlchemy."""
        self.session = session

    def all(self, user_id: int):
        """Lista avisos propios, primero los no leídos y luego por fecha."""
        return self.session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.is_read, Notification.created_at.desc())
        ).all()

    def get(self, notification_id, user_id: int):
        """Busca una notificación únicamente si pertenece al usuario indicado."""
        return self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )

    def mark_all_read(self, user_id: int):
        """Marca como leídos los avisos pendientes del usuario indicado."""
        self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )

    def add(self, notification):
        """Añade una notificación a la sesión sin confirmar la transacción."""
        self.session.add(notification)

    def delete(self, notification):
        """Marca una notificación para eliminar dentro de la sesión actual."""
        self.session.delete(notification)
