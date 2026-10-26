from datetime import date, datetime, time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from planify.domain.models import Category, Event, Notification, RoutineBlock, User


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def by_email(self, email: str):
        return self.session.scalar(select(User).where(User.email == email))

    def by_id(self, user_id: int):
        return self.session.get(User, user_id)

    def by_google_subject(self, google_subject: str):
        return self.session.scalar(select(User).where(User.google_subject == google_subject))

    def add(self, user: User):
        self.session.add(user)

    def delete(self, user: User):
        self.session.delete(user)


class CategoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def all(self, user_id: int):
        return self.session.scalars(
            select(Category).where(Category.user_id == user_id).order_by(Category.name.collate("NOCASE"))
        ).all()

    def get(self, category_id: int, user_id: int):
        return self.session.scalar(
            select(Category).where(Category.id == category_id, Category.user_id == user_id)
        )

    def by_name(self, name: str, user_id: int, exclude_id: int | None = None):
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
        return self.session.scalar(
            select(Event.id).where(
                Event.category_id == category_id,
                Event.user_id == user_id,
            ).limit(1)
        ) is not None

    def add(self, category: Category):
        self.session.add(category)

    def delete(self, category: Category):
        self.session.delete(category)

class EventRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, event_id, user_id: int):
        return self.session.scalar(
            select(Event).where(Event.id == event_id, Event.user_id == user_id)
        )

    def between(self, start_date: date, end_date: date, user_id: int):
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
        self.session.add(event)

    def delete(self, event):
        self.session.delete(event)


class RoutineRepository:
    def __init__(self, session: Session):
        self.session = session

    def for_day(self, day_of_week: int, user_id: int):
        return self.session.scalars(
            select(RoutineBlock)
            .where(
                RoutineBlock.user_id == user_id,
                RoutineBlock.day_of_week == day_of_week,
            )
            .order_by(RoutineBlock.start_time)
        ).all()

    def add(self, block):
        self.session.add(block)


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def all(self, user_id: int):
        return self.session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.is_read, Notification.created_at.desc())
        ).all()

    def get(self, notification_id, user_id: int):
        return self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )

    def mark_all_read(self, user_id: int):
        self.session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )

    def add(self, notification):
        self.session.add(notification)

    def delete(self, notification):
        self.session.delete(notification)
