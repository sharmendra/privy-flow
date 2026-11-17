# PrivyFlow — Test Strategy

This document defines how PrivyFlow is tested. Automated testing is mandatory for every feature. The acceptance criteria here are **proposed release gates, not claims about existing functionality**. Verified status lives in `docs/STATUS.md`.

## 1. Testing objectives and scope

Objectives:

- Prove that sanitization and restoration are correct: valid restoration reproduces the original supported input exactly.
- Prove the security properties: tenant isolation, authorization, encryption at rest, expiry, revocation, and no sensitive leakage.
- Prove the service boundaries: the De-sanitization Service never touches the Sanitization database or its credentials.
- Measure detection quality honestly, per entity type, without assuming any accuracy.
- Catch regressions before release.

In scope: both services, the internal mapping API, the mapping vault, detection, and the test harness itself.

Out of scope (matches product scope): document extraction, OCR, chunking, embeddings, vector databases, RAG, and LLM behavior. The harness does not test or depend on any of these.

## 2. Test architecture and pyramid

```text
            e2e            few, slow: both services as separate processes
        integration        API, database, internal API, contract
     security + evaluation  isolation, crypto, leakage; detection quality
              unit          many, fast: no network, no database
```

| Suite | Directory | Marker | Needs |
|---|---|---|---|
| Unit | `tests/unit/` | `unit` | Nothing external |
| Integration | `tests/integration/` | `integration` | In-process app; PostgreSQL via Testcontainers (Docker) |
| Security | `tests/security/` | `security` | In-process apps, test database |
| Evaluation | `tests/evaluation/` | `evaluation` | Synthetic dataset, detector |
| End-to-end | `tests/e2e/` | `e2e` | Both services running as separate processes |
| Performance | `tests/performance/` | none (Locust) | Running services |

Shared code is in `tests/support/` (service loader, leak assertions, evaluation metrics) and `tests/conftest.py`. Markers are applied automatically from the directory.

Both services use a top-level package named `app`, so they cannot be imported into one process. In-process tests load one service at a time; anything involving both services runs them as separate processes and calls them over HTTP.

## 3. Unit testing

Fast, isolated, deterministic. No network, database, clock, or real randomness unless the test is about them.

- **Sanitization:** entity detection per type, policy selection, placeholder generation and collision avoidance, repeated values, overlapping spans, restore-reference generation and entropy, digest hashing, encryption round trip, unique nonces, key versions, expiry, and revocation rules.
- **De-sanitization:** reference format validation, exact-placeholder restoration, unknown and altered placeholder handling, expiry and revocation handling, and scope checks.
- Use Hypothesis for properties: restore(sanitize(x)) == x for supported input, placeholders never collide with source text, metrics stay in range, and ciphertext never equals plaintext.

## 4. API integration testing

Drive each service through its HTTP API with `httpx.ASGITransport`.

- Valid requests, invalid input, oversized payloads, unsupported policies, and safe error shapes.
- Authentication and authorization on every sensitive endpoint.
- The internal mapping API: only the De-sanitization Service identity is accepted; scope, expiry, and revocation are enforced.
- Health: `/health/live` returns 200; `/health/ready` returns 200 or 503 depending on dependencies.
- Database: migrations apply from an empty database, constraints and indexes exist, and transactions behave. Use a real PostgreSQL through Testcontainers, not a mock.
- Contract: the internal API schema stays compatible between the two services.

## 5. Cross-service testing

Run both services as separate processes with separate environments. The De-sanitization Service's environment must not contain Sanitization database credentials; a test asserts this.

Scenarios: successful sanitize then restore, invalid reference, unauthorized caller, missing mapping, Sanitization Service unavailable, database unavailable, service restart, concurrent requests, tampered mapping or ciphertext, and replay attempts.

## 6. End-to-end testing

End-to-end means API-level: a client script plays the client application and calls both services over HTTP. There is no UI. Cover the full lifecycle: sanitize, store, restore, expire, revoke, and delete, across both services with real PostgreSQL.

## 7. Security and privacy testing

Required tests:

- Tenant isolation, and request-scope isolation.
- Authentication and authorization, including that possession of a restore-reference alone never authorizes restoration.
- Restore-reference entropy and unpredictability (length, uniqueness across many samples, no sequential or timestamp patterns).
- Only a secure digest of the reference is stored; no plaintext reference or mapping appears in the database.
- Authenticated encryption: tampered ciphertext, nonce, or key version is rejected.
- Key version handling and rotation.
- Expiry, revocation, and replay protection where one-time use applies.
- Rate limiting and request-size limits.
- Internal API authentication.
- Database access boundaries: the De-sanitization Service has no database URL and cannot connect.
- Leakage: capture logs, traces, error bodies, and metrics while processing canary values (`tests/support/leak.py`) and assert none appear. Unauthorized callers cannot learn whether a mapping exists.

Static analysis: Bandit on `services/`. Dependencies: `pip-audit`.

## 8. Detection quality evaluation

Dataset: `tests/fixtures/eval/detection_dataset.jsonl`. It is synthetic and manually annotated. Never use real customer PII.

Each line has an `id`, a `note`, the `text`, and the gold `entities` (`type`, `text`, optional `occurrence`). The loader resolves offsets, so spans are easy to review and edit.

Coverage: PERSON, EMAIL, PHONE, FINANCIAL (cards, IBAN), BUSINESS_CONFIDENTIAL (configured terms), Indian identifiers (IN_AADHAAR, IN_PAN, IN_IFSC), repeated occurrences, a nested overlap, adjacent entities, non-ASCII names, placeholder-like literal text, and negative examples (ambiguous and malformed input that must not be detected).

Annotation guidelines: titles such as "Dr." are excluded from PERSON spans; email local parts are not separate PERSON entities; configured business terms match case-insensitively. Overlap handling is an open policy decision (see `docs/STATUS.md`); the current annotation records the nested case.

Metrics (strict span match: type, start, and end must all match), reported per entity type and overall:

- Precision, recall, and F1.
- False negative rate: FN / (TP + FN).
- False positive rate: FP / (TP + FP), the share of reported entities that are wrong. True negatives are undefined for span detection, so the classic rate is not used.
- Negative-document false positive rate: the share of documents with no entities where anything was detected.

Thresholds: `tests/fixtures/eval/thresholds.json`. Every threshold starts as `null` (not approved). Procedure: run the detector, record the baseline in `docs/STATUS.md`, have the product owner approve minimums, then set them. A `null` threshold is never enforced and never reported as met. The report is written to `reports/detection_eval.json`.

The detector fixture in `tests/evaluation/conftest.py` skips until the detector interface is approved in Phase 2.

## 9. Performance and load testing

Tool: Locust (`tests/performance/locustfile.py`, `uv sync --group perf`). Synthetic text only, in a local or approved test environment.

Measure p50, p95, and p99 latency, throughput, error rate, and behavior under concurrency, across representative text sizes. Targets are set by the product owner after a baseline run; they are not assumed. Performance is a release gate, not a per-commit check.

## 10. Regression testing

- Every fixed defect gets a test that fails before the fix and passes after.
- The full suite runs on every push and pull request in CI.
- The detection evaluation runs on every change to detection or policy code and is compared with the recorded baseline; any metric that drops below its approved threshold fails the build.
- Security tests are never skipped to release.

## 11. Test data management

- Synthetic data only: reserved domains (`example.com`), the fictional US `555-01xx` phone range, documented test card and IBAN numbers, and obviously fake identifiers.
- Canary values for leakage tests are in `tests/support/leak.py`.
- Encryption keys and tokens in tests are generated at test time or are clearly marked test values; none are real, and none come from `.env`.
- Each test isolates its own state: unique tenants per test, a fresh transaction or schema per test, and no shared mutable globals.
- Fixtures live in `tests/fixtures/` and `conftest.py` files. Datasets are reviewed in pull requests like code.

## 12. CI/CD integration

`.github/workflows/tests.yml` runs on every push and pull request, on Python 3.11 and 3.12:

1. `uv sync --all-groups`
2. Lint and format check (Ruff)
3. Type check (Pyright)
4. All test suites with coverage
5. Bandit and `pip-audit`
6. Upload reports (`reports/`)

The pipeline fails on any failed test, any coverage shortfall, or any finding. Release gates in section 15 are checked before deployment approval.

## 13. Test execution commands

```text
uv sync                                   # core test tooling
uv sync --all-groups                      # plus integration, perf and security tools

uv run scripts/run_tests.py unit
uv run scripts/run_tests.py integration   # needs Docker for PostgreSQL tests
uv run scripts/run_tests.py security
uv run scripts/run_tests.py evaluation
uv run scripts/run_tests.py e2e
uv run scripts/run_tests.py all           # every suite, with coverage once services exist
uv run scripts/run_tests.py lint          # Ruff check and format check
uv run scripts/run_tests.py scan          # Bandit and pip-audit
uv run pyright                            # type check

uv run pytest tests/unit -k placeholder   # run a subset
uv run --group perf locust -f tests/performance/locustfile.py --host http://localhost:8001
```

Tests for a service that does not exist yet skip with a reason. Set `PRIVYFLOW_SERVICES_DIR` to point the loader at another services directory.

## 14. Test reporting

- Terminal summary shows skipped tests with reasons (`-ra`).
- `reports/junit-<suite>.xml`, `reports/coverage.xml`, and `reports/detection_eval.json` are produced by the runner and by CI.
- After each phase, record in `docs/STATUS.md`: date, exact command, and pass, fail, and skip counts, plus the detection baseline when it changes.
- Skipped, pending, and failing tests are reported as such. Never report them as passed.

Coverage: a minimum of 80% line coverage on `services/`, enforced by `run_tests.py` once service code exists. Security-critical modules (vault, cryptography, authorization, restoration) should reach at least 90%, with branch coverage reviewed. Coverage does not replace the security and negative tests above.

## 15. Release acceptance criteria

Proposed gates. All must have recorded evidence before a release is approved.

| Gate | Criterion |
|---|---|
| Functional | All critical unit and integration tests pass; zero failing tests. |
| Round trip | Valid restoration reproduces the original supported input exactly, verified by property tests and end-to-end tests. |
| Authorization | Unauthorized restoration is rejected; a restore-reference alone never authorizes restoration. |
| Isolation | Cross-tenant and cross-request access is prevented. |
| Encryption | Mapping data is encrypted at rest; tampering is detected; key versions are honored. |
| Boundaries | The De-sanitization Service has no Sanitization database access or credentials. |
| Privacy | No sensitive information appears in logs, traces, errors, or metrics. |
| Detection | Precision and recall meet the approved thresholds, per entity type and overall. |
| Regression | The full regression suite passes. |
| Performance | Latency and throughput meet the targets agreed after the baseline run. |
| Static security | Bandit has no unresolved findings and `pip-audit` reports no unaddressed vulnerabilities. |
| Production readiness | Production-readiness validation (TLS, identity, KMS, monitoring, backups, incident response, recovery) is reviewed and approved. |
