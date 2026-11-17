"""SQLAlchemy declarative base. Import `app.models` to register every table on it."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
