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

## 5. Validation checklist

- [ ] Inspect the repository and remove or archive obsolete extraction-service scaffolding only after review.
- [ ] Confirm separate Sanitization and De-sanitization applications.
- [ ] Confirm Sanitization Service owns the mapping database and migrations.
- [ ] Confirm De-sanitization has no mapping database credentials.
- [ ] Define and approve public and internal API contracts.
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

- Trusted source of tenant identity and caller authorization must be selected.
- Service-to-service authentication mechanism must be approved.
- Production key-management/KMS design is not selected.
- Policy semantics for overlapping entities, repeated values, and ambiguous detections need explicit definition.
- Restoration credential lifetime, one-time-use behavior, and revocation semantics need approval.
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
