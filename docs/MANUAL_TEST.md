# PrivyFlow — Manual Test Guide

Test PrivyFlow by hand with a Jupyter notebook. You start the two services, open `notebooks/manual_test.ipynb`, and run its cells one at a time. Each cell prints `PASS` or `FAIL`. All test data is synthetic, and no secret is printed.

If a result differs from what the step says, stop and note the step number.

## What you need

- PostgreSQL running locally, with a database named `privyflow` and an admin login you know.
- `uv` installed, and VS Code or Cursor with the Jupyter extension. Commands run from the repository root in PowerShell.
- The demo tenants from `config/settings.json`:
  - `tenant-demo-a` uses the `gdpr` profile. It masks EMAIL, PHONE and IP_ADDRESS.
  - `tenant-demo-b` uses `gdpr` and `hipaa`. It also masks US_SSN, and its restore references last 1800 seconds.

PrivyFlow detects EMAIL, PHONE, FINANCIAL, IN_PAN, IP_ADDRESS and US_SSN only. Names such as "Alice" are not detected, and that is expected.

## Part 1. Set up the services (once)

### Step 1.1. Install

```powershell
uv sync --all-groups
```

Expected: finishes without errors. This also installs the notebook kernel.

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

Expected: both `.env` files and `config\settings.json` exist. Do not commit or share the `.env` files.

### Step 1.3. Create the database tables

Use the same admin URL, for this shell only:

```powershell
$env:PRIVYFLOW_SAN_MIGRATION_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow"
uv run alembic -c services/sanitization_service/alembic.ini upgrade head
```

Expected: migrations `0001` and `0002` are applied (no output if they were applied before).

### Step 1.4. Start both services

Open two PowerShell terminals in the repository root and keep them open. `--no-access-log` keeps request details out of the logs.

Terminal A, Sanitization (port 8001):

```powershell
uv run uvicorn app.main:app --app-dir services/sanitization_service --port 8001 --no-access-log
```

Terminal B, De-sanitization (port 8002):

```powershell
uv run uvicorn app.main:app --app-dir services/desanitization_service --port 8002 --no-access-log
```

Expected in each terminal: a `settings_loaded` line and "Application startup complete". A `settings_load_failed` line means a secret in that service's `.env` is missing or malformed.

If a terminal shows `[Errno 10048]` (address already in use), an earlier run still holds the port. Find it with `Get-NetTCPConnection -LocalPort 8002 | Select OwningProcess`, stop it with `Stop-Process -Id <PID>`, then start again.

## Part 2. Open the notebook

1. In VS Code open `notebooks/manual_test.ipynb`.
2. Select the kernel in the top right: choose Python Environments, then the `.venv` in this repository (`.venv\Scripts\python.exe`). If it is not listed, run `uv sync --all-groups` again and reload the window.
3. Run each cell with the play button or Shift+Enter, **in order, one at a time**. Later cells use the restore reference created in step 2.2, so do not skip ahead.
4. Read the text above each cell: it says what the cell does and what you should see.
5. For your own data, go to step 7: change `SOURCE_FILE` in step 7.1 to a file in the `data` folder and run steps 7.1 to 7.7 in order. Clear All Outputs (the toolbar menu) before you share or commit the notebook, because output can contain your sanitized text.

If you restart the kernel, run Step 0 and step 2.2 again before any later step.

## Part 3. The steps in the notebook

| Notebook step | What it checks | Expected |
|---|---|---|
| 0. Setup | Loads the keys from the two `.env` files | `2 tenant keys loaded` for each service, then `Setup OK` |
| 1. Health | Live and ready on both services | 4 `PASS` |
| 2.1 Policy | Tenant A's effective policy | HTTP 200, profile `gdpr`, lifetime 3600 seconds |
| 2.2 Sanitize | Masks the sample text and saves the reference | `Contact Alice at [EMAIL_001] or [PHONE_001]. Server [IP_ADDRESS_001] reported the issue.`, reference `pf1_` plus 43 characters (shown masked) |
| 2.3 Repeats | The same value shares one placeholder | `[EMAIL_001] wrote to [EMAIL_001] and [EMAIL_002]` |
| 2.4 Nothing to mask | Text with no sensitive values | Text unchanged, no reference, 0 entities |
| 2.5 Literal placeholder | `[EMAIL_001]` already in the input | Kept as is; the real email becomes `[EMAIL_002]` |
| 3.1 Restore | The round trip with the right key, tenant and scope | Restored text equals the original, 3 restored, 0 unmatched |
| 3.2 Altered placeholders | Unknown and altered placeholders | Left alone; 1 restored and 2 unmatched |
| 3.3 Reuse | Restore again within the lifetime | HTTP 200 again |
| 4.1 Authentication | No key, wrong key, and a key for the other service | 5 `PASS`, each HTTP 401 `unauthorized` |
| 4.2 Wrong tenant, scope, reference | Other tenant, other scope, unknown and malformed references | 4 `PASS`, each the same HTTP 404 "The restore reference was not found." |
| 4.3 Bad input | Empty text, unsupported policy, tenant in the body, bad scope id | 4 `PASS`, each HTTP 422 |
| 4.4 Oversized | 300000 characters | HTTP 413 `payload_too_large` |
| 4.5 Route and method | Unknown route, wrong method | HTTP 404 `not_found`, HTTP 405 `method_not_allowed` |
| 5. Tenant policies | Same text under tenant A and tenant B, and a card number | A leaves the SSN, B masks it, lifetime about 30 minutes, card left alone |
| 6. Internal API | Who may retrieve mappings | Service secret only: 401, 401, 200 with 3 mappings, 404, 401 |
| 7.1 Choose file | Sets `SOURCE_FILE` (in `data/`) and the tenant | The values are printed |
| 7.2 Read file | Reads your file; must be in `data/`, UTF-8, under 262144 bytes | `PASS`, with characters, lines and bytes (your text is not printed) |
| 7.3 Sanitize | Sends your whole file to the Sanitization Service | HTTP 200, values masked by type, expiry, reference shown masked |
| 7.4 Check result | Placeholders equal the entity count, line breaks unchanged | 2 `PASS`, then a preview of the sanitized text |
| 7.5 Save | Writes `data/output/<name>.sanitized.txt` | `PASS` and the path |
| 7.6 Restore | Restores with the same tenant, scope and reference | 3 `PASS`, restored text equals your file exactly |
| 7.7 Safety | Other tenant, and an altered placeholder | 2 `PASS`: HTTP 404 for the other tenant, `[EMAIL_999]` left as is |
| 8. Summary | Counts every check | `N passed, 0 failed` |

A `FAIL` line names the check and the HTTP status received. Fix the cause, run that cell again, then run the summary cell.

## Part 4. Checks you do by hand

These are in step 9 of the notebook.

### Step 9.1. Logs hold no sensitive values

In the two service terminals, search for `alice@example.com`, `202-555-0143`, `192.0.2.10`, `900-12-3456` and the restore reference.

Expected: none appear. Log lines hold only fields such as the route, status code, latency and correlation ID. Terminal B also shows one `restoration_completed` line per success, with counts and a short opaque `tenant_ref`.

### Step 9.2. The database holds no plaintext (optional, needs `psql`)

```powershell
psql "postgresql://USER:PASSWORD@localhost:5432/privyflow" -c "SELECT tenant_id, request_scope_id, length(credential_digest) AS digest_bytes, encryption_alg, key_version, length(ciphertext) AS cipher_bytes, expires_at FROM mapping_records ORDER BY created_at DESC LIMIT 5;"
psql "postgresql://USER:PASSWORD@localhost:5432/privyflow" -c "SELECT count(*) FROM mapping_records WHERE position('alice@example.com'::bytea in ciphertext) > 0;"
```

Expected: `digest_bytes` 32, `AES-256-GCM`, key version 1, and nothing readable. The second query returns `0`.

### Step 9.3. A dependency fails

1. Stop the Sanitization Service (Ctrl+C in terminal A).
2. Run the next notebook cell. Expected: HTTP 503, code `dependency_unavailable`, a correlation ID and no sensitive content. It can take a few seconds because of short retries. Terminal B logs `sanitization_unavailable` with an error category only, and the service stays live.
3. Start the Sanitization Service again (step 1.4, terminal A) and wait for `settings_loaded`.
4. Run the last cell. Expected: HTTP 200 with the same reference, because the stored mapping survived the restart.

## Part 4b. Try your own text or file

`notebooks/demo.py` sanitizes your own text or file, restores it, and checks the restored text equals the original. Start both services first (step 1.4).

```powershell
uv run notebooks/demo.py                                      # the synthetic data/sample.txt
uv run notebooks/demo.py --file data/my_notes.txt             # your own file in the data folder
uv run notebooks/demo.py --text "Mail me at jo@example.com"   # your own text
uv run notebooks/demo.py --file data/my_notes.txt --tenant tenant-demo-b --save-restored
```

Put your own files in `data/`. Only `data/sample.txt` is committed to git; everything else in `data/` is ignored, so real data is not committed by accident. The file must be UTF-8 text under 262144 bytes.

Expected output: how many values were masked and of which types, the path of the sanitized file (`data/output/<name>.sanitized.txt`), `Restored N value(s), 0 unmatched`, and `PASS  restored text equals the original exactly`. Exit code 0 means pass (`echo $LASTEXITCODE`).

- The restore reference is kept in memory only. It is never printed or saved.
- The restored text is saved only with `--save-restored`, because it holds your original values.
- Only EMAIL, PHONE, FINANCIAL, IN_PAN, IP_ADDRESS and US_SSN are detected, and only the types in the tenant's policy are masked. Names and addresses stay in the text. If nothing is masked, the script says so and does not restore.
- Tenant A masks EMAIL, PHONE and IP_ADDRESS. Tenant B also masks US_SSN.

## Part 4c. Run the checks from a Python file

`notebooks/manual_test.py` is the command-line version of notebook step 7. It reads **every** `.txt`, `.md`, `.csv` and `.log` file in `data/` as input and runs the full set of checks for each file and each tenant.

```powershell
uv run notebooks/manual_test.py                                  # all files in data/, both tenants
uv run notebooks/manual_test.py --file data/my_notes.txt         # one file
uv run notebooks/manual_test.py --tenant tenant-demo-b --save-restored --preview
```

For each file and tenant it checks that the file is within the size limit, the sanitize call succeeds, the placeholder count equals the entity count, line breaks are unchanged, the restore succeeds, every masked value is restored, the restored text equals the file exactly, the other tenant cannot restore it, and an altered placeholder is not substituted. A file with nothing detectable skips the restore checks.

Expected: a `PASS` line for each check and `N passed, 0 failed` at the end. The exit code is 0 when everything passes, 1 when a check fails, and 2 when setup is missing (`echo $LASTEXITCODE`). Sanitized text is saved to `data/output/<name>.<tenant>.sanitized.txt`. Your text and the restore reference are never printed.

## Part 5. Automated checks

Optional. These do not use the running services.

```powershell
uv run scripts/run_tests.py lint
uv run pyright
uv run scripts/run_tests.py unit
uv run scripts/run_tests.py security
uv run scripts/run_tests.py evaluation
```

Expected: lint and pyright report no errors and the suites pass. To also run the database-backed integration and end-to-end tests, set the admin URL in this shell and run all suites:

```powershell
$env:PRIVYFLOW_TEST_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/privyflow"
uv run scripts/run_tests.py all
```

These tests create and drop their own `pf_test_*` databases and do not touch your `privyflow` data.

## Not testable by hand

- Expiry and revocation: expiry needs the lifetime to pass (30 to 60 minutes) and revocation has no endpoint yet. Both are covered by automated tests with a controlled clock.
- Rate limiting: not built in the pilot.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Kernel not listed in VS Code | Run `uv sync --all-groups`, then reload the window and pick the repository's `.venv`. |
| `ModuleNotFoundError` in the notebook | The kernel is not the repository's `.venv`. Change it. |
| `Missing ...\.env` in Step 0 | Do step 1.2. |
| `Cannot connect to http://127.0.0.1:8001` | The service is not running or uses another port. Check its terminal, or change `SAN_URL` and `DESAN_URL` in Step 0. |
| Many `FAIL` lines with HTTP 401 | The `.env` keys do not match what the running service loaded. Restart both services after running `gen_local_secrets.py`. |
| `FAIL` with HTTP 404 on step 3, 6 or 7 | The reference or scope is from before a kernel restart. Run step 2.2 (or 7.3 for your own file) again. |
| HTTP 503 on `ready` | A setting or the database failed to load. Read `settings_load_failed` or the database error in that service's terminal. |

## Other ways to run

- Script: `uv run scripts/manual_test.py` runs the same checks as steps 1 to 6 from the command line, and prints a PASS or FAIL line for each.
- Postman: import `docs/postman/PrivyFlow.postman_collection.json` and `PrivyFlow.postman_environment.json`, fill in the five secrets in the environment from the `.env` files, and run the collection. Keep the filled-in environment private.

## Results sheet

Run the notebook once, then record the parts that are by hand.

| Step | Expected | Pass or fail | Notes |
|---|---|---|---|
| Notebook step 8 | `N passed, 0 failed` | | |
| 9.1 | No sensitive values in the logs | | |
| 9.2 | No plaintext in the database | | |
| 9.3 | Service down gives 503, recovers after restart | | |
