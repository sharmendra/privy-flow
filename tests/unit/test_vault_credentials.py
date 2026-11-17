"""Restore-reference format and the lookup digest."""

import base64
import os
from collections.abc import Callable
from typing import Any

import pytest

PEPPER = os.urandom(32)


@pytest.fixture(scope="module")
def credentials(san: Callable[[str], Any]) -> Any:
    return san("app.vault.credentials")


def test_reference_has_the_documented_format(credentials: Any) -> None:
    reference = credentials.generate_reference()
    assert reference.startswith("pf1_")
    assert len(reference) == 4 + 43
    assert credentials.is_valid_reference(reference)


def test_reference_carries_256_bits_of_randomness(credentials: Any) -> None:
    body = credentials.generate_reference().removeprefix("pf1_")
    assert len(base64.urlsafe_b64decode(body + "=")) == 32


@pytest.mark.parametrize(
    "value",
    [
        "",
        "pf1_",
        "pf1_" + "a" * 42,
        "pf1_" + "a" * 44,
        "pf2_" + "a" * 43,
        "PF1_" + "a" * 43,
        "pf1_" + "a" * 42 + "=",
        "pf1_" + "a" * 42 + "!",
        "pf1_" + "a" * 42 + "é",
        " pf1_" + "a" * 43,
        "pf1_" + "a" * 43 + "\n",
    ],
)
def test_malformed_references_are_not_valid(credentials: Any, value: str) -> None:
    assert not credentials.is_valid_reference(value)


def test_100000_generated_references_have_no_duplicates(credentials: Any) -> None:
    references = {credentials.generate_reference() for _ in range(100_000)}
    assert len(references) == 100_000


def test_references_show_no_sequential_or_shared_prefix_pattern(credentials: Any) -> None:
    bodies = [credentials.generate_reference().removeprefix("pf1_") for _ in range(2000)]
    assert len({b[:4] for b in bodies}) > 1500  # 4 random characters, not a counter or time
    assert bodies != sorted(bodies)


def test_digest_is_32_bytes_and_deterministic(credentials: Any) -> None:
    reference = credentials.generate_reference()
    digest = credentials.credential_digest(reference, PEPPER)
    assert len(digest) == 32
    assert digest == credentials.credential_digest(reference, PEPPER)


def test_digest_does_not_contain_the_reference(credentials: Any) -> None:
    reference = credentials.generate_reference()
    digest = credentials.credential_digest(reference, PEPPER)
    assert reference.encode() not in digest
    assert reference.removeprefix("pf1_").encode() not in digest


def test_digest_depends_on_the_pepper(credentials: Any) -> None:
    reference = credentials.generate_reference()
    assert credentials.credential_digest(reference, PEPPER) != credentials.credential_digest(
        reference, os.urandom(32)
    )


def test_different_references_have_different_digests(credentials: Any) -> None:
    first, second = credentials.generate_reference(), credentials.generate_reference()
    assert credentials.credential_digest(first, PEPPER) != credentials.credential_digest(
        second, PEPPER
    )


def test_every_character_position_of_a_reference_is_random(credentials: Any) -> None:
    bodies = [credentials.generate_reference().removeprefix("pf1_") for _ in range(1000)]
    for position in range(43):
        # The last character carries only 4 bits, so at least 10 of its 16 values must show.
        assert len({b[position] for b in bodies}) >= 10, position
