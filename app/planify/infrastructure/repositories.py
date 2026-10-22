from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from planify.domain.models import Event, Notification, RoutineBlock


class EventRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, event_id):
        return self.session.get(Event, event_id)

    def between(self, start_date: date, end_date: date):
        return self.session.scalars(
            select(Event)
            .where(Event.event_date >= start_date, Event.event_date <= end_date)
            .order_by(Event.event_date, Event.start_time)
        ).all()

    def add(self, event):
        self.session.add(event)

    def delete(self, event):
        self.session.delete(event)


class RoutineRepository:
    def __init__(self, session: Session):
        self.session = session

    def for_day(self, day_of_week: int):
        return self.session.scalars(
            select(RoutineBlock)
            .where(RoutineBlock.day_of_week == day_of_week)
            .order_by(RoutineBlock.start_time)
        ).all()

    def add(self, block):
        self.session.add(block)


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def all(self):
        return self.session.scalars(
            select(Notification).order_by(Notification.is_read, Notification.created_at.desc())
        ).all()

    def get(self, notification_id):
        return self.session.get(Notification, notification_id)

    def add(self, notification):
        self.session.add(notification)

    def delete(self, notification):
        self.session.delete(notification)
