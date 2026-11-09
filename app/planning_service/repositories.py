"""Consultas de persistencia del servicio de planificación."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from planning_service.models import Category, Event, RoutineBlock


class PlanningRepository:
    """Encapsula consultas filtradas por el identificador de usuario recibido."""

    def __init__(self, session: Session):
        """Asocia el repositorio a una sesión de la base de planificación."""
        self.session = session

    def categories(self, user_id):
        """Lista categorías del usuario en orden alfabético."""
        return self.session.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.name.collate("NOCASE"))
        ).all()

    def category(self, category_id, user_id):
        """Busca una categoría por id y propietario externo."""
        return self.session.scalar(
            select(Category).where(Category.id == category_id, Category.user_id == user_id)
        )

    def category_by_name(self, name, user_id):
        """Busca un nombre de categoría sin distinguir mayúsculas."""
        return self.session.scalar(
            select(Category).where(
                Category.user_id == user_id,
                Category.name.collate("NOCASE") == name,
            )
        )

    def events_between(self, user_id, start_date: date, end_date: date):
        """Lista eventos del usuario en el intervalo inclusivo indicado."""
        return self.session.scalars(
            select(Event)
            .where(
                Event.user_id == user_id,
                Event.event_date >= start_date,
                Event.event_date <= end_date,
            )
            .order_by(Event.event_date, Event.start_time)
        ).all()

    def event(self, event_id, user_id):
        """Busca un evento únicamente si pertenece al usuario indicado."""
        return self.session.scalar(
            select(Event).where(Event.id == event_id, Event.user_id == user_id)
        )

    def routine_blocks(self, user_id, day_of_week=None):
        """Lista bloques propios, opcionalmente filtrados por día semanal."""
        statement = select(RoutineBlock).where(RoutineBlock.user_id == user_id)
        if day_of_week is not None:
            statement = statement.where(RoutineBlock.day_of_week == day_of_week)
        return self.session.scalars(statement.order_by(RoutineBlock.day_of_week, RoutineBlock.start_time)).all()