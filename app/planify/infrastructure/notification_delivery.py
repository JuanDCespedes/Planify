import base64
import json
import logging
import smtplib
import ssl
from email.message import EmailMessage

from pywebpush import WebPushException, webpush
from requests.exceptions import RequestException
from sqlalchemy import select
from sqlalchemy.orm import Session

from planify.domain.models import Notification, PushSubscription, User


def push_is_configured(config):
    return bool(
        config.get("VAPID_PUBLIC_KEY")
        and config.get("VAPID_PRIVATE_KEY")
        and config.get("VAPID_CLAIMS_EMAIL")
    )


def email_is_configured(config):
    return bool(config.get("SMTP_HOST") and config.get("SMTP_FROM"))


def send_push_notification(session: Session, notification: Notification, user: User, config, logger):
    if not user.desktop_push_notifications or not push_is_configured(config):
        return

    subscriptions = session.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).all()
    payload = json.dumps(
        {
            "title": notification.title,
            "body": notification.message,
            "url": "/notifications",
            "tag": notification.dedupe_key or f"notification-{notification.id}",
        }
    )
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=payload,
                vapid_private_key=config["VAPID_PRIVATE_KEY"],
                vapid_claims={"sub": config["VAPID_CLAIMS_EMAIL"]},
                ttl=3600,
            )
        except (WebPushException, RequestException, ValueError) as error:
            response = getattr(error, "response", None)
            if response is not None and response.status_code in (404, 410):
                session.delete(subscription)
                logger.info("Removed expired push subscription for user %s", user.id)
            else:
                logger.error("Web push failed for user %s: %s", user.id, error)
    session.commit()


def send_weekly_digest(user: User, events, config, logger):
    if not email_is_configured(config):
        logger.info("Weekly email is enabled for user %s, but SMTP is not configured.", user.id)
        return False

    message = EmailMessage()
    message["Subject"] = "Tu semana en Planify"
    message["From"] = config["SMTP_FROM"]
    message["To"] = user.email
    if not events:
        body = "No tienes eventos próximos esta semana. ¡Disfruta el espacio!"
    else:
        lines = ["Estos son tus próximos eventos:"]
        lines.extend(
            f"- {event.event_date:%d/%m} · {event.start_time:%H:%M} · {event.title}"
            for event in events
        )
        body = "\n".join(lines)
    message.set_content(body)

    context = ssl.create_default_context()
    host = config["SMTP_HOST"]
    port = config.get("SMTP_PORT", 587)
    username = config.get("SMTP_USERNAME", "")
    password = config.get("SMTP_PASSWORD", "")
    if config.get("SMTP_USE_SSL"):
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
            if username:
                server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if config.get("SMTP_STARTTLS", True):
                server.starttls(context=context)
            if username:
                server.login(username, password)
            server.send_message(message)
    return True


def generate_vapid_keys():
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization

    vapid = Vapid()
    vapid.generate_keys()
    private_key = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_key = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    encoded_private_key = base64.urlsafe_b64encode(private_key).rstrip(b"=").decode("ascii")
    encoded_public_key = base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii")
    return encoded_private_key, encoded_public_key
