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
uv run scripts/run_tests.py e2e
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
| `support/` | Service loader, leak assertions, evaluation metrics. |
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
