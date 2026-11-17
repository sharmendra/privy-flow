# AGENTS.md — PrivyFlow

## 1. Project identity

**Product:** PrivyFlow  
**Category:** Privacy engine / privacy infrastructure for applications  
**Current scope:** Two independently deployable services:
1. **Sanitization Service**
2. **De-sanitization Service**

PrivyFlow accepts text, detects configured sensitive information, replaces sensitive values with controlled placeholders, securely retains the reversible mappings, and restores original values only through an authorized workflow.

The current project is deliberately limited to the privacy engine. Do not expand the scope into document ingestion, RAG, embeddings, vector databases, or LLM orchestration unless the product owner explicitly approves that change.

## 2. Role and collaboration model

The user is the product owner, technical lead, and final approver of scope and architecture decisions.

The AI coding agent is responsible for:
- Understanding requirements and asking focused questions when essential details are missing.
- Inspecting the existing repository and documentation before proposing changes.
- Producing an implementation plan before substantial code changes.
- Following the approved architecture and coding standards.
- Implementing complete, runnable code rather than illustrative fragments when implementation is requested.
- Running relevant tests and reporting the actual commands and results.
- Updating documentation and project status after changes.
- Clearly identifying assumptions, risks, limitations, and unfinished work.

The documents in `docs/` are the product owner's requirements. Treat them as the customer's brief, and build to the standards they set.

Write plans the owner can review: say what each phase builds and why you chose that approach. Explain your work when asked, at the level asked for.

The owner may be on Windows, where the terminal is PowerShell, or on a Mac. Give commands that work on their system, and make sure scripts and tooling run on Windows.

Do not silently make material product, security, architecture, or infrastructure decisions. Present options and a recommendation when a decision affects service boundaries, data ownership, cryptography, authorization, or deployment.

## 3. Mandatory documentation review

IMPORTANT: before you plan, build or change anything in the product, or answer questions about it, read each of these project documents in full:

1. `docs/SPEC.md` — product scope and requirements
2. `docs/TECH_STACK.md` — approved architecture and technologies
3. `docs/CODE_STANDARDS.md` — coding, API, database, and security standards
4. `docs/PROCESS.md` — planning, implementation, and review workflow
5. `docs/BRAND.md` — product positioning and terminology
6. `docs/STATUS.md` — verified current implementation state and open issues
7. `docs/PLAN.md` — phases and acceptance criteria. Plans for later work go in their own documents, such as `docs/PLAN_<FEATURE>.md`
8. `docs/TEST_STRATEGY.md` — test harness, suites, commands, and release acceptance criteria

If any document is missing, inconsistent, or outdated, report the issue and propose an update. Do not assume that a feature is implemented merely because it appears in a plan or specification.

## 4. Product scope

### 4.1 In scope

- Accepting text through APIs.
- Detecting configured sensitive entities in text.
- Supporting configurable sanitization policies.
- Replacing sensitive values with placeholders.
- Generating high-entropy restoration credentials or references.
- Securely storing reversible mappings in encrypted form.
- Validating authorization, tenant scope, request scope, expiry, and revocation before restoration.
- Restoring recognized placeholders to their original values when authorized.
- Audit metadata and security-focused operational observability.
- Independent testing, configuration, migrations, and deployment of both services.

### 4.2 Explicitly out of scope unless approved

- File uploads, folder watchers, document-source connectors, and document extraction.
- PDF, DOCX, HTML, spreadsheet parsing, and OCR.
- Text chunking and document indexing.
- NLP/model tokenization for LLM token counts.
- Embedding generation.
- ChromaDB, Qdrant, Pinecone, or any vector database.
- Semantic search and RAG.
- LLM calls, prompt construction, agent frameworks, and agent orchestration.
- A mandatory API gateway or workflow orchestrator.
- Cloud resources or production deployment without explicit approval.

Do not add dependencies or modules for out-of-scope features “for future use.” Keep the implementation focused.

## 5. Approved architecture

PrivyFlow consists of two independently deployable FastAPI services.

```text
                    Client Application
                     /              \
                    /                \
                   v                  v
        Sanitization Service    De-sanitization Service
                  |                       |
                  |                       |
                  v                       |
       Encrypted Mapping Vault            |
       (owned by Sanitization)             |
                  ^                       |
                  |                       |
                  +--- authenticated -----+
                       internal API
                       for authorized
                       mapping retrieval
```

### 5.1 Sanitization Service

The Sanitization Service is responsible for:
- Accepting original text and the required tenant/request context.
- Validating request size, type, policy, and caller authorization.
- Detecting sensitive entities using configured recognizers.
- Applying the selected sanitization policy.
- Generating collision-resistant placeholders.
- Creating a high-entropy restoration credential/reference.
- Encrypting and storing the reversible mapping.
- Returning sanitized text and the restoration reference.
- Exposing a narrowly scoped, authenticated internal endpoint for authorized mapping retrieval by the De-sanitization Service.
- Enforcing retention, expiry, revocation, and deletion rules for mapping records.

The Sanitization Service must not return original sensitive values in logs, diagnostics, metrics, or ordinary API metadata.

### 5.2 De-sanitization Service

The De-sanitization Service is responsible for:
- Accepting sanitized text and a restoration reference.
- Authenticating the caller and authorizing the restoration operation.
- Validating tenant identity, request scope, policy, expiry, and revocation.
- Requesting the required mapping through the Sanitization Service's authenticated internal API.
- Restoring only placeholders that are present in the authorized mapping.
- Handling unknown, malformed, duplicated, or altered placeholders safely.
- Returning the restored text and safe operation metadata.
- Recording audit metadata without logging original sensitive values.

The De-sanitization Service must not connect directly to the Sanitization Service database or access its database credentials.

### 5.3 Service independence

Each service must have:
- Its own FastAPI application and process.
- Its own configuration and environment variables.
- Its own database credentials and migration lifecycle where it owns persistent data.
- Its own tests and API contract.
- Its own health and readiness endpoints.
- Its own deployment lifecycle.

There must be no shared runtime dependency on the other service's Python application modules. Shared API schemas may be published as a versioned contract package only if explicitly approved; otherwise keep contracts service-local and test compatibility at the API boundary.

The De-sanitization Service may depend on the Sanitization Service's documented internal API for mapping retrieval. That is network-level integration, not direct database or runtime coupling. Define timeouts, authentication, error handling, and version compatibility for this call.

## 6. Data ownership and secure mapping vault

### 6.1 Ownership model

The Sanitization Service owns the encrypted mapping vault and its database. The De-sanitization Service obtains mappings only through the authenticated internal API exposed by the Sanitization Service.

Do not create a second copy of the mapping vault in the De-sanitization Service. Do not grant the De-sanitization Service direct database access.

### 6.2 Mapping record design

The exact schema must be documented and reviewed before implementation. At minimum, evaluate fields for:
- Internal mapping record ID.
- Tenant ID.
- Request/session scope ID.
- Hash of the high-entropy restoration credential.
- Encrypted mapping payload.
- Encryption algorithm and key version.
- Creation and expiry timestamps.
- Revocation/deletion status.
- Policy/version metadata.
- Safe audit metadata.

Do not persist plaintext restoration credentials or plaintext reversible mappings.

### 6.3 Cryptographic requirements

- Use a cryptographically secure random number generator for restoration credentials.
- Generate sufficient entropy; do not use sequential IDs, timestamps, UUIDs alone, or user-provided values as bearer secrets.
- Store only a secure digest or keyed hash of the restoration credential for lookup.
- Encrypt reversible mapping payloads with authenticated encryption, such as AES-256-GCM, using a unique nonce for each encryption operation.
- Store key-version metadata with each encrypted record.
- Keep encryption keys outside source control and outside the database containing ciphertext.
- Design for key rotation and controlled decryption.
- Do not invent cryptographic primitives or implement custom encryption.
- Do not claim that encryption alone provides authorization or tenant isolation.

The concrete key-management mechanism must be suitable for the target environment. Local development may use a clearly marked local key configuration, but production key management requires an approved secrets manager or KMS design.

## 7. Privacy detection and sanitization behavior

- Detection identifies likely sensitive entities; it does not guarantee that every sensitive value is found.
- Use a recognizer abstraction so detection engines can be evaluated or replaced without changing the service API.
- Evaluate Presidio, spaCy, and custom recognizers against a representative test corpus before selecting a production configuration.
- Support explicit policy configuration for entity types, actions, and placeholder behavior.
- Make placeholder generation deterministic within a single sanitization request where repeated occurrences should map consistently.
- Avoid collisions with literal placeholder-like text already present in the source.
- Preserve text outside the selected sensitive spans.
- Define behavior for overlapping entities, nested entities, repeated values, and ambiguous detections.
- Include confidence and recognizer metadata only when useful and safe.
- Do not use an LLM as the authority for privacy decisions in the core sanitization path.

## 8. Restoration behavior

- Restoration must require authenticated caller identity and explicit authorization.
- Validate tenant and request/session scope independently of the restoration credential.
- Enforce expiry, revocation, and retention rules.
- Restore only exact placeholders known to the authorized mapping.
- Do not restore placeholders from another tenant or request scope.
- Do not interpret arbitrary user-supplied strings as restoration instructions.
- Define safe behavior for unknown placeholders and malformed input.
- Prevent replay or repeated restoration where policy requires one-time use; document the chosen behavior.
- Apply output-size limits and request timeouts.
- Record who/what requested restoration and when, without recording restored sensitive values.

## 9. API and error-handling standards

- Use versioned routes such as `/api/v1/...`.
- Use Pydantic request and response schemas.
- Define separate public endpoints and internal service-to-service endpoints.
- Authenticate and authorize all sensitive operations.
- Use consistent error response structures and appropriate HTTP status codes.
- Do not reveal whether a protected mapping exists when the caller is unauthorized.
- Do not expose stack traces, SQL, secrets, key metadata, plaintext mappings, or internal service details.
- Apply request-size limits, validation, rate limits, and timeouts.
- Define idempotency and retry behavior for sanitization and restoration operations.
- Generate and propagate correlation IDs without including sensitive text in them.

Potential endpoint names should be treated as proposals until documented in `docs/SPEC.md` and approved. Do not silently create incompatible API contracts.

## 10. Security, tenant isolation, and audit

Security is a core product requirement, not a later optional enhancement.

- Every privacy-sensitive record and operation must be scoped to a tenant.
- Never trust a tenant ID supplied by an untrusted caller without validating it against authenticated identity and authorization.
- Apply least-privilege service credentials.
- Authenticate internal service-to-service calls using an approved mechanism.
- Use TLS outside local development.
- Protect against cross-tenant access, credential guessing, replay, token leakage, injection, oversized requests, and denial-of-service patterns.
- Define retention, deletion, revocation, and audit requirements.
- Keep audit logs separate from sensitive payload storage.
- Avoid collecting more personal data than the service needs.
- Document the threat model and security assumptions.

## 11. Logging and observability

Never log:
- Original input text.
- Sanitized or restored full text unless a specifically approved test-only mechanism is used.
- Sensitive entity values.
- Plaintext reversible mappings.
- Restoration credentials or authorization secrets.
- Encryption keys or decrypted payloads.

Safe operational metadata may include:
- Service name and version.
- Request/correlation ID.
- Tenant-scoped opaque identifier where permitted.
- Operation type and outcome.
- Latency, status code, and error category.
- Entity counts or categories only when approved by the privacy policy.

Metrics and traces must be reviewed for accidental payload capture. Error messages must be sanitized.

## 12. Technology standards

Use the following baseline unless `docs/TECH_STACK.md` records an approved change:

- Python 3.11 or later.
- FastAPI.
- Pydantic v2.
- SQLAlchemy 2.x.
- PostgreSQL for the encrypted mapping vault and required metadata.
- Alembic for schema migrations.
- Pytest and HTTPX for testing.
- Ruff or an approved formatter/linter.
- A maintained cryptography library for authenticated encryption.

Do not add ChromaDB, Qdrant, embedding models, chunking frameworks, OCR libraries, LLM SDKs, Redis, or message brokers within the current scope unless the product owner approves a scope change.

## 13. Repository structure

Use this as the target structure. Inspect the existing repository before moving or renaming files.

```text
PrivyFlow/
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── SPEC.md
│   ├── TECH_STACK.md
│   ├── CODE_STANDARDS.md
│   ├── PROCESS.md
│   ├── BRAND.md
│   ├── STATUS.md
│   ├── PLAN.md
│   └── TEST_STRATEGY.md
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

The De-sanitization Service should not have a database by default unless a separately justified requirement is approved. If it needs operational audit persistence, define that store separately and do not duplicate the encrypted mapping vault.

## 14. Development workflow

For every feature or phase:

1. Read the relevant documentation and inspect the current code.
2. Restate the requirement and identify assumptions.
3. Identify which service owns the behavior and data.
4. Create or update a plan before substantial implementation.
5. Specify API contracts, schemas, security controls, tests, and acceptance criteria.
6. Ask for approval before material architecture or scope changes.
7. **Define expected behavior** as measurable acceptance criteria.
8. **Write tests** for that behavior first, in the right suites (see `docs/TEST_STRATEGY.md`).
9. **Implement** in small, reviewable increments.
10. **Execute tests**, migrations, static checks, and manual API verification.
11. **Review results.** Fix failures; do not weaken tests to pass.
12. Report exact commands and actual results. Never invent test results.
13. Update `docs/STATUS.md`, `docs/PLAN.md`, and relevant specifications.

Use `docs/PLAN_<FEATURE>.md` for substantial feature plans.

### Plan first, then implement

Work goes in two steps, with the owner's review in between.

1. **Plan.** When asked to plan, as in "Please plan <the work>", write the plan to `docs/PLAN.md` (or `docs/PLAN_<FEATURE>.md` for a feature) and write no code. Split the work into phases, each building on the last. Give each phase success criteria you can verify yourself, such as passing tests, commands and their output, and API calls and their responses. Write each criterion as a checkbox. Then stop and wait until asked to implement.
2. **Implement.** When asked to implement the plan, build every phase in order. For each phase: build it with tests, check every success criterion and fix what fails, tick the criteria in the plan, update `docs/STATUS.md`, and commit. When the last phase is done, run the full check suite and report the actual results.

Build only what the documents in `docs/` ask for. Do not build ahead for a later phase or add out-of-scope features.

### Working rules

- Add tests with each change. Tests must not call external services or real models; use stubs.
- Run the full check suite (lint, format, types, tests) before handing work over.
- Never skip commit hooks (`--no-verify`).
- Never lower a threshold, turn off a rule, or exclude a file to get a green run. If a rule looks wrong, stop and ask.
- Keep `docs/STATUS.md` up to date.
- Never push unless asked.
- Everything must work on Windows.

### Planning template

```markdown
# PLAN_<FEATURE>.md

## Objective

## Scope
### Included
### Excluded

## Service ownership

## API contract

## Data model

## Security and privacy considerations

## Implementation steps

## Files expected to change

## Tests and validation

## Acceptance criteria
- [ ] ...

## Risks and open questions
```

## 15. Testing requirements

Automated testing is mandatory for every feature. The strategy, suites, commands, and release gates are in `docs/TEST_STRATEGY.md`; the harness lives in `tests/` and is run with `uv run scripts/run_tests.py <suite>`.

- Every feature ships with tests at the appropriate levels: unit, integration, security, and, where relevant, evaluation, end-to-end, and performance.
- Workflow: define expected behavior, write tests, implement, execute tests, review results.
- Evidence is required before marking a feature complete: the exact command, the date, and the pass, fail, and skip counts, recorded in `docs/STATUS.md`.
- Never claim tests passed unless they were executed in this session or CI. Skipped or pending tests are reported as skipped or pending, never as passed.
- Never write a placeholder that passes. Tests for unbuilt features must skip with a reason or stay absent.
- Tests use synthetic data only. Never put real PII, credentials, or keys in fixtures.
- Never lower a coverage threshold, delete a test, or add a skip or xfail to get a green run.

At minimum, build tests for:

### Sanitization Service
- Sensitive entity detection and policy selection.
- Repeated entity handling and placeholder consistency.
- Placeholder collision handling.
- Overlapping or ambiguous entity spans.
- Empty, malformed, and oversized input.
- Secure credential generation and hash lookup.
- Encryption/decryption round trips.
- Key-version handling.
- Tenant and request-scope isolation.
- Expiry, revocation, and deletion.
- Confirmation that logs and errors do not expose sensitive values.

### De-sanitization Service
- Authorized restoration succeeds.
- Invalid or expired credentials fail safely.
- Unauthorized caller cannot restore.
- Cross-tenant and cross-request restoration is rejected.
- Unknown and altered placeholders are handled safely.
- Sanitization Service timeout/unavailability is handled safely.
- Internal API authentication is enforced.
- Restored values are not written to logs or traces.

### Integration and operational tests
- Both services start and deploy independently.
- De-sanitization calls the Sanitization Service only through its authenticated API.
- No direct cross-service database access exists.
- API contract compatibility is tested.
- Migrations work from a clean database and supported prior versions.
- Health/readiness endpoints behave correctly.
- Rate limits, request limits, and timeouts are tested.

A feature is not complete because code was generated. It is complete only when its acceptance criteria are validated and actual results are recorded.

## 16. Git and dependency management

- Keep `.env`, credentials, keys, local databases, virtual environments, caches, and sensitive test data out of source control.
- Maintain `.env.example` with non-secret placeholders.
- Pin or constrain dependencies and review security advisories.
- Use focused branches and commits.
- Review diffs for accidental secrets, generated files, and unrelated changes.
- Do not add a dependency without explaining why it is needed.

## 17. Infrastructure and deployment guardrails

- Local development is the default.
- Do not create cloud resources, deploy services, configure paid services, or incur costs without explicit approval.
- Do not assume a cloud provider or production environment.
- Before production, define TLS, identity, service-to-service authentication, KMS/secrets management, network policy, backups, monitoring, retention, incident response, and disaster recovery.
- Do not describe the product as production-ready until the relevant release gates are evidenced.

## 18. Definition of done

A task is done only when:

- It matches the approved PrivyFlow scope and architecture.
- The owning service is clear and service boundaries are preserved.
- API contracts and data ownership are documented.
- Security, authorization, tenant isolation, and privacy implications are addressed.
- Automated tests pass and actual results are reported.
- Migrations are included and validated where applicable.
- No secrets or sensitive payloads are committed or logged.
- Relevant documentation and project status are updated.
- Known limitations and remaining risks are stated.

## 19. Non-negotiable architecture rules

1. PrivyFlow currently has exactly two core services: Sanitization and De-sanitization.
2. The services are independently deployable.
3. Sanitization owns the encrypted reversible mapping vault.
4. De-sanitization accesses mappings only through an authenticated internal API.
5. No direct cross-service database access.
6. No shared runtime coupling between the services.
7. No document extraction, chunking, embeddings, vector databases, RAG, or LLM integration in the current scope.
8. No raw sensitive content, plaintext mappings, credentials, or keys in logs.
9. No production deployment or cloud resource creation without explicit approval.
10. Security and privacy controls must be designed and tested as part of each feature, not postponed until the end.
11. No feature is complete without executed automated tests and recorded evidence. Never claim tests passed unless they actually ran.
