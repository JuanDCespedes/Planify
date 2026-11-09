"""Adaptadores SMTP y Web Push propiedad del microservicio de entrega."""

import base64
import binascii
import json
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit

from pywebpush import WebPushException, webpush
from requests.exceptions import RequestException


def email_is_configured(config):
    """Indica si el servicio dispone de host SMTP y dirección remitente."""
    return bool(config.get("SMTP_HOST") and config.get("SMTP_FROM"))


def push_is_configured(config):
    """Indica si el servicio dispone de claves VAPID y correo de contacto."""
    return bool(
        config.get("VAPID_PRIVATE_KEY")
        and config.get("VAPID_PUBLIC_KEY")
        and config.get("VAPID_CLAIMS_EMAIL")
    )


def _send_smtp_message(message, config):
    """Envía un mensaje mediante SSL directo o STARTTLS según la configuración."""
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


def send_email(recipient, subject, body, config):
    """Envía el texto recibido al destinatario mediante la cuenta SMTP del servicio."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["SMTP_FROM"]
    message["To"] = recipient
    message.set_content(body)
    _send_smtp_message(message, config)


def valid_push_subscription(subscription):
    """Acepta solo endpoints HTTPS conocidos y claves Web Push bien formadas."""
    if not isinstance(subscription, dict):
        return False
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")
    if not isinstance(endpoint, str) or len(endpoint) > 4096 or not isinstance(keys, dict):
        return False
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    trusted_host = (
        host in {
            "fcm.googleapis.com",
            "web.push.apple.com",
            "push.services.mozilla.com",
            "updates.push.services.mozilla.com",
        }
        or host == "notify.windows.com"
        or host.endswith(".push.services.mozilla.com")
        or host.endswith(".notify.windows.com")
    )
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not isinstance(p256dh, str) or not isinstance(auth, str):
        return False
    if len(p256dh) > 255 or len(auth) > 255:
        return False
    try:
        decoded_p256dh = base64.b64decode(
            p256dh + "=" * ((4 - len(p256dh) % 4) % 4),
            altchars=b"-_",
            validate=True,
        )
        decoded_auth = base64.b64decode(
            auth + "=" * ((4 - len(auth) % 4) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and port in (None, 443)
        and not parsed.username
        and not parsed.password
        and trusted_host
        and len(decoded_p256dh) == 65
        and decoded_p256dh[0] == 4
        and len(decoded_auth) == 16
    )


def send_push(subscriptions, title, body, target_url, tag, config, logger):
    """Entrega push a suscripciones válidas y devuelve endpoints expirados."""
    payload = json.dumps({"title": title, "body": body, "url": target_url, "tag": tag})
    sent = 0
    failed = 0
    expired_endpoints = []
    for subscription in subscriptions:
        if not valid_push_subscription(subscription):
            failed += 1
            continue
        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=config["VAPID_PRIVATE_KEY"],
                vapid_claims={"sub": config["VAPID_CLAIMS_EMAIL"]},
                ttl=3600,
            )
            sent += 1
        except (WebPushException, RequestException, ValueError) as error:
            response = getattr(error, "response", None)
            if response is not None and response.status_code in (404, 410):
                expired_endpoints.append(subscription["endpoint"])
            else:
                failed += 1
                logger.error("Web Push delivery failed: %s", error)
    return {"sent": sent, "failed": failed, "expired_endpoints": expired_endpoints}