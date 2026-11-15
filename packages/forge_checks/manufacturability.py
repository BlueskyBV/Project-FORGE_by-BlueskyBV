"""Manufacturability per process: section 4's slot, reserved at stage 4b.0b (V2-stage4b-0b.md, 4) for stage 6.

Owned here (``forge_checks``, L0, as checks); judged by mutation testing, as
every check kind is (plan stage 6). One entry per process when stage 6 fills
it. The name is fixed now; the signature is provisional until 4b.0d's
conformance matrix.
"""

from __future__ import annotations

from typing import Any

from forge_registry import reserved


class Process:
    """One manufacturing process's rules, as checks."""

    #: The process this entry is for.
    key = ""

    @reserved("stage 6")
    def checks(self, spec: Any) -> tuple[Any, ...]:
        """The checks the process's rules make of the part, each with its mutants."""
        raise NotImplementedError
