"""Consultas de persistencia del servicio de notificaciones."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from notification_service.models import Notification, PushSubscription


class NotificationRepository:
    """Accede a avisos y suscripciones filtrando por propietario externo."""

    def __init__(self, session: Session):
        """Asocia el repositorio a una sesión de la base de avisos."""
        self.session = session

    def all(self, user_id):
        """Lista los avisos propios, pendientes primero y luego por fecha."""
        return self.session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.is_read, Notification.created_at.desc())
        ).all()

    def get(self, notification_id, user_id):
        """Busca un aviso solo si pertenece al usuario indicado."""
        return self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )

    def by_dedupe_key(self, dedupe_key):
        """Busca un aviso por su clave de idempotencia."""
        return self.session.scalar(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        )

    def subscriptions(self, user_id):
        """Lista suscripciones push propias."""
        return self.session.scalars(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        ).all()

    def mark_all_read(self, user_id):
        """Marca como leídos todos los avisos pendientes del usuario."""
        self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )
