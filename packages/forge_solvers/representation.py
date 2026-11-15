"""Each kind's analysis representation: section 4's slot, reserved at stage 4b.0b (V2-stage4b-0b.md, 4) for stage 4b.15.

Owned here (the analysis adapters, above L0: ADR-0034); judged by face
accounting of the FE mesh in ``forge_checks`` (item 26). One entry per kind, in
``KINDS``' order, when 4b.15 fills it. The name is fixed now; the signature is
provisional until 4b.0d's conformance matrix.
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class AnalysisRepresentation:
    """How one kind of item is meshed for analysis."""

    #: The kind this entry is for.
    key = ""

    @reserved("4b.15")
    def represent(self, item: Any) -> Any:
        """The item as meshed for analysis (a cosmetic thread as its minor cylinder, text left out), with the error that makes stated."""
        raise NotImplementedError
