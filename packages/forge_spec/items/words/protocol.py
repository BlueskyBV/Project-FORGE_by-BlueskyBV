"""How the spec's sentences say a kind of item: the ``words`` role's protocol (V2-stage4b-0b-inventory.md, 2.3).

Each kind's module words its own sentence (moved from ``render.py``'s table
at stage 4b.0b's step 3).
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class WordsKind:
    """One kind of item, as its sentence says it."""

    #: The kind this entry is for.
    key = ""

    def sentence(self, line: Any) -> str:
        """The item's sentence, from its line's values: every kind words its own."""
        raise NotImplementedError(f"a {self.key} has no sentence")

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("4b.0d4")
    def guide_entry(self) -> str:
        """Its entry in the spec writer's guide (item 23)."""
        raise NotImplementedError

    @reserved("4b.0d4")
    def family(self) -> str:
        """The family of kinds its guide entry is loaded with (item 23)."""
        raise NotImplementedError
