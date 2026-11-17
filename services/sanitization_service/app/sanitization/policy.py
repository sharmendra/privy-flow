"""The effective policy: enabled profiles merged under the restrictiveness rules (SPEC 9.9).

- Entity types are the union across profiles.
- `redact` beats `placeholder`.
- The lifetime is the smallest profile `max_ttl`, and never above the default TTL.

The result depends only on the set of profiles, not on the order they are listed in.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from app.detection.registry import covered_entity_types
from app.sanitization.profiles.loader import Action, Profile, ProfileError, get_profile
from app.settings.validator import SettingsContent, SettingsError

DEFAULT_PROFILE_ID = "gdpr"


@dataclass(frozen=True)
class EffectivePolicy:
    profiles: tuple[tuple[str, int], ...]  # (profile id, version), sorted by id
    actions: Mapping[str, Action]  # entity type to action; a type not listed is not masked
    max_ttl_seconds: int
    uncovered_entity_types: tuple[str, ...]  # named by a profile, no recognizer, sorted

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", MappingProxyType(dict(self.actions)))


def resolve_policy(
    profiles: Sequence[Profile], default_ttl_seconds: int, covered: Collection[str]
) -> EffectivePolicy:
    if not profiles:
        raise ProfileError("no profiles enabled")
    if len({p.id for p in profiles}) != len(profiles):
        raise ProfileError("duplicate profile")
    actions: dict[str, Action] = {}
    for profile in profiles:
        for entity_type, action in profile.entities.items():
            # Once a type is redact it stays redact; otherwise take this profile's action.
            if actions.get(entity_type) != "redact":
                actions[entity_type] = action
    return EffectivePolicy(
        profiles=tuple(sorted((p.id, p.version) for p in profiles)),
        actions=dict(sorted(actions.items())),
        # The shortest lifetime wins, so adding a profile can never lengthen it.
        max_ttl_seconds=min(default_ttl_seconds, *(p.max_ttl_seconds for p in profiles)),
        uncovered_entity_types=tuple(sorted(t for t in actions if t not in covered)),
    )


def resolve_policy_for_ids(
    profile_ids: Sequence[str], default_ttl_seconds: int, covered: Collection[str]
) -> EffectivePolicy:
    return resolve_policy([get_profile(i) for i in profile_ids], default_ttl_seconds, covered)


class PolicyResolver:
    """Each tenant's effective policy, built once from a validated settings snapshot."""

    def __init__(self, content: SettingsContent, covered: Collection[str] | None = None) -> None:
        coverage = covered_entity_types() if covered is None else covered
        ttl = content.default_ttl_seconds
        self._default = resolve_policy_for_ids([DEFAULT_PROFILE_ID], ttl, coverage)
        self._tenants = {
            tenant: resolve_policy_for_ids(list(dict.fromkeys(ids)), ttl, coverage)
            for tenant, ids in content.tenant_profiles.items()
        }
        if content.strict_coverage:
            self._require_full_coverage()

    def policy_for(self, tenant_id: str) -> EffectivePolicy:
        """The tenant's policy. A tenant with no entry gets the default profile only."""
        return self._tenants.get(tenant_id, self._default)

    def _require_full_coverage(self) -> None:
        # The default profile applies to every tenant without an entry, so it always counts.
        uncovered: set[str] = set()
        for policy in (self._default, *self._tenants.values()):
            uncovered.update(policy.uncovered_entity_types)
        if uncovered:
            raise SettingsError(
                "strict coverage: enabled profiles name entity types without a recognizer: "
                + ", ".join(sorted(uncovered))
            )
