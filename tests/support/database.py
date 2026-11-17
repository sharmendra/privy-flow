"""Helpers for per-test PostgreSQL databases.

An admin URL (a role that may create databases) is turned into a fresh, uniquely named
database for each test, which is dropped afterwards. The admin URL comes from
PRIVYFLOW_TEST_DATABASE_URL or from a Testcontainers PostgreSQL (needs Docker).
"""

import uuid

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def to_psycopg_dsn(url: str) -> str:
    """Convert a SQLAlchemy URL into a libpq connection string for psycopg."""
    parsed = make_url(url)
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


def create_database(admin_url: str) -> str:
    """Create an empty uniquely named database and return its SQLAlchemy URL."""
    name = f"pf_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(to_psycopg_dsn(admin_url), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return make_url(admin_url).set(database=name).render_as_string(hide_password=False)


def drop_database(admin_url: str, url: str) -> None:
    name = make_url(url).database
    assert name is not None and name.startswith("pf_test_")
    with psycopg.connect(to_psycopg_dsn(admin_url), autocommit=True) as conn:
        statement = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
        conn.execute(statement.format(sql.Identifier(name)))
