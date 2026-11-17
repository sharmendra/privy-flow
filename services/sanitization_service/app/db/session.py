"""Database engine creation and the readiness probe."""

from sqlalchemy import Engine, create_engine, text


def create_db_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def database_is_reachable(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
