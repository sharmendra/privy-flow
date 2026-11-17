"""List the HTTP routes of a FastAPI app, including routers added with include_router."""

from typing import Any


def http_routes(app: Any) -> list[tuple[str, str]]:
    """(method, path) for every route. HEAD is left out because it mirrors GET."""
    found: list[tuple[str, str]] = []
    for route in app.routes:
        routes = route.original_router.routes if hasattr(route, "original_router") else [route]
        for inner in routes:
            methods = getattr(inner, "methods", None) or ()
            found += [(m, inner.path) for m in sorted(methods) if m != "HEAD"]
    return found
