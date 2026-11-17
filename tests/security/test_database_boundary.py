"""The De-sanitization Service must have no way to reach the Sanitization database."""

import ast
import importlib
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import AppFactory
from tests.support.service_loader import services_dir

FORBIDDEN_IMPORT_ROOTS = {
    "sqlalchemy",
    "alembic",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sanitization_service",
}
SAN_DATABASE_URL = "postgresql+psycopg://vault:vault-pass@db.invalid:5432/vault"


def _desanitization_sources() -> list[Path]:
    return sorted((services_dir() / "desanitization_service").rglob("*.py"))


def _settings_class() -> Any:
    return importlib.import_module("app.core.config").Settings


def test_desanitization_service_source_exists() -> None:
    assert _desanitization_sources(), "desanitization service has no source files"


def test_desanitization_sources_import_no_database_or_sanitization_code() -> None:
    offenders: list[str] = []
    for path in _desanitization_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{path.name}: {name}"
                for name in names
                if name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS
            ]
    assert offenders == []


def test_desanitization_settings_declare_no_database_field(
    desanitization_app_factory: AppFactory,
) -> None:
    desanitization_app_factory()
    fields = set(_settings_class().model_fields)
    assert not [f for f in fields if "database" in f or "db" in f.split("_")]


def test_desanitization_settings_ignore_a_sanitization_database_url_in_environment(
    desanitization_app_factory: AppFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    desanitization_app_factory()
    monkeypatch.setenv("PRIVYFLOW_SAN_DATABASE_URL", SAN_DATABASE_URL)
    monkeypatch.setenv("PRIVYFLOW_DESAN_DATABASE_URL", SAN_DATABASE_URL)
    monkeypatch.setenv("DATABASE_URL", SAN_DATABASE_URL)
    settings = importlib.import_module("app.core.config").load_settings()
    assert SAN_DATABASE_URL not in repr(settings.model_dump())
    assert not hasattr(settings, "database_url")


def test_desanitization_settings_ignore_a_sanitization_database_url_in_env_file(
    desanitization_app_factory: AppFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desanitization_app_factory()
    env_file = tmp_path / "desan.env"
    env_file.write_text(
        f"PRIVYFLOW_SAN_DATABASE_URL={SAN_DATABASE_URL}\n"
        f"PRIVYFLOW_DESAN_DATABASE_URL={SAN_DATABASE_URL}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PRIVYFLOW_DESAN_ENV_FILE", str(env_file))
    settings = importlib.import_module("app.core.config").load_settings()
    assert SAN_DATABASE_URL not in repr(settings.model_dump())


def _desanitization_app_imports() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in _desanitization_sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [(path, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.append((path, node.module))
    return [(p, name) for p, name in found if name == "app" or name.startswith("app.")]


def test_every_app_module_the_desanitization_service_imports_is_its_own() -> None:
    """Both services have a top-level package named `app`. An import that resolves to a module
    only the Sanitization Service has would be a runtime dependency on it."""
    own_root = services_dir() / "desanitization_service"
    missing: list[str] = []
    for path, name in _desanitization_app_imports():
        relative = Path(*name.split("."))
        if not (
            (own_root / relative).with_suffix(".py").is_file() or (own_root / relative).is_dir()
        ):
            missing.append(f"{path.name}: {name}")
    assert _desanitization_app_imports()
    assert missing == []


def test_the_desanitization_sources_name_no_sanitization_setting_or_database_credential() -> None:
    offenders = [
        path.name
        for path in _desanitization_sources()
        if "PRIVYFLOW_SAN_" in path.read_text(encoding="utf-8")
        or "sanitization_service" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
