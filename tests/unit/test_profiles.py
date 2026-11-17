"""Profile data files, the entity-type list, and the loader that validates them."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

PROFILE_IDS = {"gdpr", "india_dpdp", "hipaa", "pci_dss", "glba", "ccpa"}
PILOT_TYPES = {"EMAIL", "PHONE", "FINANCIAL", "IN_PAN", "IP_ADDRESS", "US_SSN"}


@pytest.fixture(scope="module")
def loader(san: Callable[[str], Any]) -> Any:
    return san("app.sanitization.profiles.loader")


@pytest.fixture(scope="module")
def registry(san: Callable[[str], Any]) -> Any:
    return san("app.detection.registry")


def test_all_six_profiles_load(loader: Any) -> None:
    profiles = loader.load_profiles()
    assert set(profiles) == PROFILE_IDS
    for profile_id, profile in profiles.items():
        assert profile.id == profile_id
        assert profile.version >= 1
        assert 60 <= profile.max_ttl_seconds <= 3600
        assert profile.entities
        assert set(profile.entities.values()) <= {"placeholder", "redact"}


def test_profile_ttls_and_actions_match_the_data_files(loader: Any) -> None:
    profiles = loader.load_profiles()
    assert profiles["hipaa"].max_ttl_seconds == 1800
    assert profiles["pci_dss"].max_ttl_seconds == 900
    assert profiles["pci_dss"].entities == {
        "FINANCIAL": "placeholder",
        "CARD_SECURITY_CODE": "redact",
    }


def test_every_profile_entity_type_is_in_the_shared_list(loader: Any) -> None:
    known = set(loader.load_entity_types())
    for profile in loader.load_profiles().values():
        assert set(profile.entities) <= known


def test_entity_type_priorities_are_unique_so_ties_are_deterministic(loader: Any) -> None:
    priorities = [info.priority for info in loader.load_entity_types().values()]
    assert len(priorities) == len(set(priorities))


def test_pilot_recognizer_flags_match_the_registered_recognizers(
    loader: Any, registry: Any
) -> None:
    flagged = {t for t, info in loader.load_entity_types().items() if info.pilot_recognizer}
    assert flagged == registry.covered_entity_types() == PILOT_TYPES


def test_loaded_profiles_are_read_only(loader: Any) -> None:
    profile = loader.load_profiles()["gdpr"]
    with pytest.raises(TypeError):
        profile.entities["EMAIL"] = "redact"
    with pytest.raises(AttributeError):
        profile.version = 2


def test_get_profile_returns_the_named_profile(loader: Any) -> None:
    assert loader.get_profile("hipaa").id == "hipaa"


@pytest.mark.parametrize("profile_id", ["nope", "", "GDPR", "../gdpr"])
def test_unknown_profile_id_fails_with_a_safe_message(loader: Any, profile_id: str) -> None:
    with pytest.raises(loader.ProfileError) as raised:
        loader.get_profile(profile_id)
    assert "unknown profile" in str(raised.value)
    assert profile_id not in str(raised.value) or profile_id == ""


def test_uncovered_types_are_reported_per_profile(loader: Any, registry: Any) -> None:
    covered = registry.covered_entity_types()
    uncovered = {
        pid: set(loader.uncovered_types(profile, covered))
        for pid, profile in loader.load_profiles().items()
    }
    assert uncovered["pci_dss"] == {"CARD_SECURITY_CODE"}
    assert uncovered["gdpr"] == {
        "PERSON",
        "ADDRESS",
        "NATIONAL_ID",
        "LOCATION",
        "ONLINE_IDENTIFIER",
    }
    assert "EMAIL" not in uncovered["hipaa"]
    assert "US_SSN" not in uncovered["hipaa"]
    assert "DATE" in uncovered["hipaa"]


def test_uncovered_types_are_sorted(loader: Any) -> None:
    result = loader.uncovered_types(loader.get_profile("gdpr"), frozenset())
    assert list(result) == sorted(result)


def _write_profile(directory: Path, name: str, content: dict[str, Any]) -> None:
    (directory / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")


def _data_dir(tmp_path: Path, profile: dict[str, Any], stem: str = "test") -> Path:
    shutil_types = Path(__file__).resolve().parents[2] / (
        "services/sanitization_service/app/sanitization/profiles/data/entity_types.json"
    )
    (tmp_path / "entity_types.json").write_text(
        shutil_types.read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write_profile(tmp_path, stem, profile)
    return tmp_path


GOOD = {
    "id": "test",
    "version": 1,
    "max_ttl_seconds": 600,
    "entities": [{"type": "EMAIL", "action": "placeholder"}],
}


def test_a_well_formed_profile_in_another_directory_loads(loader: Any, tmp_path: Path) -> None:
    profiles = loader.load_profiles_from(_data_dir(tmp_path, GOOD))
    assert profiles["test"].entities == {"EMAIL": "placeholder"}


BAD_PROFILES = [
    ("unknown_entity_type", {**GOOD, "entities": [{"type": "CANARY_TYPE", "action": "redact"}]}),
    ("bad_action", {**GOOD, "entities": [{"type": "EMAIL", "action": "CANARY_ACTION"}]}),
    (
        "duplicate_type",
        {**GOOD, "entities": [{"type": "EMAIL", "action": "redact"}] * 2},
    ),
    ("empty_entities", {**GOOD, "entities": []}),
    ("ttl_too_long", {**GOOD, "max_ttl_seconds": 3601}),
    ("ttl_too_short", {**GOOD, "max_ttl_seconds": 59}),
    ("version_zero", {**GOOD, "version": 0}),
    ("id_not_matching_file", {**GOOD, "id": "other"}),
    ("missing_id", {k: v for k, v in GOOD.items() if k != "id"}),
]


@pytest.mark.parametrize(("case", "profile"), BAD_PROFILES, ids=[c[0] for c in BAD_PROFILES])
def test_a_malformed_profile_fails_loading_without_echoing_values(
    loader: Any, tmp_path: Path, case: str, profile: dict[str, Any]
) -> None:
    with pytest.raises(loader.ProfileError) as raised:
        loader.load_profiles_from(_data_dir(tmp_path, profile))
    message = str(raised.value)
    assert "test.json" in message
    assert "CANARY" not in message


def test_a_profile_file_that_is_not_json_fails_safely(loader: Any, tmp_path: Path) -> None:
    directory = _data_dir(tmp_path, GOOD)
    (directory / "broken.json").write_text("{CANARY", encoding="utf-8")
    with pytest.raises(loader.ProfileError) as raised:
        loader.load_profiles_from(directory)
    assert "CANARY" not in str(raised.value)
