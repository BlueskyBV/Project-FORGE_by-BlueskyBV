"""Each kind's print-spec rule: section 4's slot, reserved at stage 4b.0b (V2-stage4b-0b.md, 4) for stage 6.

Owned here (the print-spec package, L1); judged by ``forge_checks`` and the
generator's own transform (plan 4.8). One entry per kind, in ``KINDS``' order,
when stage 6 fills it. The name is fixed now; the signature is provisional
until 4b.0d's conformance matrix.
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class PrintRule:
    """One kind's print-spec rule."""

    #: The kind this entry is for.
    key = ""

    @reserved("stage 6")
    def rule(self, item: Any, profile: Any) -> Any:
        """The item as printed on the profile's printer: its part of the print-spec transform, R7's one declared rewrite."""
        raise NotImplementedError
