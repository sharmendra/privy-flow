"""Helpers for proving sensitive values never reach logs, errors or metrics."""

from collections.abc import Iterable

# Synthetic canary values. Never real customer data.
CANARIES = (
    "Canary Person",
    "canary.person@example.com",
    "+1 202-555-0199",
    "4111 1111 1111 1111",
)


def assert_no_leak(captured: str | Iterable[str], secrets: Iterable[str] = CANARIES) -> None:
    """Fail if any secret appears in the captured text (logs, response bodies, errors)."""
    text = captured if isinstance(captured, str) else "\n".join(captured)
    leaked = [s for s in secrets if s in text]
    if leaked:
        raise AssertionError(f"{len(leaked)} sensitive value(s) found in captured output")
