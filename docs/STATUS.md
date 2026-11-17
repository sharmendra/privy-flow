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
| Sanitization API | `POST /api/v1/sanitizations` and `GET /api/v1/policies` implemented and executed, pilot phase 5 (see section 4) |
| De-sanitization API | `POST /api/v1/desanitizations` implemented and executed against a stub of the Sanitization internal API, pilot phase 7 (see section 4); not yet run against the real service |
| Sensitive entity detection | Six pilot recognizers implemented and executed, pilot phase 3 (see section 4); no PERSON, Aadhaar, address or date detection |
| Policy engine | Profile loader, effective-policy resolver and overlap rule implemented and executed, pilot phase 3; not yet used by an API |
| Placeholder generation and span replacement | Implemented and executed, pilot phase 4 (see section 4); pure logic, not yet used by an API |
| Request size limit (413) and sanitization request schema | Implemented and executed for the Sanitization Service, pilot phase 4, through a test-only route; the public endpoint is phase 5. De-sanitization side is phase 7 |
| Encrypted mapping vault | Implemented and executed against PostgreSQL, pilot phase 5 |
| Credential hashing and lookup | Implemented and executed, pilot phase 5 (HMAC digest, unique index) |
| Authenticated internal mapping API | Implemented and executed against an in-memory store, pilot phase 6 (see section 4); not yet run against PostgreSQL |
| Authorization and tenant isolation | Public API key authentication and tenant scoping implemented and executed for the Sanitization API, phase 5. Internal API and De-sanitization side planned |
| Expiry and revocation | Implemented in the vault and repository and executed, phase 5; no public revoke endpoint |
| Restoration logic | Implemented and executed (property tests), pilot phase 7 |
| Settings store (file and database backends, validation, audit, CLI) | Implemented and executed, pilot phase 2A (see section 4) |
| Service foundations (both apps, health, correlation IDs, redacted logging, error body, vault table migration) | Implemented and executed, pilot phase 2 (see section 4) |
| Test harness foundation | Implemented and executed (see section 4) |
| Service-level tests (unit, integration, security, end-to-end) | Phase 2, 2A, 3 and 4 tests written; database-backed ones did not run in the last two sessions (no Docker, no database URL). The rest are pending and skipped with a reason |
| Detection evaluation dataset and metrics | Implemented and executed; pilot baseline recorded in phase 3 evidence; thresholds still unapproved (`null`) |
| CI workflow | Written, not yet run (no remote) |
| Performance (Locust) | Script written, not executed |
| Production deployment | Not approved |

Update each row only after inspecting code and running the relevant tests.

## 4. What is built and how to run it

The repository contains documentation, the test harness, and the pilot phase 2 service foundations: two FastAPI apps with health endpoints, correlation IDs, allowlist logging and the standard error body, plus the Sanitization `mapping_records` migration. Phase 3 added detection (six regex and checksum recognizers), the profile loader, the effective-policy resolver and the span planner. Phase 4 added placeholder generation and span replacement, the sanitization request schema and the request size limit. Phase 5 added the encrypted vault, API-key authentication and the public sanitization and policy endpoints. The internal mapping endpoint exists from phase 6 and restoration from phase 7. The two services have not yet run together (phase 8).

Run locally (PowerShell or macOS; values stay in git-ignored files):

```text
uv sync --all-groups
uv run scripts/gen_local_secrets.py --admin-url postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow
uv run scripts/create_db_roles.py          # creates the least-privilege runtime role
# set PRIVYFLOW_SAN_MIGRATION_DATABASE_URL to the admin URL for this shell, then:
uv run alembic -c services/sanitization_service/alembic.ini upgrade head
uv run uvicorn app.main:app --app-dir services/sanitization_service --port 8001 --no-access-log
uv run uvicorn app.main:app --app-dir services/desanitization_service --port 8002 --no-access-log
```

Settings: copy `config/settings.example.json` to `config/settings.json` (the secrets script does this), then check it with `uv run scripts/settings.py validate`. To use the database backend, run `uv run scripts/settings.py import`, set `PRIVYFLOW_SETTINGS_BACKEND=db`, and restart. `uv run scripts/gen_local_secrets.py --force` followed by `uv run scripts/create_db_roles.py` also creates the settings admin role; run the migration again afterward so it can grant that role its privileges.

Keep `--no-access-log`: the default uvicorn access log prints query strings. Each service reads only its own `services/<service>/.env`. Integration tests use Testcontainers when Docker runs, or the local PostgreSQL named by `PRIVYFLOW_TEST_DATABASE_URL` (see the deviation under test evidence).

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
| 2. Service foundations | Implemented 2026-11-17; one criterion open pending an owner decision on the coverage gate (see "Phase 2 evidence"). |
| 2A. Settings store | Implemented 2026-11-17; one criterion open (macOS run of the CLI). |
| 3. Detection and policy | Implemented 2026-11-17; one criterion open: the file-versus-database policy comparison test is written but has not run (see "Phase 3 evidence"). |
| 4. Placeholder sanitization | Implemented 2026-11-17; all five criteria met (see "Phase 4 evidence"). |
| 5. Secure mapping vault | Implemented 2026-11-17; all twelve criteria met (see "Phase 5 evidence"). |
| 6. Internal mapping API | Implemented 2026-11-17; all six criteria met (see "Phase 6 evidence"). |
| 7. De-sanitization | Implemented 2026-11-17; all eight criteria met against a stub (see "Phase 7 evidence"). |
| 8. End-to-end run and close-out | Not started |

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

### Phase 2 evidence (service foundations)

Recorded 2026-11-17, Windows, Python 3.13.13. PostgreSQL 18.6 local server.

Deviation, approved by the owner on 2026-11-17: the Docker daemon was not running, so integration tests used the local PostgreSQL named by `PRIVYFLOW_TEST_DATABASE_URL` instead of Testcontainers. Each test creates and drops its own `pf_test_*` database. If neither is available the database tests fail with a reason, never skip. The Testcontainers path in `tests/integration/conftest.py` was not run.

| Command | Result |
|---|---|
| `uv run scripts/run_tests.py all` (with the local database) | 74 passed, 0 failed, 56 skipped; coverage 93.39% (minimum 80%) |
| `uv run scripts/run_tests.py integration` | 44 passed, 0 failed, 8 skipped; coverage gate met (93.39%) |
| `uv run scripts/run_tests.py unit` | 10 passed, 0 failed, 20 skipped; coverage gate FAILED (0.00%, see below) |
| `uv run scripts/run_tests.py security` | 5 passed, 0 failed, 17 skipped |
| `uv run scripts/run_tests.py evaluation` | 15 passed, 0 failed, 1 skipped |
| `uv run scripts/run_tests.py lint` | Ruff check and format check passed |
| `uv run pyright` (now includes `services`) | 0 errors, 0 warnings |
| `uv run scripts/run_tests.py scan` | `pip-audit`: no known vulnerabilities. Bandit on `services`: no findings. Bandit on `scripts` reports 2 low findings (subprocess use) in `run_tests.py`, outside the scanned path and pre-existing. |
| `alembic upgrade head` on the `privyflow` database, then both services started from their own `.env` files | Migration at `0001 (head)`; both `/health/live` and `/health/ready` returned 200 on ports 8001 and 8002; unknown route returned the standard 404 body |

Skips are all pending placeholders for later phases. None is a pass.

Open items for the owner:

- The coverage gate in `scripts/run_tests.py` applies to `unit` alone, but unit tests cannot reach 80% of `services/` by themselves (migrations and the database layer need a real database). `unit` therefore exits non-zero on coverage although its tests pass. I did not change the gate. Options: enforce coverage only on `all`, or on `all` and `integration`.
- Unit tests of service internals (settings, log formatter, error body) do not exist yet; they were covered through the in-process API tests in `tests/integration/`.
- The De-sanitization boundary is proven at settings and source level and by running the process with no database setting. A test that it cannot connect to the database over the network is not written.
- Request-size limit and the 413 response are not built (phase 4). Update: built for the Sanitization Service in phase 4; the De-sanitization side is phase 7.
- The default uvicorn access log prints query strings. Services must be started with `--no-access-log`; a test checks that a real process then logs no query string, header or body.
- `gen_local_secrets.py` generates only the runtime database password. It grows with later phases.

### Phase 2A evidence (settings store)

Recorded 2026-11-17, Windows, Python 3.13.13, local PostgreSQL 18.6 (same owner-approved fallback as phase 2; the Testcontainers path has not run).

| Command | Result |
|---|---|
| `uv run scripts/run_tests.py all` (with the local database) | 177 passed, 0 failed, 56 skipped; coverage 93.82% (minimum 80%) |
| `uv run scripts/run_tests.py lint` | Ruff check and format check passed |
| `uv run pyright` | 0 errors, 0 warnings; no suppressions in `services`, `scripts` or `tests` |
| `uv run scripts/run_tests.py scan` | `pip-audit`: no known vulnerabilities. Bandit on `services`: no findings. Bandit on `scripts`: the two existing low findings in `run_tests.py`. |
| By hand on the `privyflow` database: `alembic upgrade head` (now `0002`), `scripts/settings.py validate`, `import --dry-run`, `import`, a repeated `import`, `show --backend db`, `export` | Version 1 imported once; the second import reported no change; the hash was identical for the file, the import and the export |
| By hand: service started with the file backend, the database backend, and `PRIVYFLOW_SETTINGS_BACKEND=xml` | File and database backends returned 200 on `/health/ready` and logged the same hash (versions 0 and 1); the invalid backend returned 503 and logged only an error category |

Skips are the same pending placeholders as before. None is a pass.

Decisions and limits to know about:

- Profile definitions stay as the versioned data files from phase 1 (SPEC 9.9). The store holds the tenant-to-profile map and the operational values, so "profiles" in Q8 is read as profile enablement.
- The internal client timeout from Q8 is not in this store. The De-sanitization Service owns it, and it has no store.
- `default_ttl_seconds` is limited to 60 to 3600. The 3600 ceiling is the D5 default and is my choice for "the allowed maximum"; the minimum of 60 is also mine.
- A failed settings load keeps the process alive but not ready, rather than exiting. Readiness does not recover until the service restarts.
- The settings tool needs a second database role. Existing local databases need `create_db_roles.py` and then `alembic upgrade head` to get it.
- Still open from phase 2: the coverage gate on `unit` alone. `unit` has 35 passed, 20 skipped, and fails only the coverage gate.
- Not verified: the settings CLI on macOS.
- Not built: the effective policy resolver (phase 3), live reload, an admin API, and per-request profile selection.

### Phase 3 evidence (detection and policy)

Recorded 2026-11-17, Windows, Python 3.13.13.

Database-backed tests did not run this session. Docker Desktop was not running and `PRIVYFLOW_TEST_DATABASE_URL` was not set in the shell, although the local PostgreSQL service (`postgresql-x64-18`) was up. I did not look for or guess a password. Every database test therefore failed with the Docker error instead of skipping, as designed. The Testcontainers path has still never run.

| Command | Result |
|---|---|
| `uv run scripts/run_tests.py unit` | 236 passed, 0 failed, 19 skipped; coverage 80.17% (minimum 80%). The gate passes only because phase 3 code is pure logic; it will fail again once database-heavy code lands, so the phase 2 open item stands. |
| `uv run scripts/run_tests.py evaluation` | 24 passed, 0 failed, 0 skipped. This suite was previously skipped for lack of a detector. |
| `uv run scripts/run_tests.py security` | 5 passed, 0 failed, 17 skipped |
| `uv run scripts/run_tests.py all` | 331 passed, 16 failed, 54 skipped, 45 errors; coverage 95.66%. All 16 failures and 45 errors are integration tests that need PostgreSQL (the Docker error `CreateFile ... cannot find the file specified`). None is in phase 3 code. |
| `uv run scripts/run_tests.py lint` | Ruff check and format check passed |
| `uv run pyright` | 0 errors, 0 warnings |
| `uv run scripts/run_tests.py scan` | `pip-audit`: no known vulnerabilities. Bandit on `services`: no findings. |
| Mutation spot checks (by hand, then reverted) | Longest-span rule removed, redact-beats-placeholder removed, profile TTL ignored, Luhn check removed: each made tests fail |

New tests: `tests/unit/test_recognizers.py`, `test_overlap.py`, `test_profiles.py`, `test_policy.py`, `test_span_planning.py` (Hypothesis properties for overlap and policy included); `tests/evaluation/test_detection_baseline.py` and `test_dataset.py` extended; `tests/integration/test_policy_startup.py`. In that last file, 3 of 5 tests need no database and passed; the 2 that need one (file-versus-database policy equality, and readiness 503 under strict coverage) did not run.

Detection baseline (`reports/detection_eval.json`, strict span match, 33 scored spans over 40 documents; recorded for the owner to approve thresholds, none are set):

| Type | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| EMAIL | 10 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| PHONE | 5 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| FINANCIAL | 3 | 0 | 1 | 1.000 | 0.750 | 0.857 |
| IN_PAN | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| IP_ADDRESS | 8 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| US_SSN | 4 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| Overall | 32 | 0 | 1 | 1.000 | 0.970 | 0.985 |

Negative documents: 9, with 0 containing a detection. Not covered, so reported and not scored: PERSON (17 spans), BUSINESS_CONFIDENTIAL (5), IN_AADHAAR (3), IN_IFSC (1).

Read this baseline with care. The same person wrote the recognizers and the dataset, and the dataset is small (40 documents), so perfect scores mostly show the recognizers handle the cases their author thought of. They are not a quality claim. The one miss is the IBAN example: D1 covers cards only, so the IBAN counts against FINANCIAL recall. Whether to add IBAN is an owner decision.

Dataset changes: added 8 positive and 3 negative documents (`ip-01` to `ip-04`, `ssn-01` to `ssn-03`, `card-adjacent-01`, `neg-07` to `neg-09`), and added IP_ADDRESS and US_SSN to the entity list and `thresholds.json` (still `null`). I also rewrote `neg-05`. It held `192.168.1.10` as a negative, which was correct before IP_ADDRESS existed and wrong now (and is outside the reserved test ranges). It now holds only a version string. Review this change.

Decisions and limits to know about:

- Detections are filtered to the types a tenant's policy names before overlaps are resolved, so an unlisted type cannot hide a listed one (SPEC 9.11).
- A dropped span counts toward every winner it overlaps, including a shorter winner chosen after it. This can raise a winner to `redact`; it never lowers one.
- The default `gdpr` profile applies to every tenant with no entry, so `strict_coverage: true` always fails today (gdpr names PERSON, ADDRESS and others with no recognizer). That is the intended honest behavior; it means the flag cannot be switched on until detection grows.
- A settings load error or a policy error both leave the service alive but not ready, with only an error category logged.
- Card detection can mask a number that is not a card (about 1 in 10 random 13 to 19 digit numbers pass Luhn), and misses cards split into groups under four digits.
- The IPv6 recognizer treats any standard-library-valid address as one, so a value such as `a::b` in prose or code is masked.
- Recognizers report no confidence. The "confidence" pending test stays pending.
- Not built: placeholder text and replacement (phase 4), the policy endpoint, and API-key tenant resolution (phase 5).

### Phase 4 evidence (placeholder sanitization)

Recorded 2026-11-17, Windows, Python 3.13.13.

Database-backed tests did not run again this session: Docker Desktop was not running and `PRIVYFLOW_TEST_DATABASE_URL` was not set. I did not look for or guess a database password. Their failures are the same 16 failures and 45 errors as in phase 3, all with the Docker error `CreateFile ... cannot find the file specified`. To check they are not caused by this phase, I stashed this phase's changes and ran `integration` on the phase 3 code: also 16 failed, 45 errors. The Testcontainers path has still never run, and the open phase 3 criterion (file versus database policy comparison) is still open.

| Command | Result |
|---|---|
| `uv run scripts/run_tests.py unit` | 350 passed, 0 failed, 17 skipped; coverage 82.75% (minimum 80%) |
| `uv run scripts/run_tests.py integration` | 86 passed, 16 failed, 8 skipped, 45 errors, 1 warning (the failures and errors are the database tests, above; the warning is a testcontainers deprecation notice that was already there); coverage gate met (84.37%) |
| `uv run scripts/run_tests.py security` | 5 passed, 0 failed, 17 skipped |
| `uv run scripts/run_tests.py evaluation` | 24 passed, 0 failed, 0 skipped (detection baseline unchanged) |
| `uv run scripts/run_tests.py all` | 465 passed, 16 failed, 52 skipped, 45 errors, 1 warning; coverage 96.05% (minimum 80%) |
| `uv run scripts/run_tests.py lint` | Ruff check and format check passed |
| `uv run pyright` | 0 errors, 0 warnings |
| `uv run scripts/run_tests.py scan` | `pip-audit`: no known vulnerabilities. Bandit on `services`: no findings. |
| Mutation spot checks (by hand, then reverted) | Collision skip removed (10 tests failed); repeated-value sharing removed (4); redacted value written into the mappings (4); size limit changed from `>` to `>=` (4); streaming byte count removed (1); Content-Length check removed (1). Each made tests fail. |

Skips went from 54 to 52 because two pending placeholders ("placeholder generation is collision resistant", "repeated values map to one placeholder within a request") were replaced by real tests. No test was deleted, skipped or weakened and no threshold changed.

New tests (134 in four files, all executed and passing): `tests/unit/test_placeholders.py` (68, including five Hypothesis properties at 300 examples each: round trip, redact markers left exactly, no collision with literal placeholder-like text, one placeholder per distinct type and value, and round trip through real detection), `tests/unit/test_sanitization_request_schema.py` (32), `tests/unit/test_size_limit.py` (14, the middleware against a stub ASGI app), `tests/integration/test_sanitization_limits.py` (20, the schema, size limit and sanitizer together through a test-only route; no database needed). `tests/support/placeholders.py` holds a test-only reference restorer.

Files changed: new `app/sanitization/placeholders.py`, `app/sanitization/sanitizer.py`, `app/schemas/sanitization.py`, `app/core/size_limit.py`; edited `app/core/errors.py` (413 code), `app/main.py` (middleware order), `app/settings/validator.py` (the 262144 default is now a named constant). No migration, no new dependency, no change to a public route.

Decisions and limits to know about:

- Placeholder rules are in `docs/SPEC.md` 9.12. Repeated values match on exact characters and entity type, so `A@example.com` and `a@example.com` get different placeholders. I chose exact matching because merging them would be a guess about what the caller considers the same value; say so if you want case-insensitive email matching.
- The criterion "200 or 422, and 413" is proven through a test-only route, not the public endpoint, because that endpoint and its authentication are phase 5. Phase 5 needs its own API tests for these cases; the pending "Sanitization API: invalid, oversized and unsupported-policy input fail safely" test stays pending.
- The size limit is measured on the raw request body in bytes, not on the `text` field. A body at the limit is accepted, so `text` can be somewhat shorter than the limit once the JSON around it is counted. SPEC 9.3 says "1 to the size limit" for the text; the body limit is the enforced one.
- The size limit has no rate limiting and no time limit on a slow body. Slow-body and rate protection are not in the pilot.
- A literal `[TYPE_REDACTED]` in the input stays as written and is never restored, so it is indistinguishable from a generated marker. Restoration never acts on markers, so this is harmless, but the text cannot tell you which markers the service wrote.
- The mappings are held in memory only in this phase. Nothing is stored, so the encrypted vault, the restore-reference and expiry are phase 5.
- Not built: the public sanitization endpoint, API-key authentication, the vault and the restorer.

### Phase 5 evidence (secure mapping vault and public sanitization endpoint)

Recorded 2026-11-17, Windows, Python 3.13.13, local PostgreSQL 18.6. This session the owner supplied the local database login in chat. It was passed as `PRIVYFLOW_TEST_DATABASE_URL` in the shell for the test commands only, and written to no file. Tests create and drop their own `pf_test_*` databases. The Testcontainers path has still never run (Docker was off).

| Command | Result |
|---|---|
| `uv run scripts/run_tests.py unit` | 471 passed, 0 failed, 10 skipped |
| `uv run scripts/run_tests.py security` | 14 passed, 0 failed, 12 skipped |
| `uv run scripts/run_tests.py evaluation` | 24 passed, 0 failed, 0 skipped |
| `uv run scripts/run_tests.py all` (with the database) | 750 passed, 0 failed, 37 skipped; coverage 96.60% (minimum 80%) |
| `uv run scripts/run_tests.py lint` | Ruff check and format check passed |
| `uv run pyright` | 0 errors, 0 warnings, no suppressions |
| `uv run scripts/run_tests.py scan` | `pip-audit`: no known vulnerabilities. Bandit on `services`: no findings. |
| Mutation spot checks (by hand, then reverted) | Associated data reduced to the key version; expiry filter removed from the repository; fixed nonce; tenant taken from a constant instead of the key; low-entropy reference. Each made tests fail. The last one first survived and exposed a weak entropy test, which was then strengthened. |

With the database available, the database tests from phases 2 to 4 ran and passed for the first time since phase 2, including the file-versus-database policy comparison (phase 3 criterion, now ticked) and the strict-coverage readiness test. Without a database the same run had 16 failures and 70 errors, all the Docker error.

Skips went from 52 to 37: 15 pending placeholders were replaced by real tests (7 unit, 5 security, 3 integration). Removing the two entries that depend on the database ("stored only as a digest", "encrypted at rest") rests on `test_mapping_repository.py`, which ran. No test was deleted, skipped or weakened, and no threshold changed.

New code: `app/vault/` (`credentials.py`, `crypto.py`, `config.py`, `vault.py`, `errors.py`), `app/repositories/mapping_repository.py`, `app/core/auth.py`, `app/api/sanitizations.py`; edited `app/main.py`, `app/api/health.py`, `app/core/config.py`, `app/core/errors.py`, `app/schemas/sanitization.py`. New dependency: `cryptography` (AES-256-GCM). No migration: the phase 2 table already had every column. `scripts/gen_local_secrets.py` now generates the API keys, encryption key and pepper, and has `--add-missing-secrets` for an existing `.env`.

New tests: `tests/unit/test_vault_crypto.py`, `test_vault_credentials.py`, `test_vault_config.py`, `test_vault.py`, `test_api_auth.py`, extended `test_gen_local_secrets.py`; `tests/integration/test_sanitization_api.py` (real app and real crypto over an in-memory store, no database) and `test_mapping_repository.py` (25, real PostgreSQL); `tests/security/test_sanitization_security.py`. Support: `tests/support/vault_env.py`, `vault_fakes.py`, `vault_api.py`.

Decisions and limits to know about:

- Action needed on the existing local setup: the Sanitization Service now needs four more secrets, or it stays alive but not ready. Run `uv run scripts/gen_local_secrets.py --add-missing-secrets` once to append them to `services/sanitization_service/.env`. I did not touch your `.env`. The generated API keys are in that file, one per tenant in `config/settings.example.json`.
- The endpoint reads and validates the body itself, after authentication, so a caller without a valid key gets 401 and not a schema error. A request over the size limit still gets 413 first, from the middleware.
- A body that names `tenant_id` or profiles is a 422 (SPEC 9.3), so the "tenant from the key even if the body names another" criterion is shown as rejection plus the stored row carrying the key's tenant.
- The `redact` criterion is shown through a stub policy table, because no shipped profile uses `redact`.
- `Vault.retrieve` is built and tested but has no route yet; the internal endpoint is phase 6. A found row that fails authentication raises `MappingIntegrityError`; phase 6 decides how to map it (it must not look different from a miss to the caller).
- Revocation and deletion exist as `Vault` functions only. The "admin tool entry point" from Q3 is not built.
- API keys are held in memory as configured and compared in constant time; they are not hashed. Pilot only (D2).
- Random 96-bit nonces are safe at pilot volume (limit about 2^32 rows per key). Key rotation tooling and re-encryption of old rows are not built.
- Not built: the internal retrieval endpoint (phase 6), the restorer (phase 7), rate limiting, and an audit store.
- Still open: the coverage gate on `unit` alone (phase 2), and the CLI check on macOS (phase 2A).

### Phase 6 evidence (internal mapping API)

Recorded 2026-11-17, Windows, Python 3.13.13. No PostgreSQL this session: Docker was off and `PRIVYFLOW_TEST_DATABASE_URL` was not set. I did not read a password from `services/sanitization_service/.env` for it, since the owner has to grant that. The internal API tests run the real app, authentication, vault and cryptography over the in-memory store used in phase 5, so none of them needs a database.

| Command | Result |
|---|---|
| `uv run pytest tests/integration/test_internal_api.py tests/security/test_internal_security.py` | 45 passed |
| `uv run scripts/run_tests.py unit` | 474 passed, 0 failed, 10 skipped; coverage 80% (minimum 80%) |
| `uv run scripts/run_tests.py security` | 21 passed, 0 failed, 12 skipped |
| `uv run pytest tests/integration` (no database) | 193 passed, 16 failed, 5 skipped, 70 errors. The 16 failures and 70 errors are the database tests (the same Docker error as phases 3 and 4); none is in phase 6 code. |
| `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` | Passed; 0 errors, 0 warnings |
| Mutation spot checks (by hand, then reverted) | Router authentication dependency removed (11 tests failed); integrity error re-raised instead of mapped to the 404 (3 failed). Each made tests fail. |

New code: `app/api/internal.py`, `app/schemas/internal.py`, `app/core/service_auth.py`; edited `app/main.py`, `app/core/config.py`, `app/api/sanitizations.py`. New secret: `PRIVYFLOW_SAN_SERVICE_SECRET`. New dev dependency: `jsonschema` (checks real responses against the saved contract). New runtime dependency: `httpx` moved to runtime (phase 7 needs it in the De-sanitization Service). No migration.

New tests: `tests/integration/test_internal_api.py`, `tests/security/test_internal_security.py`, support in `tests/support/contracts.py`, `routes.py`, and `vault_api.py`; the contract is `tests/fixtures/contracts/internal_mappings_retrieve_v1.json`. Three pending placeholders (two internal API integration entries and "internal API authentication") were replaced by the real tests above; none was deleted without a replacement, skipped or weakened.

Decisions and limits to know about:

- Action needed on the existing local setup: the Sanitization Service now needs `PRIVYFLOW_SAN_SERVICE_SECRET` or it stays alive but not ready. Run `uv run scripts/gen_local_secrets.py --add-missing-secrets`. It appends the secret to `services/sanitization_service/.env` and the matching secret and a separate client key list to `services/desanitization_service/.env`. I did not touch your files.
- Sanitization now refuses text with more than 10000 distinct sensitive values (413 `payload_too_large`) and stores nothing. SPEC 9.5 already said a response holds at most 10000 mappings; without this limit a stored reference could exist that the internal API could not return. This is a behavior change to the public endpoint, so please confirm the number.
- A stored row that fails authentication (tampered ciphertext, nonce, key version or an unknown key version) returns the same 404 as a miss and is logged by category only. That settles the open question from phase 5.
- A malformed `tenant_id` or `request_scope_id` is a 422, not a 404. Only the caller that holds the service secret can see that difference, and it reveals nothing about stored data.
- The service secret must differ from every client API key; the service is not ready otherwise.
- Pilot trust model unchanged: the shared secret (D3) and tenant assertion by the internal caller (D8) are not production grade.
- Not run: the internal API against PostgreSQL (the row-level tamper test is in phase 8).

### Phase 7 evidence (De-sanitization)

Recorded 2026-11-17, Windows, Python 3.13.13. No PostgreSQL this session (Docker off, `PRIVYFLOW_TEST_DATABASE_URL` not set, no password read from a `.env`). The Sanitization Service is stubbed at its HTTP boundary, so nothing in phase 7 needs a database.

| Command | Result |
|---|---|
| `uv run pytest tests/unit/test_restorer.py tests/unit/test_desan_auth_and_config.py tests/integration/test_desanitization_api.py tests/integration/test_internal_client.py tests/security/test_desanitization_security.py` | 125 passed |
| `uv run scripts/run_tests.py unit` | 536 passed, 0 failed, 4 skipped; coverage gate FAILED at 74% (minimum 80%), see below |
| `uv run scripts/run_tests.py security` | 29 passed, 0 failed, 9 skipped |
| `uv run scripts/run_tests.py evaluation` | 24 passed, 0 failed, 0 skipped |
| `uv run scripts/run_tests.py all` (no database) | 836 passed, 16 failed, 24 skipped, 70 errors, 1 warning; coverage 96.26% (minimum 80%). The 16 failures and 70 errors are the database tests (Docker error); none is in phase 6 or 7 code. |
| `uv run scripts/run_tests.py lint`, `uv run pyright` | Passed; 0 errors, 0 warnings |
| Mutation spot checks (by hand, then reverted) | Retry bound raised from 2 to 5 (3 tests failed); tenant replaced by a constant on the internal call (3); restored text scanned a second time (2); reference format check removed (1). Each made tests fail. |

The unit-only coverage gate (the open item from phase 2) is now at 74%, down from 80%, because the new De-sanitization endpoint and client are tested through the API in `tests/integration/`, as for the Sanitization Service, and unit tests cannot reach them. Coverage over `all` is 96.26%. I did not change the gate. The owner decision from phase 2 is still needed: enforce the gate on `all` only, or on `all` and `integration`.

New code in `services/desanitization_service/app/`: `api/desanitizations.py`, `clients/sanitization.py`, `restoration/restorer.py`, `schemas/desanitization.py`, `schemas/internal_api.py`, `core/auth.py`, `core/size_limit.py`; edited `main.py`, `api/health.py`, `core/config.py`, `core/errors.py`, `core/logging.py`. No database, no migration, no import from the Sanitization package. `httpx` moved to a runtime dependency.

New tests: `tests/unit/test_restorer.py` (33, with two Hypothesis properties), `test_desan_auth_and_config.py`; `tests/integration/test_desanitization_api.py` (35), `test_internal_client.py` (19); `tests/security/test_desanitization_security.py` (8). Support: `tests/support/sanitization_stub.py`, `desan_api.py`, `desan_env.py`. Ten pending placeholders were replaced by real tests (six unit, two security, two integration). Expired, revoked and cross-tenant restoration, the general log and error-body leakage sweep, tenant isolation, and the "invalid, expired and revoked" API entry stay pending for phase 8, because the stub only imitates the real lookup. Existing tests changed: the default De-sanitization test environment now holds the two new secrets, and the allowed log-key set in `test_service_foundations.py` gained the four audit fields. No test was deleted, skipped or weakened.

Decisions and limits to know about:

- Action needed on the existing local setup: the De-sanitization Service now needs `PRIVYFLOW_DESAN_API_KEYS` and `PRIVYFLOW_DESAN_SERVICE_SECRET`, or it stays alive but not ready. `uv run scripts/gen_local_secrets.py --add-missing-secrets` adds them, copying the service secret from the Sanitization `.env` so the two match. I did not touch your files.
- "Counted" in the phase 7 criterion: SPEC 9.6 counts only tokens that have the placeholder shape and are not in the mapping. Malformed look-alikes (`[email_001]`, `[EMAIL_01]`, `[EMAIL_001`) are left untouched but not counted, because counting every bracketed word would make the number meaningless. A repeated known placeholder is restored every time (needed for the round trip), so "duplicated" is tested as repeated unknown tokens and altered tokens such as `[EMAIL_001_001]`. Say so if you want a wider count.
- An exact placeholder inside other brackets (`[[EMAIL_001]]`) is restored, since the original text held those brackets. A `[TYPE_REDACTED]` marker is never touched.
- Audit: one log line per success with an opaque tenant reference (a SHA-256 prefix), counts and the correlation ID. The tenant reference is my choice; the plan only says audit metadata goes to redacted logs.
- Retries cover connection errors, connect timeouts and 503 only. A read timeout is not retried even though the call only reads; SPEC 9.6 says connection errors and 503. A 401 from the Sanitization Service (the two secrets differ) is reported to callers as 503, so a caller learns nothing about the misconfiguration; operators see the `UpstreamStatus401` category in the log.
- The client has no cap on the size of the Sanitization response. The response is bounded by 10000 mappings and the text that produced them, which Sanitization limits.
- The De-sanitization Service performs no rate limiting (not in the pilot) and no replay protection beyond reuse within the lifetime (D5).
- Not run: the two real services together, and any test against PostgreSQL (phase 8).

## 5. Validation checklist

- [ ] Inspect the repository and remove or archive obsolete extraction-service scaffolding only after review.
- [x] Confirm separate Sanitization and De-sanitization applications. (Phase 2: separate processes, ports, settings and env files.)
- [x] Confirm Sanitization Service owns the mapping database and migrations. (Phase 2: `mapping_records` migration lives in the Sanitization service.)
- [x] Confirm De-sanitization has no mapping database credentials. (Phase 2: no database setting, ignores one if supplied; tested.)
- [x] Define and approve public and internal API contracts. Pilot contracts: `docs/SPEC.md` section 9, approved 2026-11-17.
- [ ] Implement authentication and authorization boundaries.
- [x] Implement recognizer and policy baseline. (Phase 3: six recognizers, overlap rule D6, six profiles, restrictiveness rules; one database-backed test has not run.)
- [x] Implement placeholder generation and collision handling. (Pilot phase 4: `[TYPE_NNN]`, per-request consistency, collision skip, redact markers; property tests executed.)
- [x] Implement secure credential generation and hash lookup. (Pilot phase 5.)
- [x] Implement authenticated encryption and key-version metadata. (Pilot phase 5.)
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
