"""Effective policy resolution: the restrictiveness rules in SPEC 9.9, for every setting."""

import itertools
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.support.settings_data import valid_content

ALL_TYPES = ["EMAIL", "PHONE", "FINANCIAL", "IP_ADDRESS", "US_SSN", "PERSON", "DATE"]
ACTIONS = ["placeholder", "redact"]


@pytest.fixture(scope="module")
def pol(san: Callable[[str], Any]) -> Any:
    class Mod:
        policy = san("app.sanitization.policy")
        loader = san("app.sanitization.profiles.loader")
        validator = san("app.settings.validator")
        registry = san("app.detection.registry")

        def profile(
            self, profile_id: str, ttl: int, entities: Mapping[str, str], version: int = 1
        ) -> Any:
            return self.loader.Profile(
                id=profile_id,
                version=version,
                max_ttl_seconds=ttl,
                entities=MappingProxyType(dict(entities)),
            )

        def resolver(self, **overrides: Any) -> Any:
            content = self.validator.validate_settings(valid_content(**overrides))
            return self.policy.PolicyResolver(content)

    return Mod()


# Rule: entity types are the union across enabled profiles.
def test_entity_types_are_the_union_of_all_enabled_profiles(pol: Any) -> None:
    a = pol.profile("a", 3600, {"EMAIL": "placeholder"})
    b = pol.profile("b", 3600, {"PHONE": "placeholder"})
    policy = pol.policy.resolve_policy([a, b], 3600, frozenset())
    assert dict(policy.actions) == {"EMAIL": "placeholder", "PHONE": "placeholder"}


def test_a_type_no_profile_names_is_not_masked(pol: Any) -> None:
    policy = pol.policy.resolve_policy(
        [pol.profile("a", 3600, {"EMAIL": "redact"})], 3600, frozenset()
    )
    assert "PHONE" not in policy.actions


# Rule: redact beats placeholder.
@pytest.mark.parametrize("order", [("redact", "placeholder"), ("placeholder", "redact")])
def test_redact_beats_placeholder_in_either_order(pol: Any, order: tuple[str, str]) -> None:
    profiles = [pol.profile(f"p{i}", 3600, {"EMAIL": action}) for i, action in enumerate(order)]
    policy = pol.policy.resolve_policy(profiles, 3600, frozenset())
    assert policy.actions["EMAIL"] == "redact"


def test_agreeing_profiles_keep_their_shared_action(pol: Any) -> None:
    profiles = [pol.profile(p, 3600, {"EMAIL": "placeholder"}) for p in ("a", "b")]
    assert pol.policy.resolve_policy(profiles, 3600, frozenset()).actions["EMAIL"] == "placeholder"


# Rule: lifetime is the smallest max_ttl, and never above the default TTL.
def test_lifetime_is_the_smallest_profile_max_ttl(pol: Any) -> None:
    profiles = [
        pol.profile("a", 1800, {"EMAIL": "placeholder"}),
        pol.profile("b", 900, {"EMAIL": "placeholder"}),
        pol.profile("c", 3000, {"EMAIL": "placeholder"}),
    ]
    assert pol.policy.resolve_policy(profiles, 3600, frozenset()).max_ttl_seconds == 900


def test_lifetime_is_never_longer_than_the_default_ttl(pol: Any) -> None:
    profiles = [pol.profile("a", 3000, {"EMAIL": "placeholder"})]
    assert pol.policy.resolve_policy(profiles, 600, frozenset()).max_ttl_seconds == 600


def test_a_shorter_profile_lifetime_wins_over_a_longer_default(pol: Any) -> None:
    profiles = [pol.profile("a", 300, {"EMAIL": "placeholder"})]
    assert pol.policy.resolve_policy(profiles, 3600, frozenset()).max_ttl_seconds == 300


def test_the_policy_names_its_profiles_and_versions_sorted_by_id(pol: Any) -> None:
    profiles = [
        pol.profile("z", 3600, {"EMAIL": "placeholder"}, version=3),
        pol.profile("a", 3600, {"EMAIL": "placeholder"}, version=2),
    ]
    policy = pol.policy.resolve_policy(profiles, 3600, frozenset())
    assert policy.profiles == (("a", 2), ("z", 3))


def test_uncovered_types_are_those_without_a_recognizer_sorted(pol: Any) -> None:
    profiles = [
        pol.profile("a", 3600, {"PERSON": "placeholder", "EMAIL": "placeholder", "DATE": "redact"})
    ]
    policy = pol.policy.resolve_policy(profiles, 3600, frozenset({"EMAIL"}))
    assert policy.uncovered_entity_types == ("DATE", "PERSON")


def test_an_empty_profile_list_is_refused(pol: Any) -> None:
    with pytest.raises(pol.loader.ProfileError):
        pol.policy.resolve_policy([], 3600, frozenset())


def test_duplicate_profiles_are_refused(pol: Any) -> None:
    profile = pol.profile("a", 3600, {"EMAIL": "placeholder"})
    with pytest.raises(pol.loader.ProfileError):
        pol.policy.resolve_policy([profile, profile], 3600, frozenset())


def test_policy_is_immutable(pol: Any) -> None:
    policy = pol.policy.resolve_policy(
        [pol.profile("a", 3600, {"EMAIL": "redact"})], 3600, frozenset()
    )
    with pytest.raises(TypeError):
        policy.actions["EMAIL"] = "placeholder"
    with pytest.raises(AttributeError):
        policy.max_ttl_seconds = 99


# Properties: adding a profile never unmasks, never weakens an action, never lengthens
# the lifetime, and the order profiles are listed in does not matter.
profile_strategy = st.tuples(
    st.integers(60, 3600),
    st.dictionaries(st.sampled_from(ALL_TYPES), st.sampled_from(ACTIONS), min_size=1),
)
profiles_strategy = st.lists(profile_strategy, min_size=1, max_size=4)


def _build(pol: Any, raw: list[tuple[int, dict[str, str]]]) -> list[Any]:
    return [pol.profile(f"p{i}", ttl, entities) for i, (ttl, entities) in enumerate(raw)]


@given(profiles_strategy, profile_strategy, st.integers(60, 3600))
def test_adding_a_profile_never_unmasks_weakens_or_lengthens(
    pol: Any,
    base: list[tuple[int, dict[str, str]]],
    extra: tuple[int, dict[str, str]],
    default: int,
) -> None:
    before = pol.policy.resolve_policy(_build(pol, base), default, frozenset())
    after = pol.policy.resolve_policy(_build(pol, [*base, extra]), default, frozenset())
    assert set(before.actions) <= set(after.actions)
    for entity_type, action in before.actions.items():
        assert not (action == "redact" and after.actions[entity_type] == "placeholder")
    assert after.max_ttl_seconds <= before.max_ttl_seconds
    assert after.max_ttl_seconds <= default


@given(profiles_strategy, st.integers(60, 3600))
@settings(max_examples=50)
def test_listing_order_does_not_change_the_result(
    pol: Any, raw: list[tuple[int, dict[str, str]]], default: int
) -> None:
    profiles = _build(pol, raw)
    expected = pol.policy.resolve_policy(profiles, default, frozenset({"EMAIL"}))
    for permutation in itertools.permutations(profiles):
        assert (
            pol.policy.resolve_policy(list(permutation), default, frozenset({"EMAIL"})) == expected
        )


# The resolver reads the tenant-to-profile flags from the settings snapshot.
def test_a_tenant_with_no_entry_gets_gdpr_only(pol: Any) -> None:
    policy = pol.resolver().policy_for("tenant-test-unlisted")
    assert [p for p, _ in policy.profiles] == ["gdpr"]
    assert set(policy.actions) == set(pol.loader.get_profile("gdpr").entities)


def test_a_tenant_with_several_profiles_gets_the_union_of_their_types(pol: Any) -> None:
    resolver = pol.resolver(tenant_profiles={"tenant-test-b": ["hipaa", "gdpr", "pci_dss"]})
    policy = resolver.policy_for("tenant-test-b")
    expected: set[str] = set()
    for profile_id in ("hipaa", "gdpr", "pci_dss"):
        expected |= set(pol.loader.get_profile(profile_id).entities)
    assert set(policy.actions) == expected
    assert [p for p, _ in policy.profiles] == ["gdpr", "hipaa", "pci_dss"]


def test_real_profiles_resolve_the_card_security_code_to_redact(pol: Any) -> None:
    resolver = pol.resolver(tenant_profiles={"tenant-test-a": ["pci_dss", "glba"]})
    actions = resolver.policy_for("tenant-test-a").actions
    assert actions["CARD_SECURITY_CODE"] == "redact"
    assert actions["FINANCIAL"] == "placeholder"


def test_real_profiles_use_the_shortest_lifetime(pol: Any) -> None:
    resolver = pol.resolver(tenant_profiles={"tenant-test-a": ["gdpr", "pci_dss"]})
    assert resolver.policy_for("tenant-test-a").max_ttl_seconds == 900
    assert (
        resolver.policy_for("tenant-test-unlisted").max_ttl_seconds == 1800
    )  # default_ttl_seconds


def test_default_ttl_caps_profile_lifetimes(pol: Any) -> None:
    resolver = pol.resolver(default_ttl_seconds=120)
    assert resolver.policy_for("tenant-test-unlisted").max_ttl_seconds == 120


def test_each_tenant_gets_its_own_policy(pol: Any) -> None:
    resolver = pol.resolver(
        tenant_profiles={"tenant-test-a": ["gdpr"], "tenant-test-b": ["gdpr", "hipaa"]}
    )
    a, b = resolver.policy_for("tenant-test-a"), resolver.policy_for("tenant-test-b")
    assert set(a.actions) < set(b.actions)
    assert "US_SSN" in b.actions and "US_SSN" not in a.actions


def test_a_tenant_with_no_entry_is_not_given_another_tenants_profiles(pol: Any) -> None:
    resolver = pol.resolver(tenant_profiles={"tenant-test-b": ["hipaa"]})
    assert [p for p, _ in resolver.policy_for("tenant-test-a").profiles] == ["gdpr"]


def test_the_policy_reports_uncovered_types_using_the_registry(pol: Any) -> None:
    policy = pol.resolver().policy_for("tenant-test-unlisted")
    assert set(policy.uncovered_entity_types) == {
        "PERSON",
        "ADDRESS",
        "NATIONAL_ID",
        "LOCATION",
        "ONLINE_IDENTIFIER",
    }


# Strict coverage: startup fails when an enabled profile names types nothing can detect.
def test_strict_coverage_fails_when_an_enabled_profile_has_uncovered_types(pol: Any) -> None:
    content = pol.validator.validate_settings(valid_content(strict_coverage=True))
    with pytest.raises(pol.validator.SettingsError) as raised:
        pol.policy.PolicyResolver(content)
    assert "strict" in str(raised.value)
    assert "PERSON" in str(raised.value)


def test_strict_coverage_passes_when_every_enabled_type_has_a_recognizer(pol: Any) -> None:
    content = pol.validator.validate_settings(valid_content(strict_coverage=True))
    everything = frozenset(pol.loader.load_entity_types())
    assert pol.policy.PolicyResolver(content, covered=everything).policy_for("tenant-test-a")


def test_strict_coverage_also_checks_the_default_profile(pol: Any) -> None:
    raw = valid_content(strict_coverage=True, tenant_profiles={"tenant-test-a": ["pci_dss"]})
    content = pol.validator.validate_settings(raw)
    covered = frozenset({"FINANCIAL", "CARD_SECURITY_CODE"})
    with pytest.raises(pol.validator.SettingsError):
        pol.policy.PolicyResolver(content, covered=covered)  # gdpr applies to unlisted tenants


def test_without_strict_coverage_uncovered_types_do_not_fail(pol: Any) -> None:
    assert pol.resolver(strict_coverage=False).policy_for("tenant-test-a")


def test_resolver_refuses_a_profile_id_it_cannot_load(pol: Any) -> None:
    with pytest.raises(pol.loader.ProfileError):
        pol.policy.resolve_policy_for_ids(["nope"], 3600, frozenset())
    with pytest.raises(pol.loader.ProfileError):
        pol.policy.resolve_policy_for_ids([], 3600, frozenset())
