"""The scripts/settings.py command line tool, run as a real process."""

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url

from scripts.create_db_roles import drop_role, ensure_role
from tests.support.database import run_sql, to_psycopg_dsn
from tests.support.migrations import upgrade
from tests.support.service_loader import REPO_ROOT
from tests.support.settings_data import CANARY, VALID, valid_content, write_settings_file

SCRIPT = REPO_ROOT / "scripts" / "settings.py"
HASH = re.compile(r"hash=([0-9a-f]{64})")
ADMIN_URL_ENV = "PRIVYFLOW_SAN_SETTINGS_ADMIN_DATABASE_URL"


class Cli:
    def __init__(self, admin_url: str | None, settings_file: Path) -> None:
        self.admin_url = admin_url
        self.settings_file = settings_file

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("PRIVYFLOW_")}
        env["PRIVYFLOW_SETTINGS_FILE"] = str(self.settings_file)
        env["PRIVYFLOW_SAN_ENV_FILE"] = str(self.settings_file.parent / "absent.env")
        if self.admin_url:
            env[ADMIN_URL_ENV] = self.admin_url
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            cwd=self.settings_file.parent,
            timeout=60,
            check=False,
        )


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    return write_settings_file(tmp_path / "settings.json")


@pytest.fixture
def admin_cli(migrated_database_url: str, settings_file: Path) -> Iterator[Cli]:
    """A tool that connects as a dedicated settings admin role with a random password."""
    role, password = f"pf_test_cli_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    ensure_role(migrated_database_url, role, password)
    from tests.support.migrations import downgrade

    downgrade(migrated_database_url, "base")
    upgrade(migrated_database_url, settings_admin_role=role)
    url = make_url(migrated_database_url).set(username=role, password=password)
    try:
        yield Cli(url.render_as_string(hide_password=False), settings_file)
    finally:
        drop_role(migrated_database_url, role)


def _count(url: str, table: str) -> int:
    with psycopg.connect(to_psycopg_dsn(url), autocommit=True) as conn:
        row = run_sql(conn, f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def test_validate_accepts_a_valid_file_and_prints_its_hash(settings_file: Path) -> None:
    result = Cli(None, settings_file).run("validate")
    assert result.returncode == 0
    assert HASH.search(result.stdout)


def test_validate_rejects_a_secret_field_naming_it_but_not_its_value(tmp_path: Path) -> None:
    bad = write_settings_file(tmp_path / "bad.json", valid_content(encryption_key=CANARY))
    result = Cli(None, bad).run("validate")
    assert result.returncode == 1
    assert "encryption_key" in result.stdout + result.stderr
    assert CANARY not in result.stdout + result.stderr


def test_validate_accepts_an_explicit_file_argument(tmp_path: Path, settings_file: Path) -> None:
    other = write_settings_file(tmp_path / "other.json", valid_content(default_ttl_seconds=900))
    first = HASH.search(Cli(None, settings_file).run("validate").stdout)
    second = HASH.search(Cli(None, settings_file).run("validate", "--file", str(other)).stdout)
    assert first and second and first.group(1) != second.group(1)


def test_show_prints_the_file_snapshot(settings_file: Path) -> None:
    result = Cli(None, settings_file).run("show", "--backend", "file")
    assert result.returncode == 0
    assert "backend=file" in result.stdout
    assert "tenant-test-b" in result.stdout


def test_import_prints_a_diff_and_writes_the_snapshot_and_audit_row(
    admin_cli: Cli, migrated_database_url: str
) -> None:
    result = admin_cli.run("import", "--actor", "cli-tester")
    assert result.returncode == 0, result.stderr
    assert "+" in result.stdout and "tenant-test-b" in result.stdout
    assert "imported" in result.stdout
    assert _count(migrated_database_url, "settings_snapshots") == 1
    assert _count(migrated_database_url, "settings_audit") == 1


def test_import_of_unchanged_content_adds_nothing(
    admin_cli: Cli, migrated_database_url: str
) -> None:
    admin_cli.run("import")
    result = admin_cli.run("import")
    assert result.returncode == 0
    assert "no change" in result.stdout
    assert _count(migrated_database_url, "settings_snapshots") == 1
    assert _count(migrated_database_url, "settings_audit") == 1


def test_import_dry_run_prints_a_diff_and_writes_nothing(
    admin_cli: Cli, migrated_database_url: str
) -> None:
    result = admin_cli.run("import", "--dry-run")
    assert result.returncode == 0
    assert "tenant-test-a" in result.stdout
    assert _count(migrated_database_url, "settings_snapshots") == 0
    assert _count(migrated_database_url, "settings_audit") == 0


def test_import_of_invalid_settings_writes_nothing(
    admin_cli: Cli, migrated_database_url: str, tmp_path: Path
) -> None:
    bad = write_settings_file(
        tmp_path / "bad.json", valid_content(default_ttl_seconds=99999, pepper=CANARY)
    )
    result = admin_cli.run("import", "--file", str(bad))
    assert result.returncode == 1
    assert CANARY not in result.stdout + result.stderr
    assert _count(migrated_database_url, "settings_snapshots") == 0
    assert _count(migrated_database_url, "settings_audit") == 0


def test_export_then_import_round_trips_to_the_same_hash(admin_cli: Cli, tmp_path: Path) -> None:
    imported = admin_cli.run("import")
    original = HASH.search(imported.stdout)
    out = tmp_path / "exported.json"
    exported = admin_cli.run("export", "--out", str(out))
    assert exported.returncode == 0, exported.stderr
    reread = HASH.search(Cli(None, out).run("validate").stdout)
    assert original and reread and original.group(1) == reread.group(1)
    again = admin_cli.run("import", "--file", str(out))
    assert "no change" in again.stdout


def test_export_refuses_to_overwrite_without_force(admin_cli: Cli, tmp_path: Path) -> None:
    admin_cli.run("import")
    out = tmp_path / "exported.json"
    out.write_text("keep", encoding="utf-8")
    assert admin_cli.run("export", "--out", str(out)).returncode == 1
    assert out.read_text(encoding="utf-8") == "keep"
    assert admin_cli.run("export", "--out", str(out), "--force").returncode == 0


def test_show_db_reflects_the_imported_version(admin_cli: Cli) -> None:
    admin_cli.run("import")
    result = admin_cli.run("show", "--backend", "db")
    assert "backend=db" in result.stdout
    assert "version=1" in result.stdout


def test_database_commands_without_an_admin_url_fail_clearly(settings_file: Path) -> None:
    result = Cli(None, settings_file).run("import")
    assert result.returncode == 2
    assert ADMIN_URL_ENV in result.stdout + result.stderr


def test_import_never_writes_secret_like_values_to_the_database(
    admin_cli: Cli, migrated_database_url: str
) -> None:
    admin_cli.run("import")
    with psycopg.connect(to_psycopg_dsn(migrated_database_url), autocommit=True) as conn:
        dump = repr(conn.execute("SELECT * FROM settings_snapshots").fetchall())
        dump += repr(conn.execute("SELECT * FROM settings_audit").fetchall())
    assert str(make_url(admin_cli.admin_url or "").password) not in dump
    assert VALID["tenant_profiles"]["tenant-test-a"][0] in dump
