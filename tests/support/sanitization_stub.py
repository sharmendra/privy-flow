"""A stand-in for the Sanitization Service's internal API, at the HTTP boundary.

It plugs into the De-sanitization client as an `httpx.MockTransport` handler, so the client's
real request building, retries, timeouts and response parsing run. It follows the saved contract
(tests/fixtures/contracts): it records whether every request it received and every response it
produced conforms, and the contract tests assert that. A scripted outcome replaces the normal
answer for one call, to simulate outages.
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from tests.support.contracts import conforms
from tests.support.vault_env import SERVICE_SECRET

OUTCOMES = (
    "connect_error",
    "connect_timeout",
    "read_timeout",
    "http_503",
    "http_500",
    "http_401",
    "http_422",
    "not_json",
    "wrong_shape",
    "conflicting_duplicates",
)


# Scripted answers that are meant to be unusable, so they are not held to the contract.
FAULTS = ("not_json", "wrong_shape", "conflicting_duplicates")


def _error(status: int, code: str, message: str) -> httpx.Response:
    body = {"error": {"code": code, "message": message, "correlation_id": "stub-correlation"}}
    return httpx.Response(status, json=body)


@dataclass
class StubCall:
    headers: dict[str, str]
    body: Any
    status: int


class SanitizationStub:
    """Mappings are keyed by (reference, tenant, scope), as the real lookup requires."""

    def __init__(self, secret: str = SERVICE_SECRET) -> None:
        self.secret = secret
        self.mappings: dict[tuple[str, str, str], dict[str, str]] = {}
        self.calls: list[StubCall] = []
        self.attempts = 0  # every request that reached the stub, including ones that raised
        self.script: list[str] = []  # outcomes for the next calls, consumed in order
        self.always: str | None = None  # an outcome for every call
        self.contract_violations: list[str] = []

    def add(self, reference: str, tenant: str, scope: str, mappings: dict[str, str]) -> None:
        self.mappings[(reference, tenant, scope)] = dict(mappings)

    def remove(self, reference: str) -> None:
        """Make a reference unknown, as expiry or revocation would."""
        for key in [k for k in self.mappings if k[0] == reference]:
            del self.mappings[key]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        headers = {k.lower(): v for k, v in request.headers.items()}
        self.attempts += 1
        outcome = self.always or (self.script.pop(0) if self.script else None)
        self._check_request(request, body)
        if outcome is not None:
            response = self._scripted(outcome)  # may raise a transport error
        else:
            response = self._answer(headers, body)
        self.calls.append(StubCall(headers, body, response.status_code))
        if outcome not in FAULTS:
            self._check_response(response)
        return response

    def _scripted(self, outcome: str) -> httpx.Response:
        if outcome == "connect_error":
            raise httpx.ConnectError("refused")
        if outcome == "connect_timeout":
            raise httpx.ConnectTimeout("timed out")
        if outcome == "read_timeout":
            raise httpx.ReadTimeout("timed out")
        if outcome == "http_503":
            return _error(503, "dependency_unavailable", "A required dependency is unavailable.")
        if outcome == "http_500":
            return _error(500, "internal_error", "An internal error occurred.")
        if outcome == "http_401":
            return _error(401, "unauthorized", "Authentication failed.")
        if outcome == "http_422":
            return _error(422, "validation_error", "The request is not valid.")
        if outcome == "not_json":
            return httpx.Response(200, content=b"<html>not json</html>")
        if outcome == "wrong_shape":
            return httpx.Response(200, json={"mappings": "nope"})
        if outcome == "conflicting_duplicates":
            item = {"placeholder": "[EMAIL_001]"}
            mappings = [{**item, "value": "one"}, {**item, "value": "two"}]
            return httpx.Response(200, json={"mappings": mappings, "policy_id": "effective"})
        raise AssertionError(f"unknown scripted outcome {outcome}")

    def _answer(self, headers: dict[str, str], body: Any) -> httpx.Response:
        if headers.get("x-service-secret") != self.secret:
            return _error(401, "unauthorized", "Authentication failed.")
        if not conforms(body, "request"):
            return _error(422, "validation_error", "The request is not valid.")
        found = self.mappings.get(
            (body["restore_reference"], body["tenant_id"], body["request_scope_id"])
        )
        if found is None:
            return _error(
                404, "restore_reference_not_found", "The restore reference was not found."
            )
        items = [{"placeholder": p, "value": v} for p, v in found.items()]
        return httpx.Response(200, json={"mappings": items, "policy_id": "effective"})

    def _check_request(self, request: httpx.Request, body: Any) -> None:
        """Record any way the client's request departs from the saved contract."""
        if request.url.path != "/internal/v1/mappings/retrieve" or request.method != "POST":
            self.contract_violations.append("wrong route or method")
        if not conforms(body, "request"):
            self.contract_violations.append("request does not conform")
        if "x-service-secret" not in {k.lower() for k in request.headers}:
            self.contract_violations.append("no service secret header")

    def _check_response(self, response: httpx.Response) -> None:
        """Record any way the stub's own answer departs from the saved contract."""
        section = "response_200" if response.status_code == 200 else "error"
        if not conforms(json.loads(response.content), section):
            self.contract_violations.append(f"{response.status_code} response does not conform")
