"""Validación de credenciales, registro y autenticación local o Google."""

import re
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from planify.application.services import seed_demo_data
from planify.domain.models import User
from planify.infrastructure.repositories import UserRepository


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    """Recorta espacios y normaliza el correo para comparaciones coherentes."""
    return email.strip().casefold()


def validate_email(email: str) -> list[str]:
    """Valida la forma y longitud de un correo y devuelve errores legibles."""
    normalized_email = normalize_email(email)
    if len(normalized_email) > 254 or not _EMAIL_PATTERN.fullmatch(normalized_email):
        return ["Escribe un correo electrónico válido."]
    return []


def validate_registration(email: str, password: str, confirmation: str) -> list[str]:
    """Valida correo, longitud de contraseña y coincidencia de confirmación."""
    errors = validate_email(email)
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres.")
    elif len(password) > MAX_PASSWORD_LENGTH:
        errors.append(f"La contraseña no puede superar los {MAX_PASSWORD_LENGTH} caracteres.")
    if password != confirmation:
        errors.append("Las contraseñas no coinciden.")
    return errors


class AuthenticationService:
    """Coordina el acceso y la creación de cuentas mediante repositorios."""

    def __init__(self, session: Session):
        """Prepara el servicio con la sesión SQLAlchemy de la operación."""
        self.session = session
        self.users = UserRepository(session)

    def register(self, email: str, password: str, confirmation: str):
        """Crea una cuenta válida y sus datos iniciales, o devuelve errores."""
        errors = validate_registration(email, password, confirmation)
        if errors:
            return None, errors

        normalized_email = normalize_email(email)
        if self.users.by_email(normalized_email):
            return None, ["Ese correo ya está registrado. Inicia sesión o usa otro correo."]

        user = User(email=normalized_email)
        user.set_password(password)
        self.users.add(user)

        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            if self.users.by_email(normalized_email):
                return None, ["Ese correo ya está registrado. Inicia sesión o usa otro correo."]
            raise

        seed_demo_data(self.session, user.id)
        self.session.commit()
        return user, []

    def authenticate(self, email: str, password: str):
        """Autentica credenciales locales sin revelar si el correo existe."""
        normalized_email = normalize_email(email)
        user = self.users.by_email(normalized_email)
        encoded_password = password if len(password) <= MAX_PASSWORD_LENGTH else ""
        password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
        password_is_valid = check_password_hash(password_hash, encoded_password)
        if user and user.password_login_enabled and password_is_valid:
            return user
        return None

    def get_user(self, user_id: int):
        """Busca una cuenta por su identificador."""
        return self.users.by_id(user_id)

    def authenticate_google(self, email: str, google_subject: str, display_name: str):
        """Busca, vincula o crea una cuenta con una identidad Google verificada."""
        normalized_email = normalize_email(email)
        user = self.users.by_google_subject(google_subject)
        if user:
            return user, []

        user = self.users.by_email(normalized_email)
        if user:
            user.google_subject = google_subject
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                linked_user = self.users.by_google_subject(google_subject)
                if linked_user:
                    return linked_user, []
                raise
            return user, []

        user = User(
            email=normalized_email,
            google_subject=google_subject,
            display_name=display_name[:60],
            password_login_enabled=False,
        )
        user.set_password(secrets.token_urlsafe(32))
        self.users.add(user)
        try:
            self.session.flush()
            seed_demo_data(self.session, user.id)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing_user = self.users.by_google_subject(google_subject)
            if existing_user:
                return existing_user, []
            raise
        return user, []
