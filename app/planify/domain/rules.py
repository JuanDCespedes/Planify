from datetime import date, time


CATEGORIES = {
    "trabajo": "Trabajo",
    "estudio": "Estudio",
    "personal": "Personal",
    "salud": "Salud",
    "otro": "Otro",
}

REMINDERS = {
    "at_time": "A la hora del evento",
    "5m": "5 minutos antes",
    "15m": "15 minutos antes",
    "30m": "30 minutos antes",
    "1h": "1 hora antes",
    "1d": "1 día antes",
}


def validate_event(title, event_date, start_time, category, reminder):
    errors = []
    if not title or not title.strip():
        errors.append("Escribe un título para el evento.")
    elif len(title.strip()) > 120:
        errors.append("El título no puede superar los 120 caracteres.")
    if not isinstance(event_date, date):
        errors.append("Selecciona una fecha válida.")
    if not isinstance(start_time, time):
        errors.append("Selecciona una hora válida.")
    if category not in CATEGORIES:
        errors.append("Selecciona una categoría válida.")
    if reminder not in REMINDERS:
        errors.append("Selecciona un recordatorio válido.")
    return errors


def validate_routine_block(title, start_time, duration_minutes):
    errors = []
    if not title or not title.strip():
        errors.append("Escribe un nombre para el bloque.")
    elif len(title.strip()) > 100:
        errors.append("El nombre no puede superar los 100 caracteres.")
    if not isinstance(start_time, time):
        errors.append("Selecciona una hora válida.")
    if not isinstance(duration_minutes, int) or not 5 <= duration_minutes <= 480:
        errors.append("La duración debe estar entre 5 y 480 minutos.")
    return errors
