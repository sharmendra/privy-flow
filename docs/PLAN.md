# PrivyFlow — Implementation Roadmap

## 1. Delivery strategy

Build the privacy engine locally in small, verifiable phases. Keep the Sanitization and De-sanitization Services independently deployable. Complete security and correctness gates before production consideration.

Testing is part of every phase, not a final step. Each phase follows: define expected behavior, write tests, implement, execute tests, review results. The test harness is set up in Phase 1, and every later phase adds the tests listed below to the suites described in `docs/TEST_STRATEGY.md`. A phase is complete only when its tests have been executed and the evidence is recorded in `docs/STATUS.md`.

## 2. Roadmap

| Phase | Scope | Exit criteria | Tests added in this phase |
|---|---|---|---|
| 0. Scope and architecture baseline | Approve product specification, two-service boundaries, data ownership, API contracts, and threat assumptions. | Documentation is consistent and architecture is approved. | Test strategy and release gates approved. |
| 1. Service foundations | Two FastAPI applications, configuration, health endpoints, logging redaction baseline, Sanitization-owned PostgreSQL/Alembic setup, and the test harness. | Both services start independently; database ownership and migrations are validated; the harness runs in CI. | Harness (pytest, fixtures, CI, coverage); startup and health tests for both services; migration test from an empty database (Testcontainers); log-redaction baseline test; a test that the De-sanitization Service holds no Sanitization database credentials. |
| 2. Sanitization detection and policies | Recognizer abstraction, initial entity categories, policy model, and detection result schema. | Representative test corpus and detection-quality baseline are documented. | Unit tests for recognizers and policies; detection evaluation against the synthetic dataset with the baseline recorded; thresholds proposed for approval. |
| 3. Placeholder sanitization | Placeholder generation, repeated-value behavior, collision avoidance, span handling, and sanitized response. | Unit and API tests prove expected transformations and safe edge-case behavior. | Unit and Hypothesis property tests (collisions, repeats, overlaps, text preservation); Sanitization API tests for valid, invalid, and oversized input. |
| 4. Secure mapping vault | High-entropy credential generation, hash lookup, AES-GCM mapping encryption, key versioning, expiry, revocation, and deletion metadata. | Cryptographic and database security tests pass. | Entropy and uniqueness, digest-only storage, encryption round trip and nonce uniqueness, tamper detection, key version, expiry and revocation; database constraint tests; plaintext-at-rest check. |
| 5. Internal mapping API | Authenticated internal endpoint, caller identity, tenant/request scope checks, bounded response, and safe errors. | Only authorized De-sanitization Service calls can retrieve mappings; no direct DB access exists. | Internal API authentication and authorization tests; tenant and scope isolation; safe-error and non-disclosure tests; contract test for the internal API. |
| 6. De-sanitization | Caller authorization, internal API client, exact placeholder restoration, unknown-placeholder behavior, and audit metadata. | Positive, negative, expiry, revocation, and cross-scope tests pass. | Restoration unit and property tests (round trip); unknown and altered placeholders; expired, revoked, and cross-tenant rejection; first cross-service tests over HTTP. |
| 7. Integration and hardening | End-to-end tests, rate limits, request limits, timeouts, resilience, log/trace redaction, and threat-model review. | Security and operational test suites pass with recorded evidence. | Full end-to-end scenarios (restart, concurrency, service and database outage, tampering, replay); rate and size limits; leakage tests on logs, traces, errors, and metrics; Locust load baseline; Bandit and `pip-audit` clean. |
| 8. Production readiness assessment | TLS, identity, KMS/secrets manager, deployment, monitoring, backup, retention, incident response, and recovery design. | Release gates are reviewed and production deployment is explicitly approved. | Production-readiness validation (TLS, identity, KMS, backup and restore drill, incident and recovery runbooks), full regression run, and performance against agreed targets. |

## 3. Phase success criteria

Tick each box only after verifying it with tests, commands, or API calls, and record the evidence in `STATUS.md`. A criterion backed by tests is met only when those tests ran and passed, not when they are skipped or pending.

### Phase 0. Scope and architecture baseline
- [ ] Documentation is consistent and architecture is approved.
- [ ] `docs/TEST_STRATEGY.md` and its release gates are approved.

### Phase 1. Service foundations
- [ ] Both services start independently; database ownership and migrations are validated.
- [x] Test harness foundation in place: pytest configured, fixtures, runner script, CI workflow, coverage setup. Evidence in `STATUS.md`.
- [ ] Health and startup tests for both services pass (currently skipped: services not built).
- [ ] The harness runs in CI and the pipeline is green.
- [ ] Migration test passes from an empty PostgreSQL database.
- [ ] The De-sanitization Service has no Sanitization database credentials, and a test proves it.

### Phase 2. Sanitization detection and policies
- [ ] Representative test corpus and detection-quality baseline are documented.
- [ ] Detection evaluation runs against the synthetic dataset and the per-type and overall baseline is recorded.
- [ ] Acceptance thresholds are approved by the product owner and set in `thresholds.json`.

### Phase 3. Placeholder sanitization
- [ ] Unit and API tests prove expected transformations and safe edge-case behavior.
- [ ] Property tests pass for collision avoidance, repeated values, and text preservation.

### Phase 4. Secure mapping vault
- [ ] Cryptographic and database security tests pass.
- [ ] Tests confirm only a digest of the restore-reference and only ciphertext are stored.
- [ ] Tamper, key-version, expiry, and revocation tests pass.

### Phase 5. Internal mapping API
- [ ] Only authorized De-sanitization Service calls can retrieve mappings; no direct DB access exists.
- [ ] Tenant isolation, scope, and non-disclosure tests pass.
- [ ] Internal API contract test passes.

### Phase 6. De-sanitization
- [ ] Positive, negative, expiry, revocation, and cross-scope tests pass.
- [ ] Round-trip tests show restoration reproduces the original supported input exactly.
- [ ] A restore-reference alone is shown not to authorize restoration.

### Phase 7. Integration and hardening
- [ ] Security and operational test suites pass with recorded evidence.
- [ ] End-to-end scenarios pass: restart, concurrency, outages, tampering, and replay.
- [ ] Leakage tests show no sensitive values in logs, traces, errors, or metrics.
- [ ] Load test baseline recorded and performance targets agreed.
- [ ] Bandit and `pip-audit` report no unresolved findings.

### Phase 8. Production readiness assessment
- [ ] Release gates are reviewed and production deployment is explicitly approved.
- [ ] Production-readiness validation is complete and evidenced.
- [ ] Full regression suite passes with detection quality at or above approved thresholds.

## 4. Immediate next steps

1. Inspect the current repository and identify any old Extraction Service / Privacy Service scaffolding.
2. Reconcile the codebase with the approved Sanitization / De-sanitization architecture.
3. Finalize public API and internal mapping API contracts.
4. Define trusted tenant identity, caller authorization, and service-to-service authentication.
5. Implement the Sanitization Service foundation and its owned vault database, and turn its pending tests into real ones.
6. Implement the De-sanitization Service foundation without direct mapping database access, and turn its pending tests into real ones.
7. Write tests before advancing to detection, encryption, and restoration features.

## 5. Release gates

Release gates are requirements. A release needs recorded evidence for every gate. The full gate list with measurable criteria is in `docs/TEST_STRATEGY.md`.

| Gate | Minimum evidence |
|---|---|
| Functional | Sanitization and restoration acceptance tests pass; the full regression suite passes. |
| Security | Authentication, authorization, tenant isolation, internal API protection, and threat review. |
| Cryptographic | Credential entropy, hash lookup, authenticated encryption, nonce uniqueness, and key-version handling tested. |
| Data protection | Expiry, revocation, deletion, and audit controls verified. |
| Detection quality | Precision and recall meet approved thresholds, per entity type and overall. |
| Reliability | Timeouts, dependency failures, health checks, and bounded retries tested. |
| Performance | Load test results meet the agreed latency and throughput targets. |
| Observability | Logs, traces, and metrics reviewed for sensitive-data leakage. |
| Static security | Bandit and `pip-audit` have no unresolved findings. |
| Operational | Deployment, secrets, monitoring, backup, incident, and recovery runbooks approved. |
| Production readiness | Production-readiness validation is complete and production deployment is explicitly approved. |

## 6. Scope-change rule

Document and obtain approval before adding document extraction, file handling, chunking, embeddings, vector databases, RAG, LLM integration, additional services, direct database sharing, or new infrastructure components.
