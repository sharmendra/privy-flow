# Tests

Strategy, suites, and release gates: [docs/TEST_STRATEGY.md](../docs/TEST_STRATEGY.md).

## Run

```text
uv sync                                   # core tooling
uv sync --all-groups                      # plus Testcontainers, Locust, Bandit, pip-audit

uv run scripts/run_tests.py unit
uv run scripts/run_tests.py integration   # PostgreSQL tests need Docker, or PRIVYFLOW_TEST_DATABASE_URL
uv run scripts/run_tests.py security
uv run scripts/run_tests.py evaluation
uv run scripts/run_tests.py e2e           # needs PRIVYFLOW_TEST_DATABASE_URL (no Testcontainers)
uv run scripts/run_tests.py all
uv run scripts/run_tests.py lint
uv run scripts/run_tests.py scan
uv run pyright
```

Reports are written to `reports/`.

## Layout

| Path | Purpose |
|---|---|
| `unit/`, `integration/`, `security/`, `evaluation/`, `e2e/` | Test suites. The suite marker is added from the directory. |
| `performance/locustfile.py` | Locust load test, run on demand. |
| `fixtures/eval/` | Synthetic detection dataset and approval thresholds. |
| `fixtures/pilot/` | Synthetic multi-paragraph samples for the end-to-end round trip. Owner review requested (PLAN_PILOT Q2). |
| `fixtures/contracts/` | The saved internal API contract both services are tested against. |
| `support/` | Service loader, leak assertions, evaluation metrics, the Sanitization stub, and the end-to-end `Stack`. |
| `conftest.py` | Shared fixtures: service clients, tenant IDs. |

## Database for integration tests

Database tests use Testcontainers when Docker is running. Without Docker, set `PRIVYFLOW_TEST_DATABASE_URL` in your shell to the admin URL of a local PostgreSQL (not in a file). Each test creates and drops its own `pf_test_*` database. If neither is available the tests fail with the reason; they do not skip.

```text
$env:PRIVYFLOW_TEST_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow"   # PowerShell
```

## Pending tests

Files named `test_*_pending.py` list behavior that is not built yet. Each entry skips with a reason. When you build a feature, replace its entry with a real test. A skip is not a pass.

## Rules

- Synthetic data only. No real PII, keys, or credentials.
- Never lower a threshold, delete a test, or add a skip to get a green run.
- Both services use a package named `app`, so only one loads per process. Cross-service tests run the services as separate processes.

## End-to-end suite

`tests/e2e/` starts both services as separate uvicorn processes over a new migrated PostgreSQL database and calls them over HTTP. It needs `PRIVYFLOW_TEST_DATABASE_URL` (the same admin URL as the integration tests); without it the tests fail with the reason. Each module creates and drops its own `pf_test_*` database. Direct SQL plays an operator who expires or revokes a record, or an attacker who edits a stored row. A database outage is simulated per database (connections refused and open ones dropped), so the server and other databases are untouched.
