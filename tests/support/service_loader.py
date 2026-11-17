"""Load a service's FastAPI app for in-process API tests.

Both services use a top-level package named `app`, so only one can be loaded per
process. Cross-service tests must therefore run the services as separate processes
and talk to them over HTTP.
"""

import importlib
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("sanitization_service", "desanitization_service")


def services_dir() -> Path:
    return Path(os.environ.get("PRIVYFLOW_SERVICES_DIR", REPO_ROOT / "services"))


def service_exists(service: str) -> bool:
    return (services_dir() / service / "app" / "main.py").is_file()


def _purge_app_modules() -> None:
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]


def load_service_app(service: str) -> Any | None:
    """Return the service's `app.main.app` object, or None if it is not built yet."""
    if not service_exists(service):
        return None
    root = str(services_dir() / service)
    _purge_app_modules()
    sys.path[:] = [p for p in sys.path if not p.startswith(str(services_dir()))]
    sys.path.insert(0, root)
    return importlib.import_module("app.main").app
