# ADR 0001: Pilot decisions D1 to D17

Status: accepted. Approved by the product owner on 2026-11-17 (recommended option for every decision), as recorded in `docs/PLAN_PILOT.md`.

Later changes to any decision need a new decision from the owner and a new entry in "Change log" below.

## Context

`AGENTS.md` forbids silent decisions on authorization, cryptography, service boundaries, and deployment. The pilot (`docs/PLAN_PILOT.md`) builds one thin working path through both services. These decisions fix the choices the pilot code is held to. Several are pilot-only trust mechanisms and are marked as such.

## Decisions

| ID | Decision | Chosen option | Why | Consequence and limit |
|---|---|---|---|---|
| D1 | Entity types in the pilot | Regex and checksum recognizers: EMAIL, PHONE, FINANCIAL (Luhn), IN_PAN, IP_ADDRESS, US_SSN. No PERSON. | Deterministic, no model download, tests need no real models. | Detection is partial. PERSON, Aadhaar, addresses, and dates are reported as not covered until a detection plan with an evaluation exists. |
| D2 | Public caller auth and tenant identity | Per-tenant API keys from local config in the `X-API-Key` header. Tenant is derived from the key, never from the body. | Simplest way to satisfy "never trust a client-supplied tenant ID". | Pilot only. A real identity provider is a later gate (`docs/TECH_STACK.md` section 10). |
| D3 | Service-to-service auth | Dedicated shared secret in the `X-Service-Secret` header, compared in constant time, separate from client keys. | Simple and testable. | Pilot only. mTLS or signed short-lived tokens are required before multi-user exposure. |
| D4 | Encryption key source | Base64 AES-256 key in an environment variable of the Sanitization Service, in a keyring by version. Never in the database. | Meets "keys outside the ciphertext database". | Pilot only. Production needs an approved KMS or secrets manager. |
| D5 | Restore-reference lifetime and reuse | Default TTL 1 hour, a setting. Reusable within the TTL. Revocation supported. One-time use is not built. | Smallest design that exercises expiry and revocation. | Replay within the TTL is accepted behavior. A leaked reference is not enough to restore (authorization is independent), but a leaked reference plus a valid same-tenant API key and scope can be reused until expiry or revocation. |
| D6 | Overlapping and ambiguous spans | Longest span wins. Ties go to the higher entity-type `priority` in `entity_types.json`, then the earliest start. Shorter nested spans are dropped. The winner takes the most restrictive action among the spans it overlapped. | Deterministic and testable. | A longer false positive can hide a shorter true span. Accepted for the pilot. |
| D7 | Non-disclosure error behavior | One response for unknown, expired, revoked, deleted, cross-tenant, and cross-scope references: 404 `restore_reference_not_found`, same body shape. | Prevents learning whether a mapping exists. | Callers cannot tell the causes apart. Operators see the cause only in redacted logs (error category). |
| D8 | Who asserts the tenant on the internal call | The De-sanitization Service passes the tenant it authenticated from the API key. Sanitization trusts the authenticated internal caller to assert it. The lookup still requires digest, tenant, and request scope to all match. | Avoids a second identity system in the pilot. | A compromised De-sanitization Service (or leaked service secret) can request any tenant's mapping if it also holds a valid reference. Recorded in `docs/THREAT_MODEL.md`. |
| D9 | Who selects compliance profiles | Per tenant, in the settings store. No per-request selection. | A caller cannot switch protections off. | Changing a tenant's profiles needs a settings change and a restart. |
| D10 | Default profile | `gdpr`, for a tenant with no entry. | Owner decision. | The default is not a compliance claim. |
| D11 | Profile types the pilot cannot detect | Report as not covered. A strict flag (default off) fails startup instead. | Failing by default would make most profiles unusable in the pilot. | A tenant can enable a profile and be only partly protected. The uncovered list is returned in every sanitization response and the policy listing. |
| D12 | `redact` action | Supported. A redacted value is replaced by a marker and never stored. | Some regimes say data must not be retained (for example the card security code). | A redacted value cannot be restored. Restoration leaves the marker untouched. When every detected entity is redacted, no reference is returned. |
| D13 | Profile contents | Written by the project team from the six regimes, reviewed by the owner. | Needed to build and test the resolver. | Not reviewed by legal. Files are marked `not_reviewed_by_legal`. No compliance claim is made. |
| D14 | Settings backend | File (default) or database, selected by one startup setting `PRIVYFLOW_SETTINGS_BACKEND`. Secrets live in the environment only. | Lets operators change behavior without code changes while keeping keys out of stored settings. | Two backends double the test surface; one validator and one contract suite cover both. |
| D15 | When the backend can be chosen or changed | At startup, with a restart. No live reload or live switching. | Live changes would let protection change mid-flight and need an admin path that does not exist yet. | A settings change is not applied until restart. |
| D16 | Who can change settings in the database backend | A separate command line tool (`scripts/settings.py`) using a separate admin database role. The service runtime role is read-only on settings. | Avoids building an admin API and its authorization model in the pilot. | Whoever holds the admin role can weaken protection. Listed in the threat model. |
| D17 | Backend failure behavior | Fail startup and report not ready (`/health/ready` 503). No fallback to the other backend. | A silent fallback could apply weaker protection than configured. | A broken settings source means the service is down, by design. |

## Additional pilot conventions

These follow from the decisions and are fixed here so tests can rely on them.

- Placeholder format: `[TYPE_NNN]`, three-digit zero padding, growing only when more than 999 of one type occur in one request (Q4).
- Redact marker format: `[TYPE_REDACTED]`. It carries no counter, so it reveals nothing about repeated values.
- Collision rule: placeholder counters skip any index whose placeholder appears literally in the input.
- Whitespace-only text is valid: it is returned unchanged with `entity_count` 0 and a null reference. Empty text is rejected (422).
- Synthetic test data ranges, so no fixture can be a real person's value:
  - Email: reserved domains (`example.com`, `example.org`, `example.net`).
  - Phone: the fictional US `555-0100` to `555-0199` range.
  - Card: documented test numbers only (for example the processor test numbers that pass Luhn).
  - IPv4: RFC 5737 blocks `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`. IPv6: `2001:db8::/32`.
  - US SSN format: area number `900` to `999` or `000` or `666`, which the SSA never issues. Fixtures use `900` to `999` for positives; `000`, `666`, group `00`, and serial `0000` are the impossible-range negatives.
  - Names: invented. Pilot corpus samples (Q2) contain only these ranges and are reviewed by the owner before use.

## Alternatives not chosen

- PERSON detection via spaCy or Presidio in the pilot (D1): deferred to keep the pilot model-free.
- JWT with a local issuer (D2), mTLS or signed tokens (D3): more moving parts than the pilot needs.
- One-time-use restoration (D5): needs an atomic consume step and a retry policy that is not yet agreed.
- 403 for scope mismatch (D7): reveals that the mapping exists.
- Admin API for settings (D16), live reload (D15), automatic backend fallback (D17): see the table.

## Change log

| Date | Change | Approved by |
|---|---|---|
| 2026-11-17 | Initial record of D1 to D17. | Product owner |
