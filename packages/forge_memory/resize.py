"""What a resize moves: section 4's slot, reserved at stage 4b.0b (V2-stage4b-0b.md, 4) for stage 7.

Owned here (``forge_memory``, L3); judged by the resize's new confirmation and
the gate (item 28). One entry per kind when stage 7 fills it. The name is fixed
now; the signature is provisional until 4b.0d's conformance matrix.
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class ResizeRule:
    """What a resize moves of one kind of item."""

    #: The kind this entry is for.
    key = ""

    @reserved("stage 7")
    def moves(self, item: Any, change: Any) -> Any:
        """What the resize moves of the item, re-run before its new confirmation and shown (item 28)."""
        raise NotImplementedError
