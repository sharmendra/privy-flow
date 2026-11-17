"""Create the Sanitization Service runtime database role.

    uv run scripts/create_db_roles.py

Reads services/sanitization_service/.env (written by scripts/gen_local_secrets.py). It uses
PRIVYFLOW_SAN_MIGRATION_DATABASE_URL as the admin connection and creates the role named in
PRIVYFLOW_SAN_DATABASE_URL with that URL's password. Run it before the migration so the
migration can grant the role its table privileges. Safe to run again: it updates the password.
"""

import re
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "services" / "sanitization_service" / ".env"
_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def _check(role: str) -> None:
    if not _ROLE_NAME.match(role):
        raise ValueError("invalid role name")


def ensure_runtime_role(admin_url: str, role: str, password: str) -> None:
    """Create the login role with no extra privileges, or reset its password."""
    _check(role)
    with psycopg.connect(_dsn(admin_url), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        statement = sql.SQL(
            verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
        ).format(sql.Identifier(role), sql.Literal(password))
        conn.execute(statement)


def drop_runtime_role(admin_url: str, role: str) -> None:
    """Remove the role and its privileges in the connected database. Used by tests."""
    _check(role)
    with psycopg.connect(_dsn(admin_url), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def main() -> int:
    values = dotenv_values(ENV_FILE)
    admin_url = values.get("PRIVYFLOW_SAN_MIGRATION_DATABASE_URL")
    runtime_url = values.get("PRIVYFLOW_SAN_DATABASE_URL")
    if not admin_url or not runtime_url:
        print(f"Missing database URLs in {ENV_FILE}. Run scripts/gen_local_secrets.py first.")
        return 1
    runtime = make_url(runtime_url)
    if runtime.username is None or runtime.password is None:
        print("The runtime database URL needs a user name and password.")
        return 1
    ensure_runtime_role(admin_url, runtime.username, runtime.password)
    print(f"Role {runtime.username} is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
