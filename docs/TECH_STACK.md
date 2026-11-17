# PrivyFlow — Technology Stack and Architecture

## 1. Architecture principles

- Exactly two core services in the current scope: Sanitization and De-sanitization.
- Each service has an independent FastAPI application, process, configuration, tests, and deployment lifecycle.
- Sanitization owns the encrypted reversible mapping vault.
- De-sanitization accesses mappings only through a documented, authenticated internal API.
- No direct cross-service database access and no shared runtime coupling.
- The client application coordinates the workflow.
- No document processing, RAG, embeddings, vector database, or LLM dependency in the current scope.

## 2. Baseline technology stack

| Layer | Technology | Usage |
|---|---|---|
| Language | Python 3.11+ | Service implementation |
| API framework | FastAPI | Public and internal HTTP APIs |
| Validation | Pydantic v2 | Request/response schemas and configuration |
| ORM | SQLAlchemy 2.x | Vault and metadata persistence |
| Database | PostgreSQL | Encrypted mappings, policy metadata, and audit metadata |
| Migrations | Alembic | Versioned schema changes |
| Testing | Pytest + HTTPX, pytest-cov | Unit, API, integration, security, and end-to-end tests with coverage |
| Property testing | Hypothesis | Round-trip, collision, and bounds properties |
| Test databases | Testcontainers (PostgreSQL) | Integration tests against a real database; needs Docker |
| Load testing | Locust | Performance baselines and release gate |
| Security scanning | Bandit, pip-audit | Static analysis and dependency vulnerability scanning |
| Detection | Presidio / spaCy and custom recognizers, subject to evaluation | Sensitive entity recognition |
| Cryptography | Maintained Python cryptography library | Credential hashing support and authenticated encryption |
| Tooling | uv | Dependency management and running commands (`uv sync`, `uv run`) |
| Linting | Ruff or approved equivalent | Formatting and static quality checks |
| Type checking | Pyright or approved equivalent | Static typing in strict mode |
| Observability | Structured logs, metrics, traces with redaction | Safe operational visibility |

Do not add ChromaDB, Qdrant, embedding libraries, OCR, chunking frameworks, LLM SDKs, Redis, or message brokers in the current scope without explicit approval.

Everything must run on Windows and macOS. Configuration comes from environment variables, with local values in `.env` (never committed) and non-secret placeholders in `.env.example`.

## 3. Logical architecture

```text
                         Client Application
                         /                \
                        v                  v
             Sanitization Service   De-sanitization Service
                      |                       |
                      v                       |
             Encrypted Mapping Vault          |
             (owned by Sanitization)           |
                      ^                       |
                      |                       |
                      +--- authenticated -----+
                           internal API
                           mapping retrieval
```

The client controls when sanitization and restoration occur. The De-sanitization Service does not connect directly to the vault database.

## 4. Service boundaries

### 4.1 Sanitization Service

Owns:
- Text sanitization API.
- Detection and policy evaluation.
- Placeholder generation.
- Restoration credential generation and hashing.
- Encrypted mapping vault.
- Vault database, credentials, migrations, and retention lifecycle.
- Authenticated internal mapping-retrieval API.

Must not:
- Restore original text.
- Call external LLMs.
- Read arbitrary files or folders.
- Share database credentials with the De-sanitization Service.

### 4.2 De-sanitization Service

Owns:
- Restoration API.
- Caller authentication and authorization.
- Tenant and request-scope validation.
- Safe placeholder substitution.
- Internal client for calling Sanitization Service.
- Restoration audit metadata, if a separate store is required and approved.

Must not:
- Connect directly to the Sanitization Service database.
- Store a duplicate mapping vault.
- Generate or alter original mappings.
- Bypass Sanitization Service expiry, revocation, or scope checks.

## 5. Database and data ownership

| Data | Owner | Storage |
|---|---|---|
| Reversible placeholder mappings | Sanitization Service | Encrypted payload in PostgreSQL |
| Restoration credential lookup hash | Sanitization Service | PostgreSQL |
| Policy definitions and versions | Sanitization Service | PostgreSQL or versioned configuration, as approved |
| Encryption key material | Approved key-management boundary | Never in application source or mapping DB |
| Restoration audit metadata | De-sanitization Service, if required | Separate approved store or safe external audit sink |

Use a dedicated database role for Sanitization Service. The De-sanitization Service must not receive that database URL or credentials. The two services may use the same local PostgreSQL server instance during development, but logical ownership and permissions must remain separate.

The De-sanitization Service should not have a database by default. Add a separate operational/audit store only when a documented requirement justifies it.

## 6. Internal service communication

The De-sanitization Service calls a narrow internal endpoint on Sanitization Service to retrieve an authorized mapping.

Requirements:
- Authenticate the calling service using an approved service-to-service mechanism.
- Use TLS outside local development.
- Validate tenant, request scope, credential hash, expiry, and revocation in Sanitization Service.
- Apply short timeouts, bounded retries, and safe error handling.
- Do not expose the internal endpoint as an unauthenticated public operation.
- Do not return more mapping data than required for the restoration operation.
- Never log the request credential or decrypted mapping.

## 7. Cryptographic design

- Generate restoration credentials using a cryptographically secure random generator.
- Store a secure digest or keyed hash for lookup; never store the raw credential.
- Encrypt mapping payloads with authenticated encryption such as AES-256-GCM.
- Generate a unique nonce for each encryption operation.
- Store algorithm and key-version metadata with each ciphertext.
- Keep keys separate from the database and source code.
- Design for rotation and controlled decryption.
- Do not implement custom cryptographic algorithms.
- Do not confuse possession of a credential with authorization; validate identity, tenant, and scope independently.

The production key-management solution must be selected before production use. A local development key is acceptable only when clearly marked as non-production and excluded from source control.

## 8. Detection architecture

Use a recognizer interface so engines can be changed or combined without changing API contracts. Evaluate Presidio, spaCy, and custom recognizers against a representative corpus. Document entity types, confidence behavior, false positives, false negatives, overlap handling, and policy semantics.

Detection is probabilistic in practice and must not be represented as complete anonymization.

## 9. Deployment model

Run each service as a separate local process during development. Each may later be packaged and deployed independently. Production topology, networking, TLS, identity, KMS, monitoring, backups, and operational runbooks require explicit design and approval.

Do not introduce an API gateway, service mesh, queue, cache, or orchestration component unless a measurable requirement justifies it.

## 10. Future decision gates

| Area | Gate |
|---|---|
| Authentication provider | Decide before multi-user exposure. |
| Tenant identity propagation | Define trusted identity source and authorization model. |
| Service-to-service authentication | Approve mechanism before exposing internal mapping API. |
| KMS / secrets manager | Required before production handling of reversible sensitive mappings. |
| Audit store | Add only after retention, access, and event requirements are defined. |
| Cloud deployment | Requires explicit provider, residency, network, and cost approval. |
