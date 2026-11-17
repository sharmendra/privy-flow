"""Both services as separate processes over a real PostgreSQL, called over HTTP only.

This is the end-to-end harness. Nothing here imports either service. The Sanitization Service
gets a new migrated database and its own environment. The De-sanitization Service gets no
database setting at all, only the Sanitization Service's address and the shared service secret.
"""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
import psycopg
from sqlalchemy.engine import make_url

from tests.support.database import run_sql, to_psycopg_dsn
from tests.support.desan_env import DESAN_API_KEYS, desanitization_env
from tests.support.process import ServiceProcess, free_port
from tests.support.settings_data import valid_content, write_settings_file
from tests.support.vault_env import API_KEYS, TENANT_A, sanitization_secret_env

TIMEOUT = 15.0


class Stack:
    def __init__(self, database_url: str, admin_url: str, workdir: Path) -> None:
        self.database_url = database_url
        self.admin_url = admin_url
        self.workdir = workdir
        self._san_port = free_port()
        self._desan_port = free_port()
        self._runs = 0
        settings = write_settings_file(workdir / "settings.json", valid_content())
        self.san_env = {
            "PRIVYFLOW_SAN_DATABASE_URL": database_url,
            "PRIVYFLOW_SETTINGS_FILE": str(settings),
            **sanitization_secret_env(),
        }
        self.desan_env = desanitization_env(f"http://127.0.0.1:{self._san_port}")
        self.san: ServiceProcess | None = None
        self.desan: ServiceProcess | None = None
        self._logs: list[Path] = []
        self.san_http = httpx.Client(base_url=f"http://127.0.0.1:{self._san_port}", timeout=TIMEOUT)
        self.desan_http = httpx.Client(
            base_url=f"http://127.0.0.1:{self._desan_port}", timeout=TIMEOUT
        )

    # --- lifecycle ---------------------------------------------------------------------------

    def _log_path(self, name: str) -> Path:
        self._runs += 1
        path = self.workdir / f"{name}-{self._runs}.log"
        self._logs.append(path)
        return path

    def start_sanitization(self) -> None:
        process = ServiceProcess(
            "sanitization_service", self.san_env, self._log_path("san"), self._san_port
        )
        process.wait_until_live()
        process.wait_until_ready()
        self.san = process

    def start_desanitization(self) -> None:
        process = ServiceProcess(
            "desanitization_service", self.desan_env, self._log_path("desan"), self._desan_port
        )
        process.wait_until_live()
        process.wait_until_ready()
        self.desan = process

    def start(self) -> "Stack":
        self.start_sanitization()
        self.start_desanitization()
        return self

    def stop_sanitization(self) -> None:
        if self.san is not None:
            self.san.stop()
            self.san = None

    def stop_desanitization(self) -> None:
        if self.desan is not None:
            self.desan.stop()
            self.desan = None

    def stop(self) -> None:
        self.stop_desanitization()
        self.stop_sanitization()
        self.san_http.close()
        self.desan_http.close()

    def __enter__(self) -> "Stack":
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    # --- the client application --------------------------------------------------------------

    def sanitize(
        self, text: str, tenant: str = TENANT_A, scope: str = "scope-e2e"
    ) -> httpx.Response:
        return self.san_http.post(
            "/api/v1/sanitizations",
            json={"text": text, "request_scope_id": scope, "policy_id": "effective"},
            headers={"X-API-Key": API_KEYS[tenant]},
        )

    def restore(
        self,
        sanitized: str,
        reference: str,
        tenant: str = TENANT_A,
        scope: str = "scope-e2e",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return self.desan_http.post(
            "/api/v1/desanitizations",
            json={
                "sanitized_text": sanitized,
                "restore_reference": reference,
                "request_scope_id": scope,
            },
            headers={"X-API-Key": DESAN_API_KEYS[tenant]} if headers is None else headers,
        )

    def round_trip(
        self, text: str, tenant: str = TENANT_A, scope: str = "scope-e2e"
    ) -> tuple[httpx.Response, httpx.Response | None]:
        """Sanitize, then restore with the same tenant and scope. The second is None when
        nothing reversible was stored and so no reference exists."""
        sanitized = self.sanitize(text, tenant, scope)
        assert sanitized.status_code == 200, sanitized.text
        body = sanitized.json()
        if body["restore_reference"] is None:
            return sanitized, None
        return sanitized, self.restore(
            body["sanitized_text"], body["restore_reference"], tenant, scope
        )

    # --- the database, as an operator or an attacker with write access -----------------------

    @contextmanager
    def database(self) -> Generator[psycopg.Connection[Any]]:
        with psycopg.connect(to_psycopg_dsn(self.database_url), autocommit=True) as conn:
            yield conn

    def sql(self, statement: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
        with self.database() as conn:
            cursor = run_sql(conn, statement, params)
            return cursor.fetchall() if cursor.description else []

    def database_is_unavailable(self) -> None:
        """Make this one database refuse connections and drop the open ones, as an outage
        would, without touching the server or any other test's database."""
        name = make_url(self.database_url).database
        assert name is not None and name.startswith("pf_test_")
        with psycopg.connect(to_psycopg_dsn(self.admin_url), autocommit=True) as conn:
            run_sql(conn, f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS false')
            run_sql(
                conn,
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (name,),
            )

    def database_is_available(self) -> None:
        name = make_url(self.database_url).database
        assert name is not None and name.startswith("pf_test_")
        with psycopg.connect(to_psycopg_dsn(self.admin_url), autocommit=True) as conn:
            run_sql(conn, f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS true')

    # --- evidence ------------------------------------------------------------------------------

    def logs(self) -> str:
        """Everything both services wrote, across every run of each."""
        for process in (self.san, self.desan):
            if process is not None:
                process.output()  # flush
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in self._logs)

    def desanitization_environment_names(self) -> list[str]:
        return sorted(self.desan_env)


def decode(response: httpx.Response) -> Any:
    return json.loads(response.text)
