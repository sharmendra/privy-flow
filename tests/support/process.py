"""Start a service as a separate uvicorn process for tests."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import TracebackType

import httpx

from tests.support.service_loader import services_dir


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ServiceProcess:
    """A running service. Output goes to a log file so a full pipe can never block it."""

    def __init__(
        self, service: str, env: dict[str, str], log_path: Path, port: int | None = None
    ) -> None:
        # A fixed port lets a test stop a service and start it again where its caller expects.
        self.port = free_port() if port is None else port
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._log_path = log_path
        # Never inherit PrivyFlow settings from the developer's shell.
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("PRIVYFLOW_")}
        child_env["PRIVYFLOW_SAN_ENV_FILE"] = str(log_path.parent / "absent.env")
        child_env["PRIVYFLOW_DESAN_ENV_FILE"] = str(log_path.parent / "absent.env")
        child_env.update(env)
        self._log = log_path.open("wb")
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                str(services_dir() / service),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--no-access-log",
            ],
            env=child_env,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )

    def wait_until_live(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"service exited early with code {self._proc.returncode}")
            try:
                if httpx.get(f"{self.base_url}/health/live", timeout=1.0).status_code == 200:
                    return
            except httpx.TransportError:
                time.sleep(0.2)
        raise TimeoutError("service did not become live in time")

    def wait_until_ready(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base_url}/health/ready", timeout=1.0).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        raise TimeoutError("service did not become ready in time")

    def is_running(self) -> bool:
        return self._proc.poll() is None

    def output(self) -> str:
        self._log.flush()
        return self._log_path.read_text(encoding="utf-8", errors="replace")

    def stop(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._log.close()

    def __enter__(self) -> "ServiceProcess":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
