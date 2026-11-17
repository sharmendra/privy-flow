"""Planning the spans to mask for a policy, with the D6 overlap rule and its action rule."""

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

import pytest

from tests.support.settings_data import valid_content

EMAIL_TEXT = "Mail a@example.com"


@pytest.fixture(scope="module")
def plan(san: Callable[[str], Any]) -> Any:
    class Mod:
        spans = san("app.sanitization.spans")
        policy = san("app.sanitization.policy")
        loader = san("app.sanitization.profiles.loader")
        validator = san("app.settings.validator")
        types = san("app.detection.types")

        def policy_for(self, *profile_ids: str) -> Any:
            raw = valid_content(tenant_profiles={"tenant-test-a": list(profile_ids)})
            resolver = self.policy.PolicyResolver(self.validator.validate_settings(raw))
            return resolver.policy_for("tenant-test-a")

        def custom_policy(self, actions: Mapping[str, str]) -> Any:
            profile = self.loader.Profile(
                id="custom",
                version=1,
                max_ttl_seconds=3600,
                entities=MappingProxyType(dict(actions)),
            )
            return self.policy.resolve_policy([profile], 3600, frozenset())

        def stub(self, entity_type: str, *offsets: tuple[int, int]) -> Any:
            detection = self.types.Detection

            class Stub:
                def __init__(self) -> None:
                    self.entity_type = entity_type

                def find(self, text: str) -> list[Any]:
                    return [detection(entity_type, s, e) for s, e in offsets]

            return Stub()

        def run(self, text: str, policy: Any, *recognizers: Any) -> list[tuple[str, int, int, str]]:
            found = self.spans.plan_spans(text, policy, recognizers or None)
            return [(s.entity_type, s.start, s.end, s.action) for s in found]

    return Mod()


def test_a_listed_type_is_planned_with_its_action(plan: Any) -> None:
    assert plan.run(EMAIL_TEXT, plan.policy_for("gdpr")) == [("EMAIL", 5, 18, "placeholder")]


def test_a_type_the_policy_does_not_name_is_not_planned(plan: Any) -> None:
    assert plan.run("SSN 900-12-3456", plan.policy_for("gdpr")) == []
    assert plan.run("SSN 900-12-3456", plan.policy_for("hipaa")) == [
        ("US_SSN", 4, 15, "placeholder")
    ]


def test_a_tenant_with_more_profiles_masks_more_in_the_same_text(plan: Any) -> None:
    text = "SSN 900-12-3456 and a@example.com"
    narrow = plan.run(text, plan.policy_for("gdpr"))
    wide = plan.run(text, plan.policy_for("gdpr", "hipaa"))
    assert [s[0] for s in narrow] == ["EMAIL"]
    assert [s[0] for s in wide] == ["US_SSN", "EMAIL"]


def test_empty_and_whitespace_text_plan_nothing(plan: Any) -> None:
    policy = plan.policy_for("gdpr")
    assert plan.run("", policy) == []
    assert plan.run("  \n\t ", policy) == []


def test_text_with_nothing_sensitive_plans_nothing(plan: Any) -> None:
    assert (
        plan.run("Nothing to see in 12/03/2026 at 10:30.", plan.policy_for("gdpr", "hipaa")) == []
    )


def test_a_card_number_is_one_span_not_a_phone_fragment(plan: Any) -> None:
    result = plan.run("Card 4111 1111 1111 1111 ok", plan.policy_for("gdpr", "pci_dss"))
    assert result == [("FINANCIAL", 5, 24, "placeholder")]


def test_the_winner_of_an_overlap_keeps_its_own_action_when_all_agree(plan: Any) -> None:
    policy = plan.custom_policy({"EMAIL": "placeholder", "PHONE": "placeholder"})
    result = plan.run("x" * 20, policy, plan.stub("EMAIL", (0, 20)), plan.stub("PHONE", (5, 10)))
    assert result == [("EMAIL", 0, 20, "placeholder")]


def test_the_winner_takes_redact_from_a_displaced_span(plan: Any) -> None:
    policy = plan.custom_policy({"EMAIL": "placeholder", "PHONE": "redact"})
    result = plan.run("x" * 20, policy, plan.stub("EMAIL", (0, 20)), plan.stub("PHONE", (5, 10)))
    assert result == [("EMAIL", 0, 20, "redact")]


def test_a_redact_winner_stays_redact_over_a_displaced_placeholder(plan: Any) -> None:
    policy = plan.custom_policy({"EMAIL": "redact", "PHONE": "placeholder"})
    result = plan.run("x" * 20, policy, plan.stub("EMAIL", (0, 20)), plan.stub("PHONE", (5, 10)))
    assert result == [("EMAIL", 0, 20, "redact")]


def test_a_span_the_policy_does_not_name_cannot_hide_one_it_does(plan: Any) -> None:
    """Detections are filtered before overlap, so an unlisted longer span never wins."""
    policy = plan.custom_policy({"PHONE": "placeholder"})
    result = plan.run("x" * 20, policy, plan.stub("EMAIL", (0, 20)), plan.stub("PHONE", (5, 10)))
    assert result == [("PHONE", 5, 10, "placeholder")]


def test_adjacent_spans_are_both_planned(plan: Any) -> None:
    result = plan.run("Reach a@example.com,+1 202-555-0171", plan.policy_for("gdpr"))
    assert [s[0] for s in result] == ["EMAIL", "PHONE"]


def test_planned_spans_are_in_order_inside_the_text_and_never_overlap(plan: Any) -> None:
    text = "900-12-3456 a@example.com 192.0.2.1 4111 1111 1111 1111 ABCDE1234F +1 202-555-0143"
    result = plan.run(text, plan.policy_for("gdpr", "hipaa", "pci_dss", "india_dpdp"))
    assert len(result) == 6
    for (_, _, end, _), (_, start, _, _) in zip(result, result[1:], strict=False):
        assert end <= start
    assert all(0 <= s < e <= len(text) for _, s, e, _ in result)


def test_planned_spans_carry_no_text(plan: Any) -> None:
    (span,) = plan.spans.plan_spans(EMAIL_TEXT, plan.policy_for("gdpr"))
    assert "example.com" not in repr(span)
    assert not hasattr(span, "text") and not hasattr(span, "value")


def test_planned_spans_are_immutable(plan: Any) -> None:
    (span,) = plan.spans.plan_spans(EMAIL_TEXT, plan.policy_for("gdpr"))
    with pytest.raises(AttributeError):
        span.start = 0
