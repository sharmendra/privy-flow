"""End-to-end pilot scenarios: both services as separate processes over a real PostgreSQL.

A client script plays the client application and calls the two services over HTTP only. Nothing
here imports either service. Direct SQL stands in for an operator who expires, revokes or deletes
a record, and for an attacker with write access to the vault database.
"""

import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.support.desan_env import DESAN_API_KEYS
from tests.support.leak import CANARIES, assert_no_leak
from tests.support.stack import Stack
from tests.support.vault_env import API_KEYS, SERVICE_SECRET, TENANT_A, TENANT_B

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
UNKNOWN_REFERENCE = "pf1_" + "Q" * 43
EMAIL, PHONE, CARD = CANARIES[1], CANARIES[2], CANARIES[3]
CANARY_TEXT = f"Mail {EMAIL}, call {PHONE}, card {CARD}, name {CANARIES[0]}."


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _corpus() -> list[tuple[str, str]]:
    """Every text the pilot supports: the detection dataset, the pilot samples, and two long
    generated documents."""
    texts = [
        (f"eval-{r['id']}", r["text"]) for r in _jsonl(FIXTURES / "eval/detection_dataset.jsonl")
    ]
    texts += [(f"pilot-{r['id']}", r["text"]) for r in _jsonl(FIXTURES / "pilot/corpus.jsonl")]
    paragraphs = [
        f"Paragraph {n}: write to user{n}@example.com or call +1 202-555-{100 + n % 100:04d}.\r\n"
        for n in range(400)
    ]
    texts.append(("generated-long-crlf", "".join(paragraphs)))
    texts.append(("generated-repeat", " ".join(["same@example.com"] * 500)))
    return texts


def _normalized(response: httpx.Response) -> dict[str, Any]:
    """An error body with the per-request correlation ID replaced by a constant."""
    body = response.json()
    assert body["error"]["correlation_id"] == response.headers["X-Correlation-ID"]
    return {"error": {**body["error"], "correlation_id": "-"}}


def _assert_not_found(response: httpx.Response) -> None:
    assert response.status_code == 404
    assert _normalized(response) == {
        "error": {
            "code": "restore_reference_not_found",
            "message": "The restore reference was not found.",
            "correlation_id": "-",
        }
    }


def _issue(
    stack: Stack, scope: str, tenant: str = TENANT_A, text: str = CANARY_TEXT
) -> dict[str, Any]:
    response = stack.sanitize(text, tenant, scope)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["restore_reference"] is not None
    return body


def _wait_ready(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health/ready", timeout=2.0).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.3)
    raise TimeoutError("service did not become ready again")


# --- round trip -----------------------------------------------------------------------------


def test_sanitize_then_restore_returns_the_exact_original_for_every_corpus_text(
    stack: Stack,
) -> None:
    corpus = _corpus()
    assert len(corpus) >= 50
    mismatches: list[str] = []
    reversible = unchanged = 0
    for tenant in (TENANT_A, TENANT_B):
        for name, text in corpus:
            sanitized, restored = stack.round_trip(text, tenant, f"scope-{name}-{tenant}"[:128])
            if restored is None:
                unchanged += 1
                if sanitized.json()["sanitized_text"] != text:
                    mismatches.append(f"{name}: text changed but no reference issued")
                continue
            reversible += 1
            if restored.status_code != 200 or restored.json()["restored_text"] != text:
                mismatches.append(f"{name}/{tenant}: restored text differs")
    assert mismatches == []
    assert reversible > unchanged  # most of the corpus holds a pilot entity type
    assert unchanged >= 2  # texts with nothing to mask need no reference


def test_a_sanitized_text_no_longer_holds_the_values_the_tenant_policy_names(
    stack: Stack,
) -> None:
    """Tenant A has the default `gdpr` profile: email and phone are masked. The card is not
    named by that profile and there is no PERSON recognizer in the pilot, so both stay in the
    text. That is the documented coverage gap, reported in `uncovered_entity_types`."""
    body = _issue(stack, "scope-canary-1")
    assert_no_leak(body["sanitized_text"], [EMAIL, PHONE])
    assert (
        body["sanitized_text"]
        == f"Mail [EMAIL_001], call [PHONE_001], card {CARD}, name {CANARIES[0]}."
    )
    assert "PERSON" in body["uncovered_entity_types"]
    other = _issue(stack, "scope-canary-2", TENANT_B)  # gdpr and hipaa
    assert_no_leak(other["sanitized_text"], [EMAIL, PHONE])


def test_restoration_can_be_repeated_within_the_lifetime(stack: Stack) -> None:
    """Replay policy (D5): a reference is reusable until it expires, so a repeat succeeds."""
    body = _issue(stack, "scope-replay-1")
    first = stack.restore(body["sanitized_text"], body["restore_reference"], scope="scope-replay-1")
    second = stack.restore(
        body["sanitized_text"], body["restore_reference"], scope="scope-replay-1"
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["restored_text"] == second.json()["restored_text"] == CANARY_TEXT


def test_placeholders_not_in_the_mapping_stay_untouched_end_to_end(stack: Stack) -> None:
    body = _issue(stack, "scope-unknown-ph-1")
    altered = body["sanitized_text"] + " [EMAIL_099] [email_001]"
    response = stack.restore(altered, body["restore_reference"], scope="scope-unknown-ph-1")
    assert response.status_code == 200
    assert response.json()["restored_text"] == CANARY_TEXT + " [EMAIL_099] [email_001]"
    assert response.json()["unmatched_placeholder_count"] == 1


# --- isolation and authorization --------------------------------------------------------------


def test_cross_tenant_and_cross_request_restoration_all_fail_with_the_same_404(
    stack: Stack,
) -> None:
    tenants = (TENANT_A, TENANT_B)
    scopes = ("scope-iso-1", "scope-iso-2")
    issued = {(t, s): _issue(stack, s, t) for t in tenants for s in scopes}
    own_ok = cross_ok = 0
    for (owner, owner_scope), body in issued.items():
        for tenant in tenants:
            for scope in scopes:
                response = stack.restore(
                    body["sanitized_text"], body["restore_reference"], tenant, scope
                )
                if (tenant, scope) == (owner, owner_scope):
                    own_ok += response.status_code == 200
                elif response.status_code == 200:
                    cross_ok += 1
                else:
                    _assert_not_found(response)
    assert own_ok == 4
    assert cross_ok == 0


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "wrong-" + "k" * 30}, {"X-API-Key": API_KEYS[TENANT_A]}],
    ids=["no_key", "wrong_key", "sanitization_key"],
)
def test_an_unauthorized_caller_cannot_restore_even_with_a_valid_reference(
    stack: Stack, headers: dict[str, str]
) -> None:
    body = _issue(stack, "scope-unauth-1")
    response = stack.restore(
        body["sanitized_text"], body["restore_reference"], scope="scope-unauth-1", headers=headers
    )
    assert response.status_code == 401
    assert_no_leak(response.text)


def test_invalid_and_missing_references_are_rejected_with_the_same_404(stack: Stack) -> None:
    body = _issue(stack, "scope-invalid-1")
    attempts = [
        stack.restore(body["sanitized_text"], UNKNOWN_REFERENCE, scope="scope-invalid-1"),
        stack.restore(body["sanitized_text"], "not-a-reference", scope="scope-invalid-1"),
        stack.restore(
            body["sanitized_text"], body["restore_reference"][:-1], scope="scope-invalid-1"
        ),
    ]
    for response in attempts:
        _assert_not_found(response)


def test_the_internal_api_is_not_open_to_clients(stack: Stack) -> None:
    """The Sanitization internal route refuses a client API key and a De-sanitization key."""
    body = {
        "restore_reference": UNKNOWN_REFERENCE,
        "tenant_id": TENANT_A,
        "request_scope_id": "scope-x",
    }
    for key in (API_KEYS[TENANT_A], DESAN_API_KEYS[TENANT_A]):
        for header in ("X-API-Key", "X-Service-Secret"):
            response = stack.san_http.post(
                "/internal/v1/mappings/retrieve", json=body, headers={header: key}
            )
            assert response.status_code == 401
    ok = stack.san_http.post(
        "/internal/v1/mappings/retrieve", json=body, headers={"X-Service-Secret": SERVICE_SECRET}
    )
    assert ok.status_code == 404  # authenticated, and nothing there


# --- expiry, revocation, deletion -------------------------------------------------------------


def test_expired_revoked_and_deleted_references_fail_like_an_unknown_one(stack: Stack) -> None:
    scopes = {
        "expired": "scope-exp-1",
        "revoked": "scope-rev-1",
        "deleted": "scope-del-1",
    }
    issued = {name: _issue(stack, scope) for name, scope in scopes.items()}
    for name, scope in scopes.items():  # all three work first
        body = issued[name]
        restored = stack.restore(body["sanitized_text"], body["restore_reference"], scope=scope)
        assert restored.status_code == 200
    stack.sql(
        "UPDATE mapping_records SET created_at = now() - interval '2 hours', "
        "expires_at = now() - interval '1 hour' WHERE request_scope_id = %s",
        (scopes["expired"],),
    )
    stack.sql(
        "UPDATE mapping_records SET revoked_at = now() WHERE request_scope_id = %s",
        (scopes["revoked"],),
    )
    stack.sql(
        "UPDATE mapping_records SET deleted_at = now() WHERE request_scope_id = %s",
        (scopes["deleted"],),
    )
    unknown = stack.restore(issued["expired"]["sanitized_text"], UNKNOWN_REFERENCE, scope="scope-x")
    for name, scope in scopes.items():
        body = issued[name]
        response = stack.restore(body["sanitized_text"], body["restore_reference"], scope=scope)
        _assert_not_found(response)
        assert _normalized(response) == _normalized(unknown)


def test_a_new_sanitization_after_an_expiry_still_works(stack: Stack) -> None:
    first = _issue(stack, "scope-exp-2")
    stack.sql(
        "UPDATE mapping_records SET created_at = now() - interval '2 hours', "
        "expires_at = now() - interval '1 hour' WHERE request_scope_id = %s",
        ("scope-exp-2",),
    )
    _assert_not_found(
        stack.restore(first["sanitized_text"], first["restore_reference"], scope="scope-exp-2")
    )
    second = _issue(stack, "scope-exp-2")
    ok = stack.restore(second["sanitized_text"], second["restore_reference"], scope="scope-exp-2")
    assert ok.json()["restored_text"] == CANARY_TEXT


# --- tampering ----------------------------------------------------------------------------------

TAMPERS = {
    "ciphertext": "UPDATE mapping_records SET ciphertext = set_byte(ciphertext, 0, "
    "get_byte(ciphertext, 0) # 1) WHERE request_scope_id = %s",
    "nonce": "UPDATE mapping_records SET nonce = set_byte(nonce, 0, get_byte(nonce, 0) # 1) "
    "WHERE request_scope_id = %s",
    "key_version_unknown": "UPDATE mapping_records SET key_version = 99 "
    "WHERE request_scope_id = %s",
}


@pytest.mark.parametrize("tamper", list(TAMPERS))
def test_tampering_with_a_stored_row_makes_restoration_fail_safely(
    stack: Stack, tamper: str
) -> None:
    scope = f"scope-tamper-{tamper}"[:128]
    body = _issue(stack, scope)
    stack.sql(TAMPERS[tamper], (scope,))
    response = stack.restore(body["sanitized_text"], body["restore_reference"], scope=scope)
    _assert_not_found(response)  # the caller cannot tell it from an unknown reference
    assert_no_leak(response.text)
    assert "mapping_integrity_failure" in stack.logs()  # operators can


def test_a_row_moved_to_another_tenant_cannot_be_restored_by_either_tenant(stack: Stack) -> None:
    scope = "scope-moved-1"
    body = _issue(stack, scope, TENANT_A)
    stack.sql(
        "UPDATE mapping_records SET tenant_id = %s WHERE request_scope_id = %s", (TENANT_B, scope)
    )
    for tenant in (TENANT_A, TENANT_B):
        response = stack.restore(body["sanitized_text"], body["restore_reference"], tenant, scope)
        _assert_not_found(response)


def test_the_vault_holds_only_a_digest_and_ciphertext(stack: Stack) -> None:
    scope = "scope-at-rest-1"
    body = _issue(stack, scope)
    rows = stack.sql("SELECT * FROM mapping_records WHERE request_scope_id = %s", (scope,))
    assert len(rows) == 1
    stored = repr(rows[0])
    assert body["restore_reference"] not in stored
    assert_no_leak(stored, list(CANARIES))
    binary = [bytes(v) for v in rows[0] if isinstance(v, bytes)]
    assert binary  # the digest, ciphertext and nonce
    for value in (EMAIL, PHONE, CARD):
        assert value.encode("utf-8") not in b"".join(binary)


# --- concurrency ------------------------------------------------------------------------------


def test_concurrent_sanitize_and_restore_requests_do_not_mix_mappings(stack: Stack) -> None:
    def work(n: int) -> tuple[str, str]:
        text = f"Call {n} at user{n}@example.com or +1 202-555-{100 + n:04d} from 192.0.2.{n % 250 + 1}."
        _, restored = stack.round_trip(text, TENANT_A if n % 2 else TENANT_B, f"scope-conc-{n}")
        assert restored is not None
        return text, restored.json()["restored_text"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(work, range(1, 41)))
    assert [r for r in results if r[0] != r[1]] == []


# --- outages and restarts ---------------------------------------------------------------------


def test_a_restart_of_both_services_leaves_an_unexpired_mapping_restorable(
    fresh_stack: Stack,
) -> None:
    body = _issue(fresh_stack, "scope-restart-1")
    fresh_stack.stop_desanitization()
    fresh_stack.stop_sanitization()
    fresh_stack.start_sanitization()
    fresh_stack.start_desanitization()
    response = fresh_stack.restore(
        body["sanitized_text"], body["restore_reference"], scope="scope-restart-1"
    )
    assert response.status_code == 200
    assert response.json()["restored_text"] == CANARY_TEXT


def test_with_the_sanitization_service_stopped_restoration_is_503_and_recovers(
    fresh_stack: Stack,
) -> None:
    body = _issue(fresh_stack, "scope-outage-1")
    fresh_stack.stop_sanitization()
    started = time.monotonic()
    response = fresh_stack.restore(
        body["sanitized_text"],
        body["restore_reference"],
        scope="scope-outage-1",
        headers={"X-API-Key": DESAN_API_KEYS[TENANT_A], "X-Correlation-ID": "outage-check-0001"},
    )
    assert time.monotonic() - started < 10  # bounded retries, no hang
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "dependency_unavailable"
    assert error["correlation_id"] == "outage-check-0001"
    assert_no_leak(response.text)
    assert fresh_stack.desan_http.get("/health/live").status_code == 200
    assert fresh_stack.desan_http.get("/health/ready").status_code == 200  # config only
    fresh_stack.start_sanitization()
    recovered = fresh_stack.restore(
        body["sanitized_text"], body["restore_reference"], scope="scope-outage-1"
    )
    assert recovered.status_code == 200
    assert recovered.json()["restored_text"] == CANARY_TEXT


def test_with_the_database_down_both_services_stay_up_and_recover_without_losing_mappings(
    fresh_stack: Stack,
) -> None:
    body = _issue(fresh_stack, "scope-dbdown-1")
    fresh_stack.database_is_unavailable()
    try:
        assert fresh_stack.san_http.get("/health/live").status_code == 200
        assert fresh_stack.san_http.get("/health/ready").status_code == 503
        assert fresh_stack.desan_http.get("/health/live").status_code == 200
        assert fresh_stack.desan_http.get("/health/ready").status_code == 200
        down_sanitize = fresh_stack.sanitize(CANARY_TEXT, TENANT_A, "scope-dbdown-2")
        down_restore = fresh_stack.restore(
            body["sanitized_text"], body["restore_reference"], scope="scope-dbdown-1"
        )
        no_entities = fresh_stack.sanitize("nothing sensitive here", TENANT_A, "scope-dbdown-3")
        for response in (down_sanitize, down_restore):
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "dependency_unavailable"
            assert_no_leak(response.text)
        assert no_entities.status_code == 200  # no mapping to store, so no database needed
    finally:
        fresh_stack.database_is_available()
    _wait_ready(str(fresh_stack.san_http.base_url).rstrip("/"))
    recovered = fresh_stack.restore(
        body["sanitized_text"], body["restore_reference"], scope="scope-dbdown-1"
    )
    assert recovered.status_code == 200
    assert recovered.json()["restored_text"] == CANARY_TEXT
    after = _issue(fresh_stack, "scope-dbdown-4")
    assert after["restore_reference"] != body["restore_reference"]


# --- leakage sweep ------------------------------------------------------------------------------


def test_no_canary_or_secret_appears_in_any_log_or_error_body_across_the_scenarios(
    fresh_stack: Stack,
) -> None:
    stack = fresh_stack
    errors: list[httpx.Response] = []
    good = _issue(stack, "scope-leak-1")
    reference = good["restore_reference"]
    other = _issue(stack, "scope-leak-2", TENANT_B)
    headers = {"X-API-Key": DESAN_API_KEYS[TENANT_A], "X-Correlation-ID": "leak-sweep-0001"}
    ok = stack.restore(good["sanitized_text"], reference, scope="scope-leak-1", headers=headers)
    assert ok.json()["restored_text"] == CANARY_TEXT

    errors += [
        stack.restore(CANARY_TEXT, reference, scope="scope-leak-1", headers={}),
        stack.restore(CANARY_TEXT, reference, scope="scope-leak-1", headers={"X-API-Key": CARD}),
        stack.restore(good["sanitized_text"], reference, TENANT_B, "scope-leak-1"),
        stack.restore(good["sanitized_text"], reference, TENANT_A, "scope-leak-9"),
        stack.restore(good["sanitized_text"], other["restore_reference"], TENANT_A, "scope-leak-2"),
        stack.restore(good["sanitized_text"], f"bad-{EMAIL}", scope="scope-leak-1"),
        stack.restore(CANARY_TEXT, reference, scope=f"{EMAIL} bad scope"),
        stack.sanitize(CANARY_TEXT, TENANT_A, f"{PHONE} bad"),
        stack.san_http.post(
            "/api/v1/sanitizations",
            json={"text": CANARY_TEXT, "request_scope_id": "s1", "policy_id": f"p-{CARD}"},
            headers={"X-API-Key": API_KEYS[TENANT_A]},
        ),
        stack.san_http.post(
            "/api/v1/sanitizations",
            content=CANARY_TEXT * 1500,
            headers={"X-API-Key": API_KEYS[TENANT_A], "Content-Type": "application/json"},
        ),
        stack.san_http.post(
            "/internal/v1/mappings/retrieve",
            json={"restore_reference": reference, "tenant_id": TENANT_A, "request_scope_id": "s"},
            headers={"X-Service-Secret": f"wrong-{CARD}"},
        ),
        stack.desan_http.get(f"/no/such/route?q={EMAIL}"),
    ]
    stack.sql(
        "UPDATE mapping_records SET ciphertext = set_byte(ciphertext, 0, "
        "get_byte(ciphertext, 0) # 1) WHERE request_scope_id = %s",
        ("scope-leak-2",),
    )
    errors.append(
        stack.restore(other["sanitized_text"], other["restore_reference"], TENANT_B, "scope-leak-2")
    )
    stack.stop_sanitization()
    errors.append(stack.restore(good["sanitized_text"], reference, scope="scope-leak-1"))
    stack.start_sanitization()
    stack.database_is_unavailable()
    errors.append(stack.sanitize(CANARY_TEXT, TENANT_A, "scope-leak-3"))
    stack.database_is_available()

    assert {r.status_code for r in errors} >= {401, 404, 413, 422, 503}
    secrets = [reference, other["restore_reference"], "pf1_", SERVICE_SECRET]
    secrets += [*API_KEYS.values(), *DESAN_API_KEYS.values()]
    for response in errors:
        assert_no_leak(response.text)
        assert_no_leak(response.text, secrets)
        assert "Traceback" not in response.text
    logs = stack.logs()
    assert "request_completed" in logs
    assert_no_leak(logs)
    assert_no_leak(logs, secrets)
    assert_no_leak(logs, [CANARY_TEXT, good["sanitized_text"]])
    # The correlation ID the client chose reaches both services' logs, so one request can be
    # followed across the boundary without any sensitive content.
    assert logs.count("leak-sweep-0001") >= 2


# --- boundaries -------------------------------------------------------------------------------


def test_the_desanitization_process_gets_no_database_or_sanitization_settings(
    stack: Stack,
) -> None:
    names = stack.desanitization_environment_names()
    assert not [n for n in names if "DATABASE" in n or n.startswith("PRIVYFLOW_SAN_")]
    assert stack.database_url not in json.dumps(stack.desan_env)
    # It restores through the Sanitization Service's API alone: stop that API and it cannot.
    assert "PRIVYFLOW_DESAN_SANITIZATION_BASE_URL" in names
