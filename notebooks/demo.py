"""End-to-end demo: sanitize your own text or file, then restore it and compare.

    uv run notebooks/demo.py                          # uses data/sample.txt
    uv run notebooks/demo.py --file data/my_notes.txt
    uv run notebooks/demo.py --text "Mail me at jo@example.com"
    uv run notebooks/demo.py --file data/my_notes.txt --tenant tenant-demo-b --save-restored

Both services must be running (docs/MANUAL_TEST.md, step 1.4). The sanitized text is written to
data/output/<name>.sanitized.txt. The restore reference stays in memory and is never printed or
saved. Exit code: 0 when the restored text equals the original, 1 when it does not or a call
fails, 2 when setup is missing.
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
        return httpx.post(url, headers={"X-API-Key": key}, json=body, timeout=30)
    except httpx.ConnectError:
        print(f"Cannot connect to {url}. Start the services first.")
        sys.exit(2)


def error_summary(response):
    error = response.json().get("error", {})
    return f"HTTP {response.status_code}, {error.get('code')}"


parser = argparse.ArgumentParser(description="Sanitize and restore your own text or file.")
source = parser.add_mutually_exclusive_group()
source.add_argument("--file", help="a text file, for example data/my_notes.txt")
source.add_argument("--text", help="text to use instead of a file")
parser.add_argument("--tenant", default="tenant-demo-a", help="tenant-demo-a or tenant-demo-b")
parser.add_argument("--save-restored", action="store_true", help="also save the restored text")
parser.add_argument("--san-url", default="http://127.0.0.1:8001")
parser.add_argument("--desan-url", default="http://127.0.0.1:8002")
args = parser.parse_args()

# Input: your text, or a file (default data/sample.txt)
if args.text is not None:
    original = args.text
    name = "text"
else:
    path = ROOT / (args.file or "data/sample.txt")
    if not path.is_file():
        print(f"File not found: {path}. Put your file in the data folder.")
        sys.exit(2)
    original = path.read_text(encoding="utf-8")
    name = path.stem
if not original.strip():
    print("The input is empty.")
    sys.exit(2)

san_keys = read_keys("sanitization_service/.env", "PRIVYFLOW_SAN_API_KEYS")
desan_keys = read_keys("desanitization_service/.env", "PRIVYFLOW_DESAN_API_KEYS")
if args.tenant not in san_keys or args.tenant not in desan_keys:
    print(f"No API key for {args.tenant}. Known tenants: {', '.join(san_keys)}.")
    sys.exit(2)

scope = "demo-" + secrets.token_hex(4)
print(f"Input: {name} ({len(original)} characters), tenant {args.tenant}")

# Sanitize
response = post(
    f"{args.san_url}/api/v1/sanitizations",
    san_keys[args.tenant],
    {"text": original, "request_scope_id": scope, "policy_id": "effective"},
)
if response.status_code != 200:
    print(f"Sanitize failed: {error_summary(response)}")
    sys.exit(1)
body = response.json()
sanitized = body["sanitized_text"]
reference = body["restore_reference"]

print(f"Masked {body['entity_count']} value(s) under profile(s) {body['profiles_applied']}:")
for entity_type, count in sorted(
    Counter(re.findall(r"\[([A-Z][A-Z_]*)_\d{3}\]", sanitized)).items()
):
    print(f"  {entity_type}: {count} occurrence(s)")
OUTPUT.mkdir(exist_ok=True)
sanitized_path = OUTPUT / f"{name}.sanitized.txt"
sanitized_path.write_text(sanitized, encoding="utf-8")
print(f"Sanitized text saved to {sanitized_path.relative_to(ROOT)}")

if reference is None:
    print("Nothing was masked, so there is nothing to restore.")
    print("PrivyFlow detects EMAIL, PHONE, FINANCIAL, IN_PAN, IP_ADDRESS and US_SSN only,")
    print("and only the types in this tenant's policy are masked.")
    sys.exit(0)

# Restore and compare
response = post(
    f"{args.desan_url}/api/v1/desanitizations",
    desan_keys[args.tenant],
    {"sanitized_text": sanitized, "restore_reference": reference, "request_scope_id": scope},
)
if response.status_code != 200:
    print(f"Restore failed: {error_summary(response)}")
    sys.exit(1)
result = response.json()
print(
    f"Restored {result['restored_count']} value(s), "
    f"{result['unmatched_placeholder_count']} unmatched placeholder(s)"
)
if args.save_restored:
    restored_path = OUTPUT / f"{name}.restored.txt"
    restored_path.write_text(result["restored_text"], encoding="utf-8")
    print(f"Restored text saved to {restored_path.relative_to(ROOT)}")

if result["restored_text"] == original:
    print("PASS  restored text equals the original exactly")
    sys.exit(0)
print("FAIL  restored text differs from the original")
sys.exit(1)
