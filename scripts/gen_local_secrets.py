"""Generate local-only settings files, one per service.

    uv run scripts/gen_local_secrets.py --admin-url postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow

Writes services/<service>/.env and config/settings.json (a copy of the example). All three
are git-ignored. Existing files are kept unless --force is given. The generated database
passwords, API keys, encryption key and credential pepper are random. These values are for
local development only.

    uv run scripts/gen_local_secrets.py --add-missing-secrets

appends only the vault secrets that an existing Sanitization .env lacks (for a file written
before they existed). It changes nothing else and never overwrites a value.
"""

import argparse
import base64
import json
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
VAULT_SECRET_NAMES = (
    "PRIVYFLOW_SAN_API_KEYS",
    "PRIVYFLOW_SAN_ENCRYPTION_KEYS",
    "PRIVYFLOW_SAN_ACTIVE_KEY_VERSION",
    "PRIVYFLOW_SAN_CREDENTIAL_PEPPER",
    "PRIVYFLOW_SAN_SERVICE_SECRET",
)
DESAN_SECRET_NAMES = ("PRIVYFLOW_DESAN_API_KEYS", "PRIVYFLOW_DESAN_SERVICE_SECRET")
SETTINGS_ADMIN_ROLE = "privyflow_settings_admin"


def _role_url(admin_url: str, role: str) -> str:
    return (
        make_url(admin_url)
        .set(drivername="postgresql+psycopg", username=role, password=secrets.token_hex(24))
        .render_as_string(hide_password=False)
    )


def _example_tenants() -> list[str]:
    """The tenants of the example settings, so each gets an API key."""
    example = json.loads((ROOT / SETTINGS_EXAMPLE).read_text(encoding="utf-8"))
    return list(example["tenant_profiles"])


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _vault_secrets(service_secret: str | None = None) -> dict[str, str]:
    """New random values for every vault secret. JSON values are quoted for dotenv. The service
    secret is shared with the De-sanitization Service, so the caller may pass one to reuse."""
    api_keys = {tenant: secrets.token_urlsafe(32) for tenant in _example_tenants()}
    encryption_keys = {"1": _b64(secrets.token_bytes(32))}
    return {
        "PRIVYFLOW_SAN_API_KEYS": f"'{json.dumps(api_keys)}'",
        "PRIVYFLOW_SAN_ENCRYPTION_KEYS": f"'{json.dumps(encryption_keys)}'",
        "PRIVYFLOW_SAN_ACTIVE_KEY_VERSION": "1",
        "PRIVYFLOW_SAN_CREDENTIAL_PEPPER": _b64(secrets.token_bytes(32)),
        "PRIVYFLOW_SAN_SERVICE_SECRET": service_secret or _new_service_secret(),
    }


def _new_service_secret() -> str:
    return secrets.token_urlsafe(32)


def _desanitization_secrets(service_secret: str) -> dict[str, str]:
    """The De-sanitization Service's own client API keys (never the Sanitization ones) and the
    service secret it presents to the internal API."""
    api_keys = {tenant: secrets.token_urlsafe(32) for tenant in _example_tenants()}
    return {
        "PRIVYFLOW_DESAN_API_KEYS": f"'{json.dumps(api_keys)}'",
        "PRIVYFLOW_DESAN_SERVICE_SECRET": service_secret,
    }


def _present_names(text: str) -> set[str]:
    return {line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line}


def _env_value(text: str, name: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return None


def _append_missing(path: Path, existing: str, missing: dict[str, str]) -> None:
    separator = "" if not existing or existing.endswith("\n") else "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing + separator + _vault_secret_text(missing), encoding="utf-8")


def _vault_secret_text(values: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in values.items())


def add_missing_vault_secrets(root: Path) -> list[str]:
    """Append the vault secrets an existing Sanitization .env lacks. Returns their names."""
    path = root / SAN_ENV
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    present = _present_names(existing)
    missing = {n: v for n, v in _vault_secrets().items() if n not in present}
    if missing:
        _append_missing(path, existing, missing)
    return list(missing)


def add_missing_desanitization_secrets(root: Path) -> list[str]:
    """Append the De-sanitization secrets its .env lacks. The service secret is copied from the
    Sanitization .env so both match, and is generated there too if neither file has one."""
    san_path, desan_path = root / SAN_ENV, root / DESAN_ENV
    san_text = san_path.read_text(encoding="utf-8") if san_path.exists() else ""
    existing = desan_path.read_text(encoding="utf-8") if desan_path.exists() else ""
    secret = _env_value(san_text, "PRIVYFLOW_SAN_SERVICE_SECRET")
    if secret is None:
        secret = _new_service_secret()
        _append_missing(san_path, san_text, {"PRIVYFLOW_SAN_SERVICE_SECRET": secret})
    present = _present_names(existing)
    missing = {n: v for n, v in _desanitization_secrets(secret).items() if n not in present}
    if missing:
        _append_missing(desan_path, existing, missing)
    return list(missing)


def _sanitization_env(admin_url: str, service_secret: str) -> str:
    return (
        "# Local development only. Never commit this file.\n"
        f"PRIVYFLOW_SAN_DATABASE_URL={_role_url(admin_url, RUNTIME_ROLE)}\n"
        f"PRIVYFLOW_SAN_MIGRATION_DATABASE_URL={admin_url}\n"
        "# Used only by scripts/settings.py, never by the running service.\n"
        f"PRIVYFLOW_SAN_SETTINGS_ADMIN_DATABASE_URL={_role_url(admin_url, SETTINGS_ADMIN_ROLE)}\n"
        "# Public API keys by tenant, vault encryption keys by version, and the credential\n"
        "# pepper, and the service secret shared with the De-sanitization Service. Read by the\n"
        "# running service only.\n" + _vault_secret_text(_vault_secrets(service_secret))
    )


def _desanitization_env(sanitization_url: str, service_secret: str) -> str:
    return (
        "# Local development only. Never commit this file.\n"
        f"PRIVYFLOW_DESAN_SANITIZATION_BASE_URL={sanitization_url}\n"
        "# This service's own client API keys and the secret it presents to the internal API.\n"
        + _vault_secret_text(_desanitization_secrets(service_secret))
    )


def generate(
    root: Path,
    admin_url: str,
    sanitization_url: str = "http://127.0.0.1:8001",
    force: bool = False,
) -> list[Path]:
    """Write the local files and return the paths written."""
    service_secret = _new_service_secret()
    contents = {
        root / SAN_ENV: _sanitization_env(admin_url, service_secret),
        root / DESAN_ENV: _desanitization_env(sanitization_url, service_secret),
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
    parser.add_argument("--admin-url", help="PostgreSQL admin URL for migrations")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument(
        "--add-missing-secrets",
        action="store_true",
        help="append the vault secrets an existing Sanitization .env lacks",
    )
    args = parser.parse_args()
    if args.add_missing_secrets:
        names = add_missing_vault_secrets(ROOT) + add_missing_desanitization_secrets(ROOT)
        print(f"added {', '.join(names)}" if names else "nothing to add: all secrets exist")
        return 0
    if not args.admin_url:
        parser.error("--admin-url is required unless --add-missing-secrets is given")
    written = generate(ROOT, args.admin_url, force=args.force)
    for path in written:
        print(f"wrote {path.relative_to(ROOT)}")
    if not written:
        print("nothing written: files exist (use --force to overwrite)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
