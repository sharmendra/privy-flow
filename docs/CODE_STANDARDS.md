# PrivyFlow — Engineering and Code Standards

## 1. General principles

- Keep it simple; do not overcomplicate.
- Prefer simple, explicit code over premature abstraction.
- Comment only when necessary; let names and types carry the meaning.
- Be concise: a short README and no emojis.
- Avoid overly defensive code. Handle exceptions only when necessary. This does not relax validation, authorization, or safe-failure requirements at trust boundaries.
- Run Python through `uv` (`uv run ...`), never bare `python3`, and write scripts so they work on Windows.
- Use strict static typing for Python; avoid `Any` unless justified.
- Keep the two service boundaries strict.
- Separate API routing, business logic, data access, detection, cryptography, and infrastructure.
- Use type hints for public functions and domain models.
- Keep side effects explicit and transaction boundaries clear.
- Do not introduce dependencies for out-of-scope functionality.

## 2. Suggested repository structure

```text
PrivyFlow/
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── docs/
├── services/
│   ├── sanitization_service/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   ├── core/
│   │   │   ├── db/
│   │   │   ├── models/
│   │   │   ├── repositories/
│   │   │   ├── schemas/
│   │   │   ├── detection/
│   │   │   ├── sanitization/
│   │   │   ├── vault/
│   │   │   └── main.py
│   │   ├── migrations/
│   │   ├── tests/
│   │   └── alembic.ini
│   └── desanitization_service/
│       ├── app/
│       │   ├── api/
│       │   ├── core/
│       │   ├── schemas/
│       │   ├── clients/
│       │   ├── restoration/
│       │   └── main.py
│       └── tests/
├── tests/          # unit, integration, security, evaluation, e2e, fixtures, support
├── scripts/        # run_tests.py
├── .github/workflows/tests.yml
├── pyproject.toml
└── infrastructure/
```

The De-sanitization Service has no database by default. If a persistence requirement is approved for audit metadata, keep it separate from the mapping vault.

## 3. API conventions

- Use versioned routes such as `/api/v1/...`.
- Use Pydantic request and response schemas.
- Separate public endpoints from internal service-to-service endpoints.
- Authenticate and authorize all sensitive operations.
- Validate payload size, content type, policy identifiers, tenant context, and request scope.
- Use consistent error response structures and appropriate HTTP status codes.
- Do not expose stack traces, SQL, filesystem paths, credentials, ciphertext internals, or key metadata.
- Define pagination where collections may grow.
- Document idempotency and retry behavior.
- Generate correlation IDs that do not contain sensitive input.

## 4. Error handling

| Condition | Expected behavior |
|---|---|
| Invalid input | `400` or `422` with safe validation details |
| Unauthorized | `401` without revealing protected mapping existence |
| Forbidden / scope mismatch | `403` or deliberately non-disclosing `404`, per approved threat model |
| Unknown or expired reference | Safe documented error; do not leak cross-tenant existence |
| Payload too large | `413` |
| Unsupported policy | `400` or `422` |
| Internal dependency unavailable | `503` with correlation ID |
| Unexpected error | `500` with safe message; details only in protected redacted logs |

## 5. Database standards

- Use SQLAlchemy 2.x mappings and explicit transactions.
- Use Alembic for schema changes; do not rely on `create_all` in deployed environments.
- Add constraints and indexes for lookup, expiry, tenant, and scope access patterns.
- Store timestamps consistently in UTC using timezone-aware types.
- Use opaque IDs for externally visible references.
- Keep encrypted mapping payloads and credential lookup hashes in Sanitization Service storage only.
- Never grant De-sanitization Service direct database access.
- Do not store plaintext restoration credentials or plaintext mappings.
- Avoid storing raw request text unless a documented, approved requirement exists.

## 6. Privacy and cryptography standards

- Use a cryptographically secure random generator for restoration credentials.
- Use sufficient entropy; do not use predictable identifiers or timestamps as secrets.
- Store only a secure digest or keyed hash of the credential.
- Encrypt mappings using authenticated encryption such as AES-256-GCM.
- Use a unique nonce for each encryption operation.
- Persist key-version and algorithm metadata.
- Keep key material outside source control and outside the ciphertext database.
- Support key rotation and controlled decryption.
- Validate identity, tenant, request scope, expiry, and revocation independently.
- Use constant-time comparison where applicable to secret-derived values.
- Never write decrypted mappings to logs, traces, metrics, exception messages, or test snapshots.

## 7. Sanitization rules

- Make entity recognizers configurable and testable.
- Define supported entity categories and policy actions explicitly.
- Handle repeated values consistently within the intended request scope.
- Prevent collisions with placeholder-like strings already present in input.
- Define behavior for overlapping spans and ambiguous recognitions.
- Preserve unaffected text and formatting to the extent supported by the text API.
- Do not claim complete detection or irreversible anonymization.
- Do not use an LLM as the authority for core privacy decisions.

## 8. Restoration rules

- Restore only exact placeholders present in the authorized mapping.
- Never infer missing original values.
- Reject cross-tenant and cross-request use.
- Respect expiry, revocation, retention, and any one-time-use policy.
- Handle unknown or altered placeholders safely.
- Do not expose whether another tenant owns a mapping.
- Record safe audit metadata without recording restored text or sensitive values.

## 9. Logging and observability

Never log:
- Original or restored text.
- Sensitive entity values.
- Plaintext mappings.
- Restoration credentials.
- Encryption keys or decrypted payloads.

Safe metadata may include service/version, correlation ID, operation type, status, latency, error category, and approved counts/categories. Review tracing instrumentation to ensure request/response bodies and exception attributes are not captured.

## 10. Testing standards

Full strategy: `docs/TEST_STRATEGY.md`. Tests are mandatory for every feature. Write them before the implementation, run them, and review the results.

### Test levels

| Level | Directory | Scope |
|---|---|---|
| Unit | `tests/unit/` | Recognizers, policies, span handling, placeholders, credential generation, hashing, encryption and decryption. No network or database. |
| Integration | `tests/integration/` | Each service's API, database behavior, migrations, and the internal API, using a real PostgreSQL via Testcontainers. |
| Security | `tests/security/` | Tenant and scope isolation, authorization, entropy, tamper detection, replay, rate limits, internal API authentication, and log redaction. |
| Evaluation | `tests/evaluation/` | Detection quality (precision, recall, F1, false positive and negative rates) on the synthetic dataset. |
| End-to-end | `tests/e2e/` | Both services as separate processes, called over HTTP. No UI. |
| Performance | `tests/performance/` | Locust load tests, run on demand and before release. |

### Naming and layout

- Files are `test_<area>.py`; functions are `test_<behavior>_<condition>` and state the expected outcome, for example `test_restore_rejects_cross_tenant_reference`.
- Mirror the service layout: tests for `services/sanitization_service/app/vault/` go in `tests/unit/sanitization/vault/` (or a clearly named file in the suite directory).
- One behavior per test. Use `pytest.mark.parametrize` for input variations.
- Suite markers (`unit`, `integration`, `security`, `evaluation`, `e2e`) are applied automatically from the directory; do not add them by hand.

### Fixtures and isolation

- Shared fixtures live in `tests/conftest.py` and per-suite `conftest.py` files; reusable helpers live in `tests/support/`.
- Each test creates its own tenant, request scope, and database state, and cleans up. Tests must not depend on order or share mutable state.
- Control time and randomness where the behavior depends on them (expiry, nonces); do not use `sleep` to wait for expiry.
- Use synthetic data only: reserved domains, the fictional `555-01xx` range, documented test numbers. Never use real PII, credentials, or keys; generate test keys at test time.

### Mocking and dependencies

- Unit tests mock or stub everything outside the unit. Do not mock the code under test.
- Integration tests use a real PostgreSQL (Testcontainers), not a mock or SQLite.
- Never mock the cryptography library to make an encryption test pass; test real encryption with test keys.
- The De-sanitization Service's tests stub the Sanitization Service at its HTTP boundary and add a separate contract test against the real internal API schema.
- Tests never call external networks, cloud services, or LLMs.
- A test for an unbuilt feature must skip with a reason or not exist. Never write a test that passes without testing anything.

### Coverage and quality

- Minimum 80% line coverage on `services/`, enforced by `scripts/run_tests.py` once service code exists. Target 90% or more, with branch coverage reviewed, for the vault, cryptography, authorization, and restoration modules.
- Coverage is necessary, not sufficient: security requirements need explicit negative tests.
- Never lower a threshold, delete a test, or add a skip or xfail to get a green run.
- Every fixed defect gets a regression test.
- Use Hypothesis for properties such as round trips, collision avoidance, and bounds.

### Standard commands

```text
uv run scripts/run_tests.py unit | integration | security | evaluation | e2e | all
uv run scripts/run_tests.py lint        # Ruff check and format check
uv run scripts/run_tests.py scan        # Bandit and pip-audit
uv run pyright                          # type check
```

## 11. Quality gates

- Run formatter/linter (Ruff).
- Run the type check (Pyright).
- Run unit, integration, security, evaluation, and end-to-end tests.
- Meet the coverage minimum.
- Run Bandit and `pip-audit`.
- Validate migrations from an empty database and supported prior versions.
- Report actual commands and results; never claim unrun tests passed.
- Update documentation and status, with test evidence, before declaring a phase complete.
- Add tests with each change, and use stubs rather than real external services.
- Never lower a threshold, turn off a rule, or exclude a file to get a green run; if a rule looks wrong, stop and ask.
