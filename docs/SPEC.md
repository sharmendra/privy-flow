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

## 9. API surface

Status: final for the pilot, approved 2026-11-17 (`docs/adr/0001-pilot-decisions.md`). Changes need owner approval. Contracts are service-local; compatibility is tested at the HTTP boundary.

### 9.1 Endpoints

| Service | Endpoint | Auth | Purpose |
|---|---|---|---|
| Sanitization | `GET /health/live` | none | Process liveness |
| Sanitization | `GET /health/ready` | none | Settings loaded and database reachable |
| Sanitization | `POST /api/v1/sanitizations` | `X-API-Key` | Sanitize submitted text |
| Sanitization | `GET /api/v1/policies` | `X-API-Key` | Calling tenant's effective policy |
| Sanitization internal | `POST /internal/v1/mappings/retrieve` | `X-Service-Secret` | Mapping retrieval for De-sanitization |
| De-sanitization | `GET /health/live` | none | Process liveness |
| De-sanitization | `GET /health/ready` | none | Configuration valid (no database check) |
| De-sanitization | `POST /api/v1/desanitizations` | `X-API-Key` | Restore authorized placeholders |

Revocation has no public endpoint in the pilot. It is a repository function with an admin tool entry point (Q3).

### 9.2 Common rules

- Tenant is derived from the authenticated API key (public routes) and never read from the body. Each service has its own key list. API keys and the service secret are never accepted on each other's routes.
- Identifier patterns: `request_scope_id` matches `^[A-Za-z0-9._:-]{1,128}$`. Tenant ID matches `^[a-z0-9][a-z0-9_-]{2,62}$`. `X-Correlation-ID` is accepted if it matches `^[A-Za-z0-9._-]{8,64}$`, otherwise a new ID is generated. The ID is returned in the `X-Correlation-ID` header and in every error body.
- `restore_reference` format: `pf1_` followed by 43 URL-safe base64 characters (32 random bytes). A value that does not match this format is rejected with the same 404 as an unknown reference.
- Request bodies are JSON. Unknown fields are rejected (422). Body size is limited by the `max_request_bytes` setting (default 262144, floor 1024); larger bodies return 413. The limit is counted in bytes of the raw body, so multi-byte characters count in full, and a body of exactly the limit is accepted. A declared `Content-Length` over the limit is refused before any of the body is read; a body with no declared length, or one that understates it, is counted as it arrives and refused once it goes over. If the settings did not load, the default applies. The Sanitization Service enforces this from pilot phase 4; the De-sanitization Service from phase 7.
- All timestamps are UTC, ISO 8601.

### 9.3 Sanitization: `POST /api/v1/sanitizations`

Request:

```json
{ "text": "string, 1 to the size limit", "request_scope_id": "string", "policy_id": "effective" }
```

`policy_id` must be `effective`, the tenant's resolved policy. Any other value returns 422 `unsupported_policy`. A body field naming profiles or a tenant is rejected as an unknown field (422).

Response 200:

```json
{
  "sanitized_text": "string",
  "restore_reference": "string or null",
  "expires_at": "datetime or null",
  "profiles_applied": ["gdpr"],
  "uncovered_entity_types": ["PERSON"],
  "entity_count": 0,
  "correlation_id": "string"
}
```

`restore_reference` and `expires_at` are null when nothing reversible was stored (no entities, or every entity redacted). `entity_count` counts masked spans of both actions. Whitespace-only text is valid and returns unchanged with `entity_count` 0. Empty text (`""`) returns 422 `validation_error`. `request_scope_id` must match the pattern in 9.2, and a bad value is also 422.

### 9.4 Sanitization: `GET /api/v1/policies`

Response 200, the calling tenant's own configuration only:

```json
{
  "policy_id": "effective",
  "profiles": [{ "id": "gdpr", "version": 1 }],
  "entity_types": [{ "type": "EMAIL", "action": "placeholder" }],
  "max_ttl_seconds": 3600,
  "uncovered_entity_types": ["PERSON"]
}
```

### 9.5 Sanitization internal: `POST /internal/v1/mappings/retrieve`

Request:

```json
{ "restore_reference": "string", "tenant_id": "string", "request_scope_id": "string" }
```

Response 200 (no other fields are allowed):

```json
{ "mappings": [{ "placeholder": "[EMAIL_001]", "value": "string" }], "policy_id": "effective" }
```

The response holds at most 10000 mappings. The lookup requires the credential digest, tenant, and request scope to all match, and the record to be unexpired, unrevoked, and undeleted. Version compatibility: the path carries the version (`v1`); breaking changes get a new path.

### 9.6 De-sanitization: `POST /api/v1/desanitizations`

Request:

```json
{ "sanitized_text": "string, 1 to the size limit", "restore_reference": "string", "request_scope_id": "string" }
```

Response 200:

```json
{ "restored_text": "string", "restored_count": 0, "unmatched_placeholder_count": 0, "correlation_id": "string" }
```

Restoration is single pass, left to right, exact match only. Placeholders not in the authorized mapping, altered placeholders, malformed look-alikes, and `[TYPE_REDACTED]` markers are left untouched. A substring that has the placeholder shape but is not in the mapping is counted in `unmatched_placeholder_count`. The restored text is limited to `max_output_bytes` (default 1048576); larger output returns 413 `output_too_large`.

Internal client behavior: connect and read timeout from the `internal_client_timeout_seconds` setting (default 3), at most 2 retries, only for connection errors and 503. Sanitization unavailable or timed out returns 503 `dependency_unavailable`.

### 9.7 Error body and codes

```json
{ "error": { "code": "string", "message": "string", "correlation_id": "string" } }
```

Messages are fixed text. They never include input, values, references, keys, SQL, paths, or traces.

| HTTP | Code | When |
|---|---|---|
| 401 | `unauthorized` | Missing or invalid API key or service secret |
| 404 | `restore_reference_not_found` | Unknown, malformed, expired, revoked, deleted, cross-tenant, or cross-scope reference (D7). Same body and shape for every cause. |
| 413 | `payload_too_large` | Request body over the size limit |
| 413 | `output_too_large` | Restored text over the output limit |
| 422 | `validation_error` | Wrong type, missing or unknown field, empty text, bad identifier |
| 422 | `unsupported_policy` | `policy_id` is not `effective` |
| 500 | `internal_error` | Unexpected error; details only in redacted logs |
| 503 | `dependency_unavailable` | Database unavailable, or Sanitization unavailable or timed out |

Unknown routes return 404 `not_found` and wrong methods 405 `method_not_allowed` in the same body shape.

Health endpoints return `{ "status": "ok" }` (200) or `{ "status": "unavailable" }` (503), with no detail.

### 9.8 Idempotency and retries

Sanitization is not idempotent: each call creates a new mapping and reference, so clients must not blindly retry after a timeout. Restoration is read-only and reusable within the TTL, so it is safe to retry.

### 9.9 Compliance profiles and restrictiveness rules

A compliance profile is a versioned data file that states what one regime asks PrivyFlow to protect. Profile files and the shared entity-type list are in `services/sanitization_service/app/sanitization/profiles/data/`. They are marked `not_reviewed_by_legal`. Enabling a profile is not a claim of compliance.

Each profile declares `id`, `version`, `entities` (type and action, `placeholder` or `redact`), and `max_ttl_seconds`. Initial profiles: `gdpr` (default), `india_dpdp`, `hipaa`, `pci_dss`, `glba`, `ccpa`.

Enabled profiles are set per tenant in the settings store as a map of tenant ID to profile IDs. The tenant is the one derived from the API key. A tenant with no entry gets `gdpr`. Startup fails on an empty list, an unknown profile ID, or a malformed tenant ID. Per-request selection is not supported.

The more restrictive result always wins:

| Setting | Resolution when several enabled profiles disagree |
|---|---|
| Entity types | Union: an entity is masked if any enabled profile names it. |
| Action per entity | `redact` (irreversible, no mapping stored) beats `placeholder` (reversible). A type no profile names is not masked. |
| Restore-reference lifetime | The smallest `max_ttl` among enabled profiles, and never longer than the default TTL (D5). |
| Overlapping spans | D6 picks the winning span; it then takes the most restrictive action among the spans it overlapped. |

Two properties follow and are tested: enabling an additional profile never unmasks an entity and never lengthens a lifetime, and the result does not depend on the order profiles are listed.

Coverage honesty: profiles name more entity types than the pilot can detect. The policy listing and each sanitization response include the entity types of the enabled profiles that have no recognizer (`uncovered_entity_types`). An optional strict flag, off by default, makes startup fail instead.

### 9.10 Settings store (Sanitization Service)

Operational settings live in one store per deployment, a file (default) or the database, chosen at startup. Secrets never go in either; they stay in the environment.

Bootstrap settings (environment or the service `.env` file only): `PRIVYFLOW_SETTINGS_BACKEND` (`file` or `db`, default `file`), `PRIVYFLOW_SETTINGS_FILE` (default `config/settings.json`), the runtime database URL, keys, pepper, service secret, and API keys. Profile definitions are the versioned data files in section 9.9; the store holds which profiles each tenant enables.

Content, schema version 1. Unknown keys are rejected at every level.

| Field | Rule | Default |
|---|---|---|
| `schema_version` | Required, must be `1` | none |
| `tenant_profiles` | Map of tenant ID (pattern in 9.2) to a non-empty list of known profile IDs | `{}` |
| `default_ttl_seconds` | Integer, 60 to 3600 (the D5 default is also the ceiling) | 3600 |
| `max_request_bytes` | Integer, at least 1024 | 262144 |
| `strict_coverage` | Boolean | `false` |

The internal client timeout in Q8 is not in this store. It belongs to the De-sanitization Service, which has no store and keeps it in its own settings.

Rules shared by both backends: any field whose name looks like a secret (secret, password, token, pepper, key, credential, encryption, dsn, and similar) is rejected. Errors name the field and the reason, never a value. Loaded content is immutable, with a version (0 for the file backend) and a SHA-256 hash of the validated content, so key order and omitted defaults do not change the hash.

Startup: settings load once. If loading fails (missing or invalid file, unreachable or empty database, bad backend value, hash mismatch) the service stays up but not ready: `/health/live` is 200 and `/health/ready` is 503. It never falls back to the other backend. A change takes effect on restart. Startup logs the backend, version and hash only.

Database backend: tables `settings_snapshots` (append-only, highest version wins) and `settings_audit` (actions `import`, `export`, `activate`), created by migration `0002`. The runtime role has SELECT only. A separate settings admin role has SELECT and INSERT, no UPDATE or DELETE, and no access to `mapping_records`.

Command line tool `uv run scripts/settings.py`: `validate`, `show`, `import` (prints a diff, `--dry-run`, writes nothing if invalid or unchanged) and `export` (refuses to overwrite without `--force`). Database commands use `PRIVYFLOW_SAN_SETTINGS_ADMIN_DATABASE_URL`. Exit codes: 0 done, 1 failed or invalid, 2 setup missing.

### 9.11 Pilot recognizers and span rules (Sanitization Service)

Decision D1 limits detection to six deterministic recognizers. Each reports an entity type and character offsets, never the matched text. Detection is best effort and the formats below are the only ones found; anything else passes through unmasked.

| Type | Found | Not found or rejected |
|---|---|---|
| `EMAIL` | `local@domain.tld`, ASCII local part (letters, digits, `._%+-`), dotted domain, alphabetic TLD of 2 or more letters. Trailing sentence punctuation is excluded. | Addresses with no dot in the domain (`user@localhost`), doubled `@` or dots, non-ASCII local parts. |
| `PHONE` | `+1` with ten digits (`+1 202-555-0143`, `+12025550143`); other `+CC` numbers as `CC`, then 4 to 5 digits, then 4 to 6 digits (`+91 98765 43210`, `+44 7911 123456`); ten digits as `202-555-0143`, `202.555.0143` or `(202) 555-0143`; Indian national format `098765 43210`. | Other national layouts, extensions, and anything followed directly by a letter, digit or hyphen (`202-555-0143-B`). |
| `FINANCIAL` | A payment card number: 13 to 19 digits that pass the Luhn check, as one run of digits or groups of at least four digits split by single spaces or hyphens. Every window of groups in a run is tried, so a neighbouring number does not hide a card. | IBANs and other account numbers, numbers that fail the checksum, and numbers split into groups of fewer than four digits. About one random 13 to 19 digit number in ten passes Luhn, so a number that is not a card can still be masked. |
| `IN_PAN` | Five capital letters, four digits, one capital letter. | Lowercase, and any PAN held inside a longer alphanumeric run. The fourth letter (holder type) is not checked. |
| `IP_ADDRESS` | IPv4 with octets 0 to 255 and no leading zeros; IPv6 in any form the Python standard library parses, including `::` compression and IPv4-mapped addresses (`::ffff:192.0.2.1`). A trailing full stop or colon is excluded. | Dotted values with 5 or more parts, out-of-range octets, times, and MAC addresses. The unspecified address `::` alone is ignored. |
| `US_SSN` | `AAA-GG-SSSS` or the same with spaces, one separator style throughout. | Area `000` or `666`, group `00`, serial `0000`, mixed separators, and values glued to other digits or hyphens. Unseparated nine-digit values are not detected. Areas `900` to `999` are accepted so the synthetic test values in ADR 0001 are found. |

Overlap rule (D6), applied after detections are filtered to the entity types the tenant's policy names, so a type nobody asked to mask cannot hide one that was:

1. The longest span wins.
2. Equal length: the higher `priority` in `entity_types.json` wins. Priorities are unique.
3. Still equal: the earliest start wins.
4. A shorter span that overlaps a winner is dropped. Spans that only touch (one ends where the next starts) do not overlap.
5. A winner takes `redact` if it, or any span it overlapped, is `redact`; otherwise `placeholder`. A dropped span that overlaps two winners counts toward both.

The overlap rule and the policy merge are implemented in `app/detection/overlap.py`, `app/sanitization/policy.py` and `app/sanitization/spans.py`. Placeholder text and replacement are in 9.12.

### 9.12 Placeholders and replacement (Sanitization Service)

Implemented in `app/sanitization/placeholders.py` and `app/sanitization/sanitizer.py`. This is pure logic. It stores nothing and issues no restore-reference; the vault does that in phase 5.

| Rule | Behavior |
|---|---|
| Reversible placeholder | `[TYPE_NNN]`, where `TYPE` is the entity type. `NNN` is zero padded to three digits and grows only past 999 (`[EMAIL_1000]`). |
| Redacted marker | `[TYPE_REDACTED]`. No counter, so it shows nothing about repeated values. The value is never added to the mappings. |
| Numbering | Per entity type, from 001, in order of first appearance in the text. Per request only: nothing carries over from one request to the next, so the same value in two requests is not linked. |
| Repeated values | The same entity type and exactly the same characters share one placeholder within a request. Matching is exact: `A@example.com` and `a@example.com` get two placeholders. The same characters under two entity types get two placeholders. |
| Collision rule | A number is skipped when its placeholder appears literally in the input (anywhere, including inside a masked value). So a generated placeholder never equals text the caller wrote. Text such as `[EMAIL_0001]`, `[email_001]` or `[EMAIL_1]` is not equal to any generated placeholder and does not cause a skip. |
| Literal redact marker | A `[TYPE_REDACTED]` already in the input is left alone and is never restored, so it cannot be mistaken for a mapping. |
| Preservation | Every character outside a masked span is kept exactly, including non-ASCII text, combining and zero-width characters, and `\r\n`, `\r` and `\n` line endings. Offsets are Python string (code point) offsets. |
| Entity count | Masked spans of both actions. A repeated value counts once per occurrence. |
| Whitespace-only and empty text | Returned unchanged with no mappings. Rejecting empty text is the request schema's job (9.3), not the sanitizer's. |
| Span input | Spans must be in text order, non-empty, inside the text and not overlapping (touching is allowed). Anything else raises an error that names no text. This cannot happen with spans from the planner (9.11). |

The result holds the sanitized text, the placeholder-to-value mappings and the entity count. The text and mappings are hidden from `repr`, so printing or logging a result by mistake shows no values.

A placeholder cannot be formed by joining the input around a replacement, because a placeholder has no `[` or `]` inside it and every replacement starts with `[`. Restoration therefore only needs exact matching on the placeholder shape `\[[A-Z][A-Z0-9_]*_[0-9]{3,}\]`.

### 9.13 Vault, API keys and the public endpoint (Sanitization Service)

Implemented in `app/vault/`, `app/repositories/mapping_repository.py`, `app/core/auth.py` and `app/api/sanitizations.py`.

| Rule | Behavior |
|---|---|
| Restore-reference | `pf1_` plus 43 URL-safe characters from 32 bytes of `secrets` (256 bits). Only an HMAC-SHA-256 digest keyed with a server-side pepper is stored, and it is the lookup key (unique index). |
| Encryption | AES-256-GCM (`cryptography` package), a fresh random 96-bit nonce per seal. The payload is `{"v":1,"mappings":{placeholder: value}}`; request text is never stored. |
| Associated data | Record id, tenant, request scope and key version. A ciphertext moved to another row, tenant or scope, or relabeled with another key version, fails to open. |
| Keyring | Keys by integer version. New rows use the active version; every listed version still opens its rows. A row whose version is not listed fails safely. |
| Lookup | Digest, tenant and request scope must all match, and the record must be unexpired, unrevoked and undeleted. Time is injected. `retrieve` returns nothing for every such miss and raises `MappingIntegrityError` for a found row that fails authentication. |
| Expiry | `created_at` plus the tenant's effective `max_ttl_seconds` (smallest profile lifetime, never above the default TTL). |
| Revocation and deletion | `Vault.revoke` and `Vault.mark_deleted` (reference plus tenant) set a timestamp. There is no public endpoint and no command line tool yet. |
| Stored metadata | `profiles` holds the applied profile IDs and versions, the settings snapshot version and hash. |

Secrets come from the environment only, and a missing or malformed one leaves the service alive but not ready (`/health/ready` 503, requests 503 `dependency_unavailable`):

| Variable | Content |
|---|---|
| `PRIVYFLOW_SAN_API_KEYS` | JSON object of tenant ID to API key (ASCII, at least 24 characters, none shared) |
| `PRIVYFLOW_SAN_ENCRYPTION_KEYS` | JSON object of key version to base64 AES-256 key |
| `PRIVYFLOW_SAN_ACTIVE_KEY_VERSION` | Version used for new rows; must be in the keyring |
| `PRIVYFLOW_SAN_CREDENTIAL_PEPPER` | Base64, at least 32 bytes |

Public endpoint behavior beyond 9.3 and 9.4: the API key is read from `X-API-Key` only and compared in constant time against every configured key. Authentication runs before the body is parsed, so an unauthenticated caller gets 401 and learns nothing about the schema (a body over the size limit is refused earlier, by the size limit, with 413). A database failure while storing returns 503 `dependency_unavailable`; text with no reversible entity needs no database. Responses carry `Cache-Control: no-store`. Keys, pepper and the service secret are pilot mechanisms (D2 to D4).

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
