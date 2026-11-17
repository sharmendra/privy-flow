"""One contract suite for both settings backends: file and database."""

import importlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import Engine, create_engine

from tests.support.database import to_psycopg_dsn
from tests.support.service_loader import load_service_app
from tests.support.settings_data import (
    CANARY,
    INVALID_CASES,
    VALID,
    valid_content,
    write_settings_file,
)

MakeStore = Callable[[dict[str, Any]], Any]


@pytest.fixture
def san() -> Callable[[str], Any]:
    load_service_app("sanitization_service")
    return importlib.import_module


def insert_raw_snapshot(url: str, version: int, content: dict[str, Any], content_hash: str) -> None:
    """Write a row the way a tampering writer could, bypassing the validator."""
    with psycopg.connect(to_psycopg_dsn(url), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO settings_snapshots (version, content, content_hash, created_by) "
            "VALUES (%s, %s, %s, %s)",
            (version, json.dumps(content), content_hash, "test"),
        )


@pytest.fixture(params=["file", "db"])
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def engine_factory() -> Iterator[Callable[[str], Engine]]:
    engines: list[Engine] = []

    def make(url: str) -> Engine:
        engines.append(create_engine(url))
        return engines[-1]

    yield make
    for engine in engines:
        engine.dispose()


@pytest.fixture
def make_store(
    backend: str,
    san: Callable[[str], Any],
    tmp_path: Path,
    request: pytest.FixtureRequest,
    engine_factory: Callable[[str], Engine],
) -> MakeStore:
    """Build a store of the parametrized backend holding the given raw content."""
    store_module = san("app.settings.store")

    def build(raw: dict[str, Any]) -> Any:
        if backend == "file":
            return store_module.FileSettingsStore(write_settings_file(tmp_path / "s.json", raw))
        url: str = request.getfixturevalue("migrated_database_url")
        engine = engine_factory(url)
        content = san("app.settings.validator").validate_settings(raw)
        san("app.settings.admin").apply_import(engine, content, "test")
        return store_module.DbSettingsStore(engine)

    return build


def test_both_backends_give_identical_content_and_hash(
    san: Callable[[str], Any], make_store: MakeStore, backend: str
) -> None:
    snapshot = make_store(VALID).load()
    expected = san("app.settings.validator").validate_settings(VALID)
    assert snapshot.backend == backend
    assert snapshot.content == expected
    assert snapshot.content_hash == san("app.settings.snapshot").content_hash(expected)


def test_loaded_snapshot_is_immutable(make_store: MakeStore) -> None:
    snapshot = make_store(VALID).load()
    with pytest.raises(Exception, match="frozen|cannot assign"):
        snapshot.version = 99
    with pytest.raises(Exception, match="frozen|cannot assign"):
        snapshot.content.default_ttl_seconds = 1


@pytest.mark.parametrize(
    ("case", "overrides", "field"), INVALID_CASES, ids=[c[0] for c in INVALID_CASES]
)
def test_invalid_content_fails_loading_in_both_backends(
    san: Callable[[str], Any],
    backend: str,
    tmp_path: Path,
    request: pytest.FixtureRequest,
    engine_factory: Callable[[str], Engine],
    case: str,
    overrides: dict[str, Any],
    field: str,
) -> None:
    store_module = san("app.settings.store")
    raw = valid_content(**overrides)
    if backend == "file":
        store = store_module.FileSettingsStore(write_settings_file(tmp_path / "bad.json", raw))
    else:
        url: str = request.getfixturevalue("migrated_database_url")
        insert_raw_snapshot(url, 1, raw, "0" * 64)
        store = store_module.DbSettingsStore(engine_factory(url))
    with pytest.raises(san("app.settings.validator").SettingsError) as raised:
        store.load()
    assert field in str(raised.value)
    assert CANARY not in str(raised.value)


def test_file_backend_fails_when_file_is_missing(san: Callable[[str], Any], tmp_path: Path) -> None:
    store = san("app.settings.store").FileSettingsStore(tmp_path / "missing.json")
    with pytest.raises(san("app.settings.validator").SettingsError, match="not found"):
        store.load()


@pytest.mark.parametrize("text", ["{not json " + CANARY, "[1, 2]", ""])
def test_file_backend_fails_on_unreadable_content_without_echoing_it(
    san: Callable[[str], Any], tmp_path: Path, text: str
) -> None:
    path = tmp_path / "broken.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(san("app.settings.validator").SettingsError) as raised:
        san("app.settings.store").FileSettingsStore(path).load()
    assert CANARY not in str(raised.value)


def test_file_backend_accepts_a_utf8_byte_order_mark(
    san: Callable[[str], Any], tmp_path: Path
) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(VALID).encode("utf-8"))
    assert (
        san("app.settings.store").FileSettingsStore(path).load().content.default_ttl_seconds == 1800
    )


def test_db_backend_fails_when_no_snapshot_exists(
    san: Callable[[str], Any], migrated_database_url: str, engine_factory: Callable[[str], Engine]
) -> None:
    store = san("app.settings.store").DbSettingsStore(engine_factory(migrated_database_url))
    with pytest.raises(san("app.settings.validator").SettingsError, match="no settings snapshot"):
        store.load()


def test_db_backend_fails_when_database_is_unreachable(
    san: Callable[[str], Any],
) -> None:
    # A closed port can take minutes to fail on Windows without a connect timeout.
    engine = create_engine(
        "postgresql+psycopg://nobody:nopass@127.0.0.1:1/none", connect_args={"connect_timeout": 2}
    )
    try:
        with pytest.raises(san("app.settings.validator").SettingsError, match="unavailable"):
            san("app.settings.store").DbSettingsStore(engine).load()
    finally:
        engine.dispose()


def test_db_backend_rejects_a_row_whose_hash_does_not_match_its_content(
    san: Callable[[str], Any], migrated_database_url: str, engine_factory: Callable[[str], Engine]
) -> None:
    insert_raw_snapshot(
        migrated_database_url,
        1,
        san("app.settings.validator").validate_settings(VALID).model_dump(mode="json"),
        "f" * 64,
    )
    store = san("app.settings.store").DbSettingsStore(engine_factory(migrated_database_url))
    with pytest.raises(san("app.settings.validator").SettingsError, match="hash"):
        store.load()


def test_db_backend_uses_the_highest_version(
    san: Callable[[str], Any], migrated_database_url: str, engine_factory: Callable[[str], Engine]
) -> None:
    engine = engine_factory(migrated_database_url)
    validator = san("app.settings.validator")
    admin = san("app.settings.admin")
    admin.apply_import(engine, validator.validate_settings(VALID), "test")
    second = admin.apply_import(
        engine, validator.validate_settings(valid_content(default_ttl_seconds=900)), "test"
    )
    loaded = san("app.settings.store").DbSettingsStore(engine).load()
    assert loaded.version == second.version == 2
    assert loaded.content.default_ttl_seconds == 900
