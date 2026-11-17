# PrivyFlow — Project Status and Decision Register

> This file is the source of truth for verified implementation status. Update it after each meaningful development session. Do not mark planned or generated work as completed without validation.

## 1. Current product baseline

PrivyFlow's approved current scope is a two-service privacy engine:

1. Sanitization Service.
2. De-sanitization Service.

The earlier Extraction Service / Privacy Service design is superseded. Document ingestion, file parsing, chunking, embeddings, vector databases, RAG, and LLM integration are out of scope for the current baseline.

## 2. Approved architecture decisions

| Decision | Current position |
|---|---|
| Product | PrivyFlow |
| Product category | Privacy engine / privacy infrastructure |
| Core services | Sanitization and De-sanitization |
| Deployment | Independent service lifecycles |
| Mapping vault owner | Sanitization Service |
| Mapping retrieval | Authenticated internal API |
| Direct cross-service DB access | Prohibited |
| Shared runtime coupling | Prohibited |
| Client workflow coordination | Client application |
| Initial input | Text API payload |
| Local development | Default |
| Cloud deployment | Requires explicit approval |

## 3. Current implementation status

The project documentation defines the target architecture and requirements. Do not assume that all capabilities are implemented.

| Capability | Status |
|---|---|
| Product and service boundaries | Defined |
| Sanitization API | To be implemented / verified |
| De-sanitization API | To be implemented / verified |
| Sensitive entity detection | Planned |
| Policy engine | Planned |
| Placeholder generation | Planned |
| Encrypted mapping vault | Planned |
| Credential hashing and lookup | Planned |
| Authenticated internal mapping API | Planned |
| Authorization and tenant isolation | Planned |
| Expiry and revocation | Planned |
| Restoration logic | Planned |
| Test harness foundation | Implemented and executed (see section 4); no service tests can run yet |
| Service-level tests (unit, integration, security, end-to-end) | Pending: skipped with a reason until each feature exists |
| Detection evaluation dataset and metrics | Implemented and executed; no detector exists, so no detection baseline |
| CI workflow | Written, not yet run (the project is not in a Git repository yet) |
| Performance (Locust) | Script written, not executed |
| Production deployment | Not approved |

Update each row only after inspecting code and running the relevant tests.

## 4. What is built and how to run it

No service code exists yet. The repository contains documentation and the test harness foundation.

Install and run:

```text
uv sync                                   # core test tooling
uv sync --all-groups                      # plus integration, perf and security tools
uv run scripts/run_tests.py all           # all suites
uv run scripts/run_tests.py lint
uv run pyright
```

Full command list: `docs/TEST_STRATEGY.md` section 13 and `tests/README.md`.

### Test evidence

Recorded 2026-11-17, Windows, Python 3.12.10.

| Command | Result |
|---|---|
| `uv run scripts/run_tests.py all` | 21 passed, 0 failed, 63 skipped |
| `uv run scripts/run_tests.py lint` | Ruff check and format check passed |
| `uv run pyright` (after `uv sync --all-groups`) | 0 errors, 0 warnings |
| `uv run scripts/run_tests.py scan` | `pip-audit`: no known vulnerabilities; Bandit skipped (no service code) |
| Health tests against a temporary fake FastAPI service pair (outside the repo) | 4 passed; confirms the loader and health fixtures work |

What the 21 passing tests cover: the leak assertion and service loader helpers, the evaluation metrics (including Hypothesis property tests), and the dataset integrity checks.

What the 63 skips are: health tests for both services (4, services not built), pending placeholders for unit, integration, security, and end-to-end scenarios, and the detection quality test (detector not built). None of these is a pass.

Not verified:

- The PostgreSQL Testcontainers fixture: Docker is installed but its daemon was not running, so the fixture skipped. It has not run against a real database.
- The GitHub Actions workflow has not run.
- The Locust script has not been run.
- Coverage enforcement (80%) is wired in `scripts/run_tests.py` but activates only once service code exists; it has not been exercised.

### Pilot plan progress (`docs/PLAN_PILOT.md`)

| Phase | State |
|---|---|
| 1. Decisions, contracts, threat model | Documentation complete 2026-11-17. One criterion open: owner review of the profile files (see below). |
| 2, 2A, 3 to 8 | Not started |

Phase 1 delivered (documentation and data only, no service code, no test changes):

- `docs/adr/0001-pilot-decisions.md`: D1 to D17 recorded as approved, plus fixed conventions (placeholder and redact markers, synthetic data ranges).
- `docs/SPEC.md` section 9: final schemas, error codes, identifier patterns, and the restrictiveness rules for all five endpoints.
- `docs/THREAT_MODEL.md`: attackers, mitigations, and the planned proving tests. All tests are pending until their phases run.
- Profile data in `services/sanitization_service/app/sanitization/profiles/data/`: six profiles (`gdpr`, `india_dpdp`, `hipaa`, `pci_dss`, `glba`, `ccpa`) and `entity_types.json`. All are marked `not_reviewed_by_legal`. They are data only; no loader exists yet.

Phase 1 evidence, recorded 2026-11-17, Windows:

| Command | Result |
|---|---|
| `uv run scripts/run_tests.py all` | 21 passed, 0 failed, 63 skipped (same as the baseline above) |
| `uv run scripts/run_tests.py lint` | Ruff check and format check passed |
| `uv run pyright` | 0 errors, 0 warnings |
| JSON parse and cross-check of the seven profile data files | All parse; every profile entity type exists in `entity_types.json`; six types are marked as having a pilot recognizer |

Profile contents to review (owner action, not yet done): which entity types each profile names; the `max_ttl_seconds` values (gdpr 3600, india_dpdp 3600, hipaa 1800, pci_dss 900, glba 3600, ccpa 3600), which are my choices and not taken from any regulation; and `pci_dss` setting `FINANCIAL` to `placeholder`, which stores encrypted card numbers in the vault and may bring the vault into PCI scope. Setting it to `redact` would avoid that but makes card numbers unrestorable.

## 5. Validation checklist

- [ ] Inspect the repository and remove or archive obsolete extraction-service scaffolding only after review.
- [ ] Confirm separate Sanitization and De-sanitization applications.
- [ ] Confirm Sanitization Service owns the mapping database and migrations.
- [ ] Confirm De-sanitization has no mapping database credentials.
- [x] Define and approve public and internal API contracts. Pilot contracts: `docs/SPEC.md` section 9, approved 2026-11-17.
- [ ] Implement authentication and authorization boundaries.
- [ ] Implement recognizer and policy baseline.
- [ ] Implement placeholder generation and collision handling.
- [ ] Implement secure credential generation and hash lookup.
- [ ] Implement authenticated encryption and key-version metadata.
- [ ] Implement internal mapping retrieval with scope/expiry/revocation validation.
- [ ] Implement authorized restoration.
- [ ] Run tenant-isolation and security tests.
- [ ] Verify logs and traces do not contain sensitive values.
- [ ] Record exact test and migration results.

## 6. Known risks and open decisions

- Resolved for the pilot (ADR 0001, 2026-11-17): tenant identity and caller authorization (per-tenant API keys, D2), service-to-service authentication (shared secret, D3), overlap policy (D6), restoration lifetime, reuse, and revocation (D5). These are pilot-only mechanisms. A production identity provider, mTLS or signed tokens, and the replacement for the shared secret are still open.
- Production key-management/KMS design is not selected (pilot uses an environment-variable key, D4).
- One-time-use restoration is not built; reuse within the TTL is accepted (D5).
- Profile contents are unreviewed by legal; no compliance claim is made (D13).
- Audit retention and deletion requirements need definition.
- Detection quality must be evaluated against representative data; no perfect-detection claim is valid.

## 7. Update discipline

For each completed task, record:
- Date and phase.
- Files changed.
- APIs/schema changes.
- Migrations executed.
- Tests and exact results.
- Security checks performed.
- Known failures and follow-up tasks.

Code generation alone is not evidence of completion.
