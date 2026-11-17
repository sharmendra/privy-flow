"""Generate local-only settings files, one per service.

    uv run scripts/gen_local_secrets.py --admin-url postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow

Writes services/<service>/.env, which is git-ignored. Existing files are kept unless
--force is given. The generated runtime database password is random. These values are for
local development only. Later phases add more generated secrets here.
"""

import argparse
import secrets
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
SAN_ENV = Path("services/sanitization_service/.env")
DESAN_ENV = Path("services/desanitization_service/.env")
RUNTIME_ROLE = "privyflow_runtime"


def _sanitization_env(admin_url: str) -> str:
    runtime_url = (
        make_url(admin_url)
        .set(drivername="postgresql+psycopg", username=RUNTIME_ROLE, password=secrets.token_hex(24))
        .render_as_string(hide_password=False)
    )
    return (
        "# Local development only. Never commit this file.\n"
        f"PRIVYFLOW_SAN_DATABASE_URL={runtime_url}\n"
        f"PRIVYFLOW_SAN_MIGRATION_DATABASE_URL={admin_url}\n"
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
    """Write the env files and return the paths written."""
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
