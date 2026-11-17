"""Database engine creation and the readiness probe."""

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, text

from app.core.config import load_settings


def create_db_engine(url: str) -> Engine:
    # pool_pre_ping drops dead connections; the short connect timeout keeps readiness fast.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def database_is_reachable(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1


def get_engine(app: FastAPI) -> Engine:
    """Return the app's engine, creating it on first use from the runtime database URL."""
    if getattr(app.state, "engine", None) is None:
        app.state.engine = create_db_engine(load_settings().database_url.get_secret_value())
    engine: Engine = app.state.engine
    return engine
