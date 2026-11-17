# PrivyFlow Pilot Threat Model

Scope: the pilot described in `docs/PLAN_PILOT.md`, run locally. Decisions referenced (D1 to D17) are in `docs/adr/0001-pilot-decisions.md`. This is a design-time model. No control below is verified until its test runs and the result is recorded in `docs/STATUS.md`.

The "Proving test" column names the planned test and the phase that builds it. Test file names are proposals and follow `docs/CODE_STANDARDS.md` naming. Every row is pending until then.

## 1. Assets

| Asset | Why it matters |
|---|---|
| Original sensitive text and values | The thing the product protects |
| Mapping vault (ciphertext, digests) | Holds reversible mappings |
| Restore-references | One input to restoration |
| Encryption keyring, pepper, service secret, API keys | Compromise defeats the other controls |
| Settings (profiles, tenant flags, TTLs) | Weakening them reduces protection |
| Logs and error bodies | A leak path if they carry payloads |

## 2. Trust boundaries and assumptions

- Client application to each service: authenticated with a per-tenant API key (D2). The key identifies the tenant.
- De-sanitization to Sanitization internal API: authenticated with a shared service secret (D3), and it asserts the tenant it authenticated (D8).
- Sanitization to PostgreSQL: runtime role. Settings changes use a separate admin role (D16).
- Keys, pepper, service secret, and API keys are in environment variables outside the database (D4, D14).
- Local development only, no TLS, no production identity provider, no KMS. These are pilot assumptions, not controls.
- The operating system, the process memory of each service, and the host are trusted. A host compromise is out of scope.

## 3. Attackers

| Attacker | Goal | Mitigation | Proving test (planned) |
|---|---|---|---|
| Cross-tenant client: a valid client of tenant A | Read or restore tenant B's data, or learn that it exists | Tenant derived from the API key, never the body. Lookup requires digest, tenant, and request scope to match. Ciphertext is bound to tenant and scope through associated data. One non-disclosing 404 for all failure causes (D7). Policy listing returns only the caller's tenant. | `tests/security/test_tenant_isolation.py`, `test_non_disclosure.py` (phases 5 to 8) |
| Credential guesser: no valid reference | Find a valid restore-reference | 256-bit reference from `secrets`. Only an HMAC digest with a server-side pepper is stored. Constant-time comparison. A reference alone never authorizes (valid API key for the same tenant and scope also required). | `tests/security/test_reference_entropy.py`, `test_reference_alone_not_authorized.py` (phases 5 and 7) |
| Holder of a leaked reference | Restore text using a reference obtained from a log, chat, or client | API key and tenant check on the De-sanitization Service. Scope must match. Expiry (TTL capped by profiles) and revocation. | `tests/security/test_reference_alone_not_authorized.py`, `test_expiry_revocation.py` (phases 5 to 7) |
| Tampering database writer: can modify rows | Swap, move, or edit ciphertext, or extend an expiry | AES-256-GCM with unique nonces. Associated data binds record id, tenant, scope, and key version, so moved or edited ciphertext fails to decrypt and the restore fails safely. | `tests/security/test_tamper_detection.py`, `tests/e2e/test_tampered_row.py` (phases 5 and 8) |
| Log reader: can read logs and error bodies | Recover original text, values, references, or keys | Field-allowlist structured logging. No bodies, headers, or exception messages. Standard 500 body without trace or SQL. Canary values are checked in logs and responses of both services. | `tests/security/test_log_redaction.py`, `test_leakage_*.py` (phases 2, 6, 7, 8) |
| Settings writer: can change settings (insider or admin role holder) | Weaken protection by removing a profile or raising a TTL | Separate admin role, append-only audit, restart-only activation, startup validation. Not fully mitigated: whoever can write settings can weaken protection. Production needs change control. | `tests/integration/test_settings_roles.py`, `test_settings_audit.py` (phase 2A) |
| Compromised De-sanitization Service or leaked service secret | Retrieve mappings of any tenant | Residual risk (D8). The caller must still hold a valid reference and scope for that tenant. The route is separate from the public API, and the client API key cannot call it. | `tests/security/test_internal_auth.py` (phase 6) |
| Abusive client: oversized or malformed input | Exhaust memory or time | Request-size limits on both services, output limit on restoration, outbound timeout, bounded retries. Rate limiting is not in the pilot. | `tests/integration/test_limits.py` (phases 4, 7) |

## 4. Specific controls and the property each gives

| Control | Property |
|---|---|
| Redacted values are never stored (D12) | They cannot be recovered from a database copy |
| Settings reject secret-like fields | A settings file or dump holds no keys |
| No backend fallback (D17) | Protection is never silently weaker than configured |
| Single-pass restoration | A restored value that looks like a placeholder is not substituted again |
| Placeholder counters skip literal input matches | Source text cannot be confused with a generated placeholder |

## 5. Residual risks

- Detection is incomplete (D1). Unmasked values pass through. No completeness claim is made.
- Profile contents are an interpretation, not legal advice (D13). No compliance claim is made.
- Shared service secret, API keys, and env-var encryption key are pilot mechanisms (D2 to D4). Replace before multi-user or production use.
- The service trusts the authenticated internal caller to assert the tenant (D8).
- A reference can be reused until expiry or revocation (D5).
- Settings changes take effect on restart, and anyone who can write settings can weaken protection.
- No TLS, no rate limiting, no key rotation tooling, no audit store, and no metrics or traces in the pilot. Traces and metrics are reported as not implemented.
- Strictest-wins masking can over-mask and lower text usefulness. The effective policy is visible to the tenant.

## 6. Review

Reviewed: not yet by a security reviewer. Update this file whenever a decision, trust boundary, or control changes.
