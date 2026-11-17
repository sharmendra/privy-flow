"""The saved internal API contract and a checker for it."""

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "contracts"
    / "internal_mappings_retrieve_v1.json"
)


def load_contract() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(CONTRACT_PATH.read_text(encoding="utf-8")))


def conforms(instance: object, section: str) -> bool:
    """True when the instance satisfies the named schema section of the contract."""
    try:
        jsonschema.validate(instance, load_contract()[section])
    except jsonschema.ValidationError:
        return False
    return True


def assert_conforms(instance: object, section: str) -> None:
    jsonschema.validate(instance, load_contract()[section])
