"""Manage Sanitization Service settings: validate, show, export and import.

    uv run scripts/settings.py validate [--file PATH]
    uv run scripts/settings.py show [--backend file|db]
    uv run scripts/settings.py import [--file PATH] [--actor NAME] [--dry-run]
    uv run scripts/settings.py export --out PATH [--force] [--actor NAME]

The settings file defaults to PRIVYFLOW_SETTINGS_FILE, then config/settings.json. Database
commands connect as the settings admin role named by
PRIVYFLOW_SAN_SETTINGS_ADMIN_DATABASE_URL (environment or the service .env file). The
running service cannot make these changes. Exit codes: 0 done, 1 failed or invalid, 2 setup
missing. Output never includes secrets, only settings fields and hashes.
"""

import argparse
import difflib
import getpass
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import Engine, create_engine

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = ROOT / "services" / "sanitization_service"
ADMIN_URL_ENV = "PRIVYFLOW_SAN_SETTINGS_ADMIN_DATABASE_URL"
EXIT_FAILED = 1
EXIT_SETUP = 2


class SetupError(Exception):
    pass


def _settings_file(argument: str | None) -> Path:
    if argument:
        return Path(argument)
    return Path(os.environ.get("PRIVYFLOW_SETTINGS_FILE") or ROOT / "config" / "settings.json")


def _admin_engine() -> Engine:
    url = os.environ.get(ADMIN_URL_ENV)
    if not url:
        env_file = os.environ.get("PRIVYFLOW_SAN_ENV_FILE", str(SERVICE_ROOT / ".env"))
        url = dotenv_values(env_file).get(ADMIN_URL_ENV)
    if not url:
        raise SetupError(f"Set {ADMIN_URL_ENV} to use database commands.")
    return create_engine(url)


def _actor(argument: str | None) -> str:
    return argument or getpass.getuser()


def run(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(SERVICE_ROOT))
    from app.settings import admin
    from app.settings.snapshot import SettingsSnapshot
    from app.settings.store import DbSettingsStore, FileSettingsStore

    def describe(snapshot: SettingsSnapshot) -> str:
        return f"backend={snapshot.backend} version={snapshot.version} hash={snapshot.content_hash}"

    if args.command == "validate":
        snapshot = FileSettingsStore(_settings_file(args.file)).load()
        print(f"settings valid: hash={snapshot.content_hash}")
        return 0

    if args.command == "show":
        backend = args.backend or os.environ.get("PRIVYFLOW_SETTINGS_BACKEND", "file")
        if backend == "db":
            snapshot = DbSettingsStore(_admin_engine()).load()
        else:
            snapshot = FileSettingsStore(_settings_file(None)).load()
        print(describe(snapshot))
        print(admin.render_pretty(snapshot.content), end="")
        return 0

    if args.command == "import":
        incoming = FileSettingsStore(_settings_file(args.file)).load()
        engine = _admin_engine()
        stored = admin.latest_stored(engine)
        old_text = stored.pretty if stored else ""
        new_text = admin.render_pretty(incoming.content)
        diff = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="database",
            tofile="file",
        )
        print("".join(diff), end="")
        if stored and stored.content_hash == incoming.content_hash:
            print(f"no change: hash={incoming.content_hash}")
            return 0
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        imported = admin.apply_import(engine, incoming.content, _actor(args.actor))
        print(f"imported: version={imported.version} hash={imported.content_hash}")
        return 0

    out = Path(args.out)
    if out.exists() and not args.force:
        print("Output file exists. Use --force to overwrite it.", file=sys.stderr)
        return EXIT_FAILED
    exported = admin.record_export(_admin_engine(), _actor(args.actor))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(admin.render_pretty(exported.content), encoding="utf-8")
    print(f"exported: version={exported.version} hash={exported.content_hash}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="check a settings file")
    validate.add_argument("--file")
    show = commands.add_parser("show", help="print the settings a backend would load")
    show.add_argument("--backend", choices=["file", "db"])
    importer = commands.add_parser("import", help="load a settings file into the database")
    importer.add_argument("--file")
    importer.add_argument("--actor")
    importer.add_argument("--dry-run", action="store_true")
    export = commands.add_parser("export", help="write the database settings to a file")
    export.add_argument("--out", required=True)
    export.add_argument("--force", action="store_true")
    export.add_argument("--actor")
    args = parser.parse_args()
    sys.path.insert(0, str(SERVICE_ROOT))
    from app.settings.validator import SettingsError

    try:
        return run(args)
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAILED
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_SETUP


if __name__ == "__main__":
    sys.exit(main())
