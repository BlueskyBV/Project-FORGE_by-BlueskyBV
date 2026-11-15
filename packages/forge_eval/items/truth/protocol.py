"""What the generator's shape model asks of a kind of feature: the ``truth`` role's protocol (V2-stage4b-0b-inventory.md, 2.4).

The truth role never imports the grade role or the solver. Each kind's
module says its own facts.
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class TruthKind:
    """One kind of feature, as the shape model checks it is built."""

    #: The kind this entry is for.
    key = ""

    #: Its side is checked to be built (a hole's, a pocket's, a slot's): :func:`~forge_eval.generator._cuts_sided`.
    sided = False

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("4b.0d2")
    def face_roles(self, f: Any) -> tuple[str, ...]:
        """Its faces' roles (item 12): how they split under cuts and merge across tangent joins, a copy's by its pattern coordinates."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def edge_roles(self, f: Any) -> tuple[tuple[str, str], ...]:
        """Its edges' roles, each the two face roles that meet there (item 12)."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def select(self, f: Any, rule: Any) -> Any:
        """A selection rule's faces or edges of it (item 12), evaluated on the generator's own shape."""
        raise NotImplementedError
