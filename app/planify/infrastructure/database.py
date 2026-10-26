from pathlib import Path

from flask import current_app, g
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from planify.domain.models import Base
from planify.infrastructure.migrations import migrate_sqlite_user_ownership


def init_database(app):
    database_url = app.config.get("DATABASE_URL")
    if not database_url:
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{Path(app.instance_path, 'planify.db').as_posix()}"

    engine = create_engine(database_url, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    migrate_sqlite_user_ownership(engine)
    app.extensions["planify_engine"] = engine
    app.extensions["planify_session_factory"] = sessionmaker(bind=engine, expire_on_commit=False)

    @app.teardown_appcontext
    def close_session(_error=None):
        session = g.pop("planify_db_session", None)
        if session is not None:
            session.close()


def get_session() -> Session:
    if "planify_db_session" not in g:
        session_factory = current_app.extensions["planify_session_factory"]
        g.planify_db_session = session_factory()
    return g.planify_db_session
