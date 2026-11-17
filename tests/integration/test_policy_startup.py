"""The effective policy at startup: same result from both settings backends, strict coverage."""

import importlib
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine

from tests.conftest import AppFactory, client_for
from tests.support.service_loader import load_service_app
from tests.support.settings_data import valid_content, write_settings_file

TENANTS = ["tenant-test-a", "tenant-test-b", "tenant-test-unlisted"]


@pytest.fixture
def san() -> Callable[[str], Any]:
    load_service_app("sanitization_service")
    return importlib.import_module


@pytest.fixture
def engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    yield engine
    engine.dispose()


def _policies(resolver: Any) -> dict[str, Any]:
    return {tenant: resolver.policy_for(tenant) for tenant in TENANTS}


def test_the_same_flags_give_the_same_effective_policy_from_file_and_database(
    san: Callable[[str], Any], engine: Engine, tmp_path: Path
) -> None:
    raw = valid_content(
        tenant_profiles={
            "tenant-test-a": ["gdpr"],
            "tenant-test-b": ["hipaa", "gdpr", "pci_dss"],
        },
        default_ttl_seconds=1200,
    )
    store, admin = san("app.settings.store"), san("app.settings.admin")
    policy_module = san("app.sanitization.policy")
    from_file = store.FileSettingsStore(write_settings_file(tmp_path / "s.json", raw)).load()
    admin.apply_import(engine, san("app.settings.validator").validate_settings(raw), "test")
    from_db = store.DbSettingsStore(engine).load()
    assert (from_file.backend, from_db.backend) == ("file", "db")

    file_policies = _policies(policy_module.PolicyResolver(from_file.content))
    db_policies = _policies(policy_module.PolicyResolver(from_db.content))
    assert file_policies == db_policies
    assert file_policies["tenant-test-b"].max_ttl_seconds == 900
    assert file_policies["tenant-test-unlisted"].max_ttl_seconds == 1200


def _log_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    return [
        json.loads(formatter.format(r)) for r in caplog.records if r.name.startswith("privyflow")
    ]


# The next three tests do not need a reachable database: the policy is built from the settings
# alone, so the default (unreachable) database URL is enough to inspect application state.
@pytest.mark.anyio
async def test_a_started_service_holds_the_resolver_for_its_tenants(
    sanitization_app_factory: AppFactory,
) -> None:
    app = sanitization_app_factory()
    async with client_for(app) as client:
        assert (await client.get("/health/live")).status_code == 200
    resolver = app.state.policy_resolver
    assert "US_SSN" in resolver.policy_for("tenant-test-b").actions
    assert "US_SSN" not in resolver.policy_for("tenant-test-a").actions
    assert [p for p, _ in resolver.policy_for("tenant-test-unlisted").profiles] == ["gdpr"]


@pytest.mark.anyio
async def test_strict_coverage_leaves_no_resolver_and_logs_only_a_category(
    sanitization_app_factory: AppFactory, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    strict = write_settings_file(tmp_path / "strict.json", valid_content(strict_coverage=True))
    app = sanitization_app_factory({"PRIVYFLOW_SETTINGS_FILE": str(strict)})
    async with client_for(app) as client:
        assert (await client.get("/health/live")).status_code == 200
    assert app.state.settings_snapshot is None
    assert app.state.policy_resolver is None
    lines = _log_lines(caplog)
    (failure,) = [line for line in lines if line["event"] == "settings_load_failed"]
    assert failure["error_category"] == "SettingsError"
    assert "PERSON" not in json.dumps(lines)


@pytest.mark.anyio
async def test_settings_that_fail_validation_leave_no_resolver(
    sanitization_app_factory: AppFactory, tmp_path: Path
) -> None:
    bad = write_settings_file(tmp_path / "bad.json", valid_content(tenant_profiles={"t-ok": []}))
    app = sanitization_app_factory({"PRIVYFLOW_SETTINGS_FILE": str(bad)})
    async with client_for(app):
        pass
    assert app.state.policy_resolver is None


# With a reachable database, the only reason left for "not ready" is the policy failure.
@pytest.mark.anyio
async def test_strict_coverage_with_a_healthy_database_is_alive_but_not_ready(
    sanitization_app_factory: AppFactory, empty_database_url: str, tmp_path: Path
) -> None:
    ok = sanitization_app_factory({"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url})
    async with client_for(ok) as client:
        assert (await client.get("/health/ready")).status_code == 200
    strict = write_settings_file(tmp_path / "strict.json", valid_content(strict_coverage=True))
    app = sanitization_app_factory(
        {"PRIVYFLOW_SAN_DATABASE_URL": empty_database_url, "PRIVYFLOW_SETTINGS_FILE": str(strict)}
    )
    async with client_for(app) as client:
        assert (await client.get("/health/live")).status_code == 200
        ready = await client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable"}
