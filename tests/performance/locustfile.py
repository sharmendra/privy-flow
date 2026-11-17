"""Load test for PrivyFlow. Run only after both services exist and an auth scheme is approved.

    uv run --group perf locust -f tests/performance/locustfile.py --host http://localhost:8001

Endpoints are the proposals in docs/SPEC.md and must be updated to the approved contract.
Use synthetic text only. The auth token is read from the environment.
"""

import os

from locust import HttpUser, between, task

HEADERS = {"Authorization": f"Bearer {os.environ.get('PRIVYFLOW_TEST_TOKEN', '')}"}
TEXT = "Please contact Asha Verma at asha.verma@example.com or +1 202-555-0143."


class SanitizationUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def sanitize(self) -> None:
        self.client.post(
            "/api/v1/sanitizations",
            json={"text": TEXT, "tenant_id": "tenant-test-a", "request_id": "load-test"},
            headers=HEADERS,
        )
