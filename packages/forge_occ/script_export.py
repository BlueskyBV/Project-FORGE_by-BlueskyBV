"""The parametric script writer: section 4's slot, reserved at stage 4b.0b (V2-stage4b-0b.md, 4) for stage 6.

Owned here (``forge_occ``, L1); judged by the script rebuilt and compared by
the judge (R5). One entry per construction when stage 6 fills it. The name is
fixed now; the signature is provisional until 4b.0d's conformance matrix.
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class ScriptWriter:
    """How one construction is written into the parametric script."""

    #: The construction this entry is for.
    key = ""

    @reserved("stage 6")
    def write(self, step: Any) -> str:
        """The script's lines that make the step, its values named parameters."""
        raise NotImplementedError
