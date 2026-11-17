"""Test-only secrets for the De-sanitization Service, generated when the tests start.

The service secret is the Sanitization Service's one (tests.support.vault_env.SERVICE_SECRET),
because the two services share it. The client API keys are this service's own, different from
the Sanitization Service's. None is real or written to a file.
"""

import json
import secrets

from tests.support.vault_env import SERVICE_SECRET, TENANT_A, TENANT_B

DESAN_API_KEYS: dict[str, str] = {t: secrets.token_urlsafe(32) for t in (TENANT_A, TENANT_B)}


def desanitization_env(base_url: str = "http://127.0.0.1:1") -> dict[str, str]:
    """The environment variables the De-sanitization Service needs."""
    return {
        "PRIVYFLOW_DESAN_SANITIZATION_BASE_URL": base_url,
        "PRIVYFLOW_DESAN_API_KEYS": json.dumps(DESAN_API_KEYS),
        "PRIVYFLOW_DESAN_SERVICE_SECRET": SERVICE_SECRET,
    }
