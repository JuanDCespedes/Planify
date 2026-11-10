"""API interna para las operaciones de eventos, categorías y rutinas."""

import hmac
import os
from datetime import date, time, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, current_app, g, jsonify, request

from planify.domain.rules import CATEGORY_COLORS, REMINDERS, validate_category, validate_event, validate_routine_block
from planning_service.models import Category, Event, RoutineBlock, create_database
from planning_service.repositories import PlanningRepository


DEFAULT_CATEGORIES = (
    ("Trabajo", "work"),
    ("Estudio", "study"),
    ("Personal", "personal"),
    ("Salud", "health"),
    ("Otro", "other"),
)


def _category_dto(category):
    """Serializa una categoría sin relaciones a otros servicios."""
    return {"id": category.id, "user_id": category.user_id, "name": category.name, "color": category.color}


def _event_dto(event, category):
    """Serializa un evento e incluye su categoría en el DTO de respuesta."""
    return {
        "id": event.id,
        "user_id": event.user_id,
        "title": event.title,
        "event_date": event.event_date.isoformat(),
        "start_time": event.start_time.strftime("%H:%M"),
        "category": CATEGORY_COLORS.get(category.color, "Otro").casefold(),
        "category_id": category.id,
        "category_item": _category_dto(category),
        "reminder": event.reminder,
    }


def _routine_dto(block):
    """Serializa un bloque semanal para el gateway y el scheduler."""
    return {
        "id": block.id,
        "user_id": block.user_id,
        "title": block.title,
        "start_time": block.start_time.strftime("%H:%M"),
        "duration_minutes": block.duration_minutes,
        "day_of_week": block.day_of_week,
    }


def create_app(test_config=None):
    """Construye el API de planificación con base de datos independiente."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    app = Flask(__name__)
    instance_dir = Path(__file__).resolve().parents[1] / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        DATABASE_URL=os.environ.get(
            "PLANNING_DATABASE_URL",
            f"sqlite:///{(instance_dir / 'planning.db').as_posix()}",
        ),
        SERVICE_TOKEN=os.environ.get(
            "PLANIFY_SERVICE_TOKEN", os.environ.get("PLANIFY_DELIVERY_SERVICE_TOKEN", "")
        ),
    )
    if test_config:
        app.config.update(test_config)
    engine, session_factory = create_database(app.config["DATABASE_URL"])
    app.extensions["planning_engine"] = engine
    app.extensions["planning_session_factory"] = session_factory

    @app.before_request
    def authenticate_internal_request():
        """Protege todas las rutas internas salvo health con el token compartido."""
        if request.path == "/health":
            return None
        token = current_app.config.get("SERVICE_TOKEN", "")
        supplied = request.headers.get("Authorization", "")
        if not token or not hmac.compare_digest(supplied, f"Bearer {token}"):
            return jsonify({"error": "Autenticación interna no válida."}), 401
        g.planning_session = session_factory()
        return None

    @app.teardown_request
    def close_session(_error=None):
        """Cierra la sesión de planificación al completar la solicitud."""
        session = g.pop("planning_session", None)
        if session is not None:
            session.close()

    @app.get("/health")
    def health():
        """Expone una comprobación de vida sin detalles de la base."""
        return jsonify({"status": "ok"})

    @app.post("/api/v1/users/<int:user_id>/bootstrap")
    def bootstrap_user(user_id):
        """Crea categorías y datos de muestra solo al aprovisionar una cuenta vacía."""
        session = g.planning_session
        repository = PlanningRepository(session)
        existing = {item.color for item in repository.categories(user_id)}
        categories_by_color = {}
        for name, color in DEFAULT_CATEGORIES:
            if color not in existing:
                category = Category(user_id=user_id, name=name, color=color)
                session.add(category)
                categories_by_color[color] = category
        session.flush()
        categories_by_color.update({item.color: item for item in repository.categories(user_id)})

        if not session.query(Event.id).filter_by(user_id=user_id).first():
            today = date.today()
            samples = (
                ("Planificar la semana", today, time(9, 0), "work", "15m"),
                ("Revisar avances del proyecto", today, time(11, 30), "study", "30m"),
                ("Pausa para caminar", today, time(16, 0), "health", "at_time"),
                ("Entrega del proyecto", today + timedelta(days=2), time(10, 0), "study", "1d"),
                ("Café con Alex", today + timedelta(days=4), time(17, 30), "personal", "1h"),
            )
            session.add_all(
                [
                    Event(
                        user_id=user_id,
                        title=title,
                        event_date=event_date,
                        start_time=start_time,
                        category_id=categories_by_color[color].id,
                        reminder=reminder,
                    )
                    for title, event_date, start_time, color, reminder in samples
                ]
            )

        if not session.query(RoutineBlock.id).filter_by(user_id=user_id).first():
            session.add_all(
                [
                    RoutineBlock(
                        user_id=user_id,
                        title=title,
                        start_time=start_time,
                        duration_minutes=duration,
                        day_of_week=date.today().weekday(),
                    )
                    for title, start_time, duration in (
                        ("Rutina de mañana", time(7, 0), 45),
                        ("Bloque de concentración", time(9, 0), 90),
                        ("Pausa y estiramientos", time(11, 0), 15),
                        ("Cierre del día", time(17, 0), 30),
                    )
                ]
            )
        session.commit()
        return jsonify({"categories": [_category_dto(item) for item in repository.categories(user_id)]})

    @app.get("/api/v1/users/<int:user_id>/categories")
    def list_categories(user_id):
        """Lista únicamente categorías del identificador de usuario solicitado."""
        items = PlanningRepository(g.planning_session).categories(user_id)
        return jsonify({"categories": [_category_dto(item) for item in items]})

    @app.post("/api/v1/users/<int:user_id>/categories")
    def create_category(user_id):
        """Valida y crea una categoría personal."""
        payload = request.get_json(silent=True) or {}
        name, color = payload.get("name", ""), payload.get("color", "")
        errors = validate_category(name, color)
        repository = PlanningRepository(g.planning_session)
        if not errors and repository.category_by_name(name.strip(), user_id):
            errors.append("Ya existe una categoría con ese nombre.")
        if errors:
            return jsonify({"errors": errors}), 400
        category = Category(user_id=user_id, name=name.strip(), color=color)
        g.planning_session.add(category)
        g.planning_session.commit()
        return jsonify({"category": _category_dto(category)}), 201

    @app.patch("/api/v1/users/<int:user_id>/categories/<int:category_id>")
    def update_category(user_id, category_id):
        """Actualiza nombre y color de una categoría propia."""
        payload = request.get_json(silent=True) or {}
        category = PlanningRepository(g.planning_session).category(category_id, user_id)
        if category is None:
            return jsonify({"errors": ["No encontramos esa categoría."]}), 404
        name, color = payload.get("name", ""), payload.get("color", "")
        errors = validate_category(name, color)
        existing = PlanningRepository(g.planning_session).category_by_name(name.strip(), user_id)
        if not errors and existing and existing.id != category.id:
            errors.append("Ya existe una categoría con ese nombre.")
        if errors:
            return jsonify({"errors": errors}), 400
        category.name, category.color = name.strip(), color
        g.planning_session.commit()
        return jsonify({"category": _category_dto(category)})

    @app.delete("/api/v1/users/<int:user_id>/categories/<int:category_id>")
    def delete_category(user_id, category_id):
        """Elimina una categoría solo si no tiene eventos y no es la última."""
        session = g.planning_session
        repository = PlanningRepository(session)
        category = repository.category(category_id, user_id)
        if category is None:
            return jsonify({"errors": ["No encontramos esa categoría."]}), 404
        if len(repository.categories(user_id)) <= 1:
            return jsonify({"errors": ["Debes conservar al menos una categoría."]}), 400
        if repository.events_between(user_id, date.min, date.max) and any(
            event.category_id == category.id for event in repository.events_between(user_id, date.min, date.max)
        ):
            return jsonify({"errors": ["Esta categoría tiene eventos."]}), 400
        session.delete(category)
        session.commit()
        return jsonify({"deleted": True})

    @app.get("/api/v1/users/<int:user_id>/events")
    def list_events(user_id):
        """Lista eventos propios dentro del intervalo de fechas solicitado."""
        try:
            start_date = date.fromisoformat(request.args["start"])
            end_date = date.fromisoformat(request.args["end"])
        except (KeyError, ValueError):
            return jsonify({"error": "Indica fechas start y end válidas."}), 400
        repository = PlanningRepository(g.planning_session)
        events = repository.events_between(user_id, start_date, end_date)
        return jsonify({"events": [_event_dto(event, repository.category(event.category_id, user_id)) for event in events]})

    @app.get("/api/v1/users/<int:user_id>/events/<int:event_id>")
    def get_event(user_id, event_id):
        """Devuelve un evento solo si pertenece al usuario indicado."""
        repository = PlanningRepository(g.planning_session)
        event = repository.event(event_id, user_id)
        if event is None:
            return jsonify({"error": "No encontramos ese evento."}), 404
        return jsonify({"event": _event_dto(event, repository.category(event.category_id, user_id))})

    @app.post("/api/v1/users/<int:user_id>/events")
    def create_event(user_id):
        """Valida y crea un evento; crea la categoría si se envía por nombre."""
        return save_event(user_id, None)

    @app.put("/api/v1/users/<int:user_id>/events/<int:event_id>")
    def replace_event(user_id, event_id):
        """Valida y reemplaza un evento propio existente."""
        return save_event(user_id, event_id)

    def save_event(user_id, event_id):
        """Comparte validación y persistencia de altas y modificaciones de evento."""
        session = g.planning_session
        repository = PlanningRepository(session)
        event = repository.event(event_id, user_id) if event_id else None
        if event_id and event is None:
            return jsonify({"error": "No encontramos ese evento."}), 404
        payload = request.get_json(silent=True) or {}
        title = payload.get("title", "")
        try:
            event_date = date.fromisoformat(payload.get("event_date", ""))
            start_time = time.fromisoformat(payload.get("start_time", ""))
        except (TypeError, ValueError):
            event_date, start_time = None, None
        category_value = payload.get("category", "")
        category = None
        if isinstance(category_value, int):
            category = repository.category(category_value, user_id)
        elif isinstance(category_value, str):
            category = repository.category_by_name(category_value.strip(), user_id)
        errors = validate_event(
            title,
            event_date,
            start_time,
            category.id if category else 1,
            payload.get("reminder"),
        )
        if category is None and isinstance(category_value, str) and category_value.strip():
            errors = [error for error in errors if "categoría" not in error.casefold()]
            category_errors = validate_category(category_value, "other")
            errors.extend(category_errors)
            if not category_errors:
                category = Category(user_id=user_id, name=category_value.strip(), color="other")
                session.add(category)
                session.flush()
        elif category is None and not errors:
            errors.append("Selecciona una categoría de tu cuenta.")
        if errors:
            session.rollback()
            return jsonify({"errors": errors}), 400
        if event is None:
            event = Event(user_id=user_id)
            session.add(event)
        event.title = title.strip()
        event.event_date = event_date
        event.start_time = start_time
        event.category_id = category.id
        event.reminder = payload["reminder"]
        session.commit()
        return jsonify({"event": _event_dto(event, category)}), 201 if event_id is None else 200

    @app.delete("/api/v1/users/<int:user_id>/events/<int:event_id>")
    def delete_event(user_id, event_id):
        """Elimina un evento únicamente dentro del ámbito del propietario."""
        event = PlanningRepository(g.planning_session).event(event_id, user_id)
        if event is None:
            return jsonify({"deleted": True})
        g.planning_session.delete(event)
        g.planning_session.commit()
        return jsonify({"deleted": True})

    @app.get("/api/v1/users/<int:user_id>/routines")
    def list_routines(user_id):
        """Lista bloques semanales, opcionalmente filtrados por día."""
        day_value = request.args.get("day")
        try:
            day_of_week = int(day_value) if day_value is not None else None
        except ValueError:
            return jsonify({"error": "El día solicitado no es válido."}), 400
        if day_of_week is not None and not 0 <= day_of_week <= 6:
            return jsonify({"error": "El día debe estar entre 0 y 6."}), 400
        items = PlanningRepository(g.planning_session).routine_blocks(user_id, day_of_week)
        return jsonify({"routines": [_routine_dto(item) for item in items]})

    @app.post("/api/v1/users/<int:user_id>/routines")
    def create_routine(user_id):
        """Valida y añade un bloque semanal de rutina."""
        payload = request.get_json(silent=True) or {}
        try:
            start_time = time.fromisoformat(payload.get("start_time", ""))
            duration = int(payload.get("duration_minutes"))
            day = int(payload.get("day_of_week"))
        except (TypeError, ValueError):
            start_time, duration, day = None, None, None
        errors = validate_routine_block(payload.get("title", ""), start_time, duration)
        if day is None or not 0 <= day <= 6:
            errors.append("Selecciona un día de la semana válido.")
        if errors:
            return jsonify({"errors": errors}), 400
        block = RoutineBlock(
            user_id=user_id,
            title=payload["title"].strip(),
            start_time=start_time,
            duration_minutes=duration,
            day_of_week=day,
        )
        g.planning_session.add(block)
        g.planning_session.commit()
        return jsonify({"routine": _routine_dto(block)}), 201

    @app.delete("/api/v1/users/<int:user_id>/data")
    def delete_user_data(user_id):
        """Elimina todos los eventos, categorías y bloques del usuario externo."""
        session = g.planning_session
        session.query(Event).filter_by(user_id=user_id).delete()
        session.query(RoutineBlock).filter_by(user_id=user_id).delete()
        session.query(Category).filter_by(user_id=user_id).delete()
        session.commit()
        return jsonify({"deleted": True})

    @app.get("/api/v1/events/due")
    def list_due_events():
        """Lista eventos de un intervalo para el scheduler de notificaciones."""
        try:
            start_date = date.fromisoformat(request.args["start"])
            end_date = date.fromisoformat(request.args["end"])
        except (KeyError, ValueError):
            return jsonify({"error": "Indica fechas start y end válidas."}), 400
        session = g.planning_session
        repository = PlanningRepository(session)
        rows = session.query(Event).filter(Event.event_date >= start_date, Event.event_date <= end_date).all()
        return jsonify({"events": [_event_dto(item, repository.category(item.category_id, item.user_id)) for item in rows]})

    @app.get("/api/v1/routines/due")
    def list_due_routines():
        """Lista todos los bloques para que el scheduler aplique preferencias."""
        items = g.planning_session.query(RoutineBlock).all()
        return jsonify({"routines": [_routine_dto(item) for item in items]})

    return app