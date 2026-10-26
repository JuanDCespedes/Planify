from sqlalchemy import inspect, text


def migrate_sqlite_user_ownership(engine):
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        inspector = inspect(connection)
        for table in ("events", "routine_blocks", "notifications"):
            if table in inspector.get_table_names():
                columns = {column["name"] for column in inspector.get_columns(table)}
                if "user_id" not in columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table} "
                            "ADD COLUMN user_id INTEGER REFERENCES users(id)"
                        )
                    )
