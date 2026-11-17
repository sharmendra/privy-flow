"""Generate local-only settings files, one per service.

    uv run scripts/gen_local_secrets.py --admin-url postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow

Writes services/<service>/.env and config/settings.json (a copy of the example). All three
are git-ignored. Existing files are kept unless --force is given. The generated database
passwords are random. These values are for local development only. Later phases add more
generated secrets here.
"""

import argparse
import secrets
import shutil
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
SAN_ENV = Path("services/sanitization_service/.env")
DESAN_ENV = Path("services/desanitization_service/.env")
SETTINGS_FILE = Path("config/settings.json")
SETTINGS_EXAMPLE = Path("config/settings.example.json")
RUNTIME_ROLE = "privyflow_runtime"
SETTINGS_ADMIN_ROLE = "privyflow_settings_admin"


def _role_url(admin_url: str, role: str) -> str:
    return (
        make_url(admin_url)
        .set(drivername="postgresql+psycopg", username=role, password=secrets.token_hex(24))
        .render_as_string(hide_password=False)
    )


def _sanitization_env(admin_url: str) -> str:
    return (
        "# Local development only. Never commit this file.\n"
        f"PRIVYFLOW_SAN_DATABASE_URL={_role_url(admin_url, RUNTIME_ROLE)}\n"
        f"PRIVYFLOW_SAN_MIGRATION_DATABASE_URL={admin_url}\n"
        "# Used only by scripts/settings.py, never by the running service.\n"
        f"PRIVYFLOW_SAN_SETTINGS_ADMIN_DATABASE_URL={_role_url(admin_url, SETTINGS_ADMIN_ROLE)}\n"
    )


def _desanitization_env(sanitization_url: str) -> str:
    return (
        "# Local development only. Never commit this file.\n"
        f"PRIVYFLOW_DESAN_SANITIZATION_BASE_URL={sanitization_url}\n"
    )


def generate(
    root: Path,
    admin_url: str,
    sanitization_url: str = "http://127.0.0.1:8001",
    force: bool = False,
) -> list[Path]:
    """Write the local files and return the paths written."""
    contents = {
        root / SAN_ENV: _sanitization_env(admin_url),
        root / DESAN_ENV: _desanitization_env(sanitization_url),
    }
    written: list[Path] = []
    for path, text in contents.items():
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    settings = root / SETTINGS_FILE
    if not settings.exists() or force:
        settings.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / SETTINGS_EXAMPLE, settings)
        written.append(settings)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-url", required=True, help="PostgreSQL admin URL for migrations")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()
    written = generate(ROOT, args.admin_url, force=args.force)
    for path in written:
        print(f"wrote {path.relative_to(ROOT)}")
    if not written:
        print("nothing written: files exist (use --force to overwrite)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
