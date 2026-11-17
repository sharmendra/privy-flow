# PLAN_PILOT.md

Status: decisions D1 to D17 and questions Q1 to Q8 resolved on the recommended approach (owner instruction, 2026-11-17). Phase 1 (documentation) implemented 2026-11-17, with one criterion awaiting owner review. Phase 2 (service foundations) implemented 2026-11-17, with one criterion open (see below). Phase 2A (settings store) implemented 2026-11-17, with one criterion open (see below). Phase 3 (detection and policy) implemented 2026-11-17, with one criterion open (see below). Phase 4 (placeholder sanitization) implemented 2026-11-17, all criteria met (see the note under it). Phase 5 (secure mapping vault and public sanitization endpoint) implemented 2026-11-17, all criteria met (see "Phase 5 evidence" in `docs/STATUS.md`); the open phase 3 criterion was ticked in the same run. Phase 6 (internal mapping API) implemented 2026-11-17, all criteria met (see "Phase 6 evidence" in `docs/STATUS.md`). Phase 7 (De-sanitization) implemented 2026-11-17, all criteria met (see "Phase 7 evidence" in `docs/STATUS.md`). Phase 8 is not started.

## Objective

Build the thinnest working path through the whole engine, locally: a client sends text to the Sanitization Service, gets sanitized text and a restore-reference back, then sends both to the De-sanitization Service and gets the original text back. The pilot proves the architecture end to end (two services, encrypted vault, authenticated internal API, tenant isolation) before any breadth is added.

The pilot is a subset of phases 1 to 7 in `docs/PLAN.md`. It does not replace that roadmap.

Why a vertical slice: the highest risks are at the seams (service boundary, authorization, crypto, leakage), not in detection breadth. A narrow slice exposes them early, and each later entity type or policy then plugs into a path that already works.

## Scope

### Included

- Both FastAPI services as separate processes, run locally with `uv`.
- Sanitization of text for a small set of entity types (see decision D1).
- Compliance profiles (GDPR, India DPDP/SPDI, HIPAA, PCI DSS, GLBA, CCPA/CPRA) defined as versioned data, enabled per tenant by flags, with GDPR on by default and the most restrictive rule winning on conflict (see "Compliance profiles").
- One effective policy per tenant, resolved from its enabled profiles, plus the policy-listing endpoint.
- A settings store for the Sanitization Service with two interchangeable backends, a file (default) and the database, chosen by one startup setting. Profiles, tenant flags, and operational settings live there so they can change without code changes (see "Settings store").
- Placeholder generation with consistency for repeated values and collision avoidance.
- Encrypted mapping vault in PostgreSQL, owned by the Sanitization Service, with an Alembic migration.
- Restore-reference generation, digest-only storage, expiry, and revocation.
- Authenticated internal mapping-retrieval endpoint.
- Restoration in the De-sanitization Service with exact-placeholder replacement.
- Tenant and request-scope isolation on every path.
- Request size limits and outbound timeouts with bounded retries.
- Safe errors, correlation IDs, redacted logging, and leakage tests.
- Health and readiness endpoints for both services.

### Excluded

- Document ingestion, file handling, chunking, embeddings, vector databases, RAG, LLM calls (out of product scope).
- PERSON detection and Presidio/spaCy evaluation (see D1; follows as a separate plan).
- Rate limiting, Locust baselines, performance targets (post-pilot hardening).
- Key rotation procedure and KMS (the key-version field and a two-key keyring are tested; rotation tooling is not built).
- Production identity provider, TLS, deployment, cloud resources.
- A De-sanitization audit store (audit metadata goes to redacted structured logs only).
- Recognizers for every entity type the profiles name. Profiles declare what each regime requires; only types with a recognizer are enforced, and the rest are reported as not covered.
- Legal or compliance sign-off on the profile contents, an HTTP admin API for changing settings, live (no-restart) settings reload or backend switching, per-request profile selection, and ISO 27001 or SOC 2 as profiles (they define controls, not data categories).
- A settings database or settings store for the De-sanitization Service. It has no database; its operational settings stay in its own file and environment.
- One-time-use restoration (see D5).

## Service ownership

| Behavior | Owner |
|---|---|
| Detection, policy, placeholders, credential generation, hashing, encryption, vault, DB, migrations | Sanitization Service |
| Internal mapping retrieval endpoint (server side) | Sanitization Service |
| Caller authorization for restoration, internal client, placeholder substitution | De-sanitization Service |

The De-sanitization Service gets no database URL, no vault key, and no import of Sanitization code. Contracts are service-local and checked by a contract test at the HTTP boundary.

## Compliance profiles

A compliance profile is a versioned data file in the Sanitization Service that states what one regime asks PrivyFlow to protect. Profiles are data, not code, so adding or correcting one needs no change to detection or the API.

Each profile declares:
- `id` and `version`.
- `entities`: entity types the regime names, each with an action.
- `max_ttl`: the longest restore-reference lifetime the profile allows.

Initial profiles (my reading of each regime, to be reviewed by you and, before any real use, by legal or compliance staff):

| Profile id | Regime | Entity types it names |
|---|---|---|
| `gdpr` (default) | GDPR | PERSON, EMAIL, PHONE, ADDRESS, IP_ADDRESS, national IDs, location, online identifiers |
| `india_dpdp` | DPDP Act 2023, SPDI Rules, Aadhaar rules | PERSON, EMAIL, PHONE, ADDRESS, IN_AADHAAR, IN_PAN, IN_IFSC, FINANCIAL, SECRET |
| `hipaa` | HIPAA Safe Harbor | The 18 identifiers: PERSON, ADDRESS, DATE, PHONE, EMAIL, US_SSN, MEDICAL_RECORD_NUMBER, HEALTH_PLAN_NUMBER, ACCOUNT_NUMBER, IP_ADDRESS, URL, device and vehicle IDs |
| `pci_dss` | PCI DSS | FINANCIAL (card number), CARD_SECURITY_CODE |
| `glba` | GLBA, SOX | ACCOUNT_NUMBER, US_SSN, FINANCIAL, PERSON |
| `ccpa` | CCPA/CPRA | PERSON, EMAIL, PHONE, ADDRESS, IP_ADDRESS, US_SSN, location |

Flags:
- Enabled profiles are set per tenant in the Sanitization Service settings store (file by default, or database; see "Settings store"), as a map of tenant ID to profile IDs. The tenant is the one derived from the authenticated API key, and a request cannot change it.
- A tenant with no entry gets the default, `gdpr`.
- At least one profile must be enabled. Startup fails on an empty list, an unknown profile ID, or a tenant ID that is malformed.
- Per-request selection is not supported (decision D9).

Conflict rule: the more restrictive result always wins. Restrictiveness is defined once so it is testable:

| Setting | Resolution when several enabled profiles disagree |
|---|---|
| Entity types | Union: an entity is masked if any enabled profile names it. |
| Action per entity | `redact` (irreversible, no mapping stored) beats `placeholder` (reversible). A type no profile names is not masked. |
| Restore-reference lifetime | The smallest `max_ttl` among enabled profiles, and never longer than the default TTL (D5). |
| Overlapping spans | D6 picks the winning span; it then takes the most restrictive action among the spans it overlapped. |

Two properties follow and are tested: enabling an additional profile never unmasks an entity and never lengthens a lifetime, and the result does not depend on the order profiles are listed.

Coverage honesty: profiles name more entity types than the pilot can detect (D1). The recognizer registry records which types are implemented. The policy listing and each sanitization response include the entity types of the enabled profiles that are not covered, so a tenant that enables `hipaa` can see that it is only partly enforced. An optional strict flag, off by default in the pilot, makes startup fail instead (decision D11). No response or document claims that an enabled profile makes a tenant compliant.

## Settings store

Goal: anything an operator may want to change later is a setting, not code. The settings live in one place per deployment, and that place is either a file or the database, selected when the service starts. The default is the file.

What goes where:

| Kind | Examples | Where it lives |
|---|---|---|
| Bootstrap | Which backend to use (`PRIVYFLOW_SETTINGS_BACKEND=file` or `db`), the settings file path, the database URL, encryption keys, pepper, service secret, API keys | Environment variables only. Never in the settings file or the settings database. |
| Operational | Compliance profile definitions, tenant-to-profile flags, default TTL, request size limit, strict-coverage flag, internal client timeout | The settings store (file or database) |

Secrets stay in the environment. This keeps the rule that keys live outside the database holding ciphertext, and it means a copied settings file or database dump exposes configuration but no keys. A settings file or row that contains a recognizable secret field is rejected on load.

Design:
- One `SettingsStore` interface with two implementations, `FileSettingsStore` and `DbSettingsStore`. The rest of the service only sees the interface. Both feed the same validator, so the same rules apply regardless of backend.
- Settings are loaded into one validated, immutable snapshot with a version number and content hash. Each request uses the snapshot current when it began. Sanitization records the applied profile IDs, profile versions, and snapshot version in the mapping record.
- The file backend reads a single JSON file (default `config/settings.json`, example committed as `config/settings.example.json` with synthetic values). JSON avoids a new parser dependency and works the same on Windows and macOS.
- The database backend uses tables in the Sanitization database (see Data model): `settings_snapshots` (append-only, versioned) and `settings_audit`. The service's runtime database role can read these tables but not write them. Changes are made with a separate admin role through the command line tool below.
- Selection and switching: set `PRIVYFLOW_SETTINGS_BACKEND` and restart the service. No setting is read from the other backend afterward. A command line tool, `uv run scripts/settings.py`, supports `validate`, `show`, `export` (database to file), and `import` (file to database), so switching backends does not mean retyping settings. The tool prints a diff before an import and refuses invalid input.
- Failure behavior: the service never silently falls back from one backend to the other. If the file is missing or invalid, or the database backend is selected and unreachable, startup fails and `/health/ready` reports 503. A silent fallback could apply weaker protection than the owner configured.
- Changes: loaded at startup. Live reload is not in the pilot (decision D15); a change takes effect on restart.
- Audit: every import or change through the tool writes who, when, the version, and the content hash, but never secret values. For the file backend the audit is a log line plus the file hash at startup.

The same loader and validator rules apply to both backends. Invalid settings of any kind (unknown profile ID, empty enabled list for a tenant, TTL above the allowed maximum, size limit below a floor, unknown keys) fail loading with a safe message that names the field, not any value.

## Decisions needed from the owner

AGENTS.md requires options and a recommendation for decisions touching authorization, cryptography, and service boundaries. The owner has approved the recommended option for every decision below. Phase 1 records them in an ADR.

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Entity types in the pilot | (a) Regex and checksum recognizers only: EMAIL, PHONE, FINANCIAL (card with Luhn), IN_PAN, IP_ADDRESS, US_SSN. (b) Add PERSON via spaCy/Presidio. | (a), approved with IP_ADDRESS and US_SSN added. It needs no model download, is deterministic, and keeps tests free of real models. PERSON follows in a detection plan with a proper evaluation. |
| D2 | Public caller auth and tenant identity | (a) Per-tenant API keys from local config; tenant derived from the key, never from the body. (b) JWT with a local test issuer. | (a). It is the simplest way to meet "never trust a client-supplied tenant ID". Marked non-production. A real IdP is a later gate. |
| D3 | Service-to-service auth | (a) Dedicated shared secret in a header, compared in constant time, separate from client keys. (b) mTLS. (c) Signed short-lived JWT. | (a) for the pilot, marked non-production. mTLS or signed tokens are required before multi-user exposure. |
| D4 | Encryption key source | (a) Base64 AES-256 key in an environment variable, keyring keyed by version, generated locally and never committed. (b) File-based key. | (a). The key lives in the Sanitization Service environment only, never in the DB. Marked non-production. |
| D5 | Restore-reference lifetime and reuse | Default TTL; reusable within TTL or one-time. | 1 hour TTL, configurable; reusable within TTL; revocation supported. One-time use is deferred, and the choice is recorded in the ADR. |
| D6 | Overlapping and ambiguous spans | Longest span wins, earliest wins, or priority by type. | Longest span wins; ties broken by entity-type priority, then earliest start. Shorter nested spans are dropped. |
| D7 | Non-disclosure error behavior | 404 vs 403 for scope mismatch. | A single non-disclosing response (404 `restore_reference_not_found`) for unknown, expired, revoked, and cross-tenant or cross-scope references. |
| D8 | Who asserts the tenant on the internal call | The De-sanitization Service passes the tenant it authenticated; Sanitization trusts the authenticated internal caller to assert it. | Yes. The mapping lookup still requires the credential hash, tenant, and request scope to all match. Recorded as a pilot trust assumption in the threat model. |
| D9 | Who selects compliance profiles | Per tenant in config; global; per request. | Per tenant in config (approved). No per-request selection, so a caller cannot switch protections off. |
| D10 | Default profile | Which profile applies when a tenant has no entry. | `gdpr` (approved). |
| D11 | Profile entity types the pilot cannot detect | Warn and report as not covered; or fail startup. | Report as not covered, with a strict flag (default off) that fails startup. Failing by default would make most profiles unusable in the pilot. |
| D12 | `redact` action | Support irreversible redaction (no mapping stored) in addition to reversible placeholders. | Yes. It is needed for data a regime says must never be retained, such as the card security code. Restoration leaves redacted markers untouched. |
| D13 | Profile contents | Mine, reviewed by the owner. | Phase 1 produces the profile files and the entity-type list for your review. They are marked as unreviewed by legal. |
| D14 | Settings backend | File, database, or both selectable. | Both, selectable by one startup setting; file is the default (approved). Secrets never go in either. |
| D15 | When the backend can be chosen or changed | At startup with restart; or live while running. | Startup with restart. Live switching or reload would let protection settings change mid-flight, needs a trusted admin path that does not exist yet, and is awkward on Windows (no signal-based reload). Confirm in Q7. |
| D16 | Who can change settings in the database backend | The service itself through an admin API; or a separate command line tool with its own database role. | Command line tool with a separate admin role. The service's runtime role is read-only on settings. This avoids building an admin API and its authorization model in the pilot. |
| D17 | Backend failure behavior | Fall back to the other backend; or fail startup. | Fail startup and report not ready. No silent fallback. |

## API contract (proposal)

Route names follow `docs/SPEC.md` section 9. Schemas below are proposals and are recorded in `docs/SPEC.md` in phase 1 before any code depends on them.

Sanitization, public (`X-API-Key` header, tenant derived from key):

- `POST /api/v1/sanitizations`
  - Request: `{ "text": str, "request_scope_id": str, "policy_id": str }`. `policy_id` must be `effective`, the tenant's resolved policy; any other value is rejected as an unsupported policy.
  - Response 200: `{ "sanitized_text": str, "restore_reference": str | null, "expires_at": datetime | null, "profiles_applied": [str], "uncovered_entity_types": [str], "entity_count": int, "correlation_id": str }`. `restore_reference` and `expires_at` are null when every detected entity was redacted and nothing was stored.
  - Errors: 400/422 validation, 401 bad key, 413 too large, 503 database unavailable.
- `GET /api/v1/policies`: the calling tenant's effective policy: `{ "policy_id": "effective", "profiles": [ { "id", "version" } ], "entity_types": [ { "type", "action" } ], "max_ttl_seconds": int, "uncovered_entity_types": [str] }`. It reveals only the caller's own tenant configuration.
- `POST /api/v1/restore-references/{id}/revoke` is deferred; revocation in the pilot is exercised through the repository layer and a documented admin function so the expiry and revocation tests have a real code path. Whether to expose a public revoke endpoint is an open question (Q3).

Sanitization, internal (service secret header):

- `POST /internal/v1/mappings/retrieve`
  - Request: `{ "restore_reference": str, "tenant_id": str, "request_scope_id": str }`
  - Response 200: `{ "mappings": [ { "placeholder": str, "value": str } ], "policy_id": str }`
  - Errors: 401 bad service secret, 404 non-disclosing not-found, 503 database unavailable.

De-sanitization, public (`X-API-Key` header, own key list, tenant derived from key):

- `POST /api/v1/desanitizations`
  - Request: `{ "sanitized_text": str, "restore_reference": str, "request_scope_id": str }`
  - Response 200: `{ "restored_text": str, "restored_count": int, "unmatched_placeholder_count": int, "correlation_id": str }`
  - Errors: 401, 404 non-disclosing, 413, 422, 503 (Sanitization unavailable or timed out).

Both services: `GET /health/live`, `GET /health/ready`. Standard error body: `{ "error": { "code": str, "message": str, "correlation_id": str } }`. `X-Correlation-ID` is accepted if it matches a strict safe pattern, otherwise generated, and returned on every response.

Idempotency and retries: sanitization is not idempotent (each call creates a new mapping and reference); clients must not blindly retry after a timeout. Restoration is safe to retry (read-only, reusable within TTL). The internal client retries only connection errors and 503, at most twice, with a short timeout.

## Data model

Table `mapping_records` in the Sanitization database (single Alembic revision for the pilot):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID primary key | Internal only, never returned |
| `tenant_id` | text, not null | Indexed |
| `request_scope_id` | text, not null | |
| `credential_digest` | bytea, unique, not null | HMAC-SHA-256 of the reference with a server-side pepper (the pepper is a second secret in Sanitization config, never in the DB) |
| `ciphertext` | bytea, not null | AES-256-GCM output |
| `nonce` | bytea, not null | 96-bit, unique per encryption |
| `encryption_alg` | text, not null | `AES-256-GCM` |
| `key_version` | int, not null | |
| `profiles` | jsonb, not null | Applied profile IDs and versions at sanitization time, so the record shows which rules were in force |
| `created_at`, `expires_at` | timestamptz, not null | UTC; check `expires_at > created_at` |
| `revoked_at` | timestamptz, null | |
| `deleted_at` | timestamptz, null | Soft-delete marker for retention |

The authenticated-encryption associated data binds `id`, `tenant_id`, `request_scope_id`, and `key_version`, so a ciphertext moved to another row or tenant fails to decrypt. The plaintext payload is the placeholder-to-value map only; raw request text is never stored. Lookup is by `credential_digest` plus tenant and scope, using the unique index. The restore-reference is 32 bytes from `secrets` (256 bits), URL-safe encoded, with a short version prefix.

Settings tables, added in a second Alembic revision and used only when `PRIVYFLOW_SETTINGS_BACKEND=db`:

| Table | Columns | Notes |
|---|---|---|
| `settings_snapshots` | `version` (int, primary key), `content` (jsonb), `content_hash` (text), `created_at` (timestamptz), `created_by` (text) | Append-only. The service loads the highest version. Content is validated before insert and never contains secrets. |
| `settings_audit` | `id`, `version`, `action` (import, export, activate), `actor` (text), `content_hash`, `created_at` | Safe metadata only. Kept separate from the mapping tables. |

The runtime database role has `SELECT` on both settings tables and no write access to them. The admin role used by `scripts/settings.py` writes them and has no access to `mapping_records`. Each mapping record's `profiles` column also stores the snapshot version, so a record shows exactly which settings were in force.

The De-sanitization Service has no tables.

## Security and privacy considerations

- Tenant comes from the authenticated key, never the request body, on both public APIs.
- Redacted values are never written to the vault, so they cannot be restored or recovered from a database copy.
- Profile files and tenant flags are configuration, not secrets, but they reveal a tenant's protection settings, so the policy endpoint only returns the caller's own.
- Settings are a control point: relaxing a profile or raising a TTL reduces protection. Writes go only through the command line tool with a separate admin role, are audited, and take effect on restart. The service's runtime role cannot change them. Whoever can write settings can weaken protection, so that access is listed in the threat model.
- Settings never hold keys, pepper, service secret, or API keys; the loader rejects them. A test checks that settings content and audit rows contain none of the canary secrets.
- No silent fallback between backends (D17).
- Possession of a restore-reference alone does not authorize restoration: the De-sanitization caller must have a valid API key for the same tenant, and the scope must match.
- All failure modes for a bad reference return the same non-disclosing response in the same shape (D7).
- Secrets compared with `hmac.compare_digest`. Keys, pepper, and service secret come from environment variables; `.env.example` holds placeholders only, and local values are generated by a script that works on Windows and macOS.
- Logging: structured logs with an allowlist of fields (service, version, correlation ID, operation, status, latency, error category, entity count). No request or response bodies, no headers, no exception message passthrough. Uvicorn access logs are checked for query-string or body capture.
- Restoration is single-pass, left to right, so a restored value that looks like a placeholder is never re-substituted.
- Output-size limit on restoration, input-size limit on both services, outbound timeout on the internal client.
- Threat model documented in phase 1: attackers considered are a cross-tenant client, a credential guesser, a holder of a leaked reference, a tampering database writer, and a log reader.
- Residual risks stated honestly: detection is not complete; the pilot trust model for tenant assertion (D8), the shared service secret (D3), and the env-var key (D4) are not production-grade.

## Implementation steps

Phases build on each other. Each phase follows the project loop: define behavior, write tests first, implement, run, review, tick criteria, update `docs/STATUS.md`, commit. Pending tests in the existing `*_pending.py` files are replaced by real tests as features land; none are deleted to get green.

### Phase 1. Decisions, contracts, and threat model (documentation only)

What it builds: the written agreement that the code is then held to. Why first: AGENTS.md forbids silent decisions on auth, crypto, and contracts, and the later phases depend on these.

- ADR for D1 to D8.
- Update `docs/SPEC.md` section 9 with final schemas and error codes.
- Threat model and trust assumptions document.
- Update `docs/STATUS.md` decision register and open decisions.

Success criteria:
- [x] The ADR records D1 to D17 as approved by the owner (2026-11-17, recommended options) and lists any later change. (`docs/adr/0001-pilot-decisions.md`)
- [x] `docs/SPEC.md` contains the final request, response, and error schemas for all five endpoints. (section 9)
- [x] Threat model document exists and lists each attacker above with its mitigation and the test that proves it. (`docs/THREAT_MODEL.md`; the tests are named and pending until their phases)
- [ ] The six profile files and the shared entity-type list exist and the owner has reviewed them. Each is marked as not reviewed by legal. (Files exist in `services/sanitization_service/app/sanitization/profiles/data/` and are marked; owner review is still outstanding, so this stays unticked. Review points are listed in `docs/STATUS.md`.)
- [x] The restrictiveness rules are written down in `docs/SPEC.md` exactly as in "Compliance profiles". (section 9.9)
- [x] `uv run scripts/run_tests.py all` still passes with the same counts as the baseline in `docs/STATUS.md` (no code or test changes in this phase). (2026-11-17: 21 passed, 0 failed, 63 skipped)

### Phase 2. Service foundations

What it builds: two runnable apps with configuration, health, correlation IDs, redacted logging, the standard error body, the Sanitization database setup, and the first migration. Why: every later phase needs a running skeleton and a trustworthy test seam.

- `services/sanitization_service/app` and `services/desanitization_service/app` per the target layout, each with its own settings class and `.env.example` section.
- Alembic setup and the `mapping_records` revision in the Sanitization service.
- Script to generate local-only secrets (cross-platform).
- `pyproject.toml` additions with a one-line justification for each dependency.

Success criteria:
- [ ] `uv run scripts/run_tests.py unit` and `integration` pass with the health tests for both services now running (not skipped). (Open: `integration` passes, 44 passed, and the health tests run. `unit` has 10 passed but exits non-zero because the 80% coverage gate applies to `unit` alone and unit tests cannot cover `services/` by themselves. Awaiting owner decision; the gate was not changed.)
- [x] Both services start as separate processes on different ports; `GET /health/live` returns 200 on each. (`tests/integration/test_process_startup.py`; also run by hand on ports 8001 and 8002.)
- [x] `/health/ready` returns 200 with the database up and 503 with it down for the Sanitization Service; the De-sanitization Service reports readiness based on config only and does not report on the vault database. (`tests/integration/test_service_health.py`, including recovery after the database returns.)
- [x] Migration test passes from an empty PostgreSQL database via Testcontainers, and `alembic downgrade base` then `upgrade head` round-trips. (Run against local PostgreSQL 18.6 under the owner-approved fallback because Docker was not running; the Testcontainers path has not run. Also checks the migration matches the ORM model and the runtime role's least privilege.)
- [x] A test proves the De-sanitization settings contain no database URL and its environment loading fails or ignores a Sanitization database URL if one is supplied. (`tests/security/test_database_boundary.py`: settings fields, environment and env file ignored, no database or Sanitization imports in the source.)
- [x] Log-redaction baseline test passes: a canary in a request body and header never appears in captured logs. (Also query string; a real-process test checks the uvicorn output.)
- [x] Error-shape test passes: unhandled exceptions return the standard 500 body with no trace or SQL.
- [x] Docker daemon status is checked first. If it is not running, this phase stops and reports it rather than skipping the database tests (see Risks). (Docker was not running; reported; the owner approved the local PostgreSQL fallback on 2026-11-17. Database tests fail, never skip, when no database is available.)

### Phase 2A. Settings store

What it builds: the `SettingsStore` interface, the settings validator and immutable snapshot, the file backend (default), the database backend with its migration revision, the backend selector, and the `scripts/settings.py` tool. Why here: the compliance profiles and every later configurable value read from it, so it must exist before phase 3. Phase 2A is numbered this way to keep the existing phase numbers stable.

Success criteria:
- [x] With no backend setting, the service starts with the file backend and logs which backend and settings version it loaded (version and hash only). (`test_settings_startup.py`)
- [x] `PRIVYFLOW_SETTINGS_BACKEND=db` starts the service with the database backend after `scripts/settings.py import` loads the same settings file; an invalid value for the backend setting fails startup. (Interpretation: "fails startup" means the process stays alive but not ready, `/health/live` 200 and `/health/ready` 503, consistent with D17. Also run by hand against the `privyflow` database.)
- [x] One contract test suite runs against both backends (parametrized) and gets identical snapshots for identical content. (Content and hash are identical; `version` differs by design, 0 for the file backend.)
- [x] Validation tests pass for both backends: unknown keys, unknown profile ID, empty tenant profile list, TTL above the allowed maximum, size limit below the floor, and a field named like a secret each fail loading with a message that names the field and no value. (14 cases per backend, plus unit tests of the validator.)
- [x] Missing or invalid file, or unreachable database with the db backend selected, fails startup and `/health/ready` returns 503; the service does not use the other backend (D17). (Tests put valid settings in the other backend and show they are not used.)
- [x] Switching works both ways: `export` then `import` round-trips to an identical snapshot hash, and restarting with the other backend yields the same effective policy for a test tenant. (The effective policy resolver is phase 3, so the test compares the tenant's enabled profiles and the snapshot hash.)
- [x] The migration revision for the settings tables applies from an empty database and round-trips downgrade and upgrade. (`test_settings_roles.py`; the schema also matches the ORM models.)
- [x] A database test proves the runtime role cannot insert or update settings tables, and the admin role cannot read `mapping_records`. (The runtime role also cannot delete or truncate; the admin role can append but not update or delete.)
- [x] `settings_audit` receives a row for each import with actor, version, and hash, and a canary secret never appears in it. (`test_settings_audit.py`; an unchanged import writes nothing.)
- [x] A change in the settings file is not applied until restart (documented behavior, tested).
- [ ] `scripts/settings.py` runs on Windows and macOS through `uv run`, with `validate`, `show`, `export`, and `import`; `import` prints a diff and writes nothing if validation fails. (Open: verified on Windows only, by tests and by hand. macOS has not been run.)

### Phase 3. Detection and policy

What it builds: a `Recognizer` interface, the pilot recognizers (D1), the overlap resolver (D6), the compliance profile loader, the per-tenant flags (both read through the settings store from phase 2A, so they work with either backend), and the resolver that merges enabled profiles into one effective policy. Why: detection must sit behind an interface so engines can change later without touching the API. Starting with deterministic recognizers keeps the pilot testable without models.

Success criteria:
- [x] Unit tests pass for each of the six pilot recognizers (EMAIL, PHONE, FINANCIAL, IN_PAN, IP_ADDRESS, US_SSN), including Luhn validation for cards, invalid IPv4 octets and valid IPv6 forms for IP_ADDRESS, rejection of impossible SSN ranges, and negative examples from the dataset. (`tests/unit/test_recognizers.py`, 120 cases. Dataset negatives are checked by `tests/evaluation/test_detection_baseline.py`.)
- [x] New synthetic IP_ADDRESS and US_SSN examples, with positive and negative cases, are added to `tests/fixtures/eval/detection_dataset.jsonl`. SSN-format values use ranges reviewed in phase 1 so none can be a real person's number, and the dataset integrity tests still pass. (8 positive and 3 negative documents added; also rewrote `neg-05`, which held a private IP as a negative. Owner review of that change is requested in `docs/STATUS.md`.)
- [x] Overlap, adjacency, and nested-span tests pass for the documented D6 rule. (`tests/unit/test_overlap.py`, including Hypothesis properties.)
- [x] The detection evaluation runs against `tests/fixtures/eval/detection_dataset.jsonl` for the pilot entity types and writes `reports/detection_eval.json`. (`tests/evaluation/test_detection_baseline.py`; report is git-ignored under `reports/`.)
- [x] Per-type and overall precision, recall, and F1 for the pilot types are recorded in `docs/STATUS.md` as a baseline. `thresholds.json` stays `null` until the owner approves minimums. (Recorded in `docs/STATUS.md`, phase 3 evidence. Thresholds still `null`.)
- [x] Dataset types outside the pilot (PERSON, Aadhaar, IFSC, business terms) are reported as not covered, not as failures or passes. (Counted under `not_covered` in the report and skipped by threshold checks.)
- [x] Profile loading tests pass: all six profiles load; an unknown profile ID, an empty enabled list, and a malformed tenant ID each fail startup with a safe message. (`test_profiles.py`, `test_policy.py`, and the database-free tests in `test_policy_startup.py`.)
- [x] The same tenant flags give the same effective policy whether loaded from the file backend or the database backend. (Ticked in phase 5: `test_the_same_flags_give_the_same_effective_policy_from_file_and_database` ran and passed against local PostgreSQL.)
- [x] A tenant with no flag entry resolves to `gdpr` only; a tenant with several profiles resolves to the union of their entity types. (`test_policy.py`.)
- [x] Conflict tests pass for every rule in the restrictiveness table, using synthetic test profiles that disagree on action and lifetime. (`test_policy.py`, one test per rule.)
- [x] Hypothesis properties pass: adding a profile never removes an entity from the masked set or lengthens the lifetime, and listing order does not change the result. (`test_policy.py`.)
- [x] Uncovered entity types are reported for each profile, and the strict flag fails startup when it is on. (Unit tests. The readiness 503 check under strict coverage is in `test_policy_startup.py` and has not run: it needs PostgreSQL. Strict coverage currently always fails because the default `gdpr` profile names types with no recognizer.)

### Phase 4. Placeholder sanitization

What it builds: placeholder generation (`[EMAIL_001]` style), per-request consistency for repeated values, collision avoidance with literal placeholder-like input, and span replacement that preserves surrounding text. Why: this is the reversible-transform core and it is pure logic, so it can be proven with property tests before touching the vault.

Collision rule: counters skip any index whose placeholder appears literally in the input.

Success criteria:
- [x] Hypothesis property test passes: replacing spans and then restoring in memory returns the original text exactly. (`tests/unit/test_placeholders.py`, 300 examples per property. Restoration here is a test-only reference in `tests/support/placeholders.py`; the real restorer is phase 7. A second property covers `redact`: restoring leaves exactly the redact markers.)
- [x] Property test passes: no generated placeholder equals any placeholder-like substring already in the input. (`test_property_no_generated_placeholder_equals_placeholder_like_text_in_the_input`, with inputs that contain literal `[EMAIL_001]`, `[EMAIL_1000]`, `[EMAIL_0001]` and lowercase look-alikes, plus fixed examples.)
- [x] Repeated identical values share one placeholder within a request; the same value in two requests is not linked. (Fixed examples and a property of one placeholder per distinct type and value. "Not linked" is tested as: numbering restarts for each request and a result never depends on earlier calls.)
- [x] Text outside spans is byte-identical, including non-ASCII text and line endings. (13 parametrized gaps compared as UTF-8 bytes: CRLF, CR, LF then CR, doubled CRLF, accented and CJK text, an astral emoji, combining and zero-width characters, NUL and control characters.)
- [x] Empty input, whitespace-only input, and input at and above the size limit behave as documented (200 or 422, and 413). (Empty text is 422, whitespace-only text is 200 and unchanged, a body of exactly the limit is 200, one byte over is 413, including chunked bodies and a lying Content-Length. These run through a test-only route that uses the real request schema, size-limit middleware and sanitizer, because the public endpoint is phase 5. The endpoint inherits the behavior; its own tests are a phase 5 criterion.)

What phase 4 added beyond the placeholder logic, because the last criterion needs it: the request schema (`app/schemas/sanitization.py`) and the request size limit middleware (`app/core/size_limit.py`), which phase 2 left unbuilt. The 413 error code and the empty-text rule are in `docs/SPEC.md` 9.2, 9.3 and 9.12.

### Phase 5. Secure mapping vault

What it builds: credential generation, HMAC digest lookup, AES-256-GCM encryption with bound associated data, the keyring with version handling, the repository with tenant-and-scope-scoped lookup, expiry, revocation, and deletion marking, and the public `POST /api/v1/sanitizations` endpoint with API-key auth. Why: this is the crypto and data-protection core. It uses the `cryptography` package only; no custom primitives.

Success criteria:
- [x] Unit tests pass: round trip, unique nonce across 10,000 encryptions, ciphertext differs from plaintext, tampered ciphertext, nonce, key version, and associated data are each rejected. (`tests/unit/test_vault_crypto.py`, 10,000 nonces, every tamper case.)
- [x] A sample of 100,000 generated references has no duplicates and each carries at least 128 bits of entropy (per `docs/SPEC.md` section 12). (`tests/unit/test_vault_credentials.py`.)
- [x] A database test inspects every column of stored rows and finds no plaintext reference or mapping value (canary check), and every row has an algorithm and key version. (`tests/integration/test_mapping_repository.py`, run against local PostgreSQL 18.)
- [x] A row written under key version 1 still decrypts after the keyring gains version 2; an unknown key version fails safely. (unit with an in-memory store, and against PostgreSQL.)
- [x] Expired, revoked, and deleted records are not returned by the repository; time is controlled with an injected clock, no sleeps. (fake clock; unit and PostgreSQL.)
- [x] Sanitization API tests pass: valid request, bad key (401), invalid and oversized input, unsupported policy, and the tenant being taken from the key even if the body names a different tenant. (`tests/integration/test_sanitization_api.py`; a body naming a tenant is a 422, as SPEC 9.3 says, and the row's tenant is the key's.)
- [x] `GET /api/v1/policies` returns the calling tenant's effective policy, profiles, and uncovered types, and never another tenant's.
- [x] Two tenants with different enabled profiles get different masking for the same input in the same test run. (`gdpr` against `gdpr` plus `hipaa` on an SSN.)
- [x] The stored expiry equals the smallest `max_ttl` of the tenant's profiles; it is never longer than the default TTL.
- [x] A synthetic `redact` rule masks the value, stores nothing for it, returns a null reference when nothing else was stored, and restoration leaves the marker untouched. (through a stub policy resolver; the reference test restorer leaves the marker.)
- [x] A request with a `policy_id` other than `effective`, or a body field naming profiles, is rejected.
- [x] Coverage for vault and crypto modules is at least 90% line coverage, branch coverage reviewed. (100% line and branch on `app/vault/*` and the repository; `app/api/sanitizations.py` 93%.)

### Phase 6. Internal mapping API

What it builds: `POST /internal/v1/mappings/retrieve` with service-secret authentication, scope checks, non-disclosing errors, and a bounded response. Why: this is the only door between the two services, so it is built and tested alone before the client side exists.

Success criteria:
- [x] Requests without the service secret, or with a client API key instead, get 401. (`tests/integration/test_internal_api.py`, six header variants.)
- [x] Wrong tenant, wrong request scope, unknown, expired, and revoked references all return the identical 404 body and comparable status and shape. (Also deleted, malformed and tampered; one test compares status, headers and body across all eight causes.)
- [x] The response contains only placeholders, values, and policy ID; a test fails if extra fields appear. (Exact key sets, and the response model forbids extras.)
- [x] Decrypted values never appear in captured logs or error bodies (canary test). (`tests/security/test_internal_security.py`.)
- [x] The internal contract is saved as a schema file in the Sanitization service tests, and a compatibility test checks it. (`tests/fixtures/contracts/internal_mappings_retrieve_v1.json`; real responses are validated against it with `jsonschema`.)
- [x] The public sanitization API key cannot call any `/internal` route, and the service secret cannot call any `/api/v1` route. (Tests enumerate the app's routes, so a new route is covered automatically.)

### Phase 7. De-sanitization

What it builds: API-key authentication and tenant derivation, the internal HTTP client (timeout, bounded retry, safe error mapping), and single-pass exact-placeholder restoration. Why: it completes the loop. The tests stub the Sanitization Service at its HTTP boundary and a separate contract test checks the real schema, as `docs/CODE_STANDARDS.md` requires.

Success criteria:
- [x] Authorized restoration succeeds against the stubbed internal API. (`tests/integration/test_desanitization_api.py`; the stub is an `httpx.MockTransport` under the real client.)
- [x] A valid restore-reference with no API key, or with a key for another tenant, is rejected (reference alone never authorizes). (Seven credential variants get 401 with zero calls to the stub; a key for another tenant gets the non-disclosing 404.)
- [x] Unknown, altered, duplicated, and malformed placeholders are left untouched and counted, in 100% of the parametrized cases. (20 parametrized cases in `tests/unit/test_restorer.py`, all pass. "Counted" follows SPEC 9.6: unknown, altered and repeated-unknown tokens are counted; malformed look-alikes that do not have the placeholder shape are left untouched and not counted, and a repeated known placeholder is restored each time. See "Phase 7 evidence".)
- [x] Property test passes: restoring in-memory mappings reproduces the original text, and restored values containing placeholder-like text are not re-substituted. (Hypothesis, 300 examples, values and literals that include placeholder-like text; plus fixed examples.)
- [x] Sanitization outage, timeout, and 503 produce a 503 with correlation ID and no sensitive content; retries are bounded (assert call count). (Ten failure modes; 3 attempts for connection errors and 503, 1 for the rest, counted by the stub.)
- [x] A contract test runs the stub's responses through the real internal API schema. (The stub's answers and the client's requests are validated against the saved contract file; the Sanitization side validates the real endpoint against the same file. Both services running together is phase 8.)
- [x] Output-size limit and input-size limit return 413. (`payload_too_large` and `output_too_large`; exactly at each limit is accepted.)
- [x] Restored values never appear in captured logs or traces. (Logs: `tests/security/test_desanitization_security.py`. Traces: not implemented, so not claimed.)

### Phase 8. End-to-end pilot run and close-out

What it builds: the full cross-service scenarios over HTTP with both services as real processes and a real PostgreSQL, plus the final leakage sweep and documentation. Why: unit and stubbed tests cannot prove that the two services actually work together; this is the acceptance run for the pilot.

Success criteria:
- [ ] E2E: sanitize then restore returns the exact original text for every supported input in the pilot corpus (zero mismatches).
- [ ] E2E: cross-tenant and cross-request restoration attempts all fail with the non-disclosing response.
- [ ] E2E: expired and revoked references fail; a restart of both services leaves an unexpired mapping restorable.
- [ ] E2E: with the Sanitization Service stopped, restoration returns 503 and recovers when it restarts; with the database stopped, both services stay up and recover with no mappings lost.
- [ ] E2E: tampering with a stored ciphertext row directly in the database makes restoration fail safely.
- [ ] Leakage: canary values are absent from captured logs and error bodies of both services across all scenarios. Traces and metrics are reported as not implemented, not as passed, unless added.
- [ ] No source file in `services/desanitization_service` imports from the Sanitization package, and its environment holds no Sanitization database credentials (test).
- [ ] `uv run scripts/run_tests.py all`, `lint`, `scan`, and `uv run pyright` are run, with exact commands, date, and pass, fail, and skip counts recorded in `docs/STATUS.md`. Remaining skips are listed with reasons.
- [ ] Coverage is at or above 80% on `services/`.
- [ ] `docs/STATUS.md`, `docs/PLAN.md`, and `docs/SPEC.md` are updated, with known limitations and residual risks listed. The pilot is not described as production-ready.

## Files expected to change

New:
- `services/sanitization_service/app/**`, `migrations/**`, `alembic.ini`
- `services/desanitization_service/app/**`
- `scripts/gen_local_secrets.py` (cross-platform local secret generator)
- `services/sanitization_service/app/sanitization/profiles/` (loader, resolver) and the six profile data files
- `services/sanitization_service/app/settings/` (interface, validator, snapshot, file and database backends, selector)
- `config/settings.example.json` (synthetic example) and a git-ignored local `config/settings.json`
- `scripts/settings.py` (validate, show, export, import; cross-platform)
- Second Alembic revision for `settings_snapshots` and `settings_audit`, and the two database roles
- `.env.example` entries for `PRIVYFLOW_SETTINGS_BACKEND` and the settings file path (placeholders only)
- `docs/adr/` (decision records), `docs/THREAT_MODEL.md`
- `.env.example` (placeholders only)

Modified:
- `pyproject.toml` and `uv.lock` (runtime dependencies: FastAPI, uvicorn, Pydantic settings, SQLAlchemy, Alembic, a PostgreSQL driver, `cryptography`; each justified in the commit)
- `tests/**`: replace pending entries with real tests; add pilot corpus fixture; add `tests/support` helpers as needed
- `scripts/run_tests.py` only if the coverage gate or process-launch support needs wiring; no threshold is lowered
- `.github/workflows/tests.yml` only if Docker or process steps need adjusting
- `docs/SPEC.md`, `docs/STATUS.md`, `docs/PLAN.md`

## Tests and validation

Tests are written before each phase's implementation. Suites follow `docs/TEST_STRATEGY.md`: unit (placeholders, crypto, recognizers, restoration), integration (APIs, migrations, internal API, contract), security (isolation, authorization, tamper, non-disclosure, leakage), evaluation (pilot-type baseline), e2e (separate processes over HTTP). Synthetic data only; test keys are generated at test time.

Commands (PowerShell and macOS compatible):

```text
uv sync --all-groups
uv run scripts/run_tests.py unit
uv run scripts/run_tests.py integration
uv run scripts/run_tests.py security
uv run scripts/run_tests.py evaluation
uv run scripts/run_tests.py e2e
uv run scripts/run_tests.py all
uv run scripts/run_tests.py lint
uv run scripts/run_tests.py scan
uv run pyright
```

## Acceptance criteria

The pilot is accepted when all phase criteria above are ticked with evidence, and:

- [ ] A client script can sanitize and restore text through both services running as separate local processes, with the original reproduced exactly.
- [ ] The vault holds only digests and ciphertext; a test proves it.
- [ ] Cross-tenant and cross-request access has zero successes across the isolation matrix.
- [ ] No canary value appears in any captured log or error body.
- [ ] The full check suite is green with recorded results, and no test, threshold, or rule was weakened.
- [ ] The owner has reviewed the limitations list and approves the pilot as complete.

## Risks and open questions

Risks:
- The Docker daemon was not running when the harness was last verified (`docs/STATUS.md`), so the PostgreSQL Testcontainers fixture has never run. Phase 2 depends on it. Mitigation: confirm Docker is running before phase 2; if it cannot be, ask the owner rather than substituting SQLite or skipping.
- The GitHub Actions workflow has not run. The repository now has a first commit, so the first CI run is part of phase 2 evidence only if a remote exists; otherwise CI is reported as unverified. Pushing requires the owner's request.
- Regex detection has known gaps (no PERSON, formats vary by locale). Pilot results say nothing about overall detection quality, and no completeness claim is made.
- Shared service secret, env-var key, and API keys are pilot-only trust mechanisms. They must be replaced before any multi-user or production use.
- Both services use a package named `app`, so in-process tests load one service at a time. Cross-service behavior is only proven in phases 7 (stubbed) and 8 (real processes).
- Cross-platform process management in e2e tests (starting, stopping, restarting on Windows) is fiddly; it will be built with `subprocess` and tested on Windows first.

Open questions:
All open questions are resolved on the recommended approach. A later change to any of them needs a new decision from the owner.

- Q1 (resolved): the default restore-reference TTL is 1 hour, a setting in the store, further limited by profile `max_ttl`.
- Q2 (resolved): the pilot adds a few multi-paragraph synthetic samples to a pilot corpus fixture. The owner reviews them in phase 1 or 3 before they are used, and they contain only reserved domains, fictional number ranges, and invented names.
- Q3 (resolved): revocation is a repository-level function with an admin tool entry point, not a public endpoint, until the authorization model is decided.
- Q4 (resolved): the placeholder format is `[TYPE_NNN]` with three-digit zero padding, growing to more digits only if a request needs more than 999 of one type.
- Q5 (resolved): IP_ADDRESS and US_SSN recognizers are added to the pilot (D1). Aadhaar, addresses, and dates stay out and are reported as not covered.
- Q6 (resolved): the six profiles are the right set. Profiles are data, so changing the set later is cheap.
- Q7 (resolved): the backend is chosen at startup by one setting and switched by changing it and restarting, with the export and import tool to move settings (D15). Live switching and live reload are out of the pilot; if needed later, they get a separate plan with a trusted admin path and a rule for in-flight requests.
- Q8 (resolved): the store holds profiles, tenant flags, default TTL, request size limit, strict-coverage flag, and internal client timeout. Anything else stays in the environment until the owner adds it.

New risks from the settings store:
- Two backends double the test surface. The mitigation is one contract suite run against both, and one validator shared by both.
- Anyone who can write settings can weaken protection. Mitigations: a separate admin role, an append-only audit, restart-only activation, and a threat-model entry. Production use needs an approved change-control process.
- The database backend makes the Sanitization database the home of configuration as well as ciphertext. Keys stay in the environment, so a database dump still does not expose them.

New risks from the profile feature:
- Profile contents are an interpretation of regulations. They need legal review before anyone relies on them, and the plan makes no compliance claim.
- A tenant enabling a profile may assume full protection. The uncovered-types report is the mitigation; its wording is reviewed in phase 1.
- Strictest-wins can over-mask (for example HIPAA dates in a GDPR tenant's text). That is intended, but it lowers text usefulness, so the effective policy is visible to the tenant.
