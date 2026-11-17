# PrivyFlow — Manual Test Guide

Run PrivyFlow on your machine and check each behavior by hand. All commands are PowerShell (Windows PowerShell 5.1 or PowerShell 7). All test data is synthetic.

Each step says what to run and what you should see. If a result differs, stop and note the step number.

## What you need

- PostgreSQL running locally, with a database named `privyflow` and an admin login you know.
- `uv` installed. Run commands from the repository root.
- The demo tenants from `config/settings.json`:
  - `tenant-demo-a` uses the `gdpr` profile. It masks EMAIL, PHONE and IP_ADDRESS (the types PrivyFlow can detect today).
  - `tenant-demo-b` uses `gdpr` and `hipaa`. It also masks US_SSN, and its restore references last 1800 seconds.

Detection is limited to six recognizers (EMAIL, PHONE, FINANCIAL, IN_PAN, IP_ADDRESS, US_SSN). Names such as "Alice" are not detected, and that is expected.

## Choose how to run it

Do Part 1 (setup) first, whichever way you choose. Then pick one:

| Option | Best for | Covers |
|---|---|---|
| A. Script file | One command, a pass or fail line for each check | Parts 2 to 7 |
| B. Postman | Clicking through requests and seeing each response | Parts 2 to 7 |
| C. PowerShell by hand | Learning each step, copying single commands | Parts 2 to 9 |

Parts 8 (logs and database) and 9 (service down) are always done by hand, because they need you to look at the service windows, the database, or stop a process. Part 10 is the automated test suites.

### Option A. Run the script file

After Part 1 (services running in windows A and B), open a third window in the repository root:

```powershell
uv run scripts/manual_test.py
```

The script reads the keys and the service secret from the two `.env` files itself, so you paste nothing and nothing secret is printed. If your services run on other ports, add `--san-url http://127.0.0.1:PORT` and `--desan-url http://127.0.0.1:PORT`.

Expected: one `PASS` line for each check, ending with `N passed, 0 failed`, and exit code 0 (`echo $LASTEXITCODE` shows it). A `FAIL` line names the check and the HTTP status received.

Other results:

- `Cannot connect`: the services are not running (step 1.4). Exit code 2.
- `... is not set`: run `uv run scripts/gen_local_secrets.py --add-missing-secrets` (step 1.2). Exit code 2.

You can run it as often as you like. Each run uses new request scopes.

### Option B. Run in Postman

Two files are in `docs\postman\`:

- `PrivyFlow.postman_collection.json`: 36 requests in six folders (Health, Sanitization, Restoration, Refusals, Tenant policies, Internal API). Each request has checks that show green or red in the Test Results tab.
- `PrivyFlow.postman_environment.json`: the URLs and five empty secret values.

Steps:

1. In Postman choose Import and select both files.
2. Open Environments, select `PrivyFlow local`, and fill in the five empty values from the `.env` files (open them with `notepad services\sanitization_service\.env` and `notepad services\desanitization_service\.env`):

   | Environment value | Where it comes from |
   |---|---|
   | `san_key_a` | `PRIVYFLOW_SAN_API_KEYS` in the Sanitization `.env`, the value for `tenant-demo-a` |
   | `san_key_b` | the same line, the value for `tenant-demo-b` |
   | `desan_key_a` | `PRIVYFLOW_DESAN_API_KEYS` in the De-sanitization `.env`, the value for `tenant-demo-a` |
   | `desan_key_b` | the same line, the value for `tenant-demo-b` |
   | `service_secret` | `PRIVYFLOW_DESAN_SERVICE_SECRET` in the De-sanitization `.env` |

   Copy only the value, without the quotes. Save the environment, then pick `PrivyFlow local` in the environment menu at the top right.
3. Run everything: right-click the collection, choose Run collection, keep the order, and select Run. All requests should pass. Order matters: the second request in `2. Sanitization` saves the restore reference that later folders use.
4. Or run one request at a time. Run `2. Sanitization` > `Sanitize the sample text` first, then any other request.

Expected: every test is green. The `Oversized body` request sends 300000 characters, so it can take a moment.

Keep the filled-in environment private: do not export it or share it, because it holds your keys.

### Option C. PowerShell by hand

Use the steps in Parts 2 to 9 below, including the helper in step 1.5.

## Part 1. Setup (once)

### Step 1.1. Install

```powershell
uv sync --all-groups
```

Expected: finishes without errors.

### Step 1.2. Create the local settings files

If `services\sanitization_service\.env` and `services\desanitization_service\.env` already exist, add any missing secrets:

```powershell
uv run scripts/gen_local_secrets.py --add-missing-secrets
```

If they do not exist, create them (use your own admin URL):

```powershell
uv run scripts/gen_local_secrets.py --admin-url "postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow"
uv run scripts/create_db_roles.py
```

Expected: the files exist and `config\settings.json` exists. Do not commit or share the `.env` files; they hold secrets.

### Step 1.3. Create the database tables

Use the same admin URL as above, for this shell only:

```powershell
$env:PRIVYFLOW_SAN_MIGRATION_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow"
uv run alembic -c services/sanitization_service/alembic.ini upgrade head
```

Expected: the output ends with the migrations `0001` and `0002` applied (or no output if they were applied before).

### Step 1.4. Start both services

Open two more PowerShell windows in the repository root. Keep `--no-access-log` so request details stay out of the logs.

Window A, Sanitization (port 8001):

```powershell
uv run uvicorn app.main:app --app-dir services/sanitization_service --port 8001 --no-access-log
```

Window B, De-sanitization (port 8002):

```powershell
uv run uvicorn app.main:app --app-dir services/desanitization_service --port 8002 --no-access-log
```

Expected in each window: a `settings_loaded` log line and "Application startup complete". If you see `settings_load_failed`, a secret in that service's `.env` is missing or malformed.

### Step 1.5. Load the keys and a helper into your test window

Only for Option C (by hand). Options A and B do not need this step.

In your main window, paste this whole block. It reads the keys from the `.env` files into variables without printing them.

```powershell
function Get-EnvJson($file, $name) {
    $line = Get-Content $file | Where-Object { $_ -like "$name=*" }
    ($line.Substring($line.IndexOf('=') + 1).Trim("'") | ConvertFrom-Json)
}
function Get-EnvValue($file, $name) {
    $line = Get-Content $file | Where-Object { $_ -like "$name=*" }
    $line.Substring($line.IndexOf('=') + 1).Trim("'")
}
$sanEnv   = "services\sanitization_service\.env"
$desanEnv = "services\desanitization_service\.env"
$sanKeys   = Get-EnvJson $sanEnv "PRIVYFLOW_SAN_API_KEYS"
$desanKeys = Get-EnvJson $desanEnv "PRIVYFLOW_DESAN_API_KEYS"
$sanA   = @{ "X-API-Key" = $sanKeys.'tenant-demo-a' }
$sanB   = @{ "X-API-Key" = $sanKeys.'tenant-demo-b' }
$desanA = @{ "X-API-Key" = $desanKeys.'tenant-demo-a' }
$desanB = @{ "X-API-Key" = $desanKeys.'tenant-demo-b' }
$svc    = @{ "X-Service-Secret" = (Get-EnvValue $desanEnv "PRIVYFLOW_DESAN_SERVICE_SECRET") }
$SAN = "http://127.0.0.1:8001"
$DESAN = "http://127.0.0.1:8002"

# Sends a request and prints the status code and body, also for errors.
function Call($method, $url, $headers, $body) {
    try {
        $p = @{ Method = $method; Uri = $url; Headers = $headers; ContentType = "application/json"; UseBasicParsing = $true }
        if ($body) { $p.Body = ($body | ConvertTo-Json -Compress) }
        $r = Invoke-WebRequest @p
        "HTTP $($r.StatusCode)"
        $r.Content
    } catch {
        "HTTP $([int]$_.Exception.Response.StatusCode)"
        $_.ErrorDetails.Message
    }
}
```

Expected: no output. If `$sanA` shows an empty key, the tenant is missing from the `.env` file; rerun step 1.2.

## Part 2. Health

### Step 2.1. Liveness and readiness

```powershell
Call GET "$SAN/health/live"
Call GET "$SAN/health/ready"
Call GET "$DESAN/health/live"
Call GET "$DESAN/health/ready"
```

Expected: each prints `HTTP 200` and `{"status":"ok"}`. A `503` on `ready` means a setting or the database failed to load; check that service's window.

## Part 3. Sanitization (tenant-demo-a)

### Step 3.1. See the tenant's policy

```powershell
Call GET "$SAN/api/v1/policies" $sanA
```

Expected: `HTTP 200`, `policy_id` is `effective`, profile `gdpr`, `max_ttl_seconds` 3600. `uncovered_entity_types` lists types such as PERSON that the policy names but PrivyFlow cannot detect yet.

### Step 3.2. Sanitize a text

```powershell
$original = "Contact Alice at alice@example.com or +1 202-555-0143. Server 192.0.2.10 reported the issue."
$scope = "scope-001"
$out = Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = $original; request_scope_id = $scope; policy_id = "effective" }
$out
```

Expected: `HTTP 200` and a body with:

- `sanitized_text`: `Contact Alice at [EMAIL_001] or [PHONE_001]. Server [IP_ADDRESS_001] reported the issue.`
- `restore_reference`: starts with `pf1_` (47 characters in all)
- `entity_count`: 3
- `profiles_applied`: `["gdpr"]`
- `expires_at`: about one hour from now

"Alice" is untouched on purpose.

Save the reference for the next steps:

```powershell
$ref = (($out | Select-Object -Skip 1) | ConvertFrom-Json).restore_reference
$ref.Length
```

Expected: `47`.

### Step 3.3. Repeated values

```powershell
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = "bob@example.com wrote to bob@example.com and carol@example.com"; request_scope_id = "scope-002"; policy_id = "effective" }
```

Expected: `[EMAIL_001] wrote to [EMAIL_001] and [EMAIL_002]`, `entity_count` 3. The same value shares one placeholder.

### Step 3.4. Text with nothing to mask

```powershell
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = "Nothing sensitive here."; request_scope_id = "scope-003"; policy_id = "effective" }
```

Expected: the text unchanged, `restore_reference` null, `expires_at` null, `entity_count` 0.

### Step 3.5. A literal placeholder in the input is not confused with a real one

```powershell
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = "The code [EMAIL_001] is literal. Mail dave@example.com"; request_scope_id = "scope-004"; policy_id = "effective" }
```

Expected: the sanitized text keeps `[EMAIL_001]` and uses `[EMAIL_002]` for Dave's address.

## Part 4. Restoration (the round trip)

### Step 4.1. Restore with the correct key, tenant and scope

```powershell
$restore = Call POST "$DESAN/api/v1/desanitizations" $desanA @{ sanitized_text = "Contact Alice at [EMAIL_001] or [PHONE_001]. Server [IP_ADDRESS_001] reported the issue."; restore_reference = $ref; request_scope_id = $scope }
$restore
```

Expected: `HTTP 200`, `restored_count` 3, `unmatched_placeholder_count` 0, and `restored_text` equal to the original.

Check it is exact:

```powershell
(($restore | Select-Object -Skip 1) | ConvertFrom-Json).restored_text -ceq $original
```

Expected: `True`.

### Step 4.2. Unknown and altered placeholders are left alone

```powershell
Call POST "$DESAN/api/v1/desanitizations" $desanA @{ sanitized_text = "[EMAIL_001] [EMAIL_999] [EMAIL_0001] [email_001] [EMAIL_REDACTED]"; restore_reference = $ref; request_scope_id = $scope }
```

Expected: `restored_text` is `alice@example.com [EMAIL_999] [EMAIL_0001] [email_001] [EMAIL_REDACTED]`, `restored_count` 1, `unmatched_placeholder_count` 2 (`[EMAIL_999]` and `[EMAIL_0001]`). The other two do not have the placeholder shape and are not counted.

### Step 4.3. Reuse within the lifetime

Run step 4.1 again.

Expected: it succeeds again. Reuse is allowed until the reference expires (one-time use is not built).

## Part 5. Things that must be refused

Each of these must fail safely. The body is always `{"error": {"code": ..., "message": ..., "correlation_id": ...}}` with fixed text, and never contains your input.

### Step 5.1. Authentication

```powershell
$body = @{ text = "x@example.com"; request_scope_id = "s1"; policy_id = "effective" }
Call POST "$SAN/api/v1/sanitizations" @{} $body
Call POST "$SAN/api/v1/sanitizations" @{ "X-API-Key" = "wrong-key-wrong-key-wrong-key" } $body
Call POST "$SAN/api/v1/sanitizations" $desanA $body
```

Expected: all three `HTTP 401`, code `unauthorized`. The third shows a De-sanitization key does not work on the Sanitization Service.

```powershell
$rbody = @{ sanitized_text = "[EMAIL_001]"; restore_reference = $ref; request_scope_id = $scope }
Call POST "$DESAN/api/v1/desanitizations" @{} $rbody
Call POST "$DESAN/api/v1/desanitizations" $sanA $rbody
```

Expected: both `HTTP 401`. A restore reference alone never authorizes restoration, and a Sanitization key does not work here.

### Step 5.2. Wrong tenant

```powershell
Call POST "$DESAN/api/v1/desanitizations" $desanB $rbody
```

Expected: `HTTP 404`, code `restore_reference_not_found`, message "The restore reference was not found."

### Step 5.3. Wrong request scope

```powershell
Call POST "$DESAN/api/v1/desanitizations" $desanA @{ sanitized_text = "[EMAIL_001]"; restore_reference = $ref; request_scope_id = "some-other-scope" }
```

Expected: the same `HTTP 404`.

### Step 5.4. Unknown and malformed references

```powershell
$fake = "pf1_" + ("A" * 43)
Call POST "$DESAN/api/v1/desanitizations" $desanA @{ sanitized_text = "[EMAIL_001]"; restore_reference = $fake; request_scope_id = $scope }
Call POST "$DESAN/api/v1/desanitizations" $desanA @{ sanitized_text = "[EMAIL_001]"; restore_reference = "not-a-reference"; request_scope_id = $scope }
```

Expected: both `HTTP 404`, identical to steps 5.2 and 5.3. A caller cannot tell "does not exist" from "not yours".

### Step 5.5. Bad input

```powershell
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = ""; request_scope_id = "s1"; policy_id = "effective" }
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = "x"; request_scope_id = "s1"; policy_id = "other" }
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = "x"; request_scope_id = "s1"; policy_id = "effective"; tenant_id = "tenant-demo-b" }
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = "x"; request_scope_id = "bad scope!"; policy_id = "effective" }
```

Expected: `HTTP 422` for all four. Codes: `validation_error`, `unsupported_policy`, `validation_error` (a body cannot name a tenant), `validation_error`.

### Step 5.6. Oversized request

```powershell
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = ("a" * 300000); request_scope_id = "s1"; policy_id = "effective" }
```

Expected: `HTTP 413`, code `payload_too_large` (the limit is 262144 bytes).

### Step 5.7. Unknown route and wrong method

```powershell
Call GET "$SAN/nope"
Call GET "$SAN/api/v1/sanitizations" $sanA
```

Expected: `HTTP 404` code `not_found`, then `HTTP 405` code `method_not_allowed`.

## Part 6. Tenant policies differ (tenant-demo-b)

### Step 6.1. A US SSN under each tenant

Synthetic SSN `900-12-3456` (the 900 range is never a real number).

```powershell
$ssn = @{ text = "SSN 900-12-3456 and mail erin@example.com"; request_scope_id = "scope-ssn"; policy_id = "effective" }
Call POST "$SAN/api/v1/sanitizations" $sanA $ssn
Call POST "$SAN/api/v1/sanitizations" $sanB $ssn
```

Expected:

- Tenant A: the SSN stays in the text (`gdpr` does not name US_SSN); only the email becomes `[EMAIL_001]`.
- Tenant B: `SSN [US_SSN_001] and mail [EMAIL_001]`, `profiles_applied` lists `gdpr` and `hipaa`, and `expires_at` is about 30 minutes ahead (the shorter `hipaa` lifetime wins).

### Step 6.2. A card number is not masked by these tenants

```powershell
Call POST "$SAN/api/v1/sanitizations" $sanA @{ text = "Card 4111 1111 1111 1111"; request_scope_id = "scope-card"; policy_id = "effective" }
```

Expected: the text is unchanged. Card detection exists, but neither demo tenant's profiles name it (`pci_dss` does). This shows masking follows the tenant's policy.

## Part 7. Internal API (service to service)

### Step 7.1. Only the De-sanitization Service secret works

```powershell
$ibody = @{ restore_reference = $ref; tenant_id = "tenant-demo-a"; request_scope_id = $scope }
Call POST "$SAN/internal/v1/mappings/retrieve" @{} $ibody
Call POST "$SAN/internal/v1/mappings/retrieve" $sanA $ibody
Call POST "$SAN/internal/v1/mappings/retrieve" $svc $ibody
```

Expected: the first two are `HTTP 401` (no credential, and a client API key). The third is `HTTP 200` with `mappings` holding the three placeholder and value pairs and `policy_id` `effective`. This is the only place values appear, and only to the service secret.

```powershell
Call POST "$SAN/internal/v1/mappings/retrieve" $svc @{ restore_reference = $ref; tenant_id = "tenant-demo-b"; request_scope_id = $scope }
```

Expected: `HTTP 404`, the same body as before.

### Step 7.2. The service secret does not work on public routes

```powershell
Call POST "$SAN/api/v1/sanitizations" $svc $body
```

Expected: `HTTP 401`.

## Part 8. Privacy checks

### Step 8.1. Logs hold no sensitive values

Look at the two service windows. Search each window for `alice@example.com`, `202-555-0143`, `192.0.2.10`, `900-12-3456`, and the value of `$ref`.

Expected: none appear. Log lines hold only fields such as the route, status code, latency and correlation ID. The De-sanitization window also shows one `restoration_completed` line per success with counts and a short opaque `tenant_ref`.

### Step 8.2. The database holds no plaintext (optional, needs `psql`)

```powershell
psql "postgresql://USER:PASSWORD@localhost:5432/privyflow" -c "SELECT tenant_id, request_scope_id, length(credential_digest) AS digest_bytes, encryption_alg, key_version, length(ciphertext) AS cipher_bytes, expires_at FROM mapping_records ORDER BY created_at DESC LIMIT 5;"
psql "postgresql://USER:PASSWORD@localhost:5432/privyflow" -c "SELECT count(*) FROM mapping_records WHERE position('alice@example.com'::bytea in ciphertext) > 0;"
```

Expected: the first shows `digest_bytes` 32, `AES-256-GCM` and key version 1, with no readable values. The second returns `0`.

## Part 9. A dependency fails

### Step 9.1. Sanitization Service down

Stop the Sanitization Service (Ctrl+C in window A), then run step 4.1 again.

Expected: `HTTP 503`, code `dependency_unavailable`, a correlation ID, and no sensitive content. The call may take a few seconds because of the short retries. The De-sanitization window logs `sanitization_unavailable` with an error category only.

`Call GET "$DESAN/health/live"` still returns 200, because the service stays up.

Start the Sanitization Service again (step 1.4, window A), wait for it to load, and run step 4.1. Expected: it succeeds with the same reference, because the stored mapping survived the restart.

## Part 10. Automated checks

Close the two service windows or leave them; these do not use them.

```powershell
uv run scripts/run_tests.py lint
uv run pyright
uv run scripts/run_tests.py unit
uv run scripts/run_tests.py security
uv run scripts/run_tests.py evaluation
```

Expected: lint and pyright pass with no errors; the suites pass. To also run the database-backed integration and end-to-end tests, set the admin URL in this shell and run all suites:

```powershell
$env:PRIVYFLOW_TEST_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow"
uv run scripts/run_tests.py all
```

These tests create and drop their own `pf_test_*` databases and do not touch your `privyflow` data.

## Not testable by hand

- Expiry and revocation: expiry needs the lifetime to pass (30 to 60 minutes), and revocation has no endpoint yet. Both are covered by automated tests with a controlled clock.
- Rate limiting: not built in the pilot.

## Results sheet

With Option A or B, the script or Postman result covers Parts 2 to 7. Parts 8 and 9 are always by hand.

| Step | Expected | Pass or fail | Notes |
|---|---|---|---|
| 2.1 | All four health calls return 200 | | |
| 3.2 | Three values masked, "Alice" kept | | |
| 3.3 | Repeats share one placeholder | | |
| 4.1 | Restored text equals the original | | |
| 4.2 | Unknown and altered placeholders left alone, 2 counted | | |
| 5.1 | Missing and wrong keys get 401 | | |
| 5.2 to 5.4 | Wrong tenant, scope and bad references all get the same 404 | | |
| 5.5 to 5.6 | Bad input gets 422, oversized gets 413 | | |
| 6.1 | Policies differ by tenant | | |
| 7.1 | Internal API accepts only the service secret | | |
| 8.1 to 8.2 | No sensitive values in logs or the database | | |
| 9.1 | Service down gives 503, recovers after restart | | |
