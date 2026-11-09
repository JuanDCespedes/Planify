"""Casos de uso para el centro de avisos y las suscripciones push."""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from notification_service.models import Notification, PushSubscription
from notification_service.repositories import NotificationRepository


class NotificationService:
    """Gestiona avisos con idempotencia y límites de propiedad por usuario."""

    def __init__(self, session: Session):
        """Inicializa los casos de uso con la sesión propia del servicio."""
        self.session = session
        self.repository = NotificationRepository(session)

    def list_all(self, user_id):
        """Lista los avisos del usuario autenticado por el gateway."""
        return self.repository.all(user_id)

    def create(self, user_id, title, message, dedupe_key, notification_type):
        """Crea un aviso una sola vez; devuelve el existente si ya se procesó."""
        existing = self.repository.by_dedupe_key(dedupe_key) if dedupe_key else None
        if existing:
            return existing, False
        item = Notification(
            user_id=user_id,
            title=title,
            message=message,
            dedupe_key=dedupe_key,
            notification_type=notification_type,
        )
        self.session.add(item)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.repository.by_dedupe_key(dedupe_key) if dedupe_key else None
            if existing:
                return existing, False
            raise
        return item, True

    def mark_read(self, notification_id, user_id):
        """Marca un aviso propio como leído y devuelve si existía."""
        item = self.repository.get(notification_id, user_id)
        if item is None:
            return False
        item.is_read = True
        self.session.commit()
        return True

    def mark_all_read(self, user_id):
        """Marca todos los avisos del usuario como leídos."""
        self.repository.mark_all_read(user_id)
        self.session.commit()

    def dismiss(self, notification_id, user_id):
        """Elimina un aviso propio y devuelve si se encontró."""
        item = self.repository.get(notification_id, user_id)
        if item is None:
            return False
        self.session.delete(item)
        self.session.commit()
        return True

    def save_subscription(self, user_id, endpoint, p256dh, auth):
        """Guarda o actualiza una suscripción push dentro de una cuenta."""
        item = self.session.query(PushSubscription).filter_by(endpoint=endpoint).one_or_none()
        if item is not None and item.user_id != user_id:
            return False
        if item is None:
            item = PushSubscription(user_id=user_id, endpoint=endpoint)
            self.session.add(item)
        item.p256dh = p256dh
        item.auth = auth
        self.session.commit()
        return True

    def remove_subscription(self, user_id, endpoint):
        """Elimina una suscripción solo si pertenece al usuario indicado."""
        item = self.session.query(PushSubscription).filter_by(
            user_id=user_id,
            endpoint=endpoint,
        ).one_or_none()
        if item is not None:
            self.session.delete(item)
            self.session.commit()

    def delete_user_data(self, user_id):
        """Elimina los avisos y suscripciones de la cuenta en el servicio."""
        self.session.query(Notification).filter_by(user_id=user_id).delete()
        self.session.query(PushSubscription).filter_by(user_id=user_id).delete()
        self.session.commit()
