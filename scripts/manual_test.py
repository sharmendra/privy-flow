"""Run the manual test steps (docs/MANUAL_TEST.md) against the two running services.

    uv run scripts/manual_test.py

Start both services first (MANUAL_TEST.md, step 1.4). The API keys and the service secret are
read from the two services' .env files, so nothing is typed and no secret is printed. Test data
is synthetic. Exit code: 0 when every check passes, 1 when a check fails, 2 when setup is missing.
"""

import argparse
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SAN_ENV = ROOT / "services" / "sanitization_service" / ".env"
DESAN_ENV = ROOT / "services" / "desanitization_service" / ".env"
TENANT_A = "tenant-demo-a"
TENANT_B = "tenant-demo-b"
ORIGINAL = (
    "Contact Alice at alice@example.com or +1 202-555-0143. Server 192.0.2.10 reported the issue."
)
SANITIZED = (
    "Contact Alice at [EMAIL_001] or [PHONE_001]. Server [IP_ADDRESS_001] reported the issue."
)

Json = dict[str, object]


class Results:
    """Counts checks and prints one line each. Details never hold request or response text."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
            print(f"PASS  {name}")
        else:
            self.failed += 1
            print(f"FAIL  {name}  {detail}")


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        print(f"Missing {path.relative_to(ROOT)}. Run the setup in MANUAL_TEST.md part 1.")
        sys.exit(2)
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def read_keys(env: dict[str, str], name: str) -> dict[str, str]:
    if name not in env:
        print(f"{name} is not set. Run: uv run scripts/gen_local_secrets.py --add-missing-secrets")
        sys.exit(2)
    return cast("dict[str, str]", json.loads(env[name]))


def body_of(response: httpx.Response) -> Json:
    return cast("Json", response.json())


def error_of(response: httpx.Response) -> tuple[object, object]:
    """The error code and message, without the correlation ID, which differs on every call."""
    error = cast("Json", body_of(response).get("error", {}))
    return error.get("code"), error.get("message")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the manual test steps.")
    parser.add_argument("--san-url", default="http://127.0.0.1:8001")
    parser.add_argument("--desan-url", default="http://127.0.0.1:8002")
    args = parser.parse_args()

    san_env = read_env(SAN_ENV)
    desan_env = read_env(DESAN_ENV)
    san_keys = read_keys(san_env, "PRIVYFLOW_SAN_API_KEYS")
    desan_keys = read_keys(desan_env, "PRIVYFLOW_DESAN_API_KEYS")
    service_secret = desan_env.get("PRIVYFLOW_DESAN_SERVICE_SECRET", "")
    for tenant in (TENANT_A, TENANT_B):
        if tenant not in san_keys or tenant not in desan_keys:
            print(f"No API key for {tenant}. Run: uv run scripts/gen_local_secrets.py --force")
            return 2

    results = Results()
    client = httpx.Client(timeout=10)
    try:
        run_all(client, results, args.san_url, args.desan_url, san_keys, desan_keys, service_secret)
    except httpx.ConnectError:
        print("Cannot connect. Start both services first (MANUAL_TEST.md, step 1.4).")
        return 2
    finally:
        client.close()

    print(f"\n{results.passed} passed, {results.failed} failed")
    return 1 if results.failed else 0


def run_all(
    client: httpx.Client,
    results: Results,
    san_url: str,
    desan_url: str,
    san_keys: dict[str, str],
    desan_keys: dict[str, str],
    service_secret: str,
) -> None:
    check = results.check
    san_a = {"X-API-Key": san_keys[TENANT_A]}
    san_b = {"X-API-Key": san_keys[TENANT_B]}
    desan_a = {"X-API-Key": desan_keys[TENANT_A]}
    desan_b = {"X-API-Key": desan_keys[TENANT_B]}
    service = {"X-Service-Secret": service_secret}
    run_id = secrets.token_hex(3)  # keeps request scopes unique across runs

    def sanitize(text: str, headers: dict[str, str], scope: str, **extra: str) -> httpx.Response:
        payload = {"text": text, "request_scope_id": scope, "policy_id": "effective", **extra}
        return client.post(f"{san_url}/api/v1/sanitizations", json=payload, headers=headers)

    def restore(text: str, reference: str, scope: str, headers: dict[str, str]) -> httpx.Response:
        payload = {
            "sanitized_text": text,
            "restore_reference": reference,
            "request_scope_id": scope,
        }
        return client.post(f"{desan_url}/api/v1/desanitizations", json=payload, headers=headers)

    def retrieve(
        reference: str, tenant: str, scope: str, headers: dict[str, str]
    ) -> httpx.Response:
        payload = {"restore_reference": reference, "tenant_id": tenant, "request_scope_id": scope}
        return client.post(
            f"{san_url}/internal/v1/mappings/retrieve", json=payload, headers=headers
        )

    print("Part 2. Health")
    for name, url in (
        ("sanitization live", f"{san_url}/health/live"),
        ("sanitization ready", f"{san_url}/health/ready"),
        ("desanitization live", f"{desan_url}/health/live"),
        ("desanitization ready", f"{desan_url}/health/ready"),
    ):
        response = client.get(url)
        check(f"{name} returns 200", response.status_code == 200, f"got {response.status_code}")

    print("\nPart 3. Sanitization")
    policy = client.get(f"{san_url}/api/v1/policies", headers=san_a)
    policy_body = body_of(policy)
    check(
        "policy shows gdpr and a 3600 second lifetime",
        policy.status_code == 200 and policy_body.get("max_ttl_seconds") == 3600,
        f"got {policy.status_code}",
    )

    scope = f"scope-{run_id}-1"
    first = sanitize(ORIGINAL, san_a, scope)
    first_body = body_of(first)
    reference = str(first_body.get("restore_reference"))
    check("sanitize returns 200", first.status_code == 200, f"got {first.status_code}")
    check("three values masked, Alice kept", first_body.get("sanitized_text") == SANITIZED)
    check("entity_count is 3", first_body.get("entity_count") == 3)
    check(
        "reference is pf1_ plus 43 characters",
        reference.startswith("pf1_") and len(reference) == 47,
    )

    repeated = body_of(
        sanitize(
            "bob@example.com wrote to bob@example.com and carol@example.com",
            san_a,
            f"scope-{run_id}-2",
        )
    )
    check(
        "repeated value shares one placeholder",
        repeated.get("sanitized_text") == "[EMAIL_001] wrote to [EMAIL_001] and [EMAIL_002]",
    )

    nothing = body_of(sanitize("Nothing sensitive here.", san_a, f"scope-{run_id}-3"))
    check(
        "text with nothing to mask is unchanged, no reference",
        nothing.get("sanitized_text") == "Nothing sensitive here."
        and nothing.get("restore_reference") is None
        and nothing.get("entity_count") == 0,
    )

    literal = body_of(
        sanitize(
            "The code [EMAIL_001] is literal. Mail dave@example.com", san_a, f"scope-{run_id}-4"
        )
    )
    check(
        "a literal placeholder is kept and not reused",
        literal.get("sanitized_text") == "The code [EMAIL_001] is literal. Mail [EMAIL_002]",
    )

    print("\nPart 4. Restoration")
    restored = restore(SANITIZED, reference, scope, desan_a)
    restored_body = body_of(restored)
    check("restore returns 200", restored.status_code == 200, f"got {restored.status_code}")
    check(
        "restored text equals the original exactly", restored_body.get("restored_text") == ORIGINAL
    )
    check(
        "counts are 3 restored, 0 unmatched",
        restored_body.get("restored_count") == 3
        and restored_body.get("unmatched_placeholder_count") == 0,
    )

    altered = body_of(
        restore(
            "[EMAIL_001] [EMAIL_999] [EMAIL_0001] [email_001] [EMAIL_REDACTED]",
            reference,
            scope,
            desan_a,
        )
    )
    check(
        "unknown and altered placeholders are left alone",
        altered.get("restored_text")
        == "alice@example.com [EMAIL_999] [EMAIL_0001] [email_001] [EMAIL_REDACTED]",
    )
    check(
        "1 restored, 2 unmatched",
        altered.get("restored_count") == 1 and altered.get("unmatched_placeholder_count") == 2,
    )

    again = restore(SANITIZED, reference, scope, desan_a)
    check(
        "reuse within the lifetime succeeds", again.status_code == 200, f"got {again.status_code}"
    )

    print("\nPart 5. Refusals")
    simple = {"text": "x@example.com", "request_scope_id": "s1", "policy_id": "effective"}
    url = f"{san_url}/api/v1/sanitizations"
    check("sanitize with no key is 401", client.post(url, json=simple).status_code == 401)
    wrong = client.post(url, json=simple, headers={"X-API-Key": "wrong-key-wrong-key-wrong-key"})
    check("sanitize with a wrong key is 401", wrong.status_code == 401)
    check(
        "sanitize with a De-sanitization key is 401",
        client.post(url, json=simple, headers=desan_a).status_code == 401,
    )
    check("restore with no key is 401", restore(SANITIZED, reference, scope, {}).status_code == 401)
    check(
        "restore with a Sanitization key is 401",
        restore(SANITIZED, reference, scope, san_a).status_code == 401,
    )

    wrong_tenant = restore(SANITIZED, reference, scope, desan_b)
    wrong_scope = restore(SANITIZED, reference, "some-other-scope", desan_a)
    fake = restore(SANITIZED, "pf1_" + "A" * 43, scope, desan_a)
    malformed = restore(SANITIZED, "not-a-reference", scope, desan_a)
    not_found = ("restore_reference_not_found", "The restore reference was not found.")
    for name, response in (
        ("wrong tenant", wrong_tenant),
        ("wrong scope", wrong_scope),
        ("unknown reference", fake),
        ("malformed reference", malformed),
    ):
        check(
            f"{name} is the same 404",
            response.status_code == 404 and error_of(response) == not_found,
            f"got {response.status_code}",
        )

    unsupported = client.post(url, json={**simple, "policy_id": "other"}, headers=san_a)
    bad_inputs = (
        ("empty text", sanitize("", san_a, "s1"), "validation_error"),
        ("unsupported policy", unsupported, "unsupported_policy"),
        ("tenant in the body", sanitize("x", san_a, "s1", tenant_id=TENANT_B), "validation_error"),
        ("bad scope id", sanitize("x", san_a, "bad scope!"), "validation_error"),
    )
    for name, response, code in bad_inputs:
        check(
            f"{name} is 422 {code}",
            response.status_code == 422 and error_of(response)[0] == code,
            f"got {response.status_code}",
        )

    big = sanitize("a" * 300000, san_a, "s1")
    check(
        "oversized body is 413", big.status_code == 413 and error_of(big)[0] == "payload_too_large"
    )
    check(
        "unknown route is 404 not_found", error_of(client.get(f"{san_url}/nope"))[0] == "not_found"
    )
    wrong_method = client.get(url, headers=san_a)
    check(
        "wrong method is 405",
        wrong_method.status_code == 405 and error_of(wrong_method)[0] == "method_not_allowed",
    )

    print("\nPart 6. Tenant policies")
    ssn_text = "SSN 900-12-3456 and mail erin@example.com"
    ssn_a = body_of(sanitize(ssn_text, san_a, f"scope-{run_id}-ssn"))
    check(
        "tenant A leaves the SSN, masks the email",
        ssn_a.get("sanitized_text") == "SSN 900-12-3456 and mail [EMAIL_001]",
    )
    ssn_b = body_of(sanitize(ssn_text, san_b, f"scope-{run_id}-ssn"))
    check(
        "tenant B masks the SSN and the email",
        ssn_b.get("sanitized_text") == "SSN [US_SSN_001] and mail [EMAIL_001]",
    )
    check("tenant B applies gdpr and hipaa", ssn_b.get("profiles_applied") == ["gdpr", "hipaa"])
    seconds = (
        datetime.fromisoformat(str(ssn_b.get("expires_at"))) - datetime.now(UTC)
    ).total_seconds()
    check(
        "tenant B lifetime is about 30 minutes",
        1700 <= seconds <= 1805,
        f"got {seconds:.0f} seconds",
    )
    card = body_of(sanitize("Card 4111 1111 1111 1111", san_a, f"scope-{run_id}-card"))
    check(
        "a card number is not masked by these tenants",
        card.get("sanitized_text") == "Card 4111 1111 1111 1111",
    )

    print("\nPart 7. Internal API")
    check("no credential is 401", retrieve(reference, TENANT_A, scope, {}).status_code == 401)
    check("a client API key is 401", retrieve(reference, TENANT_A, scope, san_a).status_code == 401)
    internal = retrieve(reference, TENANT_A, scope, service)
    mappings = cast("list[Json]", body_of(internal).get("mappings", []))
    check("the service secret gets 3 mappings", internal.status_code == 200 and len(mappings) == 3)
    check(
        "wrong tenant on the internal API is 404",
        retrieve(reference, TENANT_B, scope, service).status_code == 404,
    )
    check(
        "the service secret on a public route is 401",
        client.post(url, json=simple, headers=service).status_code == 401,
    )


if __name__ == "__main__":
    sys.exit(main())
