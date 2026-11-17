"""Detection results and the recognizer interface.

A detection holds an entity type and character offsets only. It never holds the matched
text, so it cannot leak a value if it is logged or printed by mistake.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Detection:
    entity_type: str
    start: int  # character offset, inclusive
    end: int  # character offset, exclusive


class Recognizer(Protocol):
    """Finds one entity type. Engines can be swapped without changing the service API."""

    @property
    def entity_type(self) -> str: ...

    def find(self, text: str) -> list[Detection]: ...
