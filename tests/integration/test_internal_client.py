"""The De-sanitization Service's internal client: outages, timeouts, retries and the contract.

Every test counts the calls the stub received, so the retry bound is asserted, not assumed.
"""

import logging
from typing import Any

import pytest

from tests.support.contracts import load_contract
from tests.support.desan_api import REFERENCE, SCOPE, DesanApi
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.sanitization_stub import FAULTS, OUTCOMES
from tests.support.vault_env import SERVICE_SECRET, TENANT_A

pytestmark = pytest.mark.anyio

EMAIL, PHONE = CANARIES[1], CANARIES[2]
MAPPINGS = {"[EMAIL_001]": EMAIL}
TEXT = f"Mail [EMAIL_001] {PHONE}"
MAX_ATTEMPTS = 3  # one call and at most two retries (SPEC 9.6)


def _seeded(api: DesanApi) -> None:
    api.stub.add(REFERENCE, TENANT_A, SCOPE, MAPPINGS)


def _assert_safe_503(response: Any) -> None:
    body = response.json()
    assert response.status_code == 503
    assert body["error"]["code"] == "dependency_unavailable"
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    assert body["error"]["correlation_id"]
    assert set(body) == {"error"}
    assert_no_leak(response.text, [EMAIL, PHONE, REFERENCE, SERVICE_SECRET])
    assert "sanitization.test" not in response.text  # no internal address


# (outcome, calls made): connection errors and 503 are retried up to the bound, nothing else.
FAILURES = [
    ("connect_error", MAX_ATTEMPTS),
    ("connect_timeout", MAX_ATTEMPTS),
    ("http_503", MAX_ATTEMPTS),
    ("read_timeout", 1),
    ("http_500", 1),
    ("http_401", 1),
    ("http_422", 1),
    ("not_json", 1),
    ("wrong_shape", 1),
    ("conflicting_duplicates", 1),
]


@pytest.mark.parametrize(("outcome", "calls"), FAILURES, ids=[f[0] for f in FAILURES])
async def test_a_failing_sanitization_service_gives_a_safe_503_after_a_bounded_number_of_calls(
    desan_api: DesanApi, outcome: str, calls: int
) -> None:
    _seeded(desan_api)
    desan_api.stub.always = outcome
    response = await desan_api.restore(TEXT)
    _assert_safe_503(response)
    assert desan_api.stub.attempts == calls


def test_every_scripted_outcome_is_covered_by_the_failure_table() -> None:
    assert {f[0] for f in FAILURES} == set(OUTCOMES)
    assert set(FAULTS) <= set(OUTCOMES)


async def test_a_503_is_retried_and_a_later_success_is_returned(desan_api: DesanApi) -> None:
    _seeded(desan_api)
    desan_api.stub.script = ["http_503", "http_503"]
    response = await desan_api.restore(TEXT)
    assert response.status_code == 200
    assert response.json()["restored_text"] == f"Mail {EMAIL} {PHONE}"
    assert [c.status for c in desan_api.stub.calls] == [503, 503, 200]
    assert desan_api.stub.attempts == 3


async def test_a_connection_error_is_retried_and_a_later_success_is_returned(
    desan_api: DesanApi,
) -> None:
    _seeded(desan_api)
    desan_api.stub.script = ["connect_error"]
    response = await desan_api.restore(TEXT)
    assert response.status_code == 200
    assert desan_api.stub.attempts == 2


async def test_a_404_is_final_and_is_not_retried(desan_api: DesanApi) -> None:
    response = await desan_api.restore(TEXT)
    assert response.status_code == 404
    assert desan_api.stub.attempts == 1


async def test_a_503_from_a_second_request_is_not_affected_by_the_first(
    desan_api: DesanApi,
) -> None:
    _seeded(desan_api)
    desan_api.stub.always = "http_503"
    assert (await desan_api.restore(TEXT)).status_code == 503
    desan_api.stub.always = None
    assert (await desan_api.restore(TEXT)).status_code == 200


async def test_a_failure_logs_a_category_only(
    desan_api: DesanApi, caplog: pytest.LogCaptureFixture
) -> None:
    import importlib

    caplog.set_level(logging.DEBUG)
    _seeded(desan_api)
    desan_api.stub.always = "http_500"
    await desan_api.restore(TEXT)
    formatter = importlib.import_module("app.core.logging").JsonFormatter()
    logs = "\n".join(formatter.format(r) for r in caplog.records if r.name.startswith("privyflow"))
    assert "sanitization_unavailable" in logs
    assert "UpstreamStatus500" in logs
    assert_no_leak(logs, [EMAIL, PHONE, REFERENCE, SERVICE_SECRET])


# --- the saved contract -----------------------------------------------------------------------


async def test_the_clients_requests_and_the_stubs_answers_conform_to_the_saved_contract(
    desan_api: DesanApi,
) -> None:
    _seeded(desan_api)
    desan_api.stub.add("pf1_" + "D" * 43, TENANT_A, SCOPE, {})
    await desan_api.restore(TEXT)  # 200
    await desan_api.restore(TEXT, reference="pf1_" + "E" * 43)  # 404 from the stub
    await desan_api.restore(TEXT, reference="pf1_" + "D" * 43)  # 200 with no mappings
    desan_api.stub.always = "http_503"
    await desan_api.restore(TEXT)  # 503 error bodies
    desan_api.stub.always = "http_401"
    await desan_api.restore(TEXT)
    assert len(desan_api.stub.calls) >= 6
    assert desan_api.stub.contract_violations == []


async def test_the_client_accepts_the_contract_example_and_ignores_added_fields(
    desan_api: DesanApi,
) -> None:
    example = load_contract()["examples"]["response_200"]
    assert example["mappings"][0]["placeholder"] == "[EMAIL_001]"
    desan_api.stub.add(REFERENCE, TENANT_A, SCOPE, {"[EMAIL_001]": example["mappings"][0]["value"]})
    response = await desan_api.restore("[EMAIL_001]")
    assert response.json()["restored_text"] == example["mappings"][0]["value"]


async def test_the_clients_models_agree_with_the_contract(desan_api: DesanApi) -> None:
    import importlib

    schemas = importlib.import_module("app.schemas.internal_api")
    contract = load_contract()
    item = contract["response_200"]["properties"]["mappings"]
    assert schemas.MAX_MAPPINGS == item["maxItems"]
    assert schemas.PLACEHOLDER_PATTERN == item["items"]["properties"]["placeholder"]["pattern"]
    assert set(schemas.MappingResponse.model_fields) == set(contract["response_200"]["properties"])
    assert set(schemas.MappingItem.model_fields) == set(item["items"]["properties"])
    assert contract["headers"]["X-Service-Secret"] == "required"
    assert contract["examples"]["request"]["request_scope_id"] == "scope-1"
    assert (await desan_api.client.get("/health/live")).status_code == 200
