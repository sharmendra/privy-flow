"""Run and test PrivyFlow end to end on the files in the data folder.

    uv run notebooks/manual_test.py                       # every file in data/, both tenants
    uv run notebooks/manual_test.py --file data/my_notes.txt
    uv run notebooks/manual_test.py --tenant tenant-demo-b --save-restored --preview

This is the command-line version of notebooks/manual_test.ipynb, step 7. Both services must be
running (docs/MANUAL_TEST.md, step 1.4). For each file and tenant it sanitizes the file, saves the
sanitized text to data/output, restores it and checks the restored text equals the file, then
checks that the other tenant cannot restore it and that an altered placeholder is not substituted.
Your text and the restore reference are never printed.
Exit code: 0 when every check passes, 1 when a check fails, 2 when setup is missing.
"""

import argparse
import json
import re
import secrets
import sys
from collections import Counter
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "output"
TENANTS = ["tenant-demo-a", "tenant-demo-b"]
MAX_BYTES = 262144
FILE_TYPES = [".txt", ".md", ".csv", ".log"]
NOT_FOUND = ("restore_reference_not_found", "The restore reference was not found.")

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "  " + detail))


def read_keys(env_file, name):
    path = ROOT / "services" / env_file
    if not path.exists():
        print(f"Missing {path}. Run the setup in docs/MANUAL_TEST.md part 1.")
        sys.exit(2)
    value = dotenv_values(path).get(name)
    if not value:
        print(f"{name} is not set. Run: uv run scripts/gen_local_secrets.py --add-missing-secrets")
        sys.exit(2)
    return json.loads(value)


def post(url, key, body):
    try:
        response = httpx.post(url, headers={"X-API-Key": key}, json=body, timeout=30)
    except httpx.ConnectError:
        print(f"Cannot connect to {url}. Start both services first (docs/MANUAL_TEST.md 1.4).")
        sys.exit(2)
    return response.status_code, response.json()


def error_of(body):
    error = body.get("error", {})
    return error.get("code"), error.get("message")


parser = argparse.ArgumentParser(description="Run PrivyFlow checks on the files in data/.")
parser.add_argument("--file", help="one file inside data/, for example data/my_notes.txt")
parser.add_argument("--tenant", choices=TENANTS, help="one tenant (default: both)")
parser.add_argument("--save-restored", action="store_true", help="also save the restored text")
parser.add_argument("--preview", action="store_true", help="show 600 characters of the output")
parser.add_argument("--san-url", default="http://127.0.0.1:8001")
parser.add_argument("--desan-url", default="http://127.0.0.1:8002")
args = parser.parse_args()

# Setup: keys, tenants and input files
san_keys = read_keys("sanitization_service/.env", "PRIVYFLOW_SAN_API_KEYS")
desan_keys = read_keys("desanitization_service/.env", "PRIVYFLOW_DESAN_API_KEYS")
tenants = [args.tenant] if args.tenant else TENANTS

if args.file:
    path = (ROOT / args.file).resolve()
    if DATA.resolve() not in path.parents or not path.is_file():
        print(f"{args.file} must be an existing file inside the data folder.")
        sys.exit(2)
    files = [path]
else:
    files = sorted(p for p in DATA.iterdir() if p.is_file() and p.suffix.lower() in FILE_TYPES)
    if not files:
        print("No input files found in the data folder. Put a .txt file there.")
        sys.exit(2)

# Health
for label, url in [
    ("Sanitization live", f"{args.san_url}/health/live"),
    ("Sanitization ready", f"{args.san_url}/health/ready"),
    ("De-sanitization live", f"{args.desan_url}/health/live"),
    ("De-sanitization ready", f"{args.desan_url}/health/ready"),
]:
    try:
        status = httpx.get(url, timeout=10).status_code
    except httpx.ConnectError:
        print(f"Cannot connect to {url}. Start both services first (docs/MANUAL_TEST.md 1.4).")
        sys.exit(2)
    check(f"health: {label}", status == 200, f"HTTP {status}")

# One round trip per file and tenant
for path in files:
    for tenant in tenants:
        label = f"{path.name} / {tenant}"
        print(f"\n--- {label}")

        original = path.read_text(encoding="utf-8")
        size = len(original.encode("utf-8"))
        print(f"{len(original)} characters, {len(original.splitlines())} lines, {size} bytes")
        check(f"{label}: file is non-empty and within the size limit", 0 < size <= MAX_BYTES)
        if not 0 < size <= MAX_BYTES:
            continue

        # Sanitize
        scope = "run-" + secrets.token_hex(4)
        status, body = post(
            f"{args.san_url}/api/v1/sanitizations",
            san_keys[tenant],
            {"text": original, "request_scope_id": scope, "policy_id": "effective"},
        )
        check(f"{label}: sanitize succeeded", status == 200, f"HTTP {status}")
        if status != 200:
            continue
        sanitized = body["sanitized_text"]
        reference = body["restore_reference"]
        entity_count = body["entity_count"]

        placeholders = re.findall(r"\[([A-Z][A-Z_]*)_\d{3}\]", sanitized)
        print(f"Masked {entity_count} value(s), profiles {body['profiles_applied']}")
        for entity_type, count in sorted(Counter(placeholders).items()):
            print(f"  {entity_type}: {count} occurrence(s)")
        check(
            f"{label}: placeholder count matches the entity count",
            len(placeholders) == entity_count,
            f"{len(placeholders)} placeholders, entity_count {entity_count}",
        )
        check(
            f"{label}: line structure is unchanged",
            sanitized.count("\n") == original.count("\n"),
        )

        # Save the sanitized text
        OUTPUT.mkdir(exist_ok=True)
        sanitized_path = OUTPUT / f"{path.stem}.{tenant}.sanitized.txt"
        sanitized_path.write_text(sanitized, encoding="utf-8")
        print(f"Sanitized text saved to {sanitized_path.relative_to(ROOT)}")
        if args.preview:
            print("\n" + sanitized[:600] + "\n")

        if reference is None:
            print(
                "Nothing was masked, so there is nothing to restore. Skipping the restore checks."
            )
            continue

        # Restore
        restore_url = f"{args.desan_url}/api/v1/desanitizations"
        request = {
            "sanitized_text": sanitized,
            "restore_reference": reference,
            "request_scope_id": scope,
        }
        status, restored = post(restore_url, desan_keys[tenant], request)
        check(f"{label}: restore succeeded", status == 200, f"HTTP {status}")
        check(
            f"{label}: every masked value restored",
            restored.get("restored_count") == entity_count
            and restored.get("unmatched_placeholder_count") == 0,
        )
        check(
            f"{label}: restored text equals the file exactly",
            restored.get("restored_text") == original,
        )
        if args.save_restored:
            restored_path = OUTPUT / f"{path.stem}.{tenant}.restored.txt"
            restored_path.write_text(restored.get("restored_text", ""), encoding="utf-8")
            print(f"Restored text saved to {restored_path.relative_to(ROOT)}")

        # Safety checks
        other = TENANTS[1] if tenant == TENANTS[0] else TENANTS[0]
        status, refused = post(restore_url, desan_keys[other], request)
        check(
            f"{label}: the other tenant cannot restore it",
            status == 404 and error_of(refused) == NOT_FOUND,
            f"HTTP {status}",
        )
        altered = {**request, "sanitized_text": sanitized + " [EMAIL_999]"}
        status, unmatched = post(restore_url, desan_keys[tenant], altered)
        check(
            f"{label}: an altered placeholder is not substituted",
            status == 200
            and unmatched.get("restored_text", "").endswith(" [EMAIL_999]")
            and unmatched.get("unmatched_placeholder_count") == 1,
            f"HTTP {status}",
        )

failed = results.count(False)
print(f"\n{len(results) - failed} passed, {failed} failed")
sys.exit(1 if failed else 0)
