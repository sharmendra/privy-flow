"""A test-only reference restorer for placeholder round-trip properties.

This is not the De-sanitization Service's implementation (phase 7). It exists so phase 4 can
prove, in memory, that the sanitized text and its mapping carry enough to rebuild the original.
It is single pass, left to right, exact match only, like the documented restoration rule.
"""

import re
from collections.abc import Mapping

PLACEHOLDER_SHAPE = re.compile(r"\[[A-Z][A-Z0-9_]*_[0-9]{3,}\]")


def restore_in_memory(sanitized: str, mappings: Mapping[str, str]) -> str:
    return PLACEHOLDER_SHAPE.sub(lambda m: mappings.get(m.group(0), m.group(0)), sanitized)
