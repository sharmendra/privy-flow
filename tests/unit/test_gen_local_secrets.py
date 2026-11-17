"""The local secrets script writes separate env files and never overwrites by accident."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from scripts.gen_local_secrets import (
    DESAN_ENV,
    DESAN_SECRET_NAMES,
    SAN_ENV,
    SETTINGS_FILE,
    VAULT_SECRET_NAMES,
    add_missing_desanitization_secrets,
    add_missing_vault_secrets,
    generate,
)

ADMIN_URL = "postgresql+psycopg://admin:adminpw@localhost:5432/db"


def _paths(root: Path) -> tuple[Path, Path]:
    return root / SAN_ENV, root / DESAN_ENV


def test_generate_writes_one_env_file_per_service(tmp_path: Path) -> None:
    written = generate(tmp_path, admin_url="postgresql+psycopg://admin:adminpw@localhost:5432/db")
    san, desan = _paths(tmp_path)
    assert written == [san, desan, tmp_path / SETTINGS_FILE]
    san_text = san.read_text(encoding="utf-8")
    assert "PRIVYFLOW_SAN_DATABASE_URL=postgresql+psycopg://privyflow_runtime:" in san_text
    assert "PRIVYFLOW_SAN_MIGRATION_DATABASE_URL=postgresql+psycopg://admin:adminpw@" in san_text


def test_desanitization_env_file_contains_no_database_setting(tmp_path: Path) -> None:
    generate(tmp_path, admin_url="postgresql+psycopg://admin:adminpw@localhost:5432/db")
    text = _paths(tmp_path)[1].read_text(encoding="utf-8").lower()
    assert "database" not in text
    assert "postgres" not in text
    assert "adminpw" not in text


def test_runtime_password_is_random_per_run(tmp_path: Path) -> None:
    url = "postgresql+psycopg://admin:adminpw@localhost:5432/db"
    generate(tmp_path / "one", admin_url=url)
    generate(tmp_path / "two", admin_url=url)
    first = _paths(tmp_path / "one")[0].read_text(encoding="utf-8")
    second = _paths(tmp_path / "two")[0].read_text(encoding="utf-8")
    assert first != second


def test_existing_files_are_kept_unless_forced(tmp_path: Path) -> None:
    url = "postgresql+psycopg://admin:adminpw@localhost:5432/db"
    generate(tmp_path, admin_url=url)
    san = _paths(tmp_path)[0]
    san.write_text("KEEP ME", encoding="utf-8")
    assert generate(tmp_path, admin_url=url) == []
    assert san.read_text(encoding="utf-8") == "KEEP ME"
    assert san in generate(tmp_path, admin_url=url, force=True)
    assert san.read_text(encoding="utf-8") != "KEEP ME"


def test_sanitization_env_has_separate_settings_admin_credentials(tmp_path: Path) -> None:
    generate(tmp_path, admin_url="postgresql+psycopg://admin:adminpw@localhost:5432/db")
    text = _paths(tmp_path)[0].read_text(encoding="utf-8")
    lines = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    runtime = lines["PRIVYFLOW_SAN_DATABASE_URL"]
    settings_admin = lines["PRIVYFLOW_SAN_SETTINGS_ADMIN_DATABASE_URL"]
    assert "privyflow_settings_admin:" in settings_admin
    assert runtime.split("@")[0] != settings_admin.split("@")[0]


def test_local_settings_file_is_a_valid_copy_of_the_example(tmp_path: Path) -> None:
    import json

    generate(tmp_path, admin_url="postgresql+psycopg://admin:adminpw@localhost:5432/db")
    created = json.loads((tmp_path / SETTINGS_FILE).read_text(encoding="utf-8"))
    assert created["schema_version"] == 1
    assert "tenant_profiles" in created


def _san_values(root: Path) -> dict[str, str | None]:
    return dict(dotenv_values(root / SAN_ENV))


def test_sanitization_env_has_every_vault_secret_in_a_form_the_service_accepts(
    tmp_path: Path, san: Callable[[str], Any]
) -> None:
    generate(tmp_path, admin_url=ADMIN_URL)
    values = _san_values(tmp_path)
    assert all(values[name] for name in VAULT_SECRET_NAMES)
    config = san("app.vault.config")
    keyring = config.parse_keyring(
        values["PRIVYFLOW_SAN_ENCRYPTION_KEYS"] or "",
        int(values["PRIVYFLOW_SAN_ACTIVE_KEY_VERSION"] or 0),
    )
    assert keyring.active_version == 1
    assert len(config.parse_pepper(values["PRIVYFLOW_SAN_CREDENTIAL_PEPPER"] or "")) == 32
    api_keys = san("app.core.auth").parse_api_keys(values["PRIVYFLOW_SAN_API_KEYS"] or "")
    example = json.loads(Path("config/settings.example.json").read_text(encoding="utf-8"))
    assert set(api_keys) == set(example["tenant_profiles"])


def test_vault_secrets_are_random_per_run(tmp_path: Path) -> None:
    generate(tmp_path / "one", admin_url=ADMIN_URL)
    generate(tmp_path / "two", admin_url=ADMIN_URL)
    one, two = _san_values(tmp_path / "one"), _san_values(tmp_path / "two")
    for name in (
        "PRIVYFLOW_SAN_API_KEYS",
        "PRIVYFLOW_SAN_ENCRYPTION_KEYS",
        "PRIVYFLOW_SAN_CREDENTIAL_PEPPER",
    ):
        assert one[name] != two[name]


def test_desanitization_env_gets_no_vault_secret(tmp_path: Path) -> None:
    generate(tmp_path, admin_url=ADMIN_URL)
    text = (tmp_path / DESAN_ENV).read_text(encoding="utf-8")
    assert not [name for name in VAULT_SECRET_NAMES if name in text]
    assert "PEPPER" not in text.upper()
    assert "ENCRYPTION" not in text.upper()


def test_add_missing_secrets_appends_only_what_is_absent(tmp_path: Path) -> None:
    san = tmp_path / SAN_ENV
    san.parent.mkdir(parents=True)
    san.write_text(
        "PRIVYFLOW_SAN_DATABASE_URL=keep-me\nPRIVYFLOW_SAN_ACTIVE_KEY_VERSION=7", encoding="utf-8"
    )
    added = add_missing_vault_secrets(tmp_path)
    values = _san_values(tmp_path)
    assert added == [n for n in VAULT_SECRET_NAMES if n != "PRIVYFLOW_SAN_ACTIVE_KEY_VERSION"]
    assert values["PRIVYFLOW_SAN_DATABASE_URL"] == "keep-me"
    assert values["PRIVYFLOW_SAN_ACTIVE_KEY_VERSION"] == "7"  # an existing value is never changed
    assert all(values[name] for name in VAULT_SECRET_NAMES)


def test_add_missing_secrets_twice_changes_nothing_the_second_time(tmp_path: Path) -> None:
    san = tmp_path / SAN_ENV
    san.parent.mkdir(parents=True)
    san.write_text("PRIVYFLOW_SAN_DATABASE_URL=x\n", encoding="utf-8")
    assert add_missing_vault_secrets(tmp_path)
    after_first = san.read_text(encoding="utf-8")
    assert add_missing_vault_secrets(tmp_path) == []
    assert san.read_text(encoding="utf-8") == after_first


def _desan_values(root: Path) -> dict[str, str | None]:
    return dotenv_values(root / DESAN_ENV)


def test_both_services_get_the_same_service_secret_and_different_client_keys(
    tmp_path: Path,
) -> None:
    generate(tmp_path, admin_url=ADMIN_URL)
    san, desan = _san_values(tmp_path), _desan_values(tmp_path)
    assert all(desan[name] for name in DESAN_SECRET_NAMES)
    assert san["PRIVYFLOW_SAN_SERVICE_SECRET"] == desan["PRIVYFLOW_DESAN_SERVICE_SECRET"]
    san_keys = set(json.loads(san["PRIVYFLOW_SAN_API_KEYS"] or "{}").values())
    desan_keys = set(json.loads(desan["PRIVYFLOW_DESAN_API_KEYS"] or "{}").values())
    assert desan_keys
    assert not san_keys & desan_keys
    assert san["PRIVYFLOW_SAN_SERVICE_SECRET"] not in san_keys | desan_keys


def test_add_missing_desanitization_secrets_copies_the_existing_service_secret(
    tmp_path: Path,
) -> None:
    san = tmp_path / SAN_ENV
    san.parent.mkdir(parents=True)
    san.write_text(f"PRIVYFLOW_SAN_SERVICE_SECRET={'s' * 40}\n", encoding="utf-8")
    desan = tmp_path / DESAN_ENV
    desan.parent.mkdir(parents=True)
    desan.write_text("PRIVYFLOW_DESAN_SANITIZATION_BASE_URL=http://x\n", encoding="utf-8")
    assert add_missing_desanitization_secrets(tmp_path) == list(DESAN_SECRET_NAMES)
    values = _desan_values(tmp_path)
    assert values["PRIVYFLOW_DESAN_SERVICE_SECRET"] == "s" * 40
    assert values["PRIVYFLOW_DESAN_SANITIZATION_BASE_URL"] == "http://x"
    assert add_missing_desanitization_secrets(tmp_path) == []


def test_add_missing_desanitization_secrets_creates_the_shared_secret_when_neither_has_one(
    tmp_path: Path,
) -> None:
    (tmp_path / SAN_ENV).parent.mkdir(parents=True)
    (tmp_path / SAN_ENV).write_text("PRIVYFLOW_SAN_DATABASE_URL=x\n", encoding="utf-8")
    add_missing_desanitization_secrets(tmp_path)
    assert (
        _san_values(tmp_path)["PRIVYFLOW_SAN_SERVICE_SECRET"]
        == _desan_values(tmp_path)["PRIVYFLOW_DESAN_SERVICE_SECRET"]
    )
