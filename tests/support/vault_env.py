"""Test-only secrets for the Sanitization Service, generated when the tests start.

None of these values is real or reused across runs. They are never written to a file.
"""

import base64
import json
import secrets

TENANT_A = "tenant-test-a"
TENANT_B = "tenant-test-b"
TENANT_C = "tenant-test-c"  # has an API key but no entry in the test settings (default profile)

API_KEYS: dict[str, str] = {t: secrets.token_urlsafe(32) for t in (TENANT_A, TENANT_B, TENANT_C)}
KEY_V1 = secrets.token_bytes(32)
KEY_V2 = secrets.token_bytes(32)
PEPPER = secrets.token_bytes(32)


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def sanitization_secret_env(
    keys: dict[int, bytes] | None = None, active_version: int = 1
) -> dict[str, str]:
    """The environment variables the Sanitization Service needs for its vault and API keys."""
    held = keys if keys is not None else {1: KEY_V1}
    return {
        "PRIVYFLOW_SAN_API_KEYS": json.dumps(API_KEYS),
        "PRIVYFLOW_SAN_ENCRYPTION_KEYS": json.dumps({str(v): b64(k) for v, k in held.items()}),
        "PRIVYFLOW_SAN_ACTIVE_KEY_VERSION": str(active_version),
        "PRIVYFLOW_SAN_CREDENTIAL_PEPPER": b64(PEPPER),
    }
