"""Security properties of the De-sanitization Service: authorization, isolation and leakage."""

import importlib
import itertools
import json
import logging
from typing import Any

import pytest

from tests.support.desan_api import REFERENCE, SCOPE, DesanApi
from tests.support.desan_env import DESAN_API_KEYS
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.routes import http_routes
from tests.support.vault_env import API_KEYS, SERVICE_SECRET, TENANT_A, TENANT_B

pytestmark = pytest.mark.anyio

EMAIL, PHONE, CARD = CANARIES[1], CANARIES[2], CANARIES[3]
MAPPINGS = {"[EMAIL_001]": EMAIL, "[PHONE_001]": PHONE, "[FINANCIAL_001]": CARD}
TEXT = "Mail [EMAIL_001], call [PHONE_001], card [FINANCIAL_001]"
SECRETS_IN_PLAY = [SERVICE_SECRET, *DESAN_API_KEYS.values(), *API_KEYS.values()]


def _captured(caplog: pytest.LogCaptureFixture) -> str:
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    return "\n".join(formatter.format(r) for r in caplog.records if r.name.startswith("privyflow"))


async def test_a_restore_reference_alone_never_authorizes_restoration(desan_api: DesanApi) -> None:
    desan_api.stub.add(REFERENCE, TENANT_A, SCOPE, MAPPINGS)
    for method, path in http_routes(desan_api.app):
        if not path.startswith("/api/"):
            continue
        response = await desan_api.client.request(
            method,
            path,
            json={
                "sanitized_text": TEXT,
                "restore_reference": REFERENCE,
                "request_scope_id": SCOPE,
            },
        )
        assert response.status_code == 401
        assert_no_leak(response.text)
    assert desan_api.stub.attempts == 0


async def test_an_unauthenticated_caller_cannot_tell_a_real_reference_from_a_made_up_one(
    desan_api: DesanApi,
) -> None:
    desan_api.stub.add(REFERENCE, TENANT_A, SCOPE, MAPPINGS)
    bodies: list[tuple[int, str]] = []
    for reference in (REFERENCE, "pf1_" + "Z" * 43, "garbage"):
        response = await desan_api.restore(TEXT, reference=reference, headers={})
        body = response.json()
        body["error"]["correlation_id"] = "-"
        bodies.append((response.status_code, json.dumps(body, sort_keys=True)))
    assert len(set(bodies)) == 1
    assert desan_api.stub.attempts == 0


async def test_no_service_credential_works_on_the_public_route(desan_api: DesanApi) -> None:
    desan_api.stub.add(REFERENCE, TENANT_A, SCOPE, MAPPINGS)
    for credential in (SERVICE_SECRET, API_KEYS[TENANT_A], API_KEYS[TENANT_B]):
        for header in ("X-API-Key", "X-Service-Secret", "Authorization"):
            response = await desan_api.restore(TEXT, headers={header: credential})
            assert response.status_code == 401, header


async def test_no_reference_restores_across_the_tenant_and_scope_matrix_except_its_own(
    desan_api: DesanApi,
) -> None:
    tenants = (TENANT_A, TENANT_B)
    scopes = ("scope-1", "scope-2")
    references = {
        (tenant, scope): "pf1_" + f"{index}".rjust(43, "x")
        for index, (tenant, scope) in enumerate(itertools.product(tenants, scopes))
    }
    for (tenant, scope), reference in references.items():
        desan_api.stub.add(reference, tenant, scope, MAPPINGS)
    own: list[int] = []
    cross: list[int] = []
    for (owner, owner_scope), reference in references.items():
        for tenant, scope in itertools.product(tenants, scopes):
            response = await desan_api.restore(
                TEXT, reference=reference, tenant=tenant, scope=scope
            )
            is_own = (tenant, scope) == (owner, owner_scope)
            (own if is_own else cross).append(response.status_code)
    assert own == [200] * 4
    assert cross == [404] * 12


async def test_restored_values_never_reach_logs_or_error_bodies(
    desan_api: DesanApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    desan_api.stub.add(REFERENCE, TENANT_A, SCOPE, MAPPINGS)
    failures = [
        await desan_api.restore(TEXT, headers={"X-API-Key": f"wrong-{CARD}"}),
        await desan_api.restore(TEXT, tenant=TENANT_B),
        await desan_api.restore(TEXT, scope="other"),
        await desan_api.restore(TEXT, reference=f"bad-{EMAIL}"),
        await desan_api.restore(TEXT, scope=f"{EMAIL} bad scope"),
    ]
    desan_api.stub.always = "http_500"
    failures.append(await desan_api.restore(TEXT))
    desan_api.stub.always = None
    ok = await desan_api.restore(TEXT)  # the only response that carries restored text
    assert ok.status_code == 200
    assert [r.status_code for r in failures] == [401, 404, 404, 404, 422, 503]
    for response in failures:
        assert_no_leak(response.text)
        assert_no_leak(response.text, [REFERENCE, f"wrong-{CARD}", *SECRETS_IN_PLAY])
    logs = _captured(caplog)
    assert "restoration_completed" in logs
    assert_no_leak(logs)
    assert_no_leak(logs, [REFERENCE, "pf1_", TEXT, *SECRETS_IN_PLAY])


async def test_the_audit_log_line_holds_counts_and_an_opaque_tenant_only(
    desan_api: DesanApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    desan_api.stub.add(REFERENCE, TENANT_A, SCOPE, MAPPINGS)
    await desan_api.restore(
        TEXT + " [EMAIL_009]", headers={**desan_api.headers(), "X-Correlation-ID": "audit-check-01"}
    )
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    lines = [
        json.loads(formatter.format(r)) for r in caplog.records if r.name.startswith("privyflow")
    ]
    (audit,) = [line for line in lines if line["event"] == "restoration_completed"]
    assert audit["correlation_id"] == "audit-check-01"
    assert audit["operation"] == "restore"
    assert (audit["restored_count"], audit["unmatched_count"]) == (3, 1)
    assert audit["tenant_ref"] != TENANT_A
    assert TENANT_A not in json.dumps(audit)
    assert set(audit) <= {
        "ts",
        "level",
        "event",
        "service",
        "version",
        "correlation_id",
        "operation",
        "tenant_ref",
        "restored_count",
        "unmatched_count",
        "outcome",
    }


async def test_an_unexpected_error_in_restoration_is_a_standard_500_without_values(
    desan_api: DesanApi, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG)
    desan_api.stub.add(REFERENCE, TENANT_A, SCOPE, MAPPINGS)
    module: Any = importlib.import_module("app.api.desanitizations")

    def boom(*args: Any) -> Any:
        raise RuntimeError(f"boom {EMAIL} {PHONE} {SERVICE_SECRET}")

    monkeypatch.setattr(module, "restore", boom)
    response = await desan_api.restore(TEXT)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "Traceback" not in response.text
    assert_no_leak(response.text)
    assert_no_leak(response.text, SECRETS_IN_PLAY)
    assert_no_leak(_captured(caplog))
    assert_no_leak(_captured(caplog), SECRETS_IN_PLAY)


async def test_the_internal_client_never_follows_a_redirect_with_the_secret(
    desan_api: DesanApi,
) -> None:
    client: Any = desan_api.app.state.sanitization_client
    assert client._client.follow_redirects is False  # pyright: ignore[reportPrivateUsage]
    assert SERVICE_SECRET not in repr(client)
