"""The local secrets script writes separate env files and never overwrites by accident."""

from pathlib import Path

from scripts.gen_local_secrets import DESAN_ENV, SAN_ENV, generate


def _paths(root: Path) -> tuple[Path, Path]:
    return root / SAN_ENV, root / DESAN_ENV


def test_generate_writes_one_env_file_per_service(tmp_path: Path) -> None:
    written = generate(tmp_path, admin_url="postgresql+psycopg://admin:adminpw@localhost:5432/db")
    san, desan = _paths(tmp_path)
    assert written == [san, desan]
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
