"""The design agent's operations: section 4's slot, reserved at stage 4b.0b (V2-stage4b-0b.md, 4) for stage 5.

Owned here (``forge_occ``'s constructions, L1); judged by the gate, as any
construction. One entry per operation when stage 5 fills it. The name is fixed
now; the signature is provisional until 4b.0d's conformance matrix.
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class AgentOperation:
    """One operation the design agent may add, as a construction."""

    #: The operation this entry is for.
    key = ""

    @reserved("stage 5")
    def construct(self, step: Any) -> Any:
        """The construction that makes the agent's step."""
        raise NotImplementedError
