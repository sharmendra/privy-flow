# PrivyFlow — Product Specification

## 1. Product overview

PrivyFlow is a privacy engine that helps applications protect sensitive text before it is shared with external systems. Its current scope is deliberately limited to two independently deployable services:

1. **Sanitization Service** — detects configured sensitive information, applies policies, replaces sensitive values with placeholders, and securely stores reversible mappings.
2. **De-sanitization Service** — restores authorized placeholders to their original values by requesting mappings through an authenticated internal API.

The client application controls the workflow. The services do not share application runtime code or direct database access.

## 2. Product objectives

- Accept text through documented APIs.
- Detect configurable categories of sensitive entities.
- Apply explicit, configurable sanitization policies.
- Replace sensitive values with safe, collision-resistant placeholders.
- Retain reversible mappings in encrypted form.
- Permit restoration only after authentication, authorization, tenant-scope, request-scope, expiry, and revocation checks.
- Provide independent service deployment, configuration, testing, and operational lifecycles.
- Avoid exposing original sensitive content in logs, traces, metrics, and error messages.

## 3. Current scope

### In scope

- Text-based sanitization and de-sanitization APIs.
- PII/sensitive-entity detection and configurable recognizers.
- Policy-based masking and placeholder generation.
- Secure restoration credential generation and validation.
- Encrypted mapping vault owned by the Sanitization Service.
- Authenticated internal mapping-retrieval API.
- Tenant and request/session isolation.
- Expiry, revocation, deletion, and audit metadata.
- Security, validation, and integration tests.

### Explicitly out of scope

- File upload, folder watchers, document-source connectors, and document extraction.
- PDF, DOCX, HTML, spreadsheet parsing, and OCR.
- Text chunking and document indexing.
- LLM token counting or model tokenization.
- Embeddings and vector databases, including ChromaDB and Qdrant.
- Semantic search and RAG.
- LLM calls, prompt construction, agents, and orchestration.
- Mandatory API gateway or workflow orchestrator.
- Cloud resources or production deployment without explicit approval.

Do not add out-of-scope modules or dependencies for speculative future use.

## 4. Users and actors

| Actor | Responsibility |
|---|---|
| Client application / backend | Sends text to sanitization, stores the returned sanitized content and restoration reference securely, and requests restoration when authorized. |
| Application user | Uses the client application; does not automatically receive vault access. |
| Tenant administrator | Manages tenant policies and authorized access, subject to the approved authorization model. |
| Operations / security | Monitors safe operational metadata and audit events without routine access to raw sensitive content. |
| Sanitization Service | Detects, sanitizes, and owns encrypted reversible mappings. |
| De-sanitization Service | Authorizes restoration requests and obtains mappings through the Sanitization Service internal API. |

## 5. Core workflows

### 5.1 Sanitization

1. Client authenticates to the Sanitization Service.
2. Service validates caller, tenant context, request scope, payload size, and requested policy.
3. Detection engine identifies configured sensitive entities.
4. Policy engine determines which entities to mask and how.
5. Placeholder generator creates collision-resistant placeholders. Repeated occurrences may map consistently within the same request according to policy.
6. Sanitization Service creates a high-entropy restoration credential/reference.
7. Service hashes the credential for lookup and encrypts the reversible mapping payload.
8. Service stores encrypted mapping metadata in its vault.
9. Service returns sanitized text, the restoration credential/reference, and safe operation metadata.

### 5.2 De-sanitization

1. Client authenticates to the De-sanitization Service.
2. Client submits sanitized text, restoration reference, and required request context.
3. De-sanitization Service authorizes the caller and validates tenant and request scope.
4. Service calls the Sanitization Service's authenticated internal mapping-retrieval API.
5. Sanitization Service validates the credential hash, scope, expiry, revocation, and internal caller identity.
6. Sanitization Service decrypts the mapping only for the authorized operation and returns it over the protected service channel.
7. De-sanitization Service restores only placeholders present in that mapping.
8. Service returns restored text and safe audit metadata.

### 5.3 Failure behavior

- Invalid, expired, revoked, or unauthorized references must fail safely.
- Do not disclose whether a protected mapping exists to an unauthorized caller.
- Unknown or altered placeholders must not be guessed or substituted.
- Internal service unavailability must produce a safe retryable or non-retryable error according to the documented API contract.
- Sensitive values must never be included in error messages or logs.

## 6. Service responsibilities

| Capability | Sanitization Service | De-sanitization Service |
|---|---|---|
| Accept original text | Yes | No |
| Detect sensitive entities | Yes | No |
| Evaluate sanitization policies | Yes | No |
| Generate placeholders | Yes | No |
| Generate restoration credential | Yes | No |
| Hash credential for lookup | Yes | No |
| Encrypt and store mappings | Yes; owns vault | No |
| Authenticate restoration caller | No, except its own internal API authorization | Yes |
| Validate restoration authorization | Enforces internal mapping access rules | Yes |
| Retrieve mapping | Owns and serves it through internal API | Requests it through internal API |
| Restore original values | No | Yes |
| Direct access to the other service's DB | No | No |

## 7. Functional requirements

- **FR-01:** Both services expose liveness and readiness endpoints.
- **FR-02:** Sanitization accepts text, tenant context, request scope, and an approved policy reference.
- **FR-03:** Sanitization detects entities using configurable recognizers.
- **FR-04:** Sanitization replaces selected values with collision-resistant placeholders.
- **FR-05:** Repeated occurrences are handled consistently within the documented scope.
- **FR-06:** Sanitization returns sanitized text and a high-entropy restoration reference.
- **FR-07:** The vault stores only a hash of the restoration credential and encrypted mapping payloads.
- **FR-08:** The internal mapping API authenticates the De-sanitization Service and validates scope and credential status.
- **FR-09:** De-sanitization validates caller authorization, tenant, request scope, expiry, and revocation.
- **FR-10:** De-sanitization restores only known placeholders from the authorized mapping.
- **FR-11:** Both services validate input types, sizes, and request limits.
- **FR-12:** Sensitive content and secrets are excluded from logs, traces, and ordinary telemetry.
- **FR-13:** APIs are versioned and covered by automated tests.

## 8. Security and privacy requirements

- Never log original text, restored text, sensitive entity values, plaintext mappings, restoration credentials, or encryption keys.
- Use TLS outside local development.
- Bind every mapping to tenant and request/session scope.
- Generate restoration credentials with a cryptographically secure random generator and sufficient entropy.
- Store only a secure digest or keyed hash of the credential for lookup.
- Encrypt mappings using authenticated encryption such as AES-256-GCM, with unique nonces and key-version metadata.
- Keep keys outside source control and outside the ciphertext database.
- Enforce expiry, revocation, retention, and deletion.
- Use least-privilege database and service credentials.
- Treat detection and sanitization as risk reduction, not guaranteed anonymization.

## 9. API surface — initial proposal

Final schemas and route names must be approved and recorded before implementation.

| Service | Proposed endpoint | Purpose |
|---|---|---|
| Sanitization | `GET /health/live` | Process liveness |
| Sanitization | `GET /health/ready` | Dependency readiness |
| Sanitization | `POST /api/v1/sanitizations` | Sanitize submitted text |
| Sanitization | `GET /api/v1/policies` | List available policy metadata |
| Sanitization internal | `POST /internal/v1/mappings/retrieve` | Authenticated mapping retrieval for De-sanitization |
| De-sanitization | `GET /health/live` | Process liveness |
| De-sanitization | `GET /health/ready` | Dependency readiness |
| De-sanitization | `POST /api/v1/desanitizations` | Restore authorized placeholders |

## 10. Acceptance criteria for the core engine

- Both services run independently.
- Sanitization detects and masks configured test entities.
- Repeated occurrences follow the documented placeholder policy.
- The vault never stores plaintext restoration credentials or plaintext mappings.
- Mapping encryption/decryption tests pass.
- De-sanitization uses only the authenticated internal API to obtain mappings.
- Cross-tenant and cross-request restoration is rejected.
- Expired, revoked, malformed, or unauthorized references fail safely.
- Unknown placeholders are not substituted.
- Logs and traces do not expose sensitive payloads.
- API and security tests pass, with actual results recorded.

## 11. Test requirements

Full strategy: `docs/TEST_STRATEGY.md`. Every requirement in this specification must be covered by at least one automated test before it is considered met. Tests are written before the implementation and use synthetic data only.

### 11.1 Functional test requirements

| Requirement | Required tests |
|---|---|
| FR-01 health endpoints | Liveness returns 200; readiness returns 200 when dependencies are up and 503 when they are not, for both services. |
| FR-02 to FR-06 sanitization | Each configured entity type is detected and replaced; repeated values follow the documented policy; placeholders never collide with placeholder-like text in the input; text outside sensitive spans is preserved; the response carries sanitized text and a restore-reference. |
| FR-07 vault | The database contains only a digest of the restore-reference and encrypted payloads; plaintext values never appear in any column. |
| FR-08 internal API | Calls without valid service identity are rejected; scope, expiry, and revocation are enforced; the response contains only the required mapping. |
| FR-09 to FR-10 restoration | Authorized restoration succeeds; unknown, altered, or malformed placeholders are left untouched; expired, revoked, and cross-scope references are rejected. |
| FR-11 validation | Wrong types, empty input, oversized input, and unsupported policies are rejected with safe errors. |
| FR-12 telemetry | Logs, traces, metrics, and error bodies never contain the canary sensitive values. |
| FR-13 versioning | Versioned routes exist and the internal API contract is tested for compatibility. |

### 11.2 Non-functional test requirements

- **Security:** the tests in section 7 of `docs/TEST_STRATEGY.md`, including tamper detection, replay, rate limiting, and internal API authentication, are automated.
- **Privacy:** leakage tests cover logs, traces, errors, and metrics for both services.
- **Reliability:** timeouts, Sanitization Service outage, database outage, service restart, and bounded retries are tested.
- **Performance:** load tests measure p50, p95, and p99 latency, throughput, and error rate across representative text sizes. Targets are agreed after a baseline run; they are not assumed here.
- **Portability:** the test suite runs on Windows and Linux.

## 12. Measurable acceptance criteria

These extend section 10. They are proposed criteria, not claims about existing functionality. Values described as approved are set by the product owner after the baseline is recorded.

### Sanitization and restoration

- **Round trip:** for every supported input in the test corpus, restoring the sanitized text reproduces the original exactly. Zero mismatches.
- **Placeholders:** zero collisions with placeholder-like text in the corpus; repeated values map consistently within one request.
- **Detection quality:** precision and recall, per entity type and overall, meet the approved minimums in `tests/fixtures/eval/thresholds.json`. Results are reported separately by type. No perfect-detection claim is made.
- **Safe handling:** unknown, altered, duplicated, or malformed placeholders are never substituted, in 100% of test cases.

### Security and privacy

- **Authorization:** 100% of restoration attempts without valid caller authorization are rejected. A restore-reference alone never authorizes restoration.
- **Tenant isolation:** zero successful cross-tenant or cross-request reads or restorations across the isolation test matrix.
- **Entropy:** restore-references come from a cryptographically secure source with at least 128 bits of entropy, and a sample of at least 100,000 generated references contains no duplicates.
- **Encryption at rest:** no plaintext mapping value or plaintext restore-reference is present in any database column used in tests; every stored mapping carries an algorithm and key version.
- **Tampering:** modified ciphertext, nonce, or key version is rejected in 100% of test cases.
- **Expiry and revocation:** expired and revoked references are rejected in 100% of test cases, without disclosing whether the mapping exists.
- **Leakage:** zero occurrences of canary sensitive values in captured logs, traces, metrics, and error responses.
- **Database boundary:** the De-sanitization Service has no Sanitization database URL or credentials and cannot connect to that database.

### Failure handling

- Sanitization Service unavailable: restoration returns a safe, documented error (503) with a correlation ID and no sensitive content.
- Database unavailable: both services stay up, fail safely, and recover when the database returns, with no mappings lost.
- Service restart: previously stored, unexpired mappings remain restorable.

### Release

All gates in `docs/TEST_STRATEGY.md` section 15 pass with recorded evidence, including a clean regression run and approved performance targets.
